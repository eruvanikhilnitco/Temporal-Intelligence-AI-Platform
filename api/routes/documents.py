import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.middleware.auth import require_api_key
from core.config import get_settings
from models.document import DocumentResponse
from services.document_parser import DocumentParser
from services.embedding_service import EmbeddingService
from services.lifecycle_service import LifecycleService

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[require_api_key()])

parser = DocumentParser()
embedder = EmbeddingService()
lifecycle_service = LifecycleService()

def _extract_document_status(text: str) -> str | None:
    """Extract a normalized status from document text when present."""
    if not text:
        return None
    # Typical pattern in sample docs: "Status: PAID"
    match = re.search(r"^\s*status\s*:\s*([A-Za-z][A-Za-z _-]{0,40})\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value or None


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(None),  # Optional - will auto-detect if not provided
    lifecycle_id: str = Form(None),  # Optional - will auto-detect if not provided
) -> DocumentResponse:
    """Upload and process a document. Auto-detects document type and lifecycle ID if not provided."""
    settings = get_settings()
    start_time = datetime.now(timezone.utc)
    
    # Validate file extension
    allowed_extensions = {'.pdf', '.docx', '.doc', '.txt', '.csv', '.xlsx', '.xls', '.json'}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Validate file size
    content = await file.read()
    if len(content) > settings.max_upload_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.max_upload_size} bytes"
        )

    # Save file
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    document_id = str(uuid.uuid4())
    target_path = upload_dir / f"{document_id}_{file.filename}"

    try:
        with target_path.open("wb") as target:
            target.write(content)

        # Parse document using original filename for reliable type detection.
        parsed = parser.parse(str(target_path), original_filename=file.filename)
        
        # Use auto-detected values if not provided
        final_document_type = document_type or parsed.get("detected_document_type", "Document")
        final_lifecycle_id = lifecycle_id or parsed.get("detected_lifecycle_id")
        
        # If still no lifecycle ID, generate a default one
        if not final_lifecycle_id:
            final_lifecycle_id = f"lifecycle_{document_id[:8]}"
            logger.info(f"No lifecycle ID detected, using generated ID: {final_lifecycle_id}")
        
        # Generate embedding
        embedding = embedder.embed(parsed["text"])
        
        # Store embedding in Qdrant
        upload_timestamp = datetime.now(timezone.utc).isoformat()
        processing_time_s = max(0.0, (datetime.now(timezone.utc) - start_time).total_seconds())
        
        embedder.store_embedding(
            document_id=document_id,
            embedding=embedding,
            metadata={
                "filename": file.filename,
                "document_type": final_document_type,
                "lifecycle_id": final_lifecycle_id,
                "entities": parsed["entities"],
                "uploaded_at": upload_timestamp,  # Add timestamp for stats
                "processing_time_s": processing_time_s,  # For avg processing stats
                "auto_detected": {
                    "document_type": parsed.get("detected_document_type"),
                    "lifecycle_id": parsed.get("detected_lifecycle_id")
                }
            }
        )

        # Ensure lifecycle exists in Neo4j (generic, no specific type)
        lifecycle_service.create_lifecycle(final_lifecycle_id, status="active")
        
        # Link document to lifecycle in Neo4j
        lifecycle_service.link_document(
            lifecycle_id=final_lifecycle_id,
            document_id=document_id,
            document_type=final_document_type,
            filename=file.filename
        )

        # Add document upload event
        event_type = f"{final_document_type.upper().replace(' ', '_')}_UPLOADED"
        doc_status = _extract_document_status(parsed.get("text", ""))
        event_summary = f"Document {file.filename} uploaded and processed"
        if doc_status:
            event_summary = f"{event_summary} (status: {doc_status.upper()})"

        lifecycle_service.add_event(
            lifecycle_id=final_lifecycle_id,
            event_type=event_type,
            summary=event_summary,
            document_status=doc_status,
        )

        # Extract outcomes if lifecycle is completed or has terminal status
        # This provides real-time outcome extraction as documents are uploaded
        try:
            lifecycle = lifecycle_service.get_lifecycle(final_lifecycle_id)
            if lifecycle.status and lifecycle.status.lower() in ["completed", "closed"]:
                from services.outcome_extractor import OutcomeExtractor
                extractor = OutcomeExtractor()
                # Pre-load current document for efficiency
                document_files = {
                    file.filename: {
                        "path": str(target_path),
                        "content": parsed.get("text", ""),
                        "document_id": document_id
                    }
                }
                created_count = extractor.create_outcomes_for_lifecycle(
                    final_lifecycle_id, 
                    document_files=document_files
                )
                if created_count > 0:
                    logger.info(
                        f"Auto-extracted {created_count} outcome(s) for lifecycle {final_lifecycle_id} "
                        f"after document upload"
                    )
        except Exception as e:
            logger.debug(f"Outcome extraction skipped (non-terminal or error): {e}")

        return DocumentResponse(
            document_id=document_id,
            filename=file.filename,
            document_type=final_document_type,
            lifecycle_id=final_lifecycle_id,
            entities=parsed["entities"],
            embedding_preview=embedding[:5],
            storage_path=os.fspath(target_path),
        )
    except Exception as e:
        logger.error(f"Document upload failed: {e}")
        # Clean up file on error
        if target_path.exists():
            target_path.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")


@router.get("")
async def list_documents(lifecycle_id: str = None, search: str = None):
    """List documents from Qdrant, optionally filtered by lifecycle_id or search query.
    
    If search is provided, uses semantic search (vector similarity) combined with metadata filtering.
    Otherwise, uses metadata filtering only.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from core.database import get_qdrant_connection
    from services.embedding_service import EmbeddingService
    
    try:
        qdrant_config = get_qdrant_connection()
        qdrant_client = QdrantClient(host=qdrant_config.host, port=qdrant_config.port)
        
        # If search query provided, use semantic search (vector similarity)
        if search:
            try:
                embedder = EmbeddingService()
                query_embedding = embedder.embed(search)
                
                # Build filter if lifecycle_id is provided
                query_filter = None
                if lifecycle_id:
                    query_filter = Filter(
                        must=[
                            FieldCondition(
                                key="lifecycle_id",
                                match=MatchValue(value=lifecycle_id)
                            )
                        ]
                    )
                
                # Perform semantic search
                search_results = qdrant_client.search(
                    collection_name="documents",
                    query_vector=query_embedding,
                    query_filter=query_filter,
                    limit=100,
                    with_payload=True,
                    with_vectors=False
                )
                
                # Convert search results to document format
                all_documents = []
                for hit in search_results:
                    payload = hit.payload or {}
                    doc = {
                        "document_id": payload.get("document_id", ""),
                        "filename": payload.get("filename", ""),
                        "document_type": payload.get("document_type", "Document"),
                        "lifecycle_id": payload.get("lifecycle_id", ""),
                        "entities": payload.get("entities", []),
                        "similarity_score": round(hit.score, 4),  # Include similarity score
                        "embedding_preview": []
                    }
                    all_documents.append(doc)
                
                # Also do metadata-based filtering as fallback/boost
                search_lower = search.lower()
                metadata_matches = []
                
                # Scroll through all points for metadata matching
                offset = None
                while True:
                    result = qdrant_client.scroll(
                        collection_name="documents",
                        scroll_filter=query_filter,
                        limit=100,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False
                    )
                    
                    points = result[0]
                    next_offset = result[1]
                    
                    for point in points:
                        payload = point.payload or {}
                        doc_id = payload.get("document_id", "")
                        
                        # Check if already in results
                        if any(d["document_id"] == doc_id for d in all_documents):
                            continue
                        
                        # Check metadata match
                        matches_metadata = (
                            search_lower in (payload.get("filename", "") or "").lower() or
                            search_lower in (payload.get("document_type", "") or "").lower() or
                            search_lower in (payload.get("lifecycle_id", "") or "").lower() or
                            any(search_lower in str(entity).lower() for entity in (payload.get("entities", []) or []))
                        )
                        
                        if matches_metadata:
                            doc = {
                                "document_id": doc_id,
                                "filename": payload.get("filename", ""),
                                "document_type": payload.get("document_type", "Document"),
                                "lifecycle_id": payload.get("lifecycle_id", ""),
                                "entities": payload.get("entities", []),
                                "similarity_score": 0.5,  # Lower score for metadata matches
                                "embedding_preview": []
                            }
                            metadata_matches.append(doc)
                    
                    if next_offset is None:
                        break
                    offset = next_offset
                
                # Combine and deduplicate (prefer semantic search results)
                seen_ids = {d["document_id"] for d in all_documents}
                for doc in metadata_matches:
                    if doc["document_id"] not in seen_ids:
                        all_documents.append(doc)
                        seen_ids.add(doc["document_id"])
                
                # Sort by similarity score (highest first), then by filename
                all_documents.sort(key=lambda x: (x.get("similarity_score", 0), x.get("filename", "")), reverse=True)
                
            except Exception as e:
                logger.warning(f"Semantic search failed, falling back to metadata search: {e}")
                # Fall through to metadata-only search below
                search = None  # Trigger metadata search
        
        # Metadata-only search (no semantic search or search failed)
        if not search:
            # Build filter if lifecycle_id is provided
            filter_condition = None
            if lifecycle_id:
                filter_condition = Filter(
                    must=[
                        FieldCondition(
                            key="lifecycle_id",
                            match=MatchValue(value=lifecycle_id)
                        )
                    ]
                )
            
            # Scroll through all points in the collection
            all_documents = []
            offset = None
            
            while True:
                result = qdrant_client.scroll(
                    collection_name="documents",
                    scroll_filter=filter_condition,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                
                points = result[0]
                next_offset = result[1]
                
                for point in points:
                    payload = point.payload or {}
                    doc = {
                        "document_id": payload.get("document_id", ""),
                        "filename": payload.get("filename", ""),
                        "document_type": payload.get("document_type", "Document"),
                        "lifecycle_id": payload.get("lifecycle_id", ""),
                        "entities": payload.get("entities", []),
                        "embedding_preview": []
                    }
                    all_documents.append(doc)
                
                if next_offset is None:
                    break
                offset = next_offset
            
            # Sort by filename
            # Sort by filename (most recent first based on filename patterns)
            # For files with dates/versions, newer ones typically come later alphabetically
            all_documents.sort(key=lambda x: x.get("filename", ""), reverse=False)
        
        return {"documents": all_documents}
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        return {"documents": []}


@router.get("/stats")
async def get_document_stats():
    """Get document processing statistics."""
    from datetime import datetime, timedelta
    from qdrant_client import QdrantClient
    from core.database import get_qdrant_connection, get_neo4j_connection
    from neo4j import GraphDatabase
    
    stats = {
        "documents_today": 0,
        "documents_yesterday": 0,
        "avg_processing_time": 0,
        "queue_pending": 0,
        "ocr_success_rate": 0,
        "active_lifecycles": 0,
        "high_risk_lifecycles": 0
    }
    
    try:
        # Get document counts from Qdrant
        qdrant_config = get_qdrant_connection()
        qdrant_client = QdrantClient(host=qdrant_config.host, port=qdrant_config.port)

        # Try collection-info count first (may fail with older qdrant-client + newer server schema)
        total_docs = 0
        try:
            info = qdrant_client.get_collection(collection_name="documents")
            total_docs = int(getattr(info, "points_count", 0) or 0)
        except Exception as e:
            logger.warning(f"Failed to read Qdrant collection info for 'documents': {e}")
            total_docs = 0

        logger.info(f"Total documents in Qdrant: {total_docs}")

        # Query documents by timestamp (scan payloads; string timestamps aren't range-queryable reliably)
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.utcnow()
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_start

        today_count = 0
        yesterday_count = 0
        total_with_timestamp = 0
        total_docs_scanned = 0
        today_processing_sum = 0.0
        today_processing_count = 0

        offset = None
        while True:
            points, next_offset = qdrant_client.scroll(
                collection_name="documents",
                scroll_filter=None,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            if not points:
                break

            for point in points:
                total_docs_scanned += 1
                payload = point.payload or {}
                uploaded_at_str = payload.get("uploaded_at")
                if not uploaded_at_str:
                    continue

                total_with_timestamp += 1
                try:
                    if isinstance(uploaded_at_str, str) and uploaded_at_str.endswith("Z"):
                        uploaded_at_str = uploaded_at_str[:-1] + "+00:00"
                    uploaded_at = datetime.fromisoformat(uploaded_at_str)
                    if uploaded_at.tzinfo is None:
                        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
                    else:
                        uploaded_at = uploaded_at.astimezone(timezone.utc)

                    uploaded_at_utc = uploaded_at.replace(tzinfo=timezone.utc)
                    today_start_utc = today_start.replace(tzinfo=timezone.utc)
                    today_end_utc = today_end.replace(tzinfo=timezone.utc)
                    yesterday_start_utc = yesterday_start.replace(tzinfo=timezone.utc)
                    yesterday_end_utc = yesterday_end.replace(tzinfo=timezone.utc)

                    if today_start_utc <= uploaded_at_utc <= today_end_utc:
                        today_count += 1
                        pt = payload.get("processing_time_s")
                        if isinstance(pt, (int, float)) and pt > 0:
                            today_processing_sum += float(pt)
                            today_processing_count += 1
                    elif yesterday_start_utc <= uploaded_at_utc < yesterday_end_utc:
                        yesterday_count += 1
                except (ValueError, TypeError) as e:
                    logger.debug(f"Invalid timestamp format: {uploaded_at_str}, error: {e}")

            if next_offset is None:
                break
            offset = next_offset

        if total_docs_scanned > 0:
            total_docs = total_docs_scanned

        logger.info(f"Total documents in Qdrant (resolved): {total_docs}")

        if total_with_timestamp == 0 and total_docs > 0:
            stats["documents_today"] = total_docs
            stats["documents_yesterday"] = 0
            logger.info(f"No timestamps found in {total_docs} documents, showing all as 'today'")
        else:
            stats["documents_today"] = today_count
            stats["documents_yesterday"] = yesterday_count
            logger.info(
                f"Documents today: {today_count}, yesterday: {yesterday_count}, "
                f"total with timestamp: {total_with_timestamp} out of {total_docs}"
            )
        
        # Get lifecycle stats from Neo4j
        try:
            neo4j_config = get_neo4j_connection()
            driver = GraphDatabase.driver(
                neo4j_config.uri,
                auth=(neo4j_config.user, neo4j_config.password)
            )

            try:
                with driver.session() as session:
                    # Count active lifecycles (status-based OR has any events)
                    result = session.run("""
                        MATCH (l:Lifecycle)
                        WHERE l.status IN ['active', 'pending', 'in_progress']
                           OR EXISTS { MATCH (l)-[:HAS_EVENT]->(:Event) }
                        RETURN count(DISTINCT l) as count
                    """)
                    record = result.single()
                    stats["active_lifecycles"] = int(record["count"]) if record and record.get("count") is not None else 0

                    # Count high risk lifecycles (events containing RISK/ALERT)
                    result = session.run("""
                        MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                        WHERE toUpper(e.event_type) CONTAINS 'RISK' OR toUpper(e.event_type) CONTAINS 'ALERT'
                        RETURN count(DISTINCT l) as count
                    """)
                    record = result.single()
                    stats["high_risk_lifecycles"] = int(record["count"]) if record and record.get("count") is not None else 0
            finally:
                driver.close()
        except Exception as e:
            logger.error(f"Failed to get lifecycle stats from Neo4j: {e}")
            stats["active_lifecycles"] = 0
            stats["high_risk_lifecycles"] = 0
        
        # Placeholder values for processing metrics
        # These would come from actual processing logs in a real system
        if today_processing_count > 0:
            stats["avg_processing_time"] = round(today_processing_sum / today_processing_count, 2)
        else:
            stats["avg_processing_time"] = 0
        stats["queue_pending"] = 0  # Would come from a job queue system
        stats["ocr_success_rate"] = 0  # Would calculate from OCR results
        
    except Exception as e:
        logger.error(f"Failed to get document stats: {e}", exc_info=True)
        # Return zeros on error
    
    logger.info(f"Returning document stats: {stats}")
    return stats

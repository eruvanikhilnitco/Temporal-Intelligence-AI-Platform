import logging
from typing import Optional

from app.error_logger import log_error, log_warning

logger = logging.getLogger(__name__)

# Lazy-init RAG to avoid crashing the backend if Qdrant/Neo4j are unavailable
_rag = None
_orchestrator = None


def _get_rag():
    global _rag
    if _rag is None:
        try:
            from services.phase1_rag import Phase1RAG
            _rag = Phase1RAG(folder_path="sample_data")
            logger.info("[RAGService] Phase1RAG initialized")
        except Exception as e:
            logger.warning(f"[RAGService] Phase1RAG init failed (Qdrant/Neo4j may be offline): {e}")
            _rag = None
    return _rag


def _get_orchestrator():
    global _orchestrator
    rag = _get_rag()
    if rag is None:
        return None
    if _orchestrator is None:
        try:
            # Use EnhancedAgentOrchestrator (extends AgentOrchestrator — OCP)
            from services.enhanced_orchestrator import EnhancedAgentOrchestrator
            _orchestrator = EnhancedAgentOrchestrator(
                phase1_rag=rag,
                graph_service=rag.graph_rag.graph,
                llm_service=rag.llm,
                cache_service=rag.cache,
                reranker=rag.reranker,
                classifier=rag.classifier,
            )
            logger.info("[RAGService] EnhancedAgentOrchestrator initialized")
        except Exception as e:
            logger.warning(f"[RAGService] Enhanced orchestrator init failed, "
                           f"falling back to base: {e}")
            try:
                from services.agent_orchestrator import AgentOrchestrator
                _orchestrator = AgentOrchestrator(
                    phase1_rag=rag,
                    graph_service=rag.graph_rag.graph,
                    llm_service=rag.llm,
                    cache_service=rag.cache,
                    reranker=rag.reranker,
                    classifier=rag.classifier,
                )
                logger.info("[RAGService] Fallback: base AgentOrchestrator initialized")
            except Exception as e2:
                logger.warning(f"[RAGService] Orchestrator init failed: {e2}")
                _orchestrator = None
    return _orchestrator


def ask_rag(question: str, role: str) -> str:
    """Legacy single-string response for backward compat."""
    result = ask_rag_full(question, role)
    return result.get("answer", "")


def ask_rag_full(question: str, role: str, session_id: str = "",
                 conversation_history: Optional[list] = None,
                 tenant_id: Optional[str] = None) -> dict:
    """
    Full response with sources, confidence, query type, graph_used.
    Uses Agent Orchestrator when available, falls back to Phase1RAG.
    Returns a graceful message if AI backend is unavailable.
    """
    orch = _get_orchestrator()

    if orch is not None:
        try:
            state = orch.run(question, user_role=role, session_id=session_id,
                             conversation_history=conversation_history,
                             tenant_id=tenant_id)
            return {
                "answer": state.answer,
                "graph_used": bool(state.graph_context),
                "confidence": state.confidence,
                "query_type": state.query_type,
                "sources": state.sources,
                "cache_hit": state.cache_hit,
                "tools_used": state.tools_used,
                # Explainability fields (EnhancedAgentState only)
                "routing_decision": getattr(state, "routing_decision", "rag"),
                "rag_confidence_score": getattr(state, "rag_confidence_score", 0.0),
                "graph_confidence_score": getattr(state, "graph_confidence_score", 0.0),
                "reasoning_trace": getattr(state, "reasoning_trace", []),
            }
        except Exception as e:
            log_error("RAGService", "Orchestrator query failed", exc=e,
                      extra={"question": question[:200], "role": role})

    rag = _get_rag()
    if rag is not None:
        try:
            answer = rag.ask(question, user_role=role)
            return {
                "answer": answer,
                "graph_used": False,
                "confidence": 75.0,
                "query_type": "fact",
                "sources": [],
                "cache_hit": False,
                "tools_used": ["DocumentSearchTool"],
            }
        except Exception as e:
            log_error("RAGService", "Phase1RAG query failed", exc=e,
                      extra={"question": question[:200], "role": role})

    return {
        "answer": "The AI retrieval service is currently unavailable. Please ensure Qdrant is running and documents have been ingested.",
        "graph_used": False,
        "confidence": 0.0,
        "query_type": "error",
        "sources": [],
        "cache_hit": False,
        "tools_used": [],
    }


def ingest_file(
    file_path: str,
    tenant_id: Optional[str] = None,
    sharepoint_file_id: Optional[str] = None,
    sharepoint_folder_path: Optional[str] = None,
    version: int = 1,
) -> Optional[dict]:
    """
    Ingest a single file into Qdrant + knowledge graph.

    Extra params for SharePoint traceability:
      sharepoint_file_id    — stable SP item ID (survives renames)
      sharepoint_folder_path — full folder path in SharePoint drive
      version               — monotonically increasing version number used for
                              atomic swap (insert v+1 → delete v) on updates
    """
    import uuid
    from pathlib import Path
    from services.phase1_pipeline import Phase1Pipeline
    from qdrant_client.models import PointStruct

    rag = _get_rag()
    if rag is None:
        raise RuntimeError("RAG service unavailable — Qdrant may be offline.")

    pipeline = Phase1Pipeline(folder_path=str(Path(file_path).parent))
    fname = Path(file_path).name

    try:
        text = pipeline.extract_text(file_path)
    except Exception as e:
        log_error("Ingest", f"Text extraction failed for {fname}", exc=e,
                  extra={"file_path": file_path})
        raise

    if not text or not text.strip():
        raise ValueError(f"Empty document after extraction: {fname}")

    access_roles = pipeline._infer_access_roles(file_path, text)

    # Automatic metadata extraction
    metadata: dict = {}
    try:
        from services.metadata_extractor import MetadataExtractor
        metadata = MetadataExtractor().extract(text, filename=fname)
        logger.info(f"[ingest] Metadata for {fname}: {metadata}")
    except Exception as e:
        logger.warning(f"[ingest] Metadata extraction failed: {e}")

    # Token-aware chunking with rich metadata (chunk_id, line_start, line_end …)
    chunk_metas = pipeline.chunk_text_with_metadata(text)
    valid_metas = [c for c in chunk_metas if c["text"].strip()]

    if not valid_metas:
        raise ValueError(f"No usable chunks produced for {fname}")

    chunk_texts = [c["text"] for c in valid_metas]

    # Batch embedding — single model.encode() call
    vectors = rag.embedder.embed_batch(chunk_texts)

    points = []
    for meta, vector in zip(valid_metas, vectors):
        payload = {
            # Core retrieval fields
            "text": meta["text"],
            "file_name": fname,
            "access_roles": access_roles,
            # Classification
            "domain": metadata.get("domain", "general"),
            "doc_type": metadata.get("doc_type", "document"),
            "sensitivity": metadata.get("sensitivity", "low"),
            "classification_source": metadata.get("classification_source", "keyword"),
            # Chunk traceability
            "chunk_id": meta["chunk_id"],
            "line_start": meta.get("line_start"),
            "line_end": meta.get("line_end"),
            "char_start": meta.get("char_start"),
            "char_end": meta.get("char_end"),
            "token_count": meta.get("token_count"),
            # Versioning — used for atomic SP update (insert v+1 → delete v)
            "version": version,
        }
        # SharePoint traceability
        if sharepoint_file_id:
            payload["sharepoint_file_id"] = sharepoint_file_id
        if sharepoint_folder_path:
            payload["sharepoint_folder_path"] = sharepoint_folder_path
        # Multi-tenant isolation
        if tenant_id:
            payload["tenant_id"] = tenant_id

        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload=payload,
        ))

    if points:
        rag.client.upsert(collection_name=rag.collection_name, points=points)
        logger.info(f"[ingest] Stored {len(points)} vectors for {fname} (v{version}, batch)")

    entities = rag.graph_rag.ingest_document(text, fname)
    logger.info(f"[ingest] Graph ingestion complete for {fname}: {entities}")

    try:
        graph_svc = rag.graph_rag.graph
        if metadata:
            graph_svc.store_document_metadata(fname, metadata)
        if entities:
            cross_links = graph_svc.create_cross_document_links(fname, entities)
            logger.info(f"[ingest] Created {cross_links} cross-document links for {fname}")
    except Exception as e:
        logger.warning(f"[ingest] Cross-document linking failed: {e}")

    return entities

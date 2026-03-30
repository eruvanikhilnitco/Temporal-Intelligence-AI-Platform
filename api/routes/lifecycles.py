import logging

from fastapi import APIRouter, HTTPException

from api.middleware.auth import require_api_key
from models.lifecycle import LifecycleResponse
from services.lifecycle_service import LifecycleService

router = APIRouter(dependencies=[require_api_key()])

service = LifecycleService()
logger = logging.getLogger(__name__)

def _load_document_files_for_lifecycle(lifecycle_id: str) -> dict:
    """Load parsed document content keyed by filename for delta/metrics analysis."""
    from neo4j import GraphDatabase
    from core.database import get_neo4j_connection
    from core.config import get_settings
    from pathlib import Path
    from services.document_parser import DocumentParser

    document_files = {}
    try:
        neo4j_config = get_neo4j_connection()
        driver = GraphDatabase.driver(
            neo4j_config.uri,
            auth=(neo4j_config.user, neo4j_config.password)
        )
        try:
            with driver.session() as session:
                result = session.run(
                    """
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})-[:HAS_DOCUMENT]->(d:Document)
                    RETURN d.document_id as document_id, d.filename as filename
                    """,
                    lifecycle_id=lifecycle_id,
                )
                settings = get_settings()
                upload_dir = Path(settings.upload_dir)
                parser = DocumentParser()

                for record in result:
                    doc_id = record.get("document_id")
                    filename = record.get("filename")
                    if not doc_id:
                        continue

                    file_pattern = f"{doc_id}_*"
                    matching_files = list(upload_dir.glob(file_pattern))
                    if not matching_files:
                        continue

                    file_path = matching_files[0]
                    derived_filename = filename
                    try:
                        stored_name = file_path.name
                        derived_filename = stored_name.split("_", 1)[1] if "_" in stored_name else stored_name
                    except Exception:
                        derived_filename = filename or file_path.name

                    try:
                        parsed = parser.parse(str(file_path))
                        content = parsed.get("text", "")
                        key = derived_filename or filename or file_path.name
                        if not key:
                            continue
                        payload = {"path": str(file_path), "content": content, "document_id": doc_id}
                        document_files[key] = payload
                        if filename and filename != key:
                            document_files[filename] = payload
                    except Exception:
                        continue
        finally:
            driver.close()
    except Exception as exc:
        logger.warning(f"Failed loading document files for lifecycle {lifecycle_id}: {exc}")
    return document_files


@router.get("")
def list_lifecycles(limit: int = 100, search: str = None):
    """List all lifecycles, optionally filtered by search query."""
    import logging
    from neo4j import GraphDatabase
    from core.database import get_neo4j_connection
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Listing lifecycles with limit={limit}, search={search}")
        lifecycles = service.list_lifecycles(limit=limit)
        logger.info(f"Service returned {len(lifecycles)} lifecycles")
        
        if not lifecycles:
            logger.warning("No lifecycles returned from service")
            return {"lifecycles": []}
        
        # Get event counts for each lifecycle
        neo4j_config = get_neo4j_connection()
        driver = GraphDatabase.driver(
            neo4j_config.uri,
            auth=(neo4j_config.user, neo4j_config.password)
        )
        
        lifecycle_list = []
        search_lower = search.lower() if search else None
        
        with driver.session() as session:
            for lc in lifecycles:
                try:
                    result = session.run("""
                        MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})-[:HAS_EVENT]->(e:Event)
                        RETURN count(e) as event_count
                    """, lifecycle_id=lc.lifecycle_id)
                    record = result.single()
                    event_count = record["event_count"] if record else 0
                    
                    # Check if lifecycle matches search query
                    matches_search = True
                    if search_lower:
                        # Search in lifecycle_id, status, lifecycle_type, domain
                        matches_search = (
                            search_lower in (lc.lifecycle_id or "").lower() or
                            search_lower in (lc.status or "").lower() or
                            search_lower in (lc.lifecycle_type or "").lower() or
                            search_lower in (lc.domain or "").lower()
                        )
                    
                    if matches_search:
                        lifecycle_list.append({
                            "lifecycle_id": lc.lifecycle_id,
                            "status": lc.status or "unknown",
                            "lifecycle_type": lc.lifecycle_type,
                            "domain": lc.domain,
                            "event_count": event_count
                        })
                except Exception as e:
                    logger.error(f"Error processing lifecycle {lc.lifecycle_id}: {e}")
                    # Still add the lifecycle even if event count fails
                    lifecycle_list.append({
                        "lifecycle_id": lc.lifecycle_id,
                        "status": lc.status or "unknown",
                        "lifecycle_type": lc.lifecycle_type,
                        "domain": lc.domain,
                        "event_count": 0
                    })
        
        driver.close()
        logger.info(f"Returning {len(lifecycle_list)} lifecycles to client")
        return {"lifecycles": lifecycle_list}
    except Exception as e:
        logger.error(f"Failed to list lifecycles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list lifecycles: {str(e)}")


@router.post("/retroactive-evaluation")
def retroactive_evaluation():
    """
    Retroactively evaluate all existing lifecycles and update their status
    based on existing events and documents.
    
    This endpoint scans all lifecycles, checks their events and documents for
    terminal signals (PAID, SIGNED, COMPLETED, etc.), and automatically updates
    their status to 'completed' if appropriate. It also reopens closed lifecycles
    if new non-terminal activity is detected.
    
    Returns:
        Dict with evaluation statistics:
        - evaluated: Total number of lifecycles evaluated
        - completed: Number of lifecycles marked as completed
        - reopened: Number of lifecycles reopened from closed status
        - unchanged: Number of lifecycles that remained unchanged
    """
    try:
        logger.info("Starting retroactive evaluation of all lifecycles...")
        stats = service.retroactively_evaluate_lifecycles()
        logger.info(f"Retroactive evaluation complete: {stats}")
        return {
            "success": True,
            "message": "Retroactive evaluation complete",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Retroactive evaluation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Retroactive evaluation failed: {str(e)}")


@router.get("/diagnostics/evaluation-status")
def get_evaluation_diagnostics():
    """
    Get diagnostic information about why lifecycles are or aren't being marked as completed.
    
    Returns detailed information for each lifecycle:
    - Current status
    - Events and whether they contain terminal signals
    - Documents and their extracted statuses
    - Why the lifecycle is/isn't being completed
    """
    try:
        from neo4j import GraphDatabase
        from core.database import get_neo4j_connection
        from core.config import get_settings
        from pathlib import Path
        from services.document_parser import DocumentParser
        
        neo4j_config = get_neo4j_connection()
        driver = GraphDatabase.driver(
            neo4j_config.uri,
            auth=(neo4j_config.user, neo4j_config.password)
        )
        
        parser = DocumentParser()
        settings = get_settings()
        upload_dir = Path(settings.upload_dir)
        
        diagnostics = []
        
        try:
            with driver.session() as session:
                result = session.run("""
                    MATCH (l:Lifecycle)
                    OPTIONAL MATCH (l)-[:HAS_EVENT]->(e:Event)
                    OPTIONAL MATCH (l)-[:HAS_DOCUMENT]->(d:Document)
                    WITH l, 
                         collect(DISTINCT {
                             event_id: e.event_id,
                             event_type: e.event_type,
                             summary: e.summary,
                             timestamp: CASE 
                                 WHEN e.timestamp IS NOT NULL 
                                 THEN toString(e.timestamp)
                                 ELSE null
                             END
                         }) as events,
                         collect(DISTINCT {
                             document_id: d.document_id,
                             filename: d.filename,
                             document_type: d.document_type
                         }) as documents
                    RETURN l.lifecycle_id as lifecycle_id,
                           l.status as current_status,
                           events,
                           documents
                    ORDER BY l.lifecycle_id
                """)
                
                for record in result:
                    lifecycle_id = record["lifecycle_id"]
                    if not lifecycle_id:
                        continue
                    
                    current_status = record["current_status"] or "active"
                    events_data = [e for e in (record["events"] or []) if e.get("event_id")]
                    documents_data = record["documents"] or []
                    
                    # Analyze events
                    event_analysis = []
                    found_terminal_in_events = False
                    
                    for event in events_data:
                        event_type = event.get("event_type", "")
                        summary = event.get("summary", "")
                        is_terminal = service._is_terminal_signal(event_type, summary, None)
                        is_reopen = service._is_reopen_signal(event_type, summary, None)
                        
                        if is_terminal:
                            found_terminal_in_events = True
                        
                        event_analysis.append({
                            "event_type": event_type,
                            "summary": summary,
                            "is_terminal": is_terminal,
                            "is_reopen_signal": is_reopen
                        })
                    
                    # Analyze documents
                    doc_analysis = []
                    found_terminal_in_docs = False
                    
                    for doc in documents_data:
                        doc_id = doc.get("document_id")
                        filename = doc.get("filename")
                        doc_type = doc.get("document_type")
                        
                        doc_status = None
                        file_found = False
                        
                        if doc_id:
                            file_pattern = f"{doc_id}_*"
                            matching_files = list(upload_dir.glob(file_pattern))
                            
                            if matching_files:
                                try:
                                    file_path = matching_files[0]
                                    parsed = parser.parse(str(file_path))
                                    text = parsed.get("text", "")
                                    doc_status = service._extract_document_status_from_text(text)
                                    file_found = True
                                    
                                    if doc_status and service._is_terminal_signal("", "", doc_status):
                                        found_terminal_in_docs = True
                                except Exception as e:
                                    logger.debug(f"Failed to parse doc {doc_id}: {e}")
                        
                        doc_analysis.append({
                            "document_id": doc_id,
                            "filename": filename,
                            "document_type": doc_type,
                            "extracted_status": doc_status,
                            "file_found": file_found,
                            "is_terminal": doc_status and service._is_terminal_signal("", "", doc_status) if doc_status else False
                        })
                    
                    # Determine why status is what it is
                    should_be_completed = found_terminal_in_events or found_terminal_in_docs
                    reason = []
                    
                    if current_status.lower() in service.CLOSED_STATUSES:
                        reason.append(f"Currently {current_status} (closed status)")
                        if should_be_completed:
                            reason.append("Has terminal signals - should remain completed")
                        else:
                            reason.append("No terminal signals found")
                    else:
                        reason.append(f"Currently {current_status} (active status)")
                        if should_be_completed:
                            reason.append("Has terminal signals - SHOULD BE COMPLETED")
                        else:
                            reason.append("No terminal signals found - correctly active")
                    
                    diagnostics.append({
                        "lifecycle_id": lifecycle_id,
                        "current_status": current_status,
                        "should_be_completed": should_be_completed,
                        "reason": " | ".join(reason),
                        "events": event_analysis,
                        "documents": doc_analysis,
                        "terminal_signals_found": {
                            "in_events": found_terminal_in_events,
                            "in_documents": found_terminal_in_docs
                        }
                    })
        
        finally:
            driver.close()
        
        return {
            "success": True,
            "diagnostics": diagnostics,
            "summary": {
                "total_lifecycles": len(diagnostics),
                "should_be_completed": sum(1 for d in diagnostics if d["should_be_completed"]),
                "currently_active": sum(1 for d in diagnostics if d["current_status"].lower() not in service.CLOSED_STATUSES),
                "currently_completed": sum(1 for d in diagnostics if d["current_status"].lower() in service.CLOSED_STATUSES)
            }
        }
    except Exception as e:
        logger.error(f"Failed to get evaluation diagnostics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get diagnostics: {str(e)}")


@router.get("/{lifecycle_id}", response_model=LifecycleResponse)
def get_lifecycle(lifecycle_id: str) -> LifecycleResponse:
    """Get lifecycle with events."""
    try:
        return service.get_lifecycle(lifecycle_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get lifecycle: {str(e)}")


@router.get("/{lifecycle_id}/graph")
def get_lifecycle_graph(lifecycle_id: str):
    """Get graph data for visualization."""
    try:
        graph_data = service.get_graph_data(lifecycle_id)
        return graph_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get graph data: {str(e)}")


@router.get("/{lifecycle_id}/delta-analysis")
def get_delta_analysis(lifecycle_id: str):
    """Get temporal delta analysis including document revisions and changes."""
    from services.temporal_delta_engine import TemporalDeltaEngine
    from neo4j import GraphDatabase
    from core.database import get_neo4j_connection
    from core.config import get_settings
    from pathlib import Path
    from services.document_parser import DocumentParser
    
    try:
        lifecycle = service.get_lifecycle(lifecycle_id)
        if not lifecycle or not lifecycle.events:
            return {
                "revisions": [],
                "changes": [],
                "summary": "No events to analyze."
            }
        
        # Convert events to dict format for analysis
        events_data = [
            {
                "event_type": e.event_type,
                "timestamp": e.timestamp,
                "summary": e.summary or ""
            }
            for e in lifecycle.events
        ]
        
        # Get document file paths from Neo4j for detailed content analysis
        document_files = {}
        try:
            neo4j_config = get_neo4j_connection()
            driver = GraphDatabase.driver(
                neo4j_config.uri,
                auth=(neo4j_config.user, neo4j_config.password)
            )
            
            with driver.session() as session:
                # Get all documents for this lifecycle with their storage paths
                result = session.run("""
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})-[:HAS_DOCUMENT]->(d:Document)
                    RETURN d.document_id as document_id, d.filename as filename
                """, lifecycle_id=lifecycle_id)
                
                settings = get_settings()
                upload_dir = Path(settings.upload_dir)
                parser = DocumentParser()
                
                for record in result:
                    doc_id = record.get("document_id")
                    filename = record.get("filename")
                    if not doc_id:
                        continue

                    # Try to find the file in upload directory
                    # Files are stored as: {document_id}_{original_filename}
                    file_pattern = f"{doc_id}_*"
                    matching_files = list(upload_dir.glob(file_pattern))
                    if not matching_files:
                        logger.warning(
                            f"File not found for document {doc_id} (filename in neo4j: {filename}), "
                            f"pattern: {file_pattern}, upload_dir: {upload_dir}"
                        )
                        continue

                    file_path = matching_files[0]
                    # If Neo4j doesn't have filename (older data), derive it from the stored file name.
                    derived_filename = filename
                    try:
                        stored_name = file_path.name
                        if "_" in stored_name:
                            derived_filename = stored_name.split("_", 1)[1]
                        else:
                            derived_filename = stored_name
                    except Exception:
                        derived_filename = filename or file_path.name

                    try:
                        parsed = parser.parse(str(file_path))
                        content = parsed.get("text", "")
                        key = derived_filename or filename or file_path.name
                        if not key:
                            continue

                        payload = {
                            "path": str(file_path),
                            "content": content,
                            "document_id": doc_id
                        }
                        # Store under derived filename (matches event summary), and also under Neo4j filename if present.
                        document_files[key] = payload
                        if filename and filename != key:
                            document_files[filename] = payload

                        logger.info(f"Loaded document content for {key}: {len(content)} characters")
                    except Exception as e:
                        logger.warning(
                            f"Failed to parse document for delta analysis: doc_id={doc_id}, filename={filename}, derived={derived_filename}: {e}",
                            exc_info=True,
                        )
                logger.info(f"Loaded {len(document_files)} document files for delta analysis. Keys: {list(document_files.keys())}")
                for key, data in document_files.items():
                    content_len = len(data.get("content", ""))
                    logger.info(f"  - {key}: {content_len} characters")
            
            driver.close()
        except Exception as e:
            logger.warning(f"Failed to retrieve document files for detailed analysis: {e}")
        
        engine = TemporalDeltaEngine()
        analysis = engine.analyze_document_revisions(events_data, document_files)
        
        return analysis
    except Exception as e:
        logger.error(f"Failed to get delta analysis: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get delta analysis: {str(e)}")


@router.get("/{lifecycle_id}/metrics")
def get_lifecycle_metrics(lifecycle_id: str):
    """Get lifecycle metrics: change events, cycle time, variance (generic for any lifecycle type)."""
    import re
    from datetime import datetime, timedelta, timezone
    from services.outcome_service import OutcomeService
    from services.temporal_delta_engine import TemporalDeltaEngine
    
    try:
        lifecycle = service.get_lifecycle(lifecycle_id)
        outcome_service = OutcomeService()
        
        # Get cycle time target from template if available
        from core.lifecycle_templates import get_cycle_time_target
        cycle_time_target = get_cycle_time_target(lifecycle.lifecycle_type if hasattr(lifecycle, 'lifecycle_type') else None)
        
        metrics = {
            "change_orders": 0,  # Generic: any change/modification events
            "change_orders_30d": 0,
            "cycle_time_days": 0,
            "cycle_time_target": cycle_time_target,  # From template or default
            "cost_variance_percent": 0.0,
            "cost_variance_status": "normal"
        }
        
        if lifecycle.events:
            def _to_utc(ts):
                if ts is None:
                    return None
                if ts.tzinfo is None:
                    return ts.replace(tzinfo=timezone.utc)
                return ts.astimezone(timezone.utc)

            # Count explicit change/modification event types.
            explicit_change_events = [
                e for e in lifecycle.events 
                if "CHANGE" in e.event_type.upper() or 
                   "MODIFY" in e.event_type.upper() or 
                   "UPDATE" in e.event_type.upper() or
                   "REVISION" in e.event_type.upper()
            ]
            
            # Also count inferred revision-based changes (works for ANY lifecycle with reuploads/revisions).
            events_data = [
                {
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "summary": e.summary or ""
                }
                for e in lifecycle.events
            ]
            document_files = _load_document_files_for_lifecycle(lifecycle_id)
            delta_engine = TemporalDeltaEngine()
            revision_analysis = delta_engine.analyze_document_revisions(events_data, document_files)

            inferred_changes = revision_analysis.get("changes", []) or []
            inferred_change_count = len(inferred_changes)
            revision_count_total = sum((r.get("revision_count", 0) or 0) for r in (revision_analysis.get("revisions", []) or []))

            # Final change count should represent actual lifecycle changes across all domains.
            metrics["change_orders"] = max(len(explicit_change_events), inferred_change_count, revision_count_total)
            
            # Count change events in last 30 days
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            recent_explicit_changes = [
                e for e in explicit_change_events
                if _to_utc(e.timestamp) and _to_utc(e.timestamp) >= thirty_days_ago
            ]
            recent_inferred_changes = [
                c for c in inferred_changes
                if c.get("timestamp") and _to_utc(c.get("timestamp")) and _to_utc(c.get("timestamp")) >= thirty_days_ago
            ]
            metrics["change_orders_30d"] = max(len(recent_explicit_changes), len(recent_inferred_changes))
            
            # Calculate cycle time (time from first to last event)
            if len(lifecycle.events) > 1:
                normalized_events = [e for e in lifecycle.events if _to_utc(e.timestamp)]
                if len(normalized_events) > 1:
                    sorted_events = sorted(normalized_events, key=lambda e: _to_utc(e.timestamp))
                    first_event = _to_utc(sorted_events[0].timestamp)
                    last_event = _to_utc(sorted_events[-1].timestamp)
                    cycle_seconds = max(0.0, (last_event - first_event).total_seconds())
                    # UI is day-based; show same-day lifecycles as 1 day instead of N/A.
                    metrics["cycle_time_days"] = max(1, int(cycle_seconds // 86400))
            elif len(lifecycle.events) == 1:
                # Single event, cycle time is 0 or 1 day
                metrics["cycle_time_days"] = 1
        
        # Get variance from outcomes first (generic - can be cost, time, quality, etc.)
        try:
            outcome_stats = outcome_service.get_outcome_stats(lifecycle_id)
            # Look for any variance-related outcomes
            for outcome_type in ["COST_OVERRUN", "TIME_OVERRUN", "VARIANCE", "DEVIATION"]:
                if outcome_type in outcome_stats:
                    variance_data = outcome_stats[outcome_type]
                    avg = variance_data.get("avg")
                    if avg is None:
                        continue
                    # Heuristic normalization:
                    # - 0..1 => ratio
                    # - -100..100 => already percent
                    # - otherwise unknown scale, skip and let revision-derived variance decide
                    if -1.0 <= avg <= 1.0:
                        metrics["cost_variance_percent"] = round(avg * 100.0, 1)
                        break
                    if -100.0 <= avg <= 100.0:
                        metrics["cost_variance_percent"] = round(float(avg), 1)
                        break
        except Exception as e:
            # If outcomes fail, use defaults
            pass

        # Fallback variance from detected detailed revision changes (e.g., "(+25.9%)").
        if metrics["cost_variance_percent"] == 0.0 and lifecycle.events:
            try:
                events_data = [
                    {
                        "event_type": e.event_type,
                        "timestamp": e.timestamp,
                        "summary": e.summary or ""
                    }
                    for e in lifecycle.events
                ]
                document_files = _load_document_files_for_lifecycle(lifecycle_id)
                delta_engine = TemporalDeltaEngine()
                revision_analysis = delta_engine.analyze_document_revisions(events_data, document_files)
                pct_matches = []
                for c in (revision_analysis.get("changes", []) or []):
                    for detail in (c.get("detailed_changes", []) or []):
                        for m in re.findall(r'([+-]?\d+(?:\.\d+)?)%', str(detail)):
                            try:
                                pct_matches.append(float(m))
                            except Exception:
                                continue
                if pct_matches:
                    # Use largest absolute variance observed.
                    chosen = max(pct_matches, key=lambda x: abs(x))
                    metrics["cost_variance_percent"] = round(chosen, 1)
            except Exception:
                pass

        if metrics["cost_variance_percent"] > 5:
            metrics["cost_variance_status"] = "above_threshold"
        elif metrics["cost_variance_percent"] < -5:
            metrics["cost_variance_status"] = "below_threshold"
        else:
            metrics["cost_variance_status"] = "normal"
        
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get lifecycle metrics: {str(e)}")


@router.get("/{lifecycle_id}/export")
def export_lifecycle(lifecycle_id: str, format: str = "pdf"):
    """Export lifecycle report in PDF/CSV/JSON format."""
    from fastapi.responses import Response
    import re
    import json
    
    try:
        lifecycle = service.get_lifecycle(lifecycle_id)
        try:
            graph_data = service.get_graph_data(lifecycle_id)
        except Exception:
            graph_data = {"nodes": [], "links": []}

        def _pdf_escape(text: str) -> str:
            return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        def _make_simple_pdf(lines: list[str]) -> bytes:
            """
            Minimal PDF generator (no external deps).
            Creates a PDF with Helvetica text and proper line spacing.
            """
            # Build a simple content stream with line breaks.
            # Start near top-left; move down each line.
            y_start = 760
            font_size = 11
            line_height = 14
            left_margin = 72
            content_lines = [
                "BT",
                f"/F1 {font_size} Tf",
                f"{left_margin} {y_start} Td",
            ]
            for i, line in enumerate(lines):
                safe = _pdf_escape(line)
                if i == 0:
                    content_lines.append(f"({safe}) Tj")
                else:
                    # Move to next line with proper spacing
                    content_lines.append(f"0 -{line_height} Td")
                    content_lines.append(f"({safe}) Tj")
            content_lines.append("ET")
            content_stream = "\n".join(content_lines).encode("utf-8")

            objects: list[bytes] = []

            def obj(n: int, body: bytes) -> None:
                objects.append(f"{n} 0 obj\n".encode("utf-8") + body + b"\nendobj\n")

            # 1: Catalog
            obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
            # 2: Pages
            obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
            # 3: Page
            obj(
                3,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 4 0 R >> >> "
                b"/Contents 5 0 R >>",
            )
            # 4: Font
            obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
            # 5: Content stream
            obj(
                5,
                b"<< /Length " + str(len(content_stream)).encode("utf-8") + b" >>\nstream\n"
                + content_stream
                + b"\nendstream",
            )

            # Build xref
            header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
            body = b""
            offsets = [0]  # object 0
            current = len(header)
            for ob in objects:
                offsets.append(current)
                body += ob
                current += len(ob)

            xref_start = len(header) + len(body)
            xref = [b"xref\n", f"0 {len(offsets)}\n".encode("utf-8")]
            xref.append(b"0000000000 65535 f \n")
            for off in offsets[1:]:
                xref.append(f"{off:010d} 00000 n \n".encode("utf-8"))
            xref_bytes = b"".join(xref)

            trailer = (
                b"trailer\n<< /Size "
                + str(len(offsets)).encode("utf-8")
                + b" /Root 1 0 R >>\nstartxref\n"
                + str(xref_start).encode("utf-8")
                + b"\n%%EOF\n"
            )
            return header + body + xref_bytes + trailer
        
        if format.lower() == "csv":
            # Generate CSV
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(["Lifecycle ID", "Status", "Event ID", "Event Type", "Timestamp", "Summary"])
            
            # Write events
            for event in lifecycle.events:
                writer.writerow([
                    lifecycle_id,
                    lifecycle.status,
                    event.event_id,
                    event.event_type,
                    event.timestamp.isoformat(),
                    event.summary
                ])
            
            csv_content = output.getvalue()
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=lifecycle_{lifecycle_id}.csv"
                }
            )
        elif format.lower() == "pdf":
            # Generate a well-formatted PDF report (no external deps).
            from datetime import datetime
            
            lines: list[str] = []
            
            # Header Section
            lines.append("=" * 70)
            lines.append(f"LIFECYCLE EXPORT REPORT")
            lines.append("=" * 70)
            lines.append("")
            
            # Lifecycle Information Section
            lines.append("LIFECYCLE INFORMATION")
            lines.append("-" * 70)
            lines.append(f"Lifecycle ID: {lifecycle_id}")
            lines.append(f"Status: {lifecycle.status}")
            if lifecycle.lifecycle_type:
                lines.append(f"Type: {lifecycle.lifecycle_type}")
            if lifecycle.domain:
                lines.append(f"Domain: {lifecycle.domain}")
            lines.append(f"Total Events: {len(lifecycle.events)}")
            lines.append("")
            
            # Graph Information Section
            if graph_data:
                lines.append("GRAPH INFORMATION")
                lines.append("-" * 70)
                lines.append(f"Nodes: {len(graph_data.get('nodes', []))}")
                lines.append(f"Relationships: {len(graph_data.get('links', []))}")
                lines.append("")
            
            # Events Timeline Section
            if lifecycle.events:
                lines.append("EVENTS TIMELINE")
                lines.append("-" * 70)
                for idx, event in enumerate(lifecycle.events, 1):
                    lines.append("")
                    lines.append(f"Event #{idx}")
                    lines.append(f"  ID: {event.event_id}")
                    lines.append(f"  Type: {event.event_type}")
                    
                    # Format timestamp
                    if hasattr(event.timestamp, 'strftime'):
                        timestamp_str = event.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(event.timestamp, str):
                        try:
                            from dateutil.parser import parse as parse_date
                            dt = parse_date(event.timestamp)
                            timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            timestamp_str = str(event.timestamp)
                    else:
                        timestamp_str = str(event.timestamp)
                    lines.append(f"  Timestamp: {timestamp_str}")
                    
                    # Format summary with word wrapping
                    if event.summary:
                        summary_text = event.summary.strip()
                        # Wrap long summaries to fit PDF width (65 chars per line)
                        summary_words = summary_text.split()
                        summary_lines = []
                        current_line = ""
                        for word in summary_words:
                            test_line = current_line + (" " if current_line else "") + word
                            if len(test_line) <= 65:
                                current_line = test_line
                            else:
                                if current_line:
                                    summary_lines.append(current_line)
                                current_line = word
                        if current_line:
                            summary_lines.append(current_line)
                        
                        lines.append(f"  Summary:")
                        for sl in summary_lines:
                            lines.append(f"    {sl}")
                    lines.append("")
            else:
                lines.append("EVENTS TIMELINE")
                lines.append("-" * 70)
                lines.append("No events recorded for this lifecycle.")
                lines.append("")
            
            # Footer Section
            lines.append("=" * 70)
            lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("=" * 70)

            pdf_bytes = _make_simple_pdf(lines)
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=lifecycle_{lifecycle_id}.pdf"
                },
            )
        else:
            # Generate JSON
            export_data = {
                "lifecycle_id": lifecycle_id,
                "status": lifecycle.status,
                "events": [
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "timestamp": event.timestamp.isoformat(),
                        "summary": event.summary
                    }
                    for event in lifecycle.events
                ],
                "graph_nodes": len(graph_data.get("nodes", [])),
                "graph_links": len(graph_data.get("links", []))
            }
            
            return Response(
                content=json.dumps(export_data, indent=2),
                media_type="application/json",
                headers={
                    "Content-Disposition": f"attachment; filename=lifecycle_{lifecycle_id}.json"
                }
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export lifecycle: {str(e)}")

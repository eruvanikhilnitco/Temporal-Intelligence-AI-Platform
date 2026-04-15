"""
Admin API Routes — Rules CRUD, Security Events, Analytics, Graph, User Risk, SharePoint.
All endpoints require admin role.
"""

import logging
import os
import tempfile
import requests as http_requests
from datetime import datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.dependencies import require_admin
from app.models import (
    User, ChatLog, SecurityEvent, Rule, UserActivity, QueryFeedback, ApiKey
)
from app.api.schemas import (
    RuleCreate, RuleUpdate, RuleResponse,
    SecurityEventResponse, AnalyticsResponse,
    GraphDataResponse, GraphNodeResponse, GraphEdgeResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Rules CRUD ────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=List[RuleResponse])
def list_rules(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all dynamic rules."""
    return db.query(Rule).order_by(Rule.created_at.desc()).all()


@router.post("/rules", response_model=RuleResponse)
def create_rule(
    data: RuleCreate,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new security rule."""
    rule = Rule(
        name=data.name,
        pattern=data.pattern,
        action=data.action,
        role=data.role,
        created_by=current_user["user_id"],
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/rules/{rule_id}", response_model=RuleResponse)
def update_rule(
    rule_id: str,
    data: RuleUpdate,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update an existing rule."""
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if data.name is not None:
        rule.name = data.name
    if data.pattern is not None:
        rule.pattern = data.pattern
    if data.action is not None:
        rule.action = data.action
    if data.role is not None:
        rule.role = data.role
    if data.active is not None:
        rule.active = data.active
    rule.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete a rule."""
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "deleted", "rule_id": rule_id}


@router.patch("/rules/{rule_id}/toggle")
def toggle_rule(
    rule_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Toggle rule active/inactive."""
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.active = not rule.active
    db.commit()
    return {"status": "ok", "active": rule.active}


# ── Security Events ───────────────────────────────────────────────────────────

@router.get("/security/events", response_model=List[SecurityEventResponse])
def list_security_events(
    limit: int = Query(50, ge=1, le=200),
    severity: Optional[str] = None,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List recent security events."""
    q = db.query(SecurityEvent).order_by(SecurityEvent.created_at.desc())
    if severity:
        q = q.filter(SecurityEvent.severity == severity)
    return q.limit(limit).all()


@router.patch("/security/events/{event_id}/resolve")
def resolve_security_event(
    event_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Mark a security event as resolved."""
    ev = db.query(SecurityEvent).filter(SecurityEvent.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    ev.resolved = True
    db.commit()
    return {"status": "resolved"}


@router.get("/security/stats")
def security_stats(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Security statistics summary."""
    total = db.query(SecurityEvent).count()
    high = db.query(SecurityEvent).filter(SecurityEvent.severity == "high").count()
    medium = db.query(SecurityEvent).filter(SecurityEvent.severity == "medium").count()
    unresolved = db.query(SecurityEvent).filter(SecurityEvent.resolved == False).count()

    # Risk users
    risky_users = (
        db.query(User)
        .filter(User.risk_level.in_(["high", "critical"]))
        .count()
    )

    return {
        "total_events": total,
        "high_severity": high,
        "medium_severity": medium,
        "unresolved": unresolved,
        "risky_users": risky_users,
    }


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics")
def get_analytics(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return analytics data — batched into minimal DB round-trips."""
    from sqlalchemy import text

    # ── Detect PostgreSQL vs SQLite for query syntax ──────────────────────────
    from app.db import engine as _engine
    _is_pg = "postgresql" in str(_engine.url)

    # ── Single-pass aggregate query over ChatLog ──────────────────────────────
    agg = db.execute(text(
        "SELECT COUNT(*) as total, "
        "AVG(latency_ms) as avg_lat, "
        "SUM(CASE WHEN latency_ms < 50 THEN 1 ELSE 0 END) as cache_hits, "
        "SUM(CASE WHEN graph_used = true THEN 1 ELSE 0 END) as graph_hits, "
        "AVG(confidence) as avg_conf "
        "FROM chat_logs"
    )).fetchone()

    total_queries = agg[0] or 0
    avg_latency   = float(agg[1] or 0)
    cache_rate    = (agg[2] or 0) / max(total_queries, 1) * 100
    graph_rate    = (agg[3] or 0) / max(total_queries, 1) * 100
    avg_conf      = float(agg[4] or 0)

    # Counts that don't need ChatLog
    total_users    = db.query(User).count()
    active_rules   = db.query(Rule).filter(Rule.active == True).count()
    security_events = db.query(SecurityEvent).count()

    # Daily queries — PostgreSQL vs SQLite compatible
    if _is_pg:
        daily_rows = db.execute(text(
            "SELECT DATE(created_at) as d, COUNT(*) as n "
            "FROM chat_logs "
            "WHERE created_at >= CURRENT_DATE - INTERVAL '13 days' "
            "GROUP BY DATE(created_at)"
        )).fetchall()
    else:
        daily_rows = db.execute(text(
            "SELECT DATE(created_at) as d, COUNT(*) as n "
            "FROM chat_logs "
            "WHERE created_at >= DATE('now','-13 days') "
            "GROUP BY DATE(created_at)"
        )).fetchall()

    daily_map = {str(r[0]): r[1] for r in daily_rows}
    daily = [
        daily_map.get((datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d"), 0)
        for i in range(13, -1, -1)
    ]

    # Hourly queries — PostgreSQL vs SQLite compatible
    if _is_pg:
        hourly_rows = db.execute(text(
            "SELECT EXTRACT(HOUR FROM created_at)::int as h, COUNT(*) as n "
            "FROM chat_logs "
            "WHERE DATE(created_at) = CURRENT_DATE "
            "GROUP BY h"
        )).fetchall()
    else:
        hourly_rows = db.execute(text(
            "SELECT CAST(STRFTIME('%H', created_at) AS INTEGER) as h, COUNT(*) as n "
            "FROM chat_logs "
            "WHERE DATE(created_at) = DATE('now') "
            "GROUP BY h"
        )).fetchall()

    hourly_map = {r[0]: r[1] for r in hourly_rows}
    hourly = [hourly_map.get(h, 0) for h in range(24)]

    # Query type distribution
    type_rows = (
        db.query(ChatLog.query_type, func.count(ChatLog.id))
        .group_by(ChatLog.query_type)
        .all()
    )
    top_query_types = {row[0]: row[1] for row in type_rows if row[0]}

    retrieval_quality = [
        {"type": "Fact lookup",  "score": 94, "queries": top_query_types.get("fact_lookup", 0)},
        {"type": "Summary",      "score": 88, "queries": top_query_types.get("summary", 0)},
        {"type": "Multi-hop",    "score": 83, "queries": top_query_types.get("multi_hop", 0)},
        {"type": "Analytical",   "score": 79, "queries": top_query_types.get("analytical", 0)},
        {"type": "Comparison",   "score": 74, "queries": top_query_types.get("comparison", 0)},
    ]

    return {
        "total_queries":    total_queries,
        "avg_latency_ms":   round(avg_latency, 1),
        "cache_hit_rate":   round(cache_rate, 1),
        "graph_usage_rate": round(graph_rate, 1),
        "avg_confidence":   round(avg_conf, 1),
        "total_users":      total_users,
        "active_rules":     active_rules,
        "security_events":  security_events,
        "daily_queries":    daily,
        "hourly_queries":   hourly,
        "retrieval_quality": retrieval_quality,
        "top_query_types":  top_query_types,
    }


@router.get("/analytics/users")
def user_analytics(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Per-user activity analytics."""
    rows = (
        db.query(
            User.id,
            User.email,
            User.name,
            User.role,
            User.risk_level,
            User.risk_score,
            User.total_queries,
            User.suspicious_queries,
            User.last_login,
        )
        .order_by(User.total_queries.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "email": r.email,
            "name": r.name,
            "role": r.role,
            "risk_level": r.risk_level or "low",
            "risk_score": r.risk_score or 0,
            "total_queries": r.total_queries or 0,
            "suspicious_queries": r.suspicious_queries or 0,
            "last_login": r.last_login.isoformat() if r.last_login else None,
        }
        for r in rows
    ]


# ── Knowledge Graph API ───────────────────────────────────────────────────────

_graph_service_cache = None

@router.get("/graph/data")
def get_graph_data(
    limit: int = Query(200, ge=10, le=1000),
    current_user: dict = Depends(require_admin),
):
    """Return graph nodes and edges from SQLite for visualization."""
    global _graph_service_cache
    try:
        if _graph_service_cache is None:
            from services.graph_service import GraphService
            _graph_service_cache = GraphService()
        return _graph_service_cache.get_all_data(limit=limit)
    except Exception as e:
        _graph_service_cache = None  # reset so next call retries
        logger.warning(f"Graph data fetch failed: {e}")
        return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}


@router.post("/graph/prune")
def prune_graph(
    min_weight: float = Query(0.2, ge=0.0, le=1.0, description="Remove edges with weight below this"),
    current_user: dict = Depends(require_admin),
):
    """
    Prune the SQLite graph: delete low-confidence edges (weight < min_weight)
    and orphan nodes, then run ANALYZE + VACUUM to reclaim space.
    Returns counts of deleted rows.
    """
    try:
        from services.graph_service import GraphService
        gs = GraphService()
        result = gs.prune_graph(min_weight=min_weight)
        gs.vacuum()
        return {**result, "vacuum": True, "min_weight_threshold": min_weight}
    except Exception as e:
        logger.error(f"Graph prune failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.get("/graph/search")
def search_graph(
    keyword: str,
    current_user: dict = Depends(require_admin),
):
    """Search for entities in the knowledge graph."""
    try:
        from services.graph_service import GraphService
        gs = GraphService()
        results = gs.search_entities(keyword)
        gs.close()
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"Graph search failed: {e}")
        return {"results": [], "count": 0}


@router.get("/graph/entity/{entity_name}")
def get_entity_relations(
    entity_name: str,
    hops: int = Query(2, ge=1, le=3),
    current_user: dict = Depends(require_admin),
):
    """Get all relationships for a specific entity."""
    try:
        from services.graph_service import GraphService
        gs = GraphService()
        results = gs.query_entity(entity_name, max_hops=hops)
        gs.close()
        return {"entity": entity_name, "relations": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"Entity query failed: {e}")
        return {"entity": entity_name, "relations": [], "count": 0}


# SharePoint is handled by app/api/sharepoint_routes.py


# ── Document Access Control Management ───────────────────────────────────────

VALID_ROLES = {"public", "user", "admin"}


class DocumentAccessRequest(BaseModel):
    filename: str
    access_roles: List[str]   # e.g. ["user", "admin"] or ["admin"] or ["public","user","admin"]


@router.put("/document/access")
def update_document_access(
    data: DocumentAccessRequest,
    current_user: dict = Depends(require_admin),
):
    """
    Update the access roles for ALL Qdrant chunks belonging to a given document.
    Only admin can call this endpoint.

    access_roles examples:
      ["admin"]                    — admin only (most restrictive, default)
      ["user", "admin"]            — authenticated users + admin
      ["public", "user", "admin"]  — everyone (least restrictive)

    Returns the number of chunks updated.
    """
    invalid = [r for r in data.access_roles if r not in VALID_ROLES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid roles: {invalid}. Allowed: {sorted(VALID_ROLES)}",
        )
    if not data.access_roles:
        raise HTTPException(status_code=400, detail="access_roles cannot be empty")

    try:
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        cfg = get_qdrant_connection()
        client = QdrantClient(host=cfg.host, port=cfg.port)
        collection = "phase1_documents"

        # Scroll to find all points for this document
        updated = 0
        offset = None
        while True:
            results, next_offset = client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="file_name", match=MatchValue(value=data.filename))]
                ),
                limit=100,
                with_payload=True,
                with_vectors=False,
                offset=offset,
            )
            if not results:
                break

            point_ids = [str(p.id) for p in results]
            # Update payload for each batch
            client.set_payload(
                collection_name=collection,
                payload={"access_roles": data.access_roles},
                points=point_ids,
            )
            updated += len(point_ids)

            if next_offset is None:
                break
            offset = next_offset

        logger.info(
            f"[DocumentAccess] Updated {updated} chunks for '{data.filename}' "
            f"→ roles: {data.access_roles}"
        )
        return {
            "status": "updated",
            "filename": data.filename,
            "access_roles": data.access_roles,
            "chunks_updated": updated,
        }

    except Exception as e:
        logger.error(f"[DocumentAccess] Failed: {e}")
        raise HTTPException(status_code=500, detail=f"Access update failed: {str(e)[:200]}")


@router.get("/document/access")
def get_document_access(
    filename: str = Query(...),
    current_user: dict = Depends(require_admin),
):
    """Get current access roles for a document's chunks."""
    try:
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        cfg = get_qdrant_connection()
        client = QdrantClient(host=cfg.host, port=cfg.port)

        results, _ = client.scroll(
            collection_name="phase1_documents",
            scroll_filter=Filter(
                must=[FieldCondition(key="file_name", match=MatchValue(value=filename))]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not results:
            raise HTTPException(status_code=404, detail=f"No chunks found for '{filename}'")

        roles = results[0].payload.get("access_roles", ["admin"])
        return {"filename": filename, "access_roles": roles}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


# ── Document Content Reader ───────────────────────────────────────────────────

@router.get("/document/read")
def read_document_content(
    filename: str = Query(..., description="Exact filename as uploaded"),
    line: Optional[int] = Query(None, ge=1, description="Specific line number (1-indexed)"),
    line_from: Optional[int] = Query(None, ge=1, description="Start of line range"),
    line_to: Optional[int] = Query(None, ge=1, description="End of line range"),
    full: bool = Query(False, description="Return full document content"),
    current_user: dict = Depends(require_admin),
):
    """
    Read exact line(s) or full content of an uploaded document.
    Admin only — returns verbatim document text.

    Examples:
      GET /admin/document/read?filename=report.pdf&line=5        → line 5
      GET /admin/document/read?filename=report.pdf&full=true     → whole doc
      GET /admin/document/read?filename=report.pdf&line_from=3&line_to=10 → lines 3-10
    """
    from services.document_reader import DocumentReader, DocumentReadRequest
    from pathlib import Path

    reader = DocumentReader()

    # Check file exists
    available = reader.list_files()
    if filename not in available:
        raise HTTPException(
            status_code=404,
            detail=f"File '{filename}' not found. Available: {', '.join(available[:10]) or 'none'}",
        )

    req = DocumentReadRequest(
        is_doc_read=True,
        filename=filename,
        line_number=line,
        is_full_doc=full or (line is None and line_from is None and line_to is None),
        line_range=(line_from, line_to) if line_from and line_to else None,
    )

    content = reader.read(req)
    lines_total = 0
    try:
        file_path = reader._resolve_file(filename)
        if file_path:
            raw_lines = reader._extract_lines(file_path)
            lines_total = len(raw_lines)
    except Exception:
        pass

    return {
        "filename": filename,
        "total_lines": lines_total,
        "requested": {
            "line": line,
            "line_from": line_from,
            "line_to": line_to,
            "full": full,
        },
        "content": content,
    }


@router.get("/document/list")
def list_uploaded_documents(current_user: dict = Depends(require_admin)):
    """List all uploaded documents with their metadata."""
    from services.document_reader import DocumentReader
    from pathlib import Path
    import os

    reader = DocumentReader()
    files = reader.list_files()
    result = []
    for fname in files:
        fpath = reader.upload_dir / fname
        try:
            size = os.path.getsize(fpath)
            mtime = os.path.getmtime(fpath)
        except Exception:
            size = 0
            mtime = 0
        result.append({
            "filename": fname,
            "size_bytes": size,
            "modified_at": datetime.utcfromtimestamp(mtime).isoformat() if mtime else None,
            "extension": Path(fname).suffix.lower(),
        })
    return {"files": result, "total": len(result)}


# ── Cache stats ──────────────────────────────────────────────────────────────

@router.get("/cache/stats")
def cache_stats(current_user: dict = Depends(require_admin)):
    """Return cache hit/miss statistics and memory usage."""
    try:
        from app.services.rag_service import _get_rag
        rag = _get_rag()
        if rag and hasattr(rag, "cache"):
            return rag.cache.stats() | {"memory_kb": rag.cache.memory_usage_kb()}
        return {"hits": 0, "misses": 0, "total_requests": 0, "hit_rate_pct": 0.0,
                "active_entries": 0, "memory_kb": 0.0}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/cache")
def clear_cache(current_user: dict = Depends(require_admin)):
    """Clear the in-memory query cache."""
    try:
        from app.services.rag_service import _get_rag
        rag = _get_rag()
        if rag and hasattr(rag, "cache"):
            rag.cache.clear()
        return {"status": "cleared"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Document delete ───────────────────────────────────────────────────────────

@router.delete("/document/{filename:path}")
def delete_document(filename: str, current_user: dict = Depends(require_admin)):
    """
    Delete a document: removes from Qdrant (all chunks), uploaded_docs folder,
    and logs the action. Filename may include path segments.
    """
    import os
    from pathlib import Path

    deleted_vectors = 0
    deleted_file = False
    errors = []

    # 1. Remove chunks from all Qdrant collections
    try:
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        cfg = get_qdrant_connection()
        client = QdrantClient(host=cfg.host, port=cfg.port)
        cols = client.get_collections().collections

        for col in cols:
            try:
                # Try matching by file_name OR filename payload field
                for field_key in ("file_name", "filename"):
                    result = client.delete(
                        collection_name=col.name,
                        points_selector=Filter(
                            must=[FieldCondition(key=field_key, match=MatchValue(value=filename))]
                        ),
                    )
                    if result and getattr(result, "deleted_count", 0):
                        deleted_vectors += result.deleted_count
            except Exception as e:
                errors.append(f"Qdrant {col.name}: {e}")
    except Exception as e:
        errors.append(f"Qdrant connection: {e}")

    # 2. Delete physical file
    upload_dirs = [Path("uploaded_docs"), Path("uploads")]
    for udir in upload_dirs:
        candidate = udir / filename
        if candidate.exists():
            try:
                candidate.unlink()
                deleted_file = True
                logger.info("[Admin] Deleted file: %s", candidate)
            except Exception as e:
                errors.append(f"File delete: {e}")

    logger.info(
        "[Admin] %s deleted document '%s' — vectors=%d file=%s",
        current_user.get("email"), filename, deleted_vectors, deleted_file,
    )

    return {
        "status": "deleted",
        "filename": filename,
        "deleted_vectors": deleted_vectors,
        "deleted_file": deleted_file,
        "errors": errors,
    }


# ── System health ─────────────────────────────────────────────────────────────

@router.get("/system/health")
def system_health(current_user: dict = Depends(require_admin)):
    """Check status of all system components."""
    statuses = {}

    # Qdrant
    try:
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        cfg = get_qdrant_connection()
        client = QdrantClient(host=cfg.host, port=cfg.port)
        cols = client.get_collections()
        vector_count = sum(
            getattr(c, "vectors_count", None) or getattr(c, "points_count", None) or 0
            for c in cols.collections
        )
        statuses["qdrant"] = {"status": "online", "vectors": vector_count}
    except Exception as e:
        statuses["qdrant"] = {"status": "offline", "error": str(e)[:80]}

    # Graph DB (SQLite-backed — always online)
    try:
        from services.graph_service import GraphService
        gs = GraphService()
        data = gs.get_all_data(limit=1)
        import sqlite3
        from pathlib import Path
        with sqlite3.connect(str(Path("cortexflow.db"))) as c:
            cnt = c.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        statuses["neo4j"] = {"status": "online", "nodes": cnt, "backend": "SQLite"}
    except Exception as e:
        statuses["neo4j"] = {"status": "offline", "error": str(e)[:80]}

    # LLM
    try:
        from core.config import get_settings
        s = get_settings()
        has_key = bool(s.cohere_api_key or s.openai_api_key)
        statuses["llm"] = {
            "status": "online" if has_key else "warn",
            "model": s.cohere_model,
        }
    except Exception as e:
        statuses["llm"] = {"status": "offline", "error": str(e)[:80]}

    # PostgreSQL
    try:
        from app.db import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        statuses["postgres"] = {"status": "online"}
    except Exception as e:
        statuses["postgres"] = {"status": "offline", "error": str(e)[:80]}

    return statuses


# ── Qdrant Chunks Viewer ──────────────────────────────────────────────────────

@router.get("/chunks")
def get_chunks(
    limit: int = Query(50, ge=1, le=200),
    search: str = Query("", description="Filter by keyword"),
    current_user: dict = Depends(require_admin),
):
    """Return stored document chunks from Qdrant for inspection."""
    try:
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        cfg = get_qdrant_connection()
        client = QdrantClient(host=cfg.host, port=cfg.port)

        collections = client.get_collections().collections
        all_chunks = []

        for col in collections:
            try:
                results, _ = client.scroll(
                    collection_name=col.name,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in results:
                    payload = point.payload or {}
                    text = payload.get("text", "")
                    if search and search.lower() not in text.lower():
                        continue
                    all_chunks.append({
                        "id": str(point.id),
                        "collection": col.name,
                        "text": text[:400],
                        "file_name": payload.get("file_name", "Unknown"),
                        "access_roles": payload.get("access_roles", []),
                    })
            except Exception as e:
                logger.warning(f"Error reading collection {col.name}: {e}")

        return {
            "total": len(all_chunks),
            "collections": [c.name for c in collections],
            "chunks": all_chunks[:limit],
        }
    except Exception as e:
        return {"total": 0, "collections": [], "chunks": [], "error": str(e)}


@router.get("/ingest-jobs")
def get_ingest_jobs(current_user: dict = Depends(require_admin)):
    """
    Return current ingest queue state: active, queued, and recently completed jobs.
    Used by the chunks page to show live ingestion progress.
    """
    try:
        from services.ingest_queue import get_ingest_queue
        q = get_ingest_queue()
        all_jobs = q.all_statuses()  # [{status, file_path, job_id, submitted_at, ...}]

        # Enrich with SharePoint source flag and human-readable name
        enriched = []
        for job in all_jobs:
            fp = job.get("file", "")
            name = job.get("original_filename") or (fp.split("/")[-1] if fp else "unknown")
            is_sharepoint = "sharepoint" in fp.lower() or ("tmp" in fp.lower() and name.lower().endswith((".pdf",".docx",".xlsx",".pptx")))
            enriched.append({
                "job_id": job.get("job_id", ""),
                "filename": name,
                "status": job.get("status", "unknown"),
                "submitted_at": job.get("submitted_at"),
                "started_at": job.get("started_at"),
                "done_at": job.get("done_at"),
                "elapsed_s": round(job.get("elapsed_s", 0), 1),
                "error": job.get("error"),
                "is_sharepoint": is_sharepoint,
                "source": "sharepoint" if is_sharepoint else "upload",
            })

        # Separate active / queued / recent-done
        active  = [j for j in enriched if j["status"] in ("processing", "queued")]
        recent  = [j for j in enriched if j["status"] in ("done", "error")][:20]

        return {
            "active_count": len(active),
            "active": active,
            "recent": recent,
            "total_processed": sum(1 for j in enriched if j["status"] == "done"),
            "total_errors": sum(1 for j in enriched if j["status"] == "error"),
        }
    except Exception as e:
        logger.warning(f"[IngestJobs] Failed: {e}")
        return {"active_count": 0, "active": [], "recent": [], "total_processed": 0, "total_errors": 0}


@router.get("/storage/info")
def storage_info(current_user: dict = Depends(require_admin)):
    """Return info about where data is stored (SQLite/PostgreSQL + Qdrant)."""
    import os

    # DB info
    from app.db import engine
    db_url = str(engine.url)
    is_sqlite = "sqlite" in db_url
    db_path = db_url.replace("sqlite:///", "") if is_sqlite else db_url

    from app.db import get_db
    from app.models import User, ChatLog, Rule
    db = next(get_db())
    user_count = db.query(User).count()
    chat_count = db.query(ChatLog).count()
    rule_count = db.query(Rule).count()
    db.close()

    db_size = 0
    if is_sqlite:
        try:
            db_size = os.path.getsize(db_path.lstrip("/"))
        except Exception:
            db_size = 0

    # Qdrant info
    qdrant_info = {"status": "offline", "collections": [], "total_vectors": 0}
    try:
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        cfg = get_qdrant_connection()
        client = QdrantClient(host=cfg.host, port=cfg.port)
        cols = client.get_collections().collections
        qdrant_info = {
            "status": "online",
            "host": f"{cfg.host}:{cfg.port}",
            "collections": [c.name for c in cols],
            "total_vectors": sum(
                getattr(client.get_collection(c.name), "points_count", 0) or 0
                for c in cols
            ),
        }
    except Exception as e:
        qdrant_info["error"] = str(e)[:100]

    return {
        "database": {
            "type": "SQLite" if is_sqlite else "PostgreSQL",
            "location": db_path if is_sqlite else "Remote PostgreSQL",
            "size_bytes": db_size,
            "users": user_count,
            "chat_logs": chat_count,
            "rules": rule_count,
        },
        "vector_store": qdrant_info,
    }


# ── Error Log endpoints ────────────────────────────────────────────────────────

@router.get("/errors")
def get_error_log(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None, description="Filter by level: ERROR, WARNING, CRITICAL"),
    current_user: dict = Depends(require_admin),
):
    """
    Return recent error log entries. Newest first.
    Optionally filter by level (ERROR / WARNING / CRITICAL).
    """
    from app.error_logger import read_recent_errors
    entries = read_recent_errors(limit=limit, level=level)
    return {"total": len(entries), "entries": entries}


@router.get("/errors/stats")
def get_error_stats(current_user: dict = Depends(require_admin)):
    """Return aggregated error statistics (counts by level and source)."""
    from app.error_logger import get_error_stats
    return get_error_stats()


@router.delete("/errors")
def clear_error_log(current_user: dict = Depends(require_admin)):
    """Truncate the error log file (admin action — irreversible)."""
    from pathlib import Path
    log_file = Path(__file__).parent.parent.parent / "logs" / "error_log.jsonl"
    txt_file = Path(__file__).parent.parent.parent / "logs" / "error_log.txt"
    try:
        if log_file.exists():
            log_file.write_text("")
        if txt_file.exists():
            txt_file.write_text("")
        logger.info("[Admin] Error log cleared by %s", current_user.get("email"))
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not clear log: {e}")


# ── API Key Management ────────────────────────────────────────────────────────

class ApiKeyCreateRequest(BaseModel):
    name: str
    permissions: str = "read"          # "read" or "read_write"
    expires_days: Optional[int] = None  # None = never expires
    notes: Optional[str] = None


@router.post("/api-keys")
def create_api_key(
    data: ApiKeyCreateRequest,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Generate a new external API key.

    Permissions:
      read       → maps to 'user' role (can query /ask, /chat/history)
      read_write → maps to 'admin' role (can query + upload + full access)

    The raw key is returned ONCE — it cannot be retrieved again.
    Share it with the integration team and store it securely.

    Integration example:
      curl -X POST https://your-domain/ask \\
           -H "X-API-Key: cf_live_XXXX..." \\
           -H "Content-Type: application/json" \\
           -d '{"question": "What is contract 511047?"}'
    """
    from services.api_key_service import create_api_key as svc_create
    if data.permissions not in ("read", "read_write"):
        raise HTTPException(status_code=400, detail="permissions must be 'read' or 'read_write'")
    return svc_create(
        db=db,
        name=data.name,
        created_by=current_user["user_id"],
        permissions=data.permissions,
        expires_days=data.expires_days,
        notes=data.notes,
    )


@router.get("/api-keys")
def list_api_keys(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all API keys (active and revoked). Raw key is never returned."""
    from services.api_key_service import list_api_keys as svc_list
    keys = svc_list(db)
    # Return flat list so frontend Array.isArray() works correctly
    return keys


@router.get("/api-keys/{key_id}")
def get_api_key(
    key_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get detail + last 50 usage entries for a specific API key."""
    from services.api_key_service import get_api_key_detail
    detail = get_api_key_detail(db, key_id)
    if not detail:
        raise HTTPException(status_code=404, detail="API key not found")
    return detail


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke an API key immediately. All future requests with this key will fail."""
    from services.api_key_service import revoke_api_key as svc_revoke
    ok = svc_revoke(db, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked", "key_id": key_id}


@router.patch("/api-keys/{key_id}/activate")
def reactivate_api_key(
    key_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Re-activate a previously revoked API key."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = True
    db.commit()
    return {"status": "activated", "key_id": key_id}



@router.get("/health/services")
def get_service_health(current_user: dict = Depends(require_admin)):
    """
    Returns current health status of Neo4j, Qdrant, and other services.
    Checked by background monitor every 30 seconds.
    """
    from services.health_monitor import get_health_status
    return get_health_status()


# ── Scheduler admin endpoints ──────────────────────────────────────────────────

class SchedulerTriggerRequest(BaseModel):
    source_id: str


class SchedulerRegisterRequest(BaseModel):
    url: str
    source_type: str = "website"
    priority: str = "medium"
    tenant_id: str = ""


@router.get("/scheduler/status")
def scheduler_status(current_user: dict = Depends(require_admin)):
    """Get full scheduler status: running, queue depth, all sources with next-run times."""
    from services.scheduler_service import get_scheduler
    return get_scheduler().get_status()


@router.post("/scheduler/trigger")
def scheduler_trigger(
    req: SchedulerTriggerRequest,
    current_user: dict = Depends(require_admin),
):
    """Manually trigger a full re-crawl for a specific source immediately."""
    from services.scheduler_service import get_scheduler
    ok = get_scheduler().trigger_full_crawl(req.source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found in scheduler registry")
    return {"status": "triggered", "source_id": req.source_id}


@router.post("/scheduler/pause/{source_id}")
def scheduler_pause(
    source_id: str,
    current_user: dict = Depends(require_admin),
):
    """Pause scheduling for a source (won't trigger auto-updates)."""
    from services.scheduler_service import get_scheduler
    get_scheduler().pause_source(source_id)
    return {"status": "paused", "source_id": source_id}


@router.post("/scheduler/resume/{source_id}")
def scheduler_resume(
    source_id: str,
    current_user: dict = Depends(require_admin),
):
    """Resume scheduling for a paused source (triggers immediately)."""
    from services.scheduler_service import get_scheduler
    get_scheduler().resume_source(source_id)
    return {"status": "resumed", "source_id": source_id}


@router.delete("/scheduler/source/{source_id}")
def scheduler_unregister(
    source_id: str,
    current_user: dict = Depends(require_admin),
):
    """Remove a source from the scheduler registry (does not delete vectors)."""
    from services.scheduler_service import get_scheduler
    get_scheduler().unregister_source(source_id)
    return {"status": "unregistered", "source_id": source_id}


@router.get("/storage/status")
def storage_status(current_user: dict = Depends(require_admin)):
    """Return the active storage backend (minio or local) and config."""
    from services.storage_service import get_storage_service
    svc = get_storage_service()
    return {
        "backend":       svc.backend,
        "description":   "MinIO object storage" if svc.backend == "minio" else "Local filesystem (dev mode)",
        "recommendation": None if svc.backend == "minio" else "Set MINIO_ENDPOINT in .env to enable MinIO for production",
    }


@router.get("/cache/status")
def cache_status(current_user: dict = Depends(require_admin)):
    """Return cache backend and stats including live Redis key count."""
    result: dict = {}
    # Get in-process cache stats
    try:
        from app.services.rag_service import _get_rag
        rag = _get_rag()
        if rag and hasattr(rag, "cache"):
            result = rag.cache.stats()
            result["memory_kb"] = rag.cache.memory_usage_kb()
    except Exception as e:
        result = {"error": str(e)}

    # Always probe Redis directly for live key count
    try:
        import redis as _redis
        from core.config import get_settings
        settings = get_settings()
        redis_url = getattr(settings, "redis_url", "") or ""
        if redis_url:
            rc = _redis.from_url(redis_url, socket_timeout=1.0)
            rc.ping()
            cf_keys = rc.keys("cf:*")
            result["redis_live"] = True
            result["redis_cached_queries"] = len(cf_keys)
            result["redis_sample_keys"] = [k.decode()[:80] for k in sorted(cf_keys)[:5]]
            # Override backend name if Redis probe succeeded
            result["backend"] = "redis"
    except Exception:
        result["redis_live"] = False

    return result

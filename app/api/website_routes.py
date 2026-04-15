"""
Website Scraper API Routes.

Admin-facing:
  POST /website/connect       — start deep-crawl of an org URL
  POST /website/disconnect    — stop a crawl and optionally remove vectors
  GET  /website/status        — all active crawl connections
  GET  /website/status/{id}   — single connection status
  POST /website/refresh/{id}  — trigger re-crawl (incremental)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/website", tags=["website"])


# ── Request models ─────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    url: str
    org_name: Optional[str] = ""


class DisconnectRequest(BaseModel):
    connection_id: str
    remove_vectors: bool = False


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/connect")
def connect_website(
    req: ConnectRequest,
    current_user: dict = Depends(require_admin),
):
    """
    Start a background deep-crawl of an organization's website.
    Returns connection_id immediately; crawl runs in the background.
    Poll GET /website/status/{connection_id} to track progress.
    """
    from services.website_crawler import get_website_crawler

    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not url.startswith("http"):
        url = "https://" + url

    try:
        crawler = get_website_crawler()
        connection_id = crawler.connect(url, org_name=req.org_name or "")

        # Register with scheduler for automatic periodic re-crawls
        try:
            from services.scheduler_service import get_scheduler
            scheduler = get_scheduler()
            scheduler.register_source(
                url=url,
                source_type="website",
                priority="medium",
                connection_id=connection_id,
            )
        except Exception as sched_err:
            logger.warning("[Website] Scheduler registration failed (non-fatal): %s", sched_err)

        return {
            "status": "started",
            "connection_id": connection_id,
            "url": url,
            "message": (
                "Crawl started. Pages will appear in the knowledge base as they are indexed. "
                "Poll /website/status/{connection_id} for progress. "
                "Automatic re-crawls are scheduled every 2 hours."
            ),
        }
    except Exception as e:
        logger.error("[Website] Connect failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to start crawl: {str(e)[:300]}")


@router.post("/disconnect")
def disconnect_website(
    req: DisconnectRequest,
    current_user: dict = Depends(require_admin),
):
    """Stop a crawl. Optionally delete all vectors indexed from this connection."""
    from services.website_crawler import get_website_crawler

    try:
        crawler = get_website_crawler()
        conn = crawler.get_status(req.connection_id)
        if conn is None:
            raise HTTPException(status_code=404, detail="Connection not found")

        crawler.disconnect(req.connection_id)

        if req.remove_vectors:
            _remove_connection_vectors(req.connection_id)

        return {
            "status": "disconnected",
            "connection_id": req.connection_id,
            "vectors_removed": req.remove_vectors,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Website] Disconnect failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Disconnect failed: {str(e)[:300]}")


@router.get("/status")
def all_website_statuses(
    current_user: dict = Depends(require_admin),
):
    """Return all active website crawl connections."""
    from services.website_crawler import get_website_crawler

    crawler = get_website_crawler()
    return {"connections": crawler.get_all_statuses()}


@router.get("/status/{connection_id}")
def website_status(
    connection_id: str,
    current_user: dict = Depends(require_admin),
):
    """Return status for a single crawl connection."""
    from services.website_crawler import get_website_crawler

    crawler = get_website_crawler()
    status = crawler.get_status(connection_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return status


@router.post("/refresh/{connection_id}")
def refresh_website(
    connection_id: str,
    current_user: dict = Depends(require_admin),
):
    """Trigger an incremental re-crawl for an existing connection."""
    from services.website_crawler import get_website_crawler

    crawler = get_website_crawler()
    started = crawler.refresh_crawl(connection_id)
    if not started:
        raise HTTPException(
            status_code=409,
            detail="Crawl already in progress or connection not found"
        )
    return {"status": "refreshing", "connection_id": connection_id}


@router.get("/nav-graph/{connection_id}")
def get_nav_graph(
    connection_id: str,
    current_user: dict = Depends(require_admin),
):
    """Return the full navigation graph for a crawled website."""
    from services.website_crawler import get_website_crawler

    crawler = get_website_crawler()
    graph = crawler.get_nav_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"connection_id": connection_id, "nav_graph": graph, "total_pages": len(graph)}


# ── Helper ──────────────────────────────────────────────────────────────────────

def _remove_connection_vectors(connection_id: str):
    """Delete all Qdrant vectors for a website connection."""
    try:
        from services.embedding_service import get_embedding_service
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        embedder = get_embedding_service()
        if embedder is None:
            return
        embedder.qdrant.delete(
            collection_name="phase1_documents",
            points_selector=Filter(
                must=[FieldCondition(
                    key="connection_id",
                    match=MatchValue(value=connection_id)
                )]
            ),
        )
        logger.info("[Website] Removed vectors for connection %s", connection_id)
    except Exception as e:
        logger.warning("[Website] Vector removal failed: %s", e)

"""
SharePoint API Routes.

Admin-facing:
  POST /sharepoint/connect      — paste SP URL, click Connect
  POST /sharepoint/disconnect   — disconnect a connection
  GET  /sharepoint/status       — get all connections + file counts

Public (called by MS Graph — no auth token, validated by clientState):
  POST /sharepoint/webhook      — receives push notifications from MS Graph
  GET  /sharepoint/webhook      — webhook validation handshake (validationToken)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sharepoint", tags=["sharepoint"])


# ── Request models ────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    site_url: str


class DisconnectRequest(BaseModel):
    connection_id: str


# ── Admin endpoints ───────────────────────────────────────────────────────────

@router.post("/connect")
def connect_sharepoint(
    req: ConnectRequest,
    current_user: dict = Depends(require_admin),
):
    """
    Connect to a SharePoint site.
    Resolves the site via MS Graph, registers webhooks (if notification URL is
    configured), and kicks off an initial delta sync to index existing files.
    The connection stays active until admin clicks Disconnect.
    """
    from services.sharepoint_service import get_sharepoint_service

    site_url = req.site_url.strip()
    if not site_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Site URL must start with https://")

    # Check for an existing active connection for this URL
    try:
        from app.db import SessionLocal
        from app.models import SharePointConnection
        db = SessionLocal()
        try:
            existing = db.query(SharePointConnection).filter_by(
                site_url=site_url, status="connected"
            ).first()
            if existing:
                return {
                    "status": "already_connected",
                    "connection_id": existing.id,
                    "site_display_name": existing.site_display_name,
                    "message": "This SharePoint site is already connected.",
                }
        finally:
            db.close()
    except Exception:
        pass

    try:
        svc = get_sharepoint_service()
        result = svc.connect(site_url, admin_user_id=current_user.get("sub", ""))
        return {
            "status": "connected",
            **result,
            "message": (
                f"Connected to {result.get('site_display_name', site_url)}. "
                "Initial sync started — documents will appear in the knowledge base within minutes."
            ),
        }
    except RuntimeError as e:
        err = str(e)
        if "credentials not configured" in err:
            raise HTTPException(
                status_code=503,
                detail=(
                    "SharePoint credentials not configured. "
                    "Set SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET in .env"
                ),
            )
        raise HTTPException(status_code=502, detail=err[:400])
    except Exception as e:
        logger.error("[SP Connect] Failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Connection failed: {str(e)[:400]}")


@router.post("/disconnect")
def disconnect_sharepoint(
    req: DisconnectRequest,
    current_user: dict = Depends(require_admin),
):
    """Disconnect a SharePoint site. Deletes webhook subscriptions and stops sync."""
    from services.sharepoint_service import get_sharepoint_service

    try:
        svc = get_sharepoint_service()
        result = svc.disconnect(req.connection_id)
        return {**result, "message": "SharePoint site disconnected successfully."}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("[SP Disconnect] Failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Disconnect failed: {str(e)[:300]}")


@router.get("/status")
def sharepoint_status(
    current_user: dict = Depends(require_admin),
):
    """Return all SharePoint connections with file counts and sync status."""
    from services.sharepoint_service import get_sharepoint_service

    try:
        svc = get_sharepoint_service()
        return svc.get_status()
    except Exception as e:
        logger.error("[SP Status] Failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {str(e)[:300]}")


# ── Webhook endpoints (called by MS Graph, no auth token) ─────────────────────

@router.get("/webhook")
async def webhook_validation(
    validationToken: Optional[str] = Query(None),
):
    """
    MS Graph webhook validation handshake.
    When registering a subscription, Graph sends a GET with ?validationToken=...
    We must echo it back as plain text within 10 seconds.
    """
    if validationToken:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=validationToken, status_code=200)
    return {"status": "webhook endpoint active"}


@router.post("/webhook")
async def webhook_receiver(request: Request):
    """
    Receive push notifications from MS Graph.
    MS Graph posts a JSON body with a list of change notifications.
    We validate the clientState and push events to the ingest pipeline.
    Returns 202 immediately — never block webhook delivery.
    """
    from fastapi.responses import Response

    try:
        body = await request.json()
    except Exception:
        return Response(status_code=202)

    notifications = body.get("value", [])

    # Validate clientState to ensure requests come from our own subscriptions
    valid = [
        n for n in notifications
        if n.get("clientState") == "cortexflow-sp"
    ]

    if valid:
        try:
            from services.sharepoint_service import get_sharepoint_service
            import threading
            svc = get_sharepoint_service()
            # Process in background — never block the 202 response
            threading.Thread(
                target=svc.handle_webhook_notification,
                args=(valid,),
                daemon=True,
            ).start()
        except Exception as e:
            logger.error("[SP Webhook] Handler error: %s", e)

    # MS Graph requires 202 Accepted within the timeout window
    return Response(status_code=202)

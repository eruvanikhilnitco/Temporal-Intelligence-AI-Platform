"""
SharePoint Service — event-driven ingestion architecture.

Design (from sharepoint.txt):
  1.  Admin pastes a SharePoint site URL and clicks Connect.
  2.  Backend resolves the site, discovers all document library drives, and
      creates a webhook subscription for each drive (push notifications).
  3.  Webhook fires on file create/update/delete → task pushed to ingest queue.
  4.  Background worker checks metadata registry (SharePointFile table) by
      stable item ID (survives renames).  Changed files are re-embedded atomically
      (insert new version → delete old version).  Deleted files are removed from Qdrant.
  5.  Delta sync (every DELTA_SYNC_INTERVAL seconds) fetches only changed metadata
      using MS Graph's delta() API and queues any missed events — reliable fallback.
  6.  Webhook subscriptions expire (MS Graph max ~29 days for SP); a renewal
      background thread refreshes them automatically.
  7.  At query time Qdrant is queried exclusively — SharePoint is never hit at runtime.

Webhook delivery requires a publicly routable HTTPS URL:
  Set SHAREPOINT_NOTIFICATION_URL in .env, e.g.:
    SHAREPOINT_NOTIFICATION_URL=https://your-public-host.com
  If unset, webhooks are skipped and delta sync alone provides freshness.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".pdf", ".txt", ".docx", ".pptx", ".xlsx", ".csv", ".json", ".xml", ".html", ".md"}
# How many seconds before webhook expiry to trigger renewal
WEBHOOK_RENEW_BEFORE_SECS = 3 * 24 * 3600   # 3 days
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ── Graph API helpers ─────────────────────────────────────────────────────────

def _get_token() -> str:
    """Client credentials OAuth2 token from Azure AD."""
    from core.config import get_settings
    cfg = get_settings()

    tenant = cfg.sharepoint_tenant_id
    client_id = cfg.sharepoint_client_id
    client_secret = cfg.sharepoint_client_secret

    if not (tenant and client_id and client_secret):
        raise RuntimeError(
            "SharePoint credentials not configured. "
            "Set SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET in .env"
        )

    resp = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f"Token request failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["access_token"]


def _graph_get(url: str, token: str, params: dict = None) -> dict:
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Graph GET {url} → {r.status_code}: {r.text[:300]}")
    return r.json()


def _graph_post(url: str, token: str, body: dict) -> dict:
    r = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Graph POST {url} → {r.status_code}: {r.text[:300]}")
    return r.json()


def _graph_patch(url: str, token: str, body: dict) -> dict:
    r = requests.patch(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Graph PATCH {url} → {r.status_code}: {r.text[:300]}")
    return r.json()


def _graph_delete(url: str, token: str):
    requests.delete(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def _parse_site_url(site_url: str):
    """Extract (hostname, site_name) from a SharePoint site URL."""
    m = re.search(r"https://([^/]+)/sites/([^/?#]+)", site_url)
    if not m:
        raise ValueError(
            f"Cannot parse SharePoint site URL: {site_url!r}. "
            "Expected: https://yourcompany.sharepoint.com/sites/YourSite"
        )
    return m.group(1), m.group(2)


# ── Core service ──────────────────────────────────────────────────────────────

class SharePointService:
    """
    Manages SharePoint connections, webhooks, delta sync, and file ingestion.
    One instance is created at startup and lives for the process lifetime.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # connection_id → threading.Timer for delta sync
        self._delta_timers: Dict[str, threading.Timer] = {}
        # threading.Timer for webhook renewal
        self._renewal_timer: Optional[threading.Timer] = None

    # ── Connect ───────────────────────────────────────────────────────────────

    def connect(self, site_url: str, admin_user_id: str) -> dict:
        """
        Establish a persistent connection to a SharePoint site.
        1. Resolve site + drives via Graph API.
        2. Register webhook subscriptions (if notification URL is configured).
        3. Persist SharePointConnection record.
        4. Kick off initial delta sync to index existing documents.
        Returns the connection record as a dict.
        """
        from app.db import SessionLocal
        from app.models import SharePointConnection

        token = _get_token()
        hostname, site_name = _parse_site_url(site_url)

        # Resolve site
        site_info = _graph_get(
            f"{GRAPH_BASE}/sites/{hostname}:/sites/{site_name}", token
        )
        site_id = site_info["id"]
        site_display = site_info.get("displayName", site_name)

        # Get all document library drives
        drives_data = _graph_get(f"{GRAPH_BASE}/sites/{site_id}/drives", token)
        drives: List[dict] = drives_data.get("value", [])
        if not drives:
            raise RuntimeError(f"No document libraries found for site: {site_id}")

        # Register webhook subscriptions
        from core.config import get_settings
        cfg = get_settings()
        notification_url = cfg.sharepoint_notification_url.rstrip("/")
        subscription_ids: List[str] = []
        webhook_expiry: Optional[datetime] = None

        if notification_url:
            for drive in drives:
                drive_id = drive["id"]
                try:
                    sub_id, expiry = self._create_subscription(drive_id, notification_url, token)
                    subscription_ids.append(sub_id)
                    if webhook_expiry is None or expiry < webhook_expiry:
                        webhook_expiry = expiry
                    logger.info("[SP] Webhook created for drive %s: %s", drive_id, sub_id)
                except Exception as e:
                    logger.warning("[SP] Webhook creation failed for drive %s: %s", drive_id, e)
        else:
            logger.info("[SP] SHAREPOINT_NOTIFICATION_URL not set — webhooks skipped, delta sync only")

        # Persist connection
        db = SessionLocal()
        try:
            conn = SharePointConnection(
                id=str(uuid.uuid4()),
                site_url=site_url,
                site_id=site_id,
                site_display_name=site_display,
                status="connected",
                webhook_subscription_ids=subscription_ids,
                webhook_expiry=webhook_expiry,
                delta_token=None,
                connected_by=admin_user_id,
                connected_at=datetime.utcnow(),
            )
            db.add(conn)
            db.commit()
            db.refresh(conn)
            connection_id = conn.id
            result = {
                "id": conn.id,
                "site_url": conn.site_url,
                "site_display_name": conn.site_display_name,
                "status": conn.status,
                "webhooks": len(subscription_ids),
                "connected_at": conn.connected_at.isoformat(),
            }
        finally:
            db.close()

        # Start delta sync loop (runs initial sync + schedules recurring)
        self._schedule_delta_sync(connection_id)

        # Start webhook renewal scheduler
        self._schedule_renewal()

        return result

    # ── Disconnect ────────────────────────────────────────────────────────────

    def disconnect(self, connection_id: str) -> dict:
        """Delete webhook subscriptions and mark connection as disconnected."""
        from app.db import SessionLocal
        from app.models import SharePointConnection

        db = SessionLocal()
        try:
            conn = db.query(SharePointConnection).filter_by(id=connection_id).first()
            if not conn:
                raise ValueError(f"Connection {connection_id} not found")
            if conn.status == "disconnected":
                return {"status": "already_disconnected"}

            # Delete webhook subscriptions
            try:
                token = _get_token()
                for sub_id in (conn.webhook_subscription_ids or []):
                    try:
                        _graph_delete(f"{GRAPH_BASE}/subscriptions/{sub_id}", token)
                        logger.info("[SP] Deleted subscription %s", sub_id)
                    except Exception as e:
                        logger.warning("[SP] Failed to delete subscription %s: %s", sub_id, e)
            except Exception as e:
                logger.warning("[SP] Token fetch failed during disconnect: %s", e)

            conn.status = "disconnected"
            conn.disconnected_at = datetime.utcnow()
            conn.webhook_subscription_ids = []
            db.commit()

            # Cancel delta sync timer
            with self._lock:
                timer = self._delta_timers.pop(connection_id, None)
            if timer:
                timer.cancel()

            return {"status": "disconnected", "connection_id": connection_id}
        finally:
            db.close()

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return all SharePoint connections and their status."""
        from app.db import SessionLocal
        from app.models import SharePointConnection, SharePointFile

        db = SessionLocal()
        try:
            conns = db.query(SharePointConnection).all()
            result = []
            for c in conns:
                file_count = db.query(SharePointFile).filter_by(
                    connection_id=c.id, indexed_status="indexed"
                ).count()
                result.append({
                    "id": c.id,
                    "site_url": c.site_url,
                    "site_display_name": c.site_display_name,
                    "status": c.status,
                    "file_count": file_count,
                    "webhooks": len(c.webhook_subscription_ids or []),
                    "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
                    "connected_at": c.connected_at.isoformat() if c.connected_at else None,
                    "disconnected_at": c.disconnected_at.isoformat() if c.disconnected_at else None,
                    "last_error": c.last_error,
                })
            return {"connections": result, "total": len(result)}
        finally:
            db.close()

    # ── Webhook handler ───────────────────────────────────────────────────────

    def handle_webhook_notification(self, notifications: List[dict]):
        """
        Process incoming MS Graph webhook notifications.
        Each notification references a subscriptionId + resource path.
        Push affected file IDs to the ingest queue — do not block here.
        """
        for note in notifications:
            sub_id = note.get("subscriptionId", "")
            resource = note.get("resource", "")      # e.g. "drives/{driveId}/root"
            change_type = note.get("changeType", "")

            logger.info("[SP Webhook] notification: sub=%s resource=%s change=%s",
                        sub_id, resource, change_type)

            # Extract drive ID from resource path
            m = re.search(r"drives/([^/]+)", resource)
            if not m:
                continue
            drive_id = m.group(1)

            # Find connection for this subscription
            connection_id = self._connection_for_subscription(sub_id)
            if not connection_id:
                logger.warning("[SP Webhook] No connection found for sub %s", sub_id)
                continue

            # Schedule an immediate delta sync for this connection rather than
            # fetching individual items (simpler, handles batch notifications)
            threading.Thread(
                target=self._run_delta_sync,
                args=(connection_id,),
                daemon=True,
                name=f"sp-webhook-sync-{connection_id[:8]}",
            ).start()

    # ── Delta sync ────────────────────────────────────────────────────────────

    def _schedule_delta_sync(self, connection_id: str, startup_delay: float = 0.0):
        """Run delta sync now (optionally after a delay), then schedule the next run."""
        def _start():
            if startup_delay > 0:
                time.sleep(startup_delay)
            self._run_delta_sync_and_reschedule(connection_id)

        threading.Thread(
            target=_start,
            daemon=True,
            name=f"sp-delta-{connection_id[:8]}",
        ).start()

    def _run_delta_sync_and_reschedule(self, connection_id: str):
        from core.config import get_settings
        self._run_delta_sync(connection_id)
        interval = get_settings().sharepoint_delta_sync_interval
        timer = threading.Timer(interval, self._run_delta_sync_and_reschedule, args=(connection_id,))
        timer.daemon = True
        timer.start()
        with self._lock:
            self._delta_timers[connection_id] = timer

    def _run_delta_sync(self, connection_id: str):
        """
        Fetch changed metadata from MS Graph using delta() tracking.
        Processes only files that are new, modified, or deleted since last sync.
        """
        from app.db import SessionLocal
        from app.models import SharePointConnection

        db = SessionLocal()
        try:
            conn = db.query(SharePointConnection).filter_by(id=connection_id).first()
            if not conn or conn.status != "connected":
                return

            try:
                token = _get_token()
            except Exception as e:
                self._save_error(db, conn, f"Token error: {e}")
                return

            # Get all drives for the site
            try:
                drives_data = _graph_get(f"{GRAPH_BASE}/sites/{conn.site_id}/drives", token)
                drives = drives_data.get("value", [])
            except Exception as e:
                self._save_error(db, conn, f"Drive list error: {e}")
                return

            for drive in drives:
                drive_id = drive["id"]
                try:
                    self._delta_sync_drive(db, conn, drive_id, token)
                except Exception as e:
                    logger.error("[SP Delta] Drive %s sync error: %s", drive_id, e)

            conn.last_sync_at = datetime.utcnow()
            conn.last_error = None
            db.commit()
            logger.info("[SP Delta] Sync complete for connection %s", connection_id)

        except Exception as e:
            logger.error("[SP Delta] Unexpected error for %s: %s", connection_id, e)
        finally:
            db.close()

    def _delta_sync_drive(self, db, conn, drive_id: str, token: str):
        """
        Use MS Graph drive delta() to get only changed items since last deltaToken.
        Processes creates, updates, and deletes.
        """
        from app.models import SharePointFile

        # Build delta URL: use stored deltaLink if available, else start fresh
        delta_key = f"{conn.id}:{drive_id}"
        stored_delta = self._load_delta_token(db, conn.id, drive_id)

        if stored_delta:
            url = stored_delta  # full delta URL including previous token
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/delta"

        all_items = []
        next_delta_url = None

        while url:
            try:
                data = _graph_get(url, token)
            except Exception as e:
                logger.error("[SP Delta] delta fetch failed: %s", e)
                break

            items = data.get("value", [])
            all_items.extend(items)

            # Follow @odata.nextLink for pagination; save @odata.deltaLink when done
            if "@odata.nextLink" in data:
                url = data["@odata.nextLink"]
            elif "@odata.deltaLink" in data:
                next_delta_url = data["@odata.deltaLink"]
                url = None
            else:
                url = None

        # Process changed items FIRST — save deltaLink only after successful processing.
        # This ensures that if ingest fails mid-batch, the next delta sync retries
        # the same items rather than skipping them permanently.
        for item in all_items:
            item_id = item.get("id")
            if not item_id:
                continue

            # Deleted items have "deleted" facet
            if "deleted" in item:
                self._handle_deleted_file(db, conn, drive_id, item_id)
                continue

            # Skip folders
            if "folder" in item:
                continue

            # Skip unsupported file types
            name = item.get("name", "")
            ext = os.path.splitext(name)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue

            last_modified_str = item.get("lastModifiedDateTime")
            last_modified = _parse_dt(last_modified_str)
            size = item.get("size", 0)
            folder_path = item.get("parentReference", {}).get("path", "")

            # Check metadata registry
            existing = db.query(SharePointFile).filter_by(
                sharepoint_file_id=item_id
            ).first()

            if existing:
                # Update file name in registry (handles renames — name changed, ID unchanged)
                if existing.file_name != name:
                    logger.info("[SP Delta] Rename detected: %s → %s", existing.file_name, name)
                    existing.file_name = name
                    # Update Qdrant payload file_name in place
                    self._update_qdrant_filename(item_id, name)
                    db.commit()

                # Skip if not actually modified (same size and timestamp)
                if (existing.last_modified and last_modified and
                        existing.last_modified >= last_modified and
                        existing.file_size_bytes == size):
                    continue

                # File was updated — queue for re-ingestion
                self._queue_file_for_ingest(
                    db, conn, drive_id, item_id, name, folder_path,
                    last_modified, size, is_update=True, existing=existing
                )
            else:
                # New file — queue for ingestion
                self._queue_file_for_ingest(
                    db, conn, drive_id, item_id, name, folder_path,
                    last_modified, size, is_update=False
                )

        # Save deltaLink AFTER all items processed — so failed ingests retry next cycle
        if next_delta_url:
            self._save_delta_token(db, conn.id, drive_id, next_delta_url)

    # ── File ingestion ────────────────────────────────────────────────────────

    def _queue_file_for_ingest(
        self, db, conn, drive_id: str, item_id: str, name: str,
        folder_path: str, last_modified: Optional[datetime], size: int,
        is_update: bool, existing=None
    ):
        """Download the file, compute hash, skip if unchanged, else ingest."""
        from app.models import SharePointFile

        try:
            token = _get_token()
            content, content_hash = self._download_file(drive_id, item_id, token)
        except Exception as e:
            logger.error("[SP Ingest] Download failed for %s (%s): %s", name, item_id, e)
            self._mark_file_error(db, conn, item_id, name, folder_path,
                                  drive_id, last_modified, size, str(e))
            return

        # Skip if content unchanged (hash match)
        if existing and existing.content_hash == content_hash:
            logger.info("[SP Ingest] Skipping unchanged file (hash match): %s", name)
            existing.last_modified = last_modified
            existing.updated_at = datetime.utcnow()
            db.commit()
            return

        new_version = (existing.version + 1) if existing else 1

        # Write to temp dir using original filename so ingest_file stores the real name
        ext = os.path.splitext(name)[1].lower()
        tmp_dir = tempfile.mkdtemp(prefix="sp_ingest_")
        tmp_path = os.path.join(tmp_dir, name)
        with open(tmp_path, "wb") as f:
            f.write(content)

        try:
            from app.services.rag_service import ingest_file, _get_rag
            # Wait up to 120s for RAG to become ready (model loading on startup)
            _rag_wait = 0
            while _get_rag() is None and _rag_wait < 120:
                logger.info("[SP Ingest] RAG not ready, waiting… (%ds)", _rag_wait)
                time.sleep(5)
                _rag_wait += 5
            if _get_rag() is None:
                raise RuntimeError("RAG service unavailable after 120s wait — embedding model may have failed to load")

            ingest_file(
                tmp_path,
                sharepoint_file_id=item_id,
                sharepoint_folder_path=folder_path,
                version=new_version,
            )
            logger.info("[SP Ingest] Ingested: %s (v%d)", name, new_version)

            # After successful ingest of new version, delete old vectors
            if is_update and existing:
                self._delete_old_vectors(item_id, old_version=existing.version)

            # Upsert metadata registry
            if existing:
                existing.file_name = name
                existing.folder_path = folder_path
                existing.last_modified = last_modified
                existing.content_hash = content_hash
                existing.version = new_version
                existing.file_size_bytes = size
                existing.indexed_status = "indexed"
                existing.error_message = None
                existing.updated_at = datetime.utcnow()
            else:
                sp_file = SharePointFile(
                    connection_id=conn.id,
                    sharepoint_file_id=item_id,
                    file_name=name,
                    folder_path=folder_path,
                    drive_id=drive_id,
                    site_id=conn.site_id,
                    last_modified=last_modified,
                    content_hash=content_hash,
                    version=new_version,
                    indexed_status="indexed",
                    file_size_bytes=size,
                    chunk_count=0,
                )
                db.add(sp_file)

            db.commit()

        except Exception as e:
            logger.error("[SP Ingest] Ingest error for %s: %s", name, e)
            self._mark_file_error(db, conn, item_id, name, folder_path,
                                  drive_id, last_modified, size, str(e), existing)
        finally:
            try:
                os.unlink(tmp_path)
                os.rmdir(tmp_dir)
            except Exception:
                pass

    def _handle_deleted_file(self, db, conn, drive_id: str, item_id: str):
        """Remove Qdrant vectors and mark file as deleted in registry."""
        from app.models import SharePointFile

        existing = db.query(SharePointFile).filter_by(sharepoint_file_id=item_id).first()
        if not existing:
            return

        logger.info("[SP] File deleted: %s (%s)", existing.file_name, item_id)
        self._delete_vectors_by_file_id(item_id)
        existing.indexed_status = "deleted"
        existing.updated_at = datetime.utcnow()
        db.commit()

    # ── Qdrant vector management ──────────────────────────────────────────────

    def _delete_old_vectors(self, sharepoint_file_id: str, old_version: int):
        """Delete vectors for old version of a file (atomic update step 2)."""
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            qdrant = self._get_qdrant()
            qdrant.delete(
                collection_name="phase1_documents",
                points_selector=Filter(
                    must=[
                        FieldCondition(key="sharepoint_file_id",
                                       match=MatchValue(value=sharepoint_file_id)),
                        FieldCondition(key="version",
                                       match=MatchValue(value=old_version)),
                    ]
                ),
            )
            logger.info("[SP] Deleted old vectors for %s v%d", sharepoint_file_id, old_version)
        except Exception as e:
            logger.warning("[SP] Old vector deletion failed: %s", e)

    def _delete_vectors_by_file_id(self, sharepoint_file_id: str):
        """Delete all vectors for a file (on delete event)."""
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            qdrant = self._get_qdrant()
            qdrant.delete(
                collection_name="phase1_documents",
                points_selector=Filter(
                    must=[FieldCondition(key="sharepoint_file_id",
                                        match=MatchValue(value=sharepoint_file_id))]
                ),
            )
            logger.info("[SP] Deleted all vectors for file_id %s", sharepoint_file_id)
        except Exception as e:
            logger.warning("[SP] Vector deletion failed for %s: %s", sharepoint_file_id, e)

    def _update_qdrant_filename(self, sharepoint_file_id: str, new_name: str):
        """Update the file_name payload field in Qdrant on rename (no re-embed needed)."""
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            qdrant = self._get_qdrant()
            qdrant.set_payload(
                collection_name="phase1_documents",
                payload={"file_name": new_name},
                points=Filter(
                    must=[FieldCondition(key="sharepoint_file_id",
                                        match=MatchValue(value=sharepoint_file_id))]
                ),
            )
        except Exception as e:
            logger.warning("[SP] Qdrant filename update failed: %s", e)

    def _get_qdrant(self):
        from core.database import get_qdrant_connection
        from qdrant_client import QdrantClient
        cfg = get_qdrant_connection()
        return QdrantClient(host=cfg.host, port=cfg.port)

    # ── Webhook management ────────────────────────────────────────────────────

    def _create_subscription(self, drive_id: str, notification_url: str, token: str):
        """Create a MS Graph webhook subscription for a drive. Returns (sub_id, expiry_dt)."""
        expiry = datetime.utcnow() + timedelta(days=29)  # MS Graph max
        body = {
            "changeType": "created,updated,deleted",
            "notificationUrl": f"{notification_url}/sharepoint/webhook",
            "resource": f"/drives/{drive_id}/root",
            "expirationDateTime": expiry.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
            "clientState": "cortexflow-sp",
        }
        data = _graph_post(f"{GRAPH_BASE}/subscriptions", token, body)
        sub_id = data["id"]
        actual_expiry = _parse_dt(data.get("expirationDateTime")) or expiry
        return sub_id, actual_expiry

    def _schedule_renewal(self):
        """Schedule periodic webhook subscription renewal (runs every 24h)."""
        t = threading.Timer(24 * 3600, self._renew_subscriptions)
        t.daemon = True
        t.start()
        self._renewal_timer = t

    def _renew_subscriptions(self):
        """Renew webhook subscriptions that are close to expiry."""
        from app.db import SessionLocal
        from app.models import SharePointConnection

        db = SessionLocal()
        try:
            conns = db.query(SharePointConnection).filter_by(status="connected").all()
            threshold = datetime.utcnow() + timedelta(seconds=WEBHOOK_RENEW_BEFORE_SECS)

            for conn in conns:
                if not conn.webhook_expiry or conn.webhook_expiry > threshold:
                    continue
                try:
                    token = _get_token()
                    new_expiry = datetime.utcnow() + timedelta(days=29)
                    for sub_id in (conn.webhook_subscription_ids or []):
                        try:
                            _graph_patch(
                                f"{GRAPH_BASE}/subscriptions/{sub_id}", token,
                                {"expirationDateTime": new_expiry.strftime(
                                    "%Y-%m-%dT%H:%M:%S.0000000Z")}
                            )
                            logger.info("[SP] Renewed subscription %s", sub_id)
                        except Exception as e:
                            logger.warning("[SP] Renewal failed for %s: %s", sub_id, e)
                    conn.webhook_expiry = new_expiry
                    db.commit()
                except Exception as e:
                    logger.error("[SP] Renewal error for conn %s: %s", conn.id, e)
        finally:
            db.close()

        # Reschedule
        self._schedule_renewal()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _download_file(self, drive_id: str, item_id: str, token: str):
        """Download file bytes; returns (content_bytes, sha256_hex)."""
        # Try pre-signed download URL first
        item_info = _graph_get(
            f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
            "?$select=id,name,@microsoft.graph.downloadUrl,size",
            token,
        )
        dl_url = item_info.get("@microsoft.graph.downloadUrl")
        if dl_url:
            r = requests.get(dl_url, timeout=120)
        else:
            r = requests.get(
                f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content",
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
                allow_redirects=True,
            )
        if not r.ok:
            raise RuntimeError(f"Download failed: HTTP {r.status_code}")
        content = r.content
        content_hash = hashlib.sha256(content).hexdigest()
        return content, content_hash

    def _connection_for_subscription(self, sub_id: str) -> Optional[str]:
        """Find connection_id owning a webhook subscription."""
        from app.db import SessionLocal
        from app.models import SharePointConnection

        db = SessionLocal()
        try:
            conns = db.query(SharePointConnection).filter_by(status="connected").all()
            for c in conns:
                if sub_id in (c.webhook_subscription_ids or []):
                    return c.id
        finally:
            db.close()
        return None

    def _load_delta_token(self, db, connection_id: str, drive_id: str) -> Optional[str]:
        """Load the stored delta URL for a drive."""
        from app.models import SharePointConnection
        conn = db.query(SharePointConnection).filter_by(id=connection_id).first()
        if conn and conn.delta_token:
            try:
                import json
                tokens = json.loads(conn.delta_token)
                return tokens.get(drive_id)
            except Exception:
                return conn.delta_token if drive_id in (conn.delta_token or "") else None
        return None

    def _save_delta_token(self, db, connection_id: str, drive_id: str, delta_url: str):
        """Persist delta URL keyed by drive_id."""
        from app.models import SharePointConnection
        import json
        conn = db.query(SharePointConnection).filter_by(id=connection_id).first()
        if not conn:
            return
        try:
            tokens = json.loads(conn.delta_token) if conn.delta_token else {}
        except Exception:
            tokens = {}
        tokens[drive_id] = delta_url
        conn.delta_token = json.dumps(tokens)
        db.commit()

    def _mark_file_error(self, db, conn, item_id, name, folder_path,
                         drive_id, last_modified, size, error, existing=None):
        try:
            from app.models import SharePointFile
            if existing:
                existing.indexed_status = "failed"
                existing.error_message = error[:500]
                existing.updated_at = datetime.utcnow()
            else:
                db.add(SharePointFile(
                    connection_id=conn.id,
                    sharepoint_file_id=item_id,
                    file_name=name,
                    folder_path=folder_path,
                    drive_id=drive_id,
                    site_id=conn.site_id,
                    last_modified=last_modified,
                    file_size_bytes=size,
                    indexed_status="failed",
                    error_message=error[:500],
                ))
            db.commit()
        except Exception as db_err:
            logger.error("[SP] Failed to persist file error for %s: %s", name, db_err)
            try:
                db.rollback()
            except Exception:
                pass

    def _save_error(self, db, conn, error: str):
        conn.last_error = error[:500]
        db.commit()

    # ── Resume on startup ─────────────────────────────────────────────────────

    def resume_connections(self):
        """
        Called at startup. Resumes delta sync for any connections that were
        active when the process last stopped.
        """
        from app.db import SessionLocal
        from app.models import SharePointConnection

        db = SessionLocal()
        try:
            active = db.query(SharePointConnection).filter_by(status="connected").all()
            for conn in active:
                logger.info("[SP] Resuming sync for connection %s (%s)",
                            conn.id[:8], conn.site_display_name)
                # 90-second delay gives embedding model time to finish loading
                # (bge-large-en-v1.5 + bge-reranker-large take ~60-90s from disk)
                self._schedule_delta_sync(conn.id, startup_delay=90.0)
            if active:
                self._schedule_renewal()
        finally:
            db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_sp_service: Optional[SharePointService] = None
_sp_lock = threading.Lock()


def get_sharepoint_service() -> SharePointService:
    global _sp_service
    if _sp_service is None:
        with _sp_lock:
            if _sp_service is None:
                _sp_service = SharePointService()
    return _sp_service

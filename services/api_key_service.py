"""
API Key Service — CortexFlow External Integration Layer.

Admins generate named API keys.  External organisations embed the key in the
X-API-Key header to access /ask, /upload, and related endpoints without JWT.

Security design:
  • Raw key is returned ONCE at creation and never stored (only SHA-256 hash kept).
  • Key format:  cf_live_<40 random hex chars>   (52 chars total, clearly branded)
  • Hash algorithm: SHA-256 (constant-time comparison via hmac.compare_digest)
  • Keys can be scoped (read / read_write), given expiry, and revoked instantly.
  • Every request is logged to api_key_usage for admin visibility.
"""

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models import ApiKey, ApiKeyUsage

logger = logging.getLogger(__name__)

_PREFIX = "cf_live_"


# ── Key generation ─────────────────────────────────────────────────────────────

def _generate_raw_key() -> str:
    """Return a cryptographically random API key string."""
    return _PREFIX + os.urandom(20).hex()          # 40 hex chars → 52 total


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


# ── CRUD ───────────────────────────────────────────────────────────────────────

def create_api_key(
    db: Session,
    name: str,
    created_by: str,
    permissions: str = "read",
    expires_days: Optional[int] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Generate a new API key.  Returns dict with `raw_key` (shown once only).
    """
    raw = _generate_raw_key()
    key = ApiKey(
        name=name,
        key_hash=_hash_key(raw),
        key_prefix=raw[:12],
        created_by=created_by,
        permissions=permissions,
        expires_at=datetime.utcnow() + timedelta(days=expires_days) if expires_days else None,
        notes=notes,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    logger.info("[ApiKey] Created key '%s' (id=%s) by %s", name, key.id, created_by)
    return {
        "id": key.id,
        "name": key.name,
        "raw_key": raw,          # ← shown ONCE; not stored
        "key_prefix": key.key_prefix,
        "permissions": key.permissions,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "created_at": key.created_at.isoformat(),
        "warning": "Save this key now — it will NOT be shown again.",
    }


def list_api_keys(db: Session) -> List[dict]:
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [_safe_dict(k) for k in keys]


def revoke_api_key(db: Session, key_id: str) -> bool:
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        return False
    key.is_active = False
    db.commit()
    logger.info("[ApiKey] Revoked key id=%s ('%s')", key_id, key.name)
    return True


def get_api_key_detail(db: Session, key_id: str) -> Optional[dict]:
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        return None
    usage = (
        db.query(ApiKeyUsage)
        .filter(ApiKeyUsage.key_id == key_id)
        .order_by(ApiKeyUsage.created_at.desc())
        .limit(50)
        .all()
    )
    d = _safe_dict(key)
    d["recent_usage"] = [
        {
            "endpoint": u.endpoint,
            "method": u.method,
            "status_code": u.status_code,
            "latency_ms": u.latency_ms,
            "created_at": u.created_at.isoformat(),
        }
        for u in usage
    ]
    return d


# ── Authentication ─────────────────────────────────────────────────────────────

def authenticate_api_key(db: Session, raw_key: str) -> Optional[dict]:
    """
    Validate X-API-Key header value.
    Returns a user-like dict  {user_id, role, permissions, key_id}  on success,
    or None if the key is missing, revoked, expired, or unknown.
    """
    if not raw_key or not raw_key.startswith(_PREFIX):
        return None

    candidate_hash = _hash_key(raw_key)

    # Fetch all active, non-expired keys and compare hashes.
    # (We can't do a DB filter on hash without constant-time compare.)
    now = datetime.utcnow()
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.is_active == True)
        .all()
    )

    for key in keys:
        if key.expires_at and key.expires_at < now:
            continue
        if _safe_compare(key.key_hash, candidate_hash):
            # Update last_used_at and request count
            key.last_used_at = now
            key.total_requests = (key.total_requests or 0) + 1
            db.commit()
            return {
                "user_id": f"api_key:{key.id}",
                "email": f"apikey:{key.name}",
                "role": "admin" if key.permissions == "read_write" else "user",
                "key_id": key.id,
                "key_name": key.name,
                "tenant_id": key.id,          # unique tenant per API key
                "permissions": key.permissions,
                "auth_method": "api_key",
            }
    return None


def log_api_key_usage(
    db: Session,
    key_id: str,
    endpoint: str,
    method: str = "POST",
    status_code: int = 200,
    latency_ms: int = 0,
) -> None:
    """Fire-and-forget usage log. Silently ignores errors."""
    try:
        entry = ApiKeyUsage(
            key_id=key_id,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
        )
        db.add(entry)
        # Cap usage log per key at 1000 rows
        count = db.query(ApiKeyUsage).filter(ApiKeyUsage.key_id == key_id).count()
        if count > 1000:
            oldest = (
                db.query(ApiKeyUsage)
                .filter(ApiKeyUsage.key_id == key_id)
                .order_by(ApiKeyUsage.created_at.asc())
                .first()
            )
            if oldest:
                db.delete(oldest)
        db.commit()
    except Exception as e:
        logger.warning("[ApiKey] Usage log failed: %s", e)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_dict(key: ApiKey) -> dict:
    return {
        "id": key.id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "permissions": key.permissions,
        "is_active": key.is_active,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "total_requests": key.total_requests or 0,
        "created_at": key.created_at.isoformat(),
        "notes": key.notes,
    }

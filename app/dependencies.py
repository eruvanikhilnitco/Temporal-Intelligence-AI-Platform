import time
import threading
from collections import deque

from fastapi import Depends, HTTPException, Header, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from app.core.security import decode_token

# ── Rate Limiter ───────────────────────────────────────────────────────────────

class _RateLimiter:
    """
    Sliding-window in-memory rate limiter.
    Limits: admin → 300 req/hr, user/client/api_key → 60 req/hr.
    Returns 429 with Retry-After header on breach.
    """
    _WINDOW = 3600          # 1 hour in seconds
    _LIMITS = {"admin": 300, "user": 60, "client": 60}
    _DEFAULT = 60

    def __init__(self):
        self._buckets: dict[str, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str, role: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). retry_after=0 when allowed."""
        limit = self._LIMITS.get(role, self._DEFAULT)
        now = time.time()
        cutoff = now - self._WINDOW
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = deque()
            bucket = self._buckets[key]
            # Evict old timestamps
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = int(self._WINDOW - (now - oldest)) + 1
                return False, retry_after
            bucket.append(now)
            return True, 0


_rate_limiter = _RateLimiter()

security = HTTPBearer(auto_error=False)       # auto_error=False so X-API-Key can take over
security_optional = HTTPBearer(auto_error=False)


def _get_db_from_request(request: Request):
    """Pull a DB session from the request state (set by middleware) or open a new one."""
    from app.db import SessionLocal
    return SessionLocal()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    """
    Authenticate via JWT Bearer token OR X-API-Key header.

    Priority:
      1. X-API-Key header  →  validated against api_keys table (hashed)
      2. Authorization: Bearer <jwt>  →  standard JWT validation

    Returns a unified user dict:
      {user_id, email, role, auth_method}
    """
    # ── Path 1: API Key ────────────────────────────────────────────────────────
    if x_api_key:
        from app.db import SessionLocal
        from services.api_key_service import authenticate_api_key
        db = SessionLocal()
        try:
            user = authenticate_api_key(db, x_api_key)
        finally:
            db.close()
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    # ── Path 2: JWT Bearer ────────────────────────────────────────────────────
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Authorization: Bearer <token> or X-API-Key header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    return {
        "user_id": user_id,
        "email": payload.get("email"),
        "role": payload.get("role"),
        "auth_method": "jwt",
    }


async def OptionalUser(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    x_api_key: Optional[str] = Header(default=None),
) -> Optional[dict]:
    """Return current user or None if not authenticated."""
    if x_api_key:
        from app.db import SessionLocal
        from services.api_key_service import authenticate_api_key
        db = SessionLocal()
        try:
            return authenticate_api_key(db, x_api_key)
        finally:
            db.close()
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload:
        return None
    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "role": payload.get("role"),
        "auth_method": "jwt",
    }


async def require_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Require admin role (works for both JWT and read_write API keys)."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_client(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Require client or admin role (any authenticated user or valid API key)."""
    if current_user.get("role") not in ["admin", "client", "user"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client access required",
        )
    return current_user


async def check_rate_limit(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Rate limit the /ask endpoint.
    Limits: admin → 300/hr, user/client → 60/hr.
    Raises HTTP 429 with Retry-After header on breach.
    """
    user_id = current_user.get("user_id", "anon")
    role = current_user.get("role", "user")
    allowed, retry_after = _rate_limiter.check(user_id, role)
    if not allowed:
        limit = _RateLimiter._LIMITS.get(role, _RateLimiter._DEFAULT)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({limit} requests/hour). Please retry after {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )
    return current_user

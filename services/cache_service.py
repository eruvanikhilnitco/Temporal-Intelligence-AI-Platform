"""
CacheService — TTL-aware cache with Redis persistence + in-memory LRU fallback.

Hierarchy:
  1. Redis (if available) — survives server restarts, shared across workers
  2. In-memory LRU OrderedDict — fast, no dependencies, single-process

Configuration:
  Set REDIS_URL in .env (e.g. redis://localhost:6379/0) to enable Redis.
  If not set or Redis is unreachable, falls back transparently to in-memory.

Thread-safe for concurrent requests.
"""
import json
import logging
import time
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Redis backend ──────────────────────────────────────────────────────────────

class _RedisBackend:
    """Thin wrapper around Redis with JSON serialization."""

    def __init__(self, redis_url: str):
        import redis as _redis
        self._client = _redis.from_url(redis_url, decode_responses=True, socket_timeout=1.0)
        self._client.ping()   # will raise if unreachable
        logger.info("[Cache] Redis backend connected: %s", redis_url)

    def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(f"cf:{key}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            self._client.setex(f"cf:{key}", ttl, json.dumps(value, default=str))
        except Exception:
            pass

    def delete(self, key: str) -> None:
        try:
            self._client.delete(f"cf:{key}")
        except Exception:
            pass

    def clear(self) -> None:
        try:
            keys = self._client.keys("cf:*")
            if keys:
                self._client.delete(*keys)
        except Exception:
            pass

    def size(self) -> int:
        try:
            return len(self._client.keys("cf:*"))
        except Exception:
            return 0


# ── In-memory backend ──────────────────────────────────────────────────────────

class _MemoryBackend:
    def __init__(self, max_entries: int = 2000):
        self._store: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._evictions = 0
        # Background cleanup
        t = threading.Thread(target=self._cleanup_loop, daemon=True, name="cache-cleanup")
        t.start()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expire_at = entry
            if expire_at < time.time():
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        expire_at = time.time() + ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, expire_at)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)
                self._evictions += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def _cleanup_loop(self):
        while True:
            time.sleep(60)
            try:
                now = time.time()
                with self._lock:
                    expired = [k for k, (_, exp) in self._store.items() if exp < now]
                    for k in expired:
                        del self._store[k]
            except Exception:
                pass


# ── Public CacheService ────────────────────────────────────────────────────────

class CacheService:
    """
    TTL-aware cache.  Redis-backed when REDIS_URL is set; in-memory otherwise.
    Both backends are thread-safe and support the same get/set/delete/clear API.
    """

    def __init__(self, default_ttl: int = 600, max_entries: int = 2000):
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0
        self._total_sets = 0
        self._lock = threading.Lock()

        # Try Redis first
        self._backend: Any = None
        self._backend_name = "memory"
        try:
            from core.config import get_settings
            settings = get_settings()
            redis_url = getattr(settings, "redis_url", "") or ""
            if redis_url:
                self._backend = _RedisBackend(redis_url)
                self._backend_name = "redis"
        except Exception as e:
            logger.debug("[Cache] Redis unavailable (%s), using in-memory cache", e)

        if self._backend is None:
            self._backend = _MemoryBackend(max_entries=max_entries)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        value = self._backend.get(key)
        with self._lock:
            if value is None:
                self._misses += 1
            else:
                self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        self._backend.set(key, value, effective_ttl)
        with self._lock:
            self._total_sets += 1

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def clear(self) -> None:
        self._backend.clear()

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = round(self._hits / total * 100, 1) if total > 0 else 0.0
            return {
                "backend":        self._backend_name,
                "hits":           self._hits,
                "misses":         self._misses,
                "total_requests": total,
                "hit_rate_pct":   hit_rate,
                "total_sets":     self._total_sets,
                "active_entries": self._backend.size(),
            }

    def memory_usage_kb(self) -> float:
        """Estimate memory usage (in-memory backend only)."""
        if self._backend_name == "redis":
            return 0.0
        try:
            import sys
            backend = self._backend
            with backend._lock:
                size = sum(sys.getsizeof(k) + sys.getsizeof(v) for k, (v, _) in backend._store.items())
            return round(size / 1024, 1)
        except Exception:
            return 0.0

"""
In-memory cache with TTL support and bounded LRU eviction.
Thread-safe for concurrent requests.
"""
import time
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple


class CacheService:
    """
    TTL-aware in-memory cache with LRU eviction and background cleanup.
    - Default TTL: 10 minutes (600s)
    - Max entries: 2000 (evicts least-recently-used when full)
    - Background thread expires stale entries every 60s to prevent memory creep
    - Tracks hit/miss stats for admin monitoring
    """

    def __init__(self, default_ttl: int = 600, max_entries: int = 2000):
        # OrderedDict preserves insertion order for O(1) LRU eviction
        self._store: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._total_sets = 0
        self._evictions = 0

        # Background cleanup: remove expired entries every 60 seconds
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="cache-cleanup"
        )
        self._cleanup_thread.start()

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expire_at = entry
            if expire_at < time.time():
                del self._store[key]
                self._misses += 1
                return None
            # Move to end = most recently used
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expire_at = time.time() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, expire_at)
            self._total_sets += 1
            # Evict LRU entries when over capacity
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)
                self._evictions += 1

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    # ── Stats for admin monitoring ──────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = round(self._hits / total * 100, 1) if total > 0 else 0.0
            now = time.time()
            active = sum(1 for _, (_, exp) in self._store.items() if exp >= now)
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total,
                "hit_rate_pct": hit_rate,
                "active_entries": active,
                "total_entries": len(self._store),
                "total_sets": self._total_sets,
                "evictions": self._evictions,
                "max_entries": self._max_entries,
            }

    # ── Memory usage estimate ───────────────────────────────────────────────

    def memory_usage_kb(self) -> float:
        import sys
        with self._lock:
            size = sum(sys.getsizeof(k) + sys.getsizeof(v) for k, (v, _) in self._store.items())
        return round(size / 1024, 1)

    # ── Background cleanup ──────────────────────────────────────────────────

    def _cleanup_loop(self):
        """Remove expired entries every 60 seconds to reclaim memory."""
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

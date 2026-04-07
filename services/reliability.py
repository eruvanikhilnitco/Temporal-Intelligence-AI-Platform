"""
CortexFlow — Reliability Layer
================================
Provides:
  1. with_retry()   — exponential-backoff retry decorator
  2. CircuitBreaker — opens after N consecutive failures, recovers after timeout
  3. Shared breaker singletons for Qdrant, Neo4j, LLM

SOLID:
  - Single Responsibility: each class handles exactly one failure strategy.
  - Open/Closed: add new strategies without modifying existing ones.
  - DI: pass custom breakers to service constructors; default to module-level singletons.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


# ── Retry decorator ────────────────────────────────────────────────────────────

def with_retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_failure_return: Any = None,
):
    """
    Exponential-backoff retry decorator.

    Usage:
        @with_retry(max_attempts=3, base_delay=0.5)
        def call_qdrant(...): ...

        # Or inline:
        result = with_retry(max_attempts=2)(my_fn)(args)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_attempts:
                        logger.error(
                            "[Retry] %s gave up after %d attempts: %s",
                            func.__qualname__, max_attempts, e,
                        )
                        return on_failure_return
                    logger.warning(
                        "[Retry] %s attempt %d/%d failed: %s — retrying in %.1fs",
                        func.__qualname__, attempt, max_attempts, e, delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, max_delay)
            return on_failure_return
        return wrapper
    return decorator


# ── Circuit Breaker ────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Classic three-state circuit breaker:
      CLOSED   — normal operation, failures are counted
      OPEN     — service is down; calls return fallback immediately
      HALF_OPEN— one test call allowed; success → CLOSED, failure → OPEN

    Usage:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="Qdrant")

        result = breaker.call(
            qdrant_client.query_points,
            collection_name="...", ...,
            fallback=[],
        )
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "service",
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._state = self.CLOSED
        self._last_failure_time: float = 0.0

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = self.HALF_OPEN
                logger.info("[CircuitBreaker:%s] → HALF_OPEN (testing recovery)", self.name)
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN

    def call(self, func: Callable, *args, fallback: Any = None, **kwargs) -> Any:
        """
        Call func(*args, **kwargs) through the breaker.
        - OPEN: immediately returns fallback (callable or value)
        - HALF_OPEN / CLOSED: executes normally; failures update state
        """
        if self.state == self.OPEN:
            logger.warning("[CircuitBreaker:%s] OPEN — skipping call, returning fallback", self.name)
            return fallback() if callable(fallback) else fallback

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            if fallback is not None:
                return fallback() if callable(fallback) else fallback
            raise

    def reset(self):
        """Manually close the breaker (admin action)."""
        self._failures = 0
        self._state = self.CLOSED
        logger.info("[CircuitBreaker:%s] Manually reset to CLOSED", self.name)

    def status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self._failures,
            "threshold": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout,
            "last_failure_ago_s": round(time.time() - self._last_failure_time, 1)
            if self._last_failure_time else None,
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _on_success(self):
        self._failures = 0
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            logger.info("[CircuitBreaker:%s] → CLOSED (recovered)", self.name)

    def _on_failure(self, exc: Exception):
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.failure_threshold and self._state != self.OPEN:
            self._state = self.OPEN
            logger.error(
                "[CircuitBreaker:%s] → OPEN after %d failures (last: %s)",
                self.name, self._failures, exc,
            )


# ── Shared singletons ─────────────────────────────────────────────────────────
# Import these in services that call external systems.

qdrant_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="Qdrant")
neo4j_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="Neo4j")
llm_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=20.0, name="LLM")


def all_breaker_statuses() -> dict:
    """Return status of every shared circuit breaker (for admin health endpoint)."""
    return {
        "qdrant": qdrant_breaker.status(),
        "neo4j": neo4j_breaker.status(),
        "llm": llm_breaker.status(),
    }

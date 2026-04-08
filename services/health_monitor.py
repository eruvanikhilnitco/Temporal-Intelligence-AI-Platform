"""
CortexFlow — Health Monitor
============================
Background thread that checks external service health every 30 seconds.

Tracked services:
  - Neo4j (bolt://localhost:7687) — optional, 2s timeout
  - Qdrant (localhost:6333)       — vector store

Status is exposed via get_health_status() for the admin dashboard.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_STATUS = {
    "neo4j": {
        "status": "unknown",       # "ok" | "down" | "unknown"
        "last_checked": None,
        "last_ok": None,
        "error": None,
    },
    "qdrant": {
        "status": "unknown",
        "last_checked": None,
        "last_ok": None,
        "error": None,
    },
}
_STATUS_LOCK = threading.Lock()
_MONITOR_STARTED = False


def _check_neo4j() -> tuple[bool, Optional[str]]:
    try:
        from core.database import get_neo4j_driver
        driver = get_neo4j_driver(timeout=2.0)
        with driver.session() as sess:
            sess.run("RETURN 1")
        driver.close()
        return True, None
    except Exception as e:
        return False, str(e)[:200]


def _check_qdrant() -> tuple[bool, Optional[str]]:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333, timeout=3.0)
        client.get_collections()
        return True, None
    except Exception as e:
        return False, str(e)[:200]


def _run_checks():
    now_iso = datetime.utcnow().isoformat()

    ok, err = _check_neo4j()
    with _STATUS_LOCK:
        _STATUS["neo4j"]["status"] = "ok" if ok else "down"
        _STATUS["neo4j"]["last_checked"] = now_iso
        _STATUS["neo4j"]["error"] = err
        if ok:
            _STATUS["neo4j"]["last_ok"] = now_iso

    ok, err = _check_qdrant()
    with _STATUS_LOCK:
        _STATUS["qdrant"]["status"] = "ok" if ok else "down"
        _STATUS["qdrant"]["last_checked"] = now_iso
        _STATUS["qdrant"]["error"] = err
        if ok:
            _STATUS["qdrant"]["last_ok"] = now_iso


def _monitor_loop(interval: int = 30):
    logger.info("[HealthMonitor] Started (interval=%ds)", interval)
    while True:
        try:
            _run_checks()
        except Exception as e:
            logger.warning("[HealthMonitor] Check cycle error: %s", e)
        time.sleep(interval)


def start_health_monitor(interval: int = 30):
    """Start the background health monitor (idempotent)."""
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True
    # Run an immediate check before the loop starts
    threading.Thread(target=_run_checks, daemon=True, name="health-init").start()
    t = threading.Thread(
        target=_monitor_loop,
        args=(interval,),
        daemon=True,
        name="health-monitor",
    )
    t.start()


def get_health_status() -> dict:
    """Return a snapshot of all service health statuses."""
    with _STATUS_LOCK:
        import copy
        return copy.deepcopy(_STATUS)

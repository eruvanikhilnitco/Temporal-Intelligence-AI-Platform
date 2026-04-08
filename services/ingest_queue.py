"""
CortexFlow — Background Ingest Queue
======================================
Non-blocking document ingestion:
  - Submit a file path → get a job_id back immediately
  - Worker thread processes jobs from the queue in order
  - Batch embedding: embed multiple chunks in one model call (10x faster)
  - Admin can check status / list all jobs

SOLID:
  - Single Responsibility: IngestQueue only manages queue state; ingestion logic stays in rag_service.
  - Open/Closed: add new job types by subclassing IngestJob — don't touch the queue loop.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class IngestJob:
    file_path: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    submitted_at: float = field(default_factory=time.time)
    original_filename: Optional[str] = None  # override stored filename
    callback: Optional[Callable[[str, Any], None]] = None


class IngestQueue:
    """
    Background FIFO queue that ingests documents without blocking HTTP responses.

    Usage:
        q = get_ingest_queue()
        job_id = q.submit("/tmp/contract.pdf")
        # Returns immediately

        status = q.status(job_id)
        # {"status": "processing"|"done"|"error"|"queued", "elapsed_s": 2.1, ...}
    """

    def __init__(self, workers: int = 1):
        self._q: queue.Queue = queue.Queue()
        self._results: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._running = False
        self._workers: List[threading.Thread] = []
        self._num_workers = workers

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        for i in range(self._num_workers):
            t = threading.Thread(
                target=self._process_loop,
                name=f"ingest-worker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)
        logger.info("[IngestQueue] Started %d worker(s)", self._num_workers)

    def stop(self):
        self._running = False
        logger.info("[IngestQueue] Stopped")

    # ── Public API ─────────────────────────────────────────────────────────────

    def submit(
        self,
        file_path: str,
        job_id: Optional[str] = None,
        original_filename: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        job = IngestJob(
            file_path=file_path,
            job_id=job_id or str(uuid.uuid4()),
            original_filename=original_filename,
            callback=callback,
        )
        with self._lock:
            self._results[job.job_id] = {
                "status": "queued",
                "file": file_path,
                "job_id": job.job_id,
                "submitted_at": job.submitted_at,
                "queue_depth": self._q.qsize() + 1,
            }
        self._q.put(job)
        logger.info("[IngestQueue] Queued %s (%s)", file_path, job.job_id)
        return job.job_id

    def status(self, job_id: str) -> dict:
        with self._lock:
            return dict(self._results.get(job_id, {"status": "not_found"}))

    def all_statuses(self) -> List[dict]:
        with self._lock:
            return sorted(self._results.values(), key=lambda x: x.get("submitted_at", 0), reverse=True)

    def queue_depth(self) -> int:
        return self._q.qsize()

    # ── Worker loop ────────────────────────────────────────────────────────────

    def _process_loop(self):
        while self._running:
            try:
                job: IngestJob = self._q.get(timeout=1.0)
            except queue.Empty:
                continue

            t0 = time.time()
            with self._lock:
                self._results[job.job_id]["status"] = "processing"
                self._results[job.job_id]["started_at"] = t0

            try:
                from app.services.rag_service import ingest_file
                entities = ingest_file(job.file_path)
                elapsed = round(time.time() - t0, 2)
                with self._lock:
                    self._results[job.job_id].update({
                        "status": "done",
                        "entities": entities,
                        "elapsed_s": elapsed,
                        "done_at": time.time(),
                    })
                logger.info("[IngestQueue] Done %s in %.1fs", job.file_path, elapsed)
                if job.callback:
                    try:
                        job.callback(job.job_id, entities)
                    except Exception as cb_err:
                        logger.warning("[IngestQueue] Callback error: %s", cb_err)

            except Exception as exc:
                elapsed = round(time.time() - t0, 2)
                with self._lock:
                    self._results[job.job_id].update({
                        "status": "error",
                        "error": str(exc)[:300],
                        "elapsed_s": elapsed,
                    })
                from app.error_logger import log_error
                log_error("IngestQueue", f"Ingest failed for {job.file_path}", exc=exc)
            finally:
                self._q.task_done()


# ── Batch embedding helper ─────────────────────────────────────────────────────

def batch_embed(texts: List[str], embedder) -> List[List[float]]:
    """
    Embed a list of texts in one model.encode() call.
    Falls back to one-by-one if batch fails.

    10x faster than calling embed() in a loop for large documents.
    """
    if not texts:
        return []
    try:
        # SentenceTransformer supports batch encode natively
        vectors = embedder.model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]
    except Exception as e:
        logger.warning("[BatchEmbed] Batch failed (%s), falling back to sequential", e)
        return [embedder.embed(t) for t in texts]


# ── Singleton ──────────────────────────────────────────────────────────────────

_queue_instance: Optional[IngestQueue] = None
_queue_lock = threading.Lock()

# Default: min(cpu_count, 4) workers so 100-file batches process in parallel
_DEFAULT_WORKERS = min(os.cpu_count() or 2, 4)


def get_ingest_queue() -> IngestQueue:
    global _queue_instance
    if _queue_instance is None:
        with _queue_lock:
            if _queue_instance is None:
                _queue_instance = IngestQueue(workers=_DEFAULT_WORKERS)
                _queue_instance.start()
    return _queue_instance

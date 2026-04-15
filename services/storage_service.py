"""
StorageService — Abstracted object storage for raw files and HTML snapshots.

Architecture (per storage.txt spec):
  Primary:  MinIO / S3 — unlimited scale, cheap, enterprise-grade
  Fallback: Local filesystem (uploaded_docs/) — dev/offline mode

Why object storage:
  - Raw files (PDF, DOCX), website HTML snapshots, processed text
  - Never stored in Qdrant or PostgreSQL (wrong tool for binary blobs)
  - Keeps DB lean; only metadata in Postgres, only vectors in Qdrant

Configuration:
  Set MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY in .env
  If not set, automatically falls back to local filesystem.

Usage:
  svc = get_storage_service()
  path_or_key = svc.store(file_bytes, filename, content_type="application/pdf")
  data = svc.retrieve(path_or_key)
  svc.delete(path_or_key)
"""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploaded_docs")


class StorageService:
    """
    Unified file storage: MinIO first, local filesystem fallback.
    All methods are synchronous and thread-safe.
    """

    def __init__(self):
        self._minio = None
        self._bucket = "cortexflow"
        self._backend = "local"
        self._init_minio()

    def _init_minio(self):
        """Try to connect to MinIO/S3. Falls back silently to local."""
        try:
            from core.config import get_settings
            settings = get_settings()

            endpoint   = getattr(settings, "minio_endpoint", "")
            access_key = getattr(settings, "minio_access_key", "")
            secret_key = getattr(settings, "minio_secret_key", "")
            bucket     = getattr(settings, "minio_bucket", "cortexflow")
            secure     = getattr(settings, "minio_secure", False)

            if not endpoint:
                return

            from minio import Minio
            client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            )
            # Ensure bucket exists
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                logger.info("[Storage] Created MinIO bucket: %s", bucket)

            self._minio  = client
            self._bucket = bucket
            self._backend = "minio"
            logger.info("[Storage] MinIO backend ready: %s / %s", endpoint, bucket)

        except ImportError:
            logger.debug("[Storage] minio package not installed; using local storage")
        except Exception as e:
            logger.warning("[Storage] MinIO unavailable (%s); falling back to local storage", e)

    # ── Public API ─────────────────────────────────────────────────────────────

    def store(
        self,
        data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        prefix: str = "uploads",
    ) -> str:
        """
        Store bytes. Returns object key (MinIO) or local path string.
        Prefix examples: "uploads", "html_snapshots", "processed_text"
        """
        if self._minio is not None:
            return self._store_minio(data, filename, content_type, prefix)
        return self._store_local(data, filename)

    def retrieve(self, key: str) -> Optional[bytes]:
        """Retrieve file bytes by key/path."""
        if self._minio is not None and not key.startswith("/") and not os.path.isabs(key):
            return self._retrieve_minio(key)
        return self._retrieve_local(key)

    def delete(self, key: str) -> bool:
        """Delete a stored object."""
        if self._minio is not None and not key.startswith("/") and not os.path.isabs(key):
            return self._delete_minio(key)
        return self._delete_local(key)

    def exists(self, key: str) -> bool:
        """Check whether an object exists."""
        if self._minio is not None and not key.startswith("/") and not os.path.isabs(key):
            try:
                self._minio.stat_object(self._bucket, key)
                return True
            except Exception:
                return False
        return Path(key).exists()

    def get_url(self, key: str, expires_seconds: int = 3600) -> Optional[str]:
        """Get a presigned URL (MinIO) or None (local)."""
        if self._minio is not None:
            try:
                from datetime import timedelta
                return self._minio.presigned_get_object(
                    self._bucket, key, expires=timedelta(seconds=expires_seconds)
                )
            except Exception as e:
                logger.warning("[Storage] Presigned URL failed: %s", e)
        return None

    @property
    def backend(self) -> str:
        return self._backend

    # ── MinIO helpers ──────────────────────────────────────────────────────────

    def _store_minio(
        self, data: bytes, filename: str, content_type: str, prefix: str
    ) -> str:
        key = f"{prefix}/{int(time.time())}_{filename}"
        try:
            self._minio.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return key
        except Exception as e:
            logger.warning("[Storage] MinIO store failed (%s), falling back to local", e)
            return self._store_local(data, filename)

    def _retrieve_minio(self, key: str) -> Optional[bytes]:
        try:
            response = self._minio.get_object(self._bucket, key)
            data = response.read()
            response.close()
            return data
        except Exception as e:
            logger.warning("[Storage] MinIO retrieve failed for %s: %s", key, e)
            return None

    def _delete_minio(self, key: str) -> bool:
        try:
            self._minio.remove_object(self._bucket, key)
            return True
        except Exception:
            return False

    # ── Local helpers ──────────────────────────────────────────────────────────

    def _store_local(self, data: bytes, filename: str) -> str:
        UPLOAD_DIR.mkdir(exist_ok=True)
        dest = UPLOAD_DIR / filename
        dest.write_bytes(data)
        return str(dest)

    def _retrieve_local(self, path: str) -> Optional[bytes]:
        try:
            return Path(path).read_bytes()
        except Exception:
            return None

    def _delete_local(self, path: str) -> bool:
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
            return True
        except Exception:
            return False


# ── Singleton ──────────────────────────────────────────────────────────────────

_storage_instance: Optional[StorageService] = None
_storage_lock = __import__("threading").Lock()


def get_storage_service() -> StorageService:
    global _storage_instance
    if _storage_instance is None:
        with _storage_lock:
            if _storage_instance is None:
                _storage_instance = StorageService()
    return _storage_instance

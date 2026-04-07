"""
CortexFlow — Structured Error Logger
=====================================
Writes every application error to  logs/error_log.jsonl  (one JSON object per line).
Each entry contains:
  - timestamp    ISO-8601 UTC
  - level        ERROR / WARNING / CRITICAL
  - source       module or component that raised the error
  - message      human-readable description
  - exception    exception type + message (if applicable)
  - traceback    full stack trace (if applicable)
  - request_id   UUID tied to the HTTP request (if available)
  - path         HTTP path that triggered the error (if available)
  - user         authenticated user email (if available)
  - extra        any additional structured data passed by the caller

Usage
-----
    from app.error_logger import log_error, log_warning

    try:
        risky_operation()
    except Exception as e:
        log_error("RAGService", "Vector search failed", exc=e, extra={"query": q})

FastAPI middleware automatically captures all unhandled 5xx errors.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# ── Log directory setup ────────────────────────────────────────────────────────

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_LOG_FILE = _LOG_DIR / "error_log.jsonl"

# Keep a plain-text mirror for quick tail / grep
_LOG_FILE_TXT = _LOG_DIR / "error_log.txt"

_std_logger = logging.getLogger("cortexflow.errors")


# ── Core writer ───────────────────────────────────────────────────────────────

def _write_entry(entry: Dict[str, Any]) -> None:
    """Append one JSON line to the log file (thread-safe via open-append)."""
    line = json.dumps(entry, ensure_ascii=False, default=str)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        # Mirror as human-readable text
        with open(_LOG_FILE_TXT, "a", encoding="utf-8") as fh:
            ts = entry.get("timestamp", "")
            lvl = entry.get("level", "ERROR")
            src = entry.get("source", "?")
            msg = entry.get("message", "")
            exc = entry.get("exception", "")
            fh.write(f"[{ts}] [{lvl}] [{src}] {msg}")
            if exc:
                fh.write(f" | {exc}")
            fh.write("\n")
            if entry.get("traceback"):
                for tb_line in entry["traceback"].splitlines():
                    fh.write(f"    {tb_line}\n")
    except Exception as write_err:
        # Last-resort: print to stderr so we never swallow errors silently
        import sys
        print(f"[ErrorLogger] Failed to write log: {write_err}", file=sys.stderr)


def _build_entry(
    level: str,
    source: str,
    message: str,
    exc: Optional[BaseException] = None,
    request_id: Optional[str] = None,
    path: Optional[str] = None,
    user: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "source": source,
        "message": message,
        "request_id": request_id or str(uuid.uuid4()),
        "path": path,
        "user": user,
        "extra": extra or {},
    }
    if exc is not None:
        entry["exception"] = f"{type(exc).__name__}: {exc}"
        entry["traceback"] = traceback.format_exc()
    else:
        entry["exception"] = None
        entry["traceback"] = None
    return entry


# ── Public API ─────────────────────────────────────────────────────────────────

def log_error(
    source: str,
    message: str,
    exc: Optional[BaseException] = None,
    request_id: Optional[str] = None,
    path: Optional[str] = None,
    user: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log an ERROR level entry. Call from except blocks."""
    entry = _build_entry("ERROR", source, message, exc, request_id, path, user, extra)
    _write_entry(entry)
    _std_logger.error("[%s] %s%s", source, message,
                      f" | {entry['exception']}" if entry["exception"] else "")


def log_warning(
    source: str,
    message: str,
    exc: Optional[BaseException] = None,
    request_id: Optional[str] = None,
    path: Optional[str] = None,
    user: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log a WARNING level entry."""
    entry = _build_entry("WARNING", source, message, exc, request_id, path, user, extra)
    _write_entry(entry)
    _std_logger.warning("[%s] %s", source, message)


def log_critical(
    source: str,
    message: str,
    exc: Optional[BaseException] = None,
    request_id: Optional[str] = None,
    path: Optional[str] = None,
    user: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log a CRITICAL level entry (startup failures, data corruption etc.)."""
    entry = _build_entry("CRITICAL", source, message, exc, request_id, path, user, extra)
    _write_entry(entry)
    _std_logger.critical("[%s] %s", source, message)


# ── FastAPI middleware ─────────────────────────────────────────────────────────

def get_error_middleware():
    """
    Return a Starlette middleware callable that:
      - Attaches a unique request_id to every request (X-Request-ID header)
      - Catches any unhandled exception and logs it before re-raising
      - Logs all 5xx responses automatically
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class ErrorLoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
            # Attach to request state so route handlers can reference it
            request.state.request_id = request_id

            try:
                response: Response = await call_next(request)
            except Exception as exc:
                # Extract user from JWT state if already decoded
                user_email = getattr(request.state, "user_email", None)
                log_error(
                    source="HTTP",
                    message=f"Unhandled exception on {request.method} {request.url.path}",
                    exc=exc,
                    request_id=request_id,
                    path=str(request.url.path),
                    user=user_email,
                    extra={"method": request.method, "client": str(request.client)},
                )
                raise  # Let FastAPI's default error handler return 500

            # Log 5xx responses that were handled (e.g. HTTPException 500)
            if response.status_code >= 500:
                user_email = getattr(request.state, "user_email", None)
                log_error(
                    source="HTTP",
                    message=f"{response.status_code} on {request.method} {request.url.path}",
                    request_id=request_id,
                    path=str(request.url.path),
                    user=user_email,
                    extra={"status_code": response.status_code},
                )

            response.headers["X-Request-ID"] = request_id
            return response

    return ErrorLoggingMiddleware


# ── Log reader (for admin endpoint) ──────────────────────────────────────────

def read_recent_errors(limit: int = 100, level: Optional[str] = None) -> list:
    """
    Read the most recent `limit` entries from the log file.
    Optionally filter by level (ERROR / WARNING / CRITICAL).
    Returns a list of dicts, newest-first.
    """
    if not _LOG_FILE.exists():
        return []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        entries = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if level and entry.get("level") != level.upper():
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        return entries
    except Exception as e:
        _std_logger.error("[ErrorLogger] Could not read log file: %s", e)
        return []


def get_error_stats() -> Dict[str, Any]:
    """Return summary statistics for the error log."""
    if not _LOG_FILE.exists():
        return {"total": 0, "by_level": {}, "by_source": {}, "log_file": str(_LOG_FILE)}
    try:
        counts_level: Dict[str, int] = {}
        counts_source: Dict[str, int] = {}
        total = 0
        with open(_LOG_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    total += 1
                    lvl = e.get("level", "UNKNOWN")
                    src = e.get("source", "unknown")
                    counts_level[lvl] = counts_level.get(lvl, 0) + 1
                    counts_source[src] = counts_source.get(src, 0) + 1
                except json.JSONDecodeError:
                    pass
        size_kb = round(_LOG_FILE.stat().st_size / 1024, 1)
        return {
            "total": total,
            "by_level": counts_level,
            "by_source": dict(sorted(counts_source.items(), key=lambda x: -x[1])[:10]),
            "log_file": str(_LOG_FILE),
            "log_size_kb": size_kb,
        }
    except Exception as e:
        return {"total": -1, "error": str(e)}

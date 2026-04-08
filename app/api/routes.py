import os
import re
import shutil
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Form
from fastapi.responses import StreamingResponse
from typing import List as TypingList
import json

import hashlib

from app.api.schemas import AskRequest, AskResponse, UploadResponse, HealthResponse, SourceItem, FeedbackRequest
from app.services.rag_service import ask_rag, ask_rag_full, ingest_file
from app.dependencies import get_current_user, require_client, OptionalUser, check_rate_limit
from app.db import get_db
from app.models import ChatLog, SecurityEvent, UserActivity, QueryFeedback, User, Document
from sqlalchemy.orm import Session
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = Path("uploaded_docs")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".xml", ".txt", ".docx", ".json", ".csv", ".html", ".pptx", ".md"}


@router.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@router.get("/api/verify")
@router.post("/api/verify")
def verify_api_key(current_user: dict = Depends(get_current_user)):
    """
    Simple endpoint to verify an API key is valid.
    Use this in Postman to confirm your X-API-Key header works.

    Returns your auth info (role, permissions, tenant) without running a query.
    """
    return {
        "status": "authenticated",
        "auth_method": current_user.get("auth_method"),
        "role": current_user.get("role"),
        "permissions": current_user.get("permissions"),
        "tenant_id": current_user.get("tenant_id"),
        "key_name": current_user.get("key_name"),
        "user_id": current_user.get("user_id"),
        "message": "API key is valid. You can now use /ask to query documents.",
    }


@router.post("/ask", response_model=AskResponse)
def ask_question(
    req: AskRequest,
    request: Request,
    current_user: dict = Depends(check_rate_limit),
    db: Session = Depends(get_db),
):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Role is always determined by the authenticated user's JWT — never trust client-provided role
    auth_role = current_user.get("role", "client")
    # Map backend roles: admin stays admin, client/user stays user, public is unauthenticated
    if auth_role == "admin":
        role = "admin"
    else:
        role = "user"

    # ── Document exfiltration / data-leak guardrail (non-admin only) ──────────
    if role != "admin":
        q_lower = req.question.lower()
        exfil_patterns = [
            # Asking for raw document content / file names
            r"give me (the |all |the full |)document",
            r"show me (the |all |)document",
            r"list (all |the |)(document|file) name",
            r"what (are |is )(the |all )?(document|file) name",
            r"all file",
            r"full document",
            r"entire document",
            r"raw (document|file|text|content|data)",
            r"dump (the |all |)(document|file|data|content)",
            r"export (the |all |)(document|file|data)",
            r"print (the |all |full |)(document|file|content)",
            r"share (the |all |)(document|file|source)",
            r"send me (the |all |)(document|file)",
            r"leak",
            r"reveal (the |all |)(document|file|source|content)",
            r"background code",
            r"source code",
            r"backend code",
            r"system prompt",
            r"ignore (previous|above|all) instruction",
        ]
        is_exfil = any(re.search(p, q_lower) for p in exfil_patterns)
        if is_exfil:
            _log_security_event(
                db=db,
                user_id=current_user["user_id"],
                email=current_user.get("email", ""),
                event_type="document_exfiltration_attempt",
                severity="high",
                description=f"User attempted to extract document data or system internals: '{req.question[:200]}'",
                query=req.question,
            )
            _update_user_risk(db, current_user["user_id"])
            from app.error_logger import log_warning
            log_warning(
                "Security",
                f"Document exfiltration attempt by {current_user.get('email', 'unknown')}",
                extra={"query": req.question[:300], "user_id": current_user["user_id"]},
            )
            return AskResponse(
                answer=(
                    "I'm here to help you find specific information and insights from the documents, "
                    "but I'm not able to share complete documents, file names, or raw source data. "
                    "Feel free to ask me specific questions and I'll be happy to assist!"
                ),
                graph_used=False,
                confidence=100.0,
                query_type="blocked",
                sources=[],
                latency_ms=0,
                chat_log_id="",
            )

    # Full security analysis: threat detection + PII masking + attack scoring
    security_info: dict = {}
    try:
        from services.security_service import full_security_analysis
        security_info = full_security_analysis(req.question, current_user["user_id"], role)
        if security_info.get("should_block"):
            _log_security_event(
                db=db,
                user_id=current_user["user_id"],
                email=current_user.get("email", ""),
                event_type=security_info.get("threat_type", "attack"),
                severity="high",
                description=str(security_info.get("attack_types", [])),
                query=req.question,
            )
            _update_user_risk(db, current_user["user_id"])
            raise HTTPException(
                status_code=400,
                detail=f"Query blocked (attack score {security_info.get('attack_score', 0):.0f}/10): "
                       f"{', '.join(security_info.get('attack_types', ['policy violation']))}",
            )
        elif security_info.get("is_threat"):
            _log_security_event(
                db=db,
                user_id=current_user["user_id"],
                email=current_user.get("email", ""),
                event_type=security_info.get("threat_type", "suspicious"),
                severity="medium",
                description=str(security_info.get("threat_severity")),
                query=req.question,
            )
            _update_user_risk(db, current_user["user_id"])
    except ImportError:
        pass

    t_start = time.time()
    session_id = req.session_id or current_user.get("user_id", "anon")

    # ── Admin shortcut: detect system-level intents and answer directly ──────
    if role == "admin":
        admin_answer = _try_admin_intent(req.question)
        if admin_answer:
            latency_ms = int((time.time() - t_start) * 1000)
            chat_log_id = str(uuid.uuid4())
            try:
                log = ChatLog(
                    id=chat_log_id, user_id=current_user["user_id"],
                    session_id=session_id, question=req.question,
                    answer=admin_answer[:2000], query_type="admin",
                    graph_used=False, confidence=100.0, sources=[], latency_ms=latency_ms,
                )
                db.add(log)
                _update_user_activity(db, current_user["user_id"])
                db.commit()
            except Exception:
                db.rollback()
            return AskResponse(
                answer=admin_answer, graph_used=False, confidence=100.0,
                query_type="admin", sources=[], latency_ms=latency_ms, chat_log_id=chat_log_id,
            )

    # Use self-learning service
    try:
        from services.self_learning import get_self_learning
        sl = get_self_learning()
        hints = sl.before_query(req.question, current_user["user_id"], session_id)
        enriched_q = hints.get("enriched_query", req.question)
    except Exception:
        enriched_q = req.question
        hints = {}

    # D3: Fetch last 3 turns of conversation history for context-aware replies
    conversation_history = []
    try:
        recent_logs = (
            db.query(ChatLog)
            .filter(ChatLog.session_id == session_id)
            .order_by(ChatLog.created_at.desc())
            .limit(3)
            .all()
        )
        for log in reversed(recent_logs):
            conversation_history.append({"role": "user", "text": log.question})
            conversation_history.append({"role": "assistant", "text": log.answer})
    except Exception as e:
        logger.warning("[Ask] Could not fetch conversation history: %s", e)

    # Use agent orchestrator
    tenant_id = current_user.get("tenant_id")
    result = ask_rag_full(enriched_q, role, session_id=session_id,
                          conversation_history=conversation_history or None,
                          tenant_id=tenant_id)

    latency_ms = int((time.time() - t_start) * 1000)

    # Adjust confidence with feedback signal
    confidence = result.get("confidence", 75.0)
    if hints:
        confidence = min(confidence + hints.get("confidence_modifier", 0) * 100, 99.0)

    # Build sources — admin sees full chunks, user sees none
    raw_sources = result.get("sources", [])
    if role == "admin":
        sources = [
            SourceItem(
                name=s.get("name", "Document"),
                relevance=float(s.get("relevance", 0.8)),
                chunk=s.get("chunk", "")[:2000],  # full chunk for admin (was 500)
            )
            for s in raw_sources[:8]  # show more sources for admin (was 5)
        ]
    else:
        # Users do not see raw document chunks
        sources = []

    # Enforce summarized response for non-admin users
    answer = result.get("answer", "")
    if role != "admin":
        # Truncate to a clear summary — no raw document exposure
        words = answer.split()
        if len(words) > 150:
            answer = " ".join(words[:150]) + "…"

    # Store chat log
    chat_log_id = str(uuid.uuid4())
    try:
        log = ChatLog(
            id=chat_log_id,
            user_id=current_user["user_id"],
            session_id=session_id,
            question=req.question,
            answer=answer,
            query_type=result.get("query_type", "fact"),
            graph_used=result.get("graph_used", False),
            confidence=confidence,
            sources=[{"name": s.name, "relevance": s.relevance} for s in sources],
            latency_ms=latency_ms,
        )
        db.add(log)
        # Update user activity
        _update_user_activity(db, current_user["user_id"])
        # Update total queries on user
        user = db.query(User).filter(User.id == current_user["user_id"]).first()
        if user:
            user.total_queries = (user.total_queries or 0) + 1
        db.commit()
    except Exception as e:
        logger.warning(f"Chat log storage failed: {e}")
        db.rollback()

    # Post-query self-learning
    try:
        sl.after_query(
            req.question, result.get("answer", ""),
            current_user["user_id"], session_id, confidence
        )
    except Exception:
        pass

    # Hallucination guard — score synchronously (reranker already loaded)
    grounding_score: Optional[float] = None
    grounding_warning: Optional[str] = None
    try:
        from services.hallucination_guard import compute_grounding_score
        raw_chunks = [s.get("chunk", "") for s in result.get("sources", []) if s.get("chunk")]
        if raw_chunks and answer:
            guard = compute_grounding_score(answer, raw_chunks)
            grounding_score = guard["grounding_score"]
            grounding_warning = guard["warning"]
    except Exception:
        pass

    # Explainability — admin gets full reasoning trace
    explanation: Optional[dict] = None
    if role == "admin":
        explanation = {
            "routing": result.get("routing_decision", "rag"),
            "rag_confidence": result.get("rag_confidence_score", 0.0),
            "graph_confidence": result.get("graph_confidence_score", 0.0),
            "reasoning_trace": result.get("reasoning_trace", []),
            "tools_used": result.get("tools_used", []),
            "provider_used": result.get("provider_used", "cohere"),
            "fallback_used": result.get("fallback_used", False),
            "grounding_score": grounding_score,
            "security": {
                "risk_level": security_info.get("risk_level", "LOW"),
                "pii_found": security_info.get("pii_found", []),
                "attack_score": security_info.get("attack_score", 0),
            },
        }

    return AskResponse(
        answer=answer,
        graph_used=result.get("graph_used", False),
        confidence=round(confidence, 1),
        query_type=result.get("query_type", "fact"),
        sources=sources,
        latency_ms=latency_ms,
        chat_log_id=chat_log_id,
        explanation=explanation,
        grounding_score=grounding_score,
        grounding_warning=grounding_warning,
        provider_used=result.get("provider_used", "cohere"),
        fallback_used=result.get("fallback_used", False),
    )


@router.get("/ask/stream")
async def ask_stream(
    question: str,
    role: str = "user",
    current_user: dict = Depends(get_current_user),
):
    """SSE streaming endpoint — returns token-by-token response."""
    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    async def event_generator():
        try:
            result = ask_rag_full(question, role)
            answer = result.get("answer", "No answer generated.")

            # Stream the metadata first
            meta = {
                "type": "meta",
                "graph_used": result.get("graph_used", False),
                "confidence": result.get("confidence", 75.0),
                "query_type": result.get("query_type", "fact"),
                "sources": result.get("sources", []),
            }
            yield f"data: {json.dumps(meta)}\n\n"

            # Stream answer tokens
            chunk_size = 4
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i:i + chunk_size]
                payload = {"type": "token", "text": chunk}
                yield f"data: {json.dumps(payload)}\n\n"

            # Done signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback")
def submit_feedback(
    req: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store user feedback on a chat response."""
    if req.feedback not in ("positive", "negative"):
        raise HTTPException(status_code=400, detail="Feedback must be 'positive' or 'negative'")

    # Find the chat log
    log = db.query(ChatLog).filter(ChatLog.id == req.chat_log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Chat log not found")

    log.feedback = req.feedback
    db.commit()

    # Record in self-learning service
    try:
        from services.self_learning import get_self_learning
        get_self_learning().record_feedback(
            log.question, log.answer, req.feedback, current_user["user_id"]
        )
    except Exception:
        pass

    # Store in feedback table
    fb = QueryFeedback(
        chat_log_id=req.chat_log_id,
        user_id=current_user["user_id"],
        question=log.question,
        answer=log.answer[:500],
        feedback=req.feedback,
        comment=req.comment,
    )
    db.add(fb)
    db.commit()

    return {"status": "ok", "message": f"Feedback '{req.feedback}' recorded"}


@router.get("/chat/history")
def get_chat_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's chat history."""
    logs = (
        db.query(ChatLog)
        .filter(ChatLog.user_id == current_user["user_id"])
        .order_by(ChatLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": l.id,
            "question": l.question,
            "answer": l.answer[:500],
            "query_type": l.query_type,
            "graph_used": l.graph_used,
            "confidence": l.confidence,
            "feedback": l.feedback,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_client),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    new_hash = hashlib.sha256(file_bytes).hexdigest()

    # ── A5: Document Versioning ───────────────────────────────────────────────
    existing: Document | None = db.query(Document).filter_by(filename=file.filename).first()
    if existing and existing.content_hash == new_hash:
        logger.info("[Upload] '%s' unchanged (hash match) — skip re-embed", file.filename)
        return UploadResponse(
            status="unchanged",
            filename=file.filename,
            message="Document is identical to the existing version — no re-processing needed.",
        )

    # Save file to disk
    dest = UPLOAD_DIR / file.filename
    try:
        dest.write_bytes(file_bytes)
    except Exception as e:
        from app.error_logger import log_error
        log_error("Upload", f"File save failed for '{file.filename}'", exc=e,
                  user=current_user.get("email"), extra={"filename": file.filename})
        logger.error(f"File save failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    # Delete stale Qdrant chunks for updated documents
    if existing:
        try:
            from app.services.rag_service import _get_rag
            rag = _get_rag()
            if rag:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                rag.client.delete(
                    collection_name=rag.collection_name,
                    points_selector=Filter(
                        must=[FieldCondition(key="file_name", match=MatchValue(value=file.filename))]
                    ),
                )
                logger.info("[Upload] Deleted stale Qdrant chunks for '%s'", file.filename)
        except Exception as e:
            logger.warning("[Upload] Could not delete stale chunks for '%s': %s", file.filename, e)

    # Upsert Document registry record
    try:
        if existing:
            existing.content_hash = new_hash
            existing.version = (existing.version or 1) + 1
            existing.file_size_bytes = len(file_bytes)
            existing.last_updated = datetime.utcnow()
            existing.ingested_by = current_user.get("user_id", "unknown")
        else:
            db.add(Document(
                filename=file.filename,
                content_hash=new_hash,
                version=1,
                file_size_bytes=len(file_bytes),
                ingested_by=current_user.get("user_id", "unknown"),
            ))
        db.commit()
    except Exception as e:
        logger.warning("[Upload] Document registry update failed: %s", e)
        db.rollback()

    # Queue for background ingestion (returns immediately — no more 5-min waits)
    tenant_id = current_user.get("tenant_id")
    try:
        from services.ingest_queue import get_ingest_queue
        q = get_ingest_queue()
        job_id = q.submit(str(dest), original_filename=file.filename, tenant_id=tenant_id)
        logger.info(f"[Upload] Queued '{file.filename}' as job {job_id}")
        version_label = f" (v{existing.version})" if existing else ""
        return UploadResponse(
            status="queued",
            filename=file.filename,
            message=f"File saved{version_label} and queued for processing (job: {job_id[:8]}…). It will be searchable within seconds.",
            entities=[],
        )
    except Exception as e:
        # Fallback: synchronous ingestion
        from app.error_logger import log_error
        log_error("Upload", f"Queue submit failed for '{file.filename}', trying sync", exc=e,
                  user=current_user.get("email"))
        try:
            entities = ingest_file(str(dest))
            return UploadResponse(
                status="success",
                filename=file.filename,
                message="Document ingested into vector store and knowledge graph.",
                entities=entities,
            )
        except Exception as e2:
            log_error("Upload", f"Ingestion failed for '{file.filename}'", exc=e2,
                      user=current_user.get("email"), extra={"filename": file.filename})
            return UploadResponse(
                status="partial",
                filename=file.filename,
                message=f"File saved but ingestion failed: {str(e2)}",
            )


@router.post("/upload/batch")
async def upload_folder(
    files: TypingList[UploadFile] = File(...),
    current_user: dict = Depends(require_client),
):
    """
    Batch upload endpoint — accepts up to 100+ files at once (folder upload).
    Files are saved to disk then immediately queued for background ingestion.
    Returns per-file job IDs instantly — poll /upload/status/{job_id} for progress.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    from services.ingest_queue import get_ingest_queue
    q = get_ingest_queue()

    results = []
    for file in files:
        if not file.filename:
            continue

        raw_name = file.filename.replace("/", "__").replace("\\", "__")
        suffix = Path(raw_name).suffix.lower()

        if suffix not in ALLOWED_EXTENSIONS:
            results.append({
                "filename": file.filename,
                "status": "skipped",
                "message": f"Unsupported file type '{suffix}'",
                "job_id": None,
            })
            continue

        dest = UPLOAD_DIR / raw_name
        try:
            with dest.open("wb") as f:
                shutil.copyfileobj(file.file, f)
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": f"Failed to save: {str(e)}",
                "job_id": None,
            })
            continue

        # Queue immediately — never block the HTTP handler on ingestion
        batch_tenant_id = current_user.get("tenant_id")
        try:
            job_id = q.submit(str(dest), original_filename=file.filename, tenant_id=batch_tenant_id)
            results.append({
                "filename": file.filename,
                "stored_as": raw_name,
                "status": "queued",
                "message": "Queued for background ingestion",
                "job_id": job_id,
            })
        except Exception as e:
            logger.error(f"[BatchUpload] Queue failed for {raw_name}: {e}")
            results.append({
                "filename": file.filename,
                "stored_as": raw_name,
                "status": "error",
                "message": f"Queue submit failed: {str(e)[:120]}",
                "job_id": None,
            })

    queued_count = sum(1 for r in results if r["status"] == "queued")
    error_count = sum(1 for r in results if r["status"] == "error")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")

    return {
        "status": "queued",
        "total": len(results),
        "queued": queued_count,
        "errors": error_count,
        "skipped": skipped_count,
        "queue_depth": q.queue_depth(),
        "files": results,
    }


# ── Ingest Queue endpoints ────────────────────────────────────────────────────

@router.post("/upload/async")
async def upload_async(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_client),
):
    """
    Non-blocking upload — saves the file, queues ingestion in background,
    returns a job_id immediately. Poll /upload/status/{job_id} for result.
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{suffix}'")

    dest = UPLOAD_DIR / file.filename
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    from services.ingest_queue import get_ingest_queue
    q = get_ingest_queue()
    job_id = q.submit(str(dest), original_filename=file.filename)
    return {"status": "queued", "job_id": job_id, "filename": file.filename}


@router.get("/upload/status/all")
def upload_status_all(current_user: dict = Depends(require_client)):
    """Return status of all recent ingest jobs (newest first, limit 50)."""
    from services.ingest_queue import get_ingest_queue
    return get_ingest_queue().all_statuses()[:50]


@router.get("/upload/status/{job_id}")
def upload_status(job_id: str, current_user: dict = Depends(require_client)):
    """Poll the status of an async ingestion job."""
    from services.ingest_queue import get_ingest_queue
    return get_ingest_queue().status(job_id)


@router.get("/system/reliability")
def system_reliability(current_user: dict = Depends(require_client)):
    """Return circuit breaker states for all external services."""
    from services.reliability import all_breaker_statuses
    return all_breaker_statuses()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_security_event(db: Session, user_id: str, email: str,
                         event_type: str, severity: str,
                         description: str, query: str):
    try:
        ev = SecurityEvent(
            user_id=user_id,
            user_email=email,
            event_type=event_type,
            severity=severity,
            description=description,
            query=query[:500],
        )
        db.add(ev)
        db.commit()
    except Exception as e:
        logger.warning(f"Security event log failed: {e}")
        db.rollback()


def _update_user_risk(db: Session, user_id: str):
    try:
        from services.security_service import compute_user_risk
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.suspicious_queries = (user.suspicious_queries or 0) + 1
            score, level = compute_user_risk(
                user.suspicious_queries, user.total_queries or 1
            )
            user.risk_score = score
            user.risk_level = level
            db.commit()
    except Exception as e:
        logger.warning(f"Risk update failed: {e}")
        db.rollback()


# Matches requests for the FILE LIST — but NOT requests to read a specific document
# (specific doc reads are handled by the EnhancedOrchestrator DOC_READ_INTENT)
_FILE_LIST_RE = re.compile(
    r"\b(list|show|display|what|which|all|get|give|tell).{0,30}(file|document|upload|doc)s?\b"
    r"|\b(uploaded|available)\s+(file|document|doc)s?\b"
    r"|\bfile\s*(list|name)s?\b",
    re.IGNORECASE,
)
# Patterns that indicate a specific document read — skip file list for these
_DOC_READ_RE = re.compile(
    r"\b(show|display|read|print|give|fetch|get)\b.{0,50}\.(pdf|xml|txt|docx|json|csv|html|pptx|md)\b"
    r"|whole\s+document|entire\s+document|every\s+line|as\s+it\s+is|full\s+content"
    r"|contents?\s+of\s+\w",
    re.IGNORECASE,
)
_LOG_RE = re.compile(
    r"\b(error|system|access|recent|latest|last|show|get)\s+(log|error|warning)s?\b"
    r"|\blog\s+(entry|entries|file)\b"
    r"|\b(what|show|get|access)\s+.{0,20}log\b",
    re.IGNORECASE,
)


def _try_admin_intent(question: str):
    """
    Detect admin-only system intents and answer them directly without going through RAG.
    Returns a formatted string answer or None (fall through to RAG).
    """
    q = question.strip()

    # ── Intent: list uploaded files ──────────────────────────────────────────
    # Skip if the query is asking to read a specific document (let RAG handle it)
    if _FILE_LIST_RE.search(q) and not _DOC_READ_RE.search(q):
        try:
            from services.document_reader import DocumentReader
            import os
            reader = DocumentReader()
            files = reader.list_files()
            if not files:
                return "No documents have been uploaded yet. Use the Upload tab to add files."
            lines = [f"**{i+1}. {f}**" for i, f in enumerate(files)]
            return (
                f"There are **{len(files)} uploaded document(s)** in the system:\n\n"
                + "\n".join(lines)
            )
        except Exception as e:
            logger.warning(f"[AdminIntent] File list failed: {e}")

    # ── Intent: access system / error logs ───────────────────────────────────
    if _LOG_RE.search(q):
        try:
            from app.error_logger import read_recent_errors
            entries = read_recent_errors(limit=10)
            if not entries:
                return "No error log entries found. The system is running cleanly."
            lines = []
            for e in entries:
                ts = e.get("timestamp", "")[:19]
                lvl = e.get("level", "")
                src = e.get("source", "")
                msg = e.get("message", "")[:200]
                lines.append(f"[{ts}] **{lvl}** ({src}): {msg}")
            return (
                f"**Last {len(entries)} system log entries** (newest first):\n\n"
                + "\n".join(lines)
                + "\n\nFor full logs use the Admin Panel → System Logs tab."
            )
        except Exception as e:
            logger.warning(f"[AdminIntent] Log read failed: {e}")

    return None  # fall through to RAG


def _update_user_activity(db: Session, user_id: str):
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        activity = (
            db.query(UserActivity)
            .filter(UserActivity.user_id == user_id, UserActivity.date == today)
            .first()
        )
        if activity:
            activity.queries_count += 1
        else:
            activity = UserActivity(user_id=user_id, date=today, queries_count=1)
            db.add(activity)
        db.commit()
    except Exception as e:
        logger.warning(f"Activity update failed: {e}")
        db.rollback()

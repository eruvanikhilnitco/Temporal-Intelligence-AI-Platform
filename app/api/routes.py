import os
import shutil
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
import json

from app.api.schemas import AskRequest, AskResponse, UploadResponse, HealthResponse, SourceItem, FeedbackRequest
from app.services.rag_service import ask_rag, ask_rag_full, ingest_file
from app.dependencies import get_current_user, require_client, OptionalUser
from app.db import get_db
from app.models import ChatLog, SecurityEvent, UserActivity, QueryFeedback, User
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


@router.post("/ask", response_model=AskResponse)
def ask_question(
    req: AskRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
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

    # Security check
    try:
        from services.security_service import analyze_query, compute_user_risk
        threat = analyze_query(req.question, current_user["user_id"], role)
        if threat.is_threat:
            # Log security event
            _log_security_event(
                db=db,
                user_id=current_user["user_id"],
                email=current_user.get("email", ""),
                event_type=threat.threat_type,
                severity=threat.severity,
                description=threat.description,
                query=req.question,
            )
            # Update user risk score
            _update_user_risk(db, current_user["user_id"])
            if threat.severity == "high":
                raise HTTPException(status_code=400, detail=f"Query blocked: {threat.description}")
    except ImportError:
        pass

    t_start = time.time()
    session_id = req.session_id or current_user.get("user_id", "anon")

    # Use self-learning service
    try:
        from services.self_learning import get_self_learning
        sl = get_self_learning()
        hints = sl.before_query(req.question, current_user["user_id"], session_id)
        enriched_q = hints.get("enriched_query", req.question)
    except Exception:
        enriched_q = req.question
        hints = {}

    # Use agent orchestrator
    result = ask_rag_full(enriched_q, role, session_id=session_id)

    latency_ms = int((time.time() - t_start) * 1000)

    # Adjust confidence with feedback signal
    confidence = result.get("confidence", 75.0)
    if hints:
        confidence = min(confidence + hints.get("confidence_modifier", 0) * 100, 99.0)

    # Build sources — admin sees chunks, user sees none
    raw_sources = result.get("sources", [])
    if role == "admin":
        sources = [
            SourceItem(
                name=s.get("name", "Document"),
                relevance=float(s.get("relevance", 0.8)),
                chunk=s.get("chunk", "")[:500],
            )
            for s in raw_sources[:5]
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

    return AskResponse(
        answer=answer,
        graph_used=result.get("graph_used", False),
        confidence=round(confidence, 1),
        query_type=result.get("query_type", "fact"),
        sources=sources,
        latency_ms=latency_ms,
        chat_log_id=chat_log_id,
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
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    dest = UPLOAD_DIR / file.filename
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        logger.error(f"File save failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    try:
        entities = ingest_file(str(dest))
        return UploadResponse(
            status="success",
            filename=file.filename,
            message="Document ingested into vector store and knowledge graph.",
            entities=entities,
        )
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return UploadResponse(
            status="partial",
            filename=file.filename,
            message=f"File saved but ingestion encountered an error: {str(e)}",
        )


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

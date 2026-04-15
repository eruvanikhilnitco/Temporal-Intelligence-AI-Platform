import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as rag_router
from app.api.auth_routes import router as auth_router
from app.api.admin_routes import router as admin_router
from app.api.sharepoint_routes import router as sharepoint_router
from app.api.website_routes import router as website_router
from app.db import init_db, get_db
from core.config import get_settings
from app.error_logger import get_error_middleware, log_critical

settings = get_settings()

app = FastAPI(
    title="CortexFlow AI API",
    description=(
        "Enterprise RAG platform with Graph Intelligence, Agent Orchestration, "
        "Self-Learning, Zero-Trust Security, and Real-time Streaming."
    ),
    version="4.0.0",
)

# Error logging middleware must be added BEFORE CORSMiddleware so it wraps everything
app.add_middleware(get_error_middleware())

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        log_critical("Startup", "Database initialisation failed", exc=e)
    _seed_default_rules()
    _seed_superadmin()
    _warmup_rag_background()
    _start_ingest_queue()
    _start_health_monitor()
    _resume_sharepoint_connections()
    _start_scheduler()
    logging.getLogger(__name__).info("[Startup] CortexFlow v5.0 started — error log: logs/error_log.jsonl")


def _start_ingest_queue():
    """Start the background document ingest queue."""
    try:
        from services.ingest_queue import get_ingest_queue
        get_ingest_queue()  # Initialises and starts the worker thread
        logging.getLogger(__name__).info("[Startup] Ingest queue worker started")
    except Exception as e:
        logging.getLogger(__name__).warning(f"[Startup] Ingest queue failed to start: {e}")


def _start_health_monitor():
    """Start background service health checks (Neo4j, Qdrant)."""
    try:
        from services.health_monitor import start_health_monitor
        start_health_monitor(interval=30)
        logging.getLogger(__name__).info("[Startup] Health monitor started")
    except Exception as e:
        logging.getLogger(__name__).warning(f"[Startup] Health monitor failed to start: {e}")


def _start_scheduler():
    """Start the centralized scheduling service for website + SharePoint updates."""
    try:
        from services.scheduler_service import start_scheduler
        start_scheduler()
        logging.getLogger(__name__).info("[Startup] Scheduler service started")
    except Exception as e:
        logging.getLogger(__name__).warning(f"[Startup] Scheduler failed to start (non-fatal): {e}")


def _resume_sharepoint_connections():
    """Resume delta sync for any SharePoint connections that were active before restart."""
    try:
        from services.sharepoint_service import get_sharepoint_service
        svc = get_sharepoint_service()
        svc.resume_connections()
        logging.getLogger(__name__).info("[Startup] SharePoint connections resumed")
    except Exception as e:
        logging.getLogger(__name__).warning(f"[Startup] SharePoint resume failed (non-fatal): {e}")


def _seed_superadmin():
    """
    Ensure the hardcoded superadmin account exists on every startup.
    Credentials: n.eruva@nitcoinc.com / Nikhil@1234
    This is the ONLY admin account; the signup endpoint for admin is blocked.
    """
    import logging
    logger = logging.getLogger(__name__)
    SUPERADMIN_EMAIL    = "n.eruva@nitcoinc.com"
    SUPERADMIN_PASSWORD = "Nikhil@1234"
    SUPERADMIN_NAME     = "Nikhil Eruva (Superadmin)"

    try:
        from app.db import get_db
        from app.models import User
        from app.core.security import hash_password
        db = next(get_db())
        existing = db.query(User).filter(User.email == SUPERADMIN_EMAIL).first()
        if existing:
            # Ensure role is admin (in case of data corruption)
            if existing.role != "admin":
                existing.role = "admin"
                db.commit()
            db.close()
            logger.info("[Startup] Superadmin already exists: %s", SUPERADMIN_EMAIL)
            return

        superadmin = User(
            email=SUPERADMIN_EMAIL,
            name=SUPERADMIN_NAME,
            password_hash=hash_password(SUPERADMIN_PASSWORD),
            role="admin",
        )
        db.add(superadmin)
        db.commit()
        db.close()
        logger.info("[Startup] Superadmin seeded: %s", SUPERADMIN_EMAIL)
    except Exception as e:
        logging.getLogger(__name__).warning(f"[Startup] Superadmin seed failed (non-fatal): {e}")


def _warmup_rag_background():
    """Pre-load all ML models + orchestrator in a background thread so first queries are instant."""
    import threading
    import logging
    logger = logging.getLogger(__name__)

    def warmup():
        try:
            logger.info("[Warmup] Pre-loading RAG pipeline (embedding model + reranker)…")
            from app.services.rag_service import _get_rag, _get_orchestrator
            rag = _get_rag()
            if rag is None:
                logger.warning("[Warmup] RAG unavailable — Qdrant may be offline.")
                return
            # Also pre-initialize the orchestrator so the first user query is instant
            orch = _get_orchestrator()
            if orch is None:
                logger.warning("[Warmup] Orchestrator init failed.")
                return
            logger.info("[Warmup] All models ready — first query will be fast.")
        except Exception as e:
            logger.warning(f"[Warmup] RAG warmup failed (non-fatal): {e}")

    t = threading.Thread(target=warmup, daemon=True)
    t.start()


def _seed_default_rules():
    """Seed the rules table with sensible defaults on first run."""
    try:
        from app.models import Rule
        db = next(get_db())
        count = db.query(Rule).count()
        if count == 0:
            defaults = [
                Rule(name="Block PII queries",
                     pattern=r"ssn|social.security|passport.number|date.of.birth",
                     action="block", role="public", active=True),
                Rule(name="Warn on financial PII",
                     pattern=r"salary|compensation|credit.card|bank.account",
                     action="warn", role="public", active=True),
                Rule(name="Admin-only confidential",
                     pattern=r"confidential|restricted|internal.only|top.secret",
                     action="restrict", role="user", active=True),
                Rule(name="Block prompt injection",
                     pattern=r"ignore.previous|forget.everything|jailbreak|DAN\b",
                     action="block", role="public", active=True),
                Rule(name="Log SQL-like queries",
                     pattern=r"DROP\s+TABLE|DELETE\s+FROM|UNION\s+SELECT",
                     action="log", role="public", active=True),
            ]
            for rule in defaults:
                db.add(rule)
            db.commit()
        db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Rule seeding skipped: {e}")


app.include_router(auth_router)
app.include_router(rag_router)
app.include_router(admin_router)
app.include_router(sharepoint_router)
app.include_router(website_router)

# ── Serve built React SPA from FastAPI (port 8000) ──────────────────────────
_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _DIST.exists():
    # Static assets (hashed filenames — safe to mount before the catch-all)
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    _API_PREFIXES = (
        "auth/", "ask", "upload", "health", "admin/", "chat/",
        "feedback", "sharepoint/", "website/", "api/",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Let API paths fall through (should already be handled above, but safety net)
        if any(full_path.startswith(p) for p in _API_PREFIXES):
            raise HTTPException(status_code=404)
        # Serve index.html for all other paths (React Router handles them)
        return FileResponse(str(_DIST / "index.html"))

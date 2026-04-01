from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as rag_router
from app.api.auth_routes import router as auth_router
from app.api.admin_routes import router as admin_router
from app.db import init_db, get_db
from core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="CortexFlow AI API",
    description=(
        "Enterprise RAG platform with Graph Intelligence, Agent Orchestration, "
        "Self-Learning, Zero-Trust Security, and Real-time Streaming."
    ),
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    # Create all database tables
    init_db()
    # Seed default security rules if none exist
    _seed_default_rules()


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

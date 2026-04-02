import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from core.config import get_settings
from typing import Generator

logger = logging.getLogger(__name__)
settings = get_settings()

# Try PostgreSQL first; fall back to SQLite for local dev
_POSTGRES_URL = (
    f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/cortexflow_db"
)
_SQLITE_URL = "sqlite:///./cortexflow.db"


def _make_engine():
    try:
        eng = create_engine(_POSTGRES_URL, pool_pre_ping=True, connect_args={})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("[DB] Connected to PostgreSQL")
        return eng
    except Exception as e:
        logger.warning(f"[DB] PostgreSQL unavailable ({e}), falling back to SQLite")
        return create_engine(
            _SQLITE_URL,
            connect_args={"check_same_thread": False},
        )


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    from app.models import Base
    Base.metadata.create_all(bind=engine)

from sqlalchemy import Column, String, DateTime, Boolean, Integer, Float, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="client")  # admin, client
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    login_attempts = Column(Integer, default=0)
    risk_score = Column(Integer, default=0)           # 0–100
    risk_level = Column(String, default="low")        # low, medium, high, critical
    total_queries = Column(Integer, default=0)
    suspicious_queries = Column(Integer, default=0)

    def __repr__(self):
        return f"<User {self.email}>"


class ChatLog(Base):
    """Stores all chat interactions for self-learning and audit."""
    __tablename__ = "chat_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    session_id = Column(String, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    query_type = Column(String, default="fact")
    graph_used = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    sources = Column(JSON, default=list)
    latency_ms = Column(Integer, default=0)
    feedback = Column(String, nullable=True)      # positive, negative, None
    created_at = Column(DateTime, default=datetime.utcnow)


class SecurityEvent(Base):
    """Logs security-related events: prompt injection, rate limits, etc."""
    __tablename__ = "security_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=True, index=True)
    user_email = Column(String, nullable=True)
    event_type = Column(String, nullable=False)   # prompt_injection, rate_limit, unauthorized, scraping
    severity = Column(String, default="medium")   # low, medium, high, critical
    description = Column(Text, nullable=False)
    query = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Rule(Base):
    """Dynamic rule engine: keyword filtering, access control per role."""
    __tablename__ = "rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    pattern = Column(String, nullable=False)      # regex pattern
    action = Column(String, default="block")      # block, warn, restrict, log
    role = Column(String, default="public")       # public, user, admin
    active = Column(Boolean, default=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserActivity(Base):
    """Tracks per-user daily activity for analytics and self-learning."""
    __tablename__ = "user_activity"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    date = Column(String, index=True)             # YYYY-MM-DD
    queries_count = Column(Integer, default=0)
    uploads_count = Column(Integer, default=0)
    avg_confidence = Column(Float, default=0.0)
    cache_hits = Column(Integer, default=0)
    graph_queries = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class QueryFeedback(Base):
    """Stores user thumbs up/down feedback for self-learning loop."""
    __tablename__ = "query_feedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_log_id = Column(String, index=True)
    user_id = Column(String, index=True)
    question = Column(Text)
    answer = Column(Text)
    feedback = Column(String)                     # positive, negative
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

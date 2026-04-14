from sqlalchemy import Column, String, DateTime, Boolean, Integer, Float, Text, JSON, BigInteger
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


class ApiKey(Base):
    """
    External API keys for organisation integrations.
    Admins generate keys; external systems use X-API-Key header.
    Only the SHA-256 hash is stored — plaintext is shown once at creation.
    """
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)                      # e.g. "Acme Corp Chatbot"
    key_hash = Column(String, nullable=False, unique=True)     # SHA-256 of raw key
    key_prefix = Column(String, nullable=False)                # first 12 chars for identification
    created_by = Column(String, nullable=True)                 # admin user_id
    permissions = Column(String, default="read")               # read, read_write
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)               # None = never expires
    last_used_at = Column(DateTime, nullable=True)
    total_requests = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)                        # admin notes


class ApiKeyUsage(Base):
    """Per-request usage log for API keys (capped at last 1000 per key)."""
    __tablename__ = "api_key_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String, index=True, nullable=False)
    endpoint = Column(String, nullable=False)
    method = Column(String, default="POST")
    status_code = Column(Integer, default=200)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Document(Base):
    """
    Document registry: tracks every uploaded file with content hash + version.
    Enables skip-re-embed on unchanged re-upload and stale chunk cleanup.
    """
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False, index=True, unique=True)
    content_hash = Column(String, nullable=False)              # SHA-256 of file bytes
    version = Column(Integer, default=1)
    chunk_count = Column(Integer, default=0)
    file_size_bytes = Column(Integer, default=0)
    access_roles = Column(JSON, default=list)                  # ["admin"] etc.
    ingested_by = Column(String, nullable=True)                # user_id or "api_key:{id}"
    last_updated = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class SharePointConnection(Base):
    """
    Tracks an admin-established SharePoint site connection.
    One row = one connected site. Stays active until admin disconnects.
    """
    __tablename__ = "sharepoint_connections"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    site_url = Column(String, nullable=False, index=True)       # full SharePoint site URL
    site_id = Column(String, nullable=True)                     # resolved MS Graph site ID
    site_display_name = Column(String, nullable=True)
    status = Column(String, default="connected")                # connected | disconnected
    # Webhook subscription IDs (one per drive, stored as JSON list)
    webhook_subscription_ids = Column(JSON, default=list)
    webhook_expiry = Column(DateTime, nullable=True)            # when subscriptions expire
    # Delta sync change token (persisted so we resume from correct point after restart)
    delta_token = Column(Text, nullable=True)
    connected_by = Column(String, nullable=True)                # admin user_id
    connected_at = Column(DateTime, default=datetime.utcnow)
    disconnected_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)


class SharePointFile(Base):
    """
    Metadata registry for every SharePoint file that has been ingested.
    Used to detect new/modified/deleted files and skip unchanged files.

    Primary key: sharepoint_file_id (stable MS Graph item ID — survives renames).
    """
    __tablename__ = "sharepoint_files"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id = Column(String, index=True, nullable=False)  # FK → sharepoint_connections.id
    sharepoint_file_id = Column(String, nullable=False, index=True, unique=True)  # stable item ID
    file_name = Column(String, nullable=False)
    folder_path = Column(String, nullable=True)                 # /sites/Finance/Shared Docs/Q1/
    drive_id = Column(String, nullable=True)
    site_id = Column(String, nullable=True)
    last_modified = Column(DateTime, nullable=True)             # from MS Graph lastModifiedDateTime
    content_hash = Column(String, nullable=True)                # SHA-256 of downloaded bytes
    version = Column(Integer, default=1)                        # increments on each update
    indexed_status = Column(String, default="pending")          # pending | indexed | failed | deleted
    chunk_count = Column(Integer, default=0)
    file_size_bytes = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

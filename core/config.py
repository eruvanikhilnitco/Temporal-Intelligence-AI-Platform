from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ---------------- DB CONFIG ----------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "outcomes_db"
    postgres_user: str = "postgres"
    postgres_password: str = "password123"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # ---------------- MODELS ----------------
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    spacy_model: str = "en_core_web_sm"

    # Token-based chunking — 500 tokens (enterprise quality), 100 overlap (strong continuity)
    # BGE-large max context = 512 tokens; 500 leaves room for special tokens overhead
    chunk_token_size: int = 500
    chunk_token_overlap: int = 100

    # ---------------- API ----------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me"
    api_key: str = "dev-local-key"

    allowed_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]

    max_upload_size: int = 500 * 1024 * 1024  # 500 MB — no practical limit
    upload_dir: str = "./uploads"

    # ---------------- LLM CONFIG ----------------

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"

    # Redis (cache persistence + sessions)
    redis_url: str = ""   # e.g. redis://localhost:6379/0  — leave empty to use in-memory cache

    # MinIO / S3 (object storage for raw files and HTML snapshots)
    minio_endpoint: str = ""        # e.g. localhost:9000
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "cortexflow"
    minio_secure: bool = False      # True for HTTPS/production

    # SharePoint (Microsoft Graph API)
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str = ""
    sharepoint_notification_url: str = ""   # Public HTTPS URL for webhooks (e.g. https://yourhost.com)
    sharepoint_delta_sync_interval: int = 300  # seconds (5 min)

    # Cohere
    cohere_api_key: Optional[str] = None
    cohere_model: str = "command-r7b-12-2024"

    # Ollama (local LLM)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    use_ollama: bool = False

    chatbot_max_sources: int = 8
    chatbot_max_context_chars: int = 12000
    chatbot_memory_turns: int = 6

    # ---------------- PERFORMANCE ----------------
    # Ingest queue: number of parallel worker threads (auto-detected at runtime if 0)
    ingest_workers: int = 4
    # Embedding cache: max vectors to keep in process memory
    embed_cache_max: int = 5000
    # Query cache: max entries before LRU eviction kicks in
    cache_max_entries: int = 2000
    # Query cache TTL in seconds (default 10 min)
    cache_ttl: int = 600
    # Qdrant batch upsert size
    qdrant_batch_size: int = 256

    # ---------------- CONFIG ----------------
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"  # 🔥 FIX: allow unknown env variables


@lru_cache
def get_settings() -> Settings:
    return Settings()
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
    spacy_model: str = "en_core_web_sm"

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

    max_upload_size: int = 10 * 1024 * 1024
    upload_dir: str = "./uploads"

    # ---------------- LLM CONFIG ----------------

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Cohere (🔥 ADD THIS)
    cohere_api_key: Optional[str] = None
    cohere_model: str = "command-r7b-12-2024"

    # Ollama (local LLM)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    use_ollama: bool = False

    chatbot_max_sources: int = 8
    chatbot_max_context_chars: int = 12000
    chatbot_memory_turns: int = 6

    # ---------------- CONFIG ----------------
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"  # 🔥 FIX: allow unknown env variables


@lru_cache
def get_settings() -> Settings:
    return Settings()
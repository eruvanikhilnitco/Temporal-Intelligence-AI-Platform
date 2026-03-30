from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7689"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password123"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "outcomes_db"
    postgres_user: str = "postgres"
    postgres_password: str = "password123"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    embedding_model: str = "BAAI/bge-large-en-v1.5"
    spacy_model: str = "en_core_web_sm"

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
    # Optional LLM settings for chatbot synthesis.
    # OpenAI settings
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    # Ollama settings (local LLM, no API key required)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"  # or "mistral", "llama2", etc.
    use_ollama: bool = False  # Set to True to use Ollama instead of OpenAI
    chatbot_max_sources: int = 8
    chatbot_max_context_chars: int = 12000
    chatbot_memory_turns: int = 6

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()

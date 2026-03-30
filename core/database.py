from dataclasses import dataclass
from typing import Optional

from core.config import get_settings


@dataclass
class Neo4jConnection:
    uri: str
    user: str
    password: str


@dataclass
class PostgresConnection:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass
class QdrantConnection:
    host: str
    port: int


def get_neo4j_connection() -> Neo4jConnection:
    settings = get_settings()
    return Neo4jConnection(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )


def get_postgres_connection() -> PostgresConnection:
    settings = get_settings()
    return PostgresConnection(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


def get_qdrant_connection() -> QdrantConnection:
    settings = get_settings()
    return QdrantConnection(host=settings.qdrant_host, port=settings.qdrant_port)


_initialized: Optional[bool] = None


def initialize_datastores() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

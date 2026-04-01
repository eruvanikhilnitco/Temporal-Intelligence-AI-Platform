import logging
from typing import Optional
from services.phase1_rag import Phase1RAG

logger = logging.getLogger(__name__)

rag = Phase1RAG(folder_path="sample_data")

# Lazy-init orchestrator to avoid circular imports
_orchestrator = None


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        try:
            from services.agent_orchestrator import AgentOrchestrator
            _orchestrator = AgentOrchestrator(
                phase1_rag=rag,
                graph_service=rag.graph_rag.graph,
                llm_service=rag.llm,
                cache_service=rag.cache,
                reranker=rag.reranker,
                classifier=rag.classifier,
            )
            logger.info("[RAGService] Agent orchestrator initialized")
        except Exception as e:
            logger.warning(f"[RAGService] Orchestrator init failed: {e}")
            _orchestrator = None
    return _orchestrator


def ask_rag(question: str, role: str) -> str:
    """Legacy single-string response for backward compat."""
    result = ask_rag_full(question, role)
    return result.get("answer", "")


def ask_rag_full(question: str, role: str, session_id: str = "") -> dict:
    """
    Full response with sources, confidence, query type, graph_used.
    Uses Agent Orchestrator when available, falls back to Phase1RAG.
    """
    orch = _get_orchestrator()

    if orch is not None:
        try:
            state = orch.run(question, user_role=role, session_id=session_id)
            return {
                "answer": state.answer,
                "graph_used": bool(state.graph_context),
                "confidence": state.confidence,
                "query_type": state.query_type,
                "sources": state.sources,
                "cache_hit": state.cache_hit,
                "tools_used": state.tools_used,
            }
        except Exception as e:
            logger.error(f"[RAGService] Orchestrator error: {e}")

    # Fallback to Phase1RAG directly
    answer = rag.ask(question, user_role=role)
    return {
        "answer": answer,
        "graph_used": False,
        "confidence": 75.0,
        "query_type": "fact",
        "sources": [],
        "cache_hit": False,
        "tools_used": ["DocumentSearchTool"],
    }


def ingest_file(file_path: str) -> Optional[dict]:
    """
    Ingest a single uploaded file:
      1. Run the pipeline on that file to get chunks
      2. Store embeddings in Qdrant
      3. Extract entities and store in Neo4j (Phase 3)

    Returns extracted entity dict or None on error.
    """
    import uuid
    from pathlib import Path
    from services.phase1_pipeline import Phase1Pipeline
    from qdrant_client.models import PointStruct

    pipeline = Phase1Pipeline(folder_path=str(Path(file_path).parent))

    try:
        text = pipeline.extract_text(file_path)
    except Exception as e:
        logger.error(f"Text extraction failed for {file_path}: {e}")
        raise

    chunks = pipeline.chunk_text(text)
    fname = Path(file_path).name
    access_roles = pipeline._infer_access_roles(file_path, text)

    points = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        vector = rag.embedder.embed(chunk)
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={"text": chunk, "file_name": fname, "access_roles": access_roles},
            )
        )

    if points:
        rag.client.upsert(collection_name=rag.collection_name, points=points)
        logger.info(f"Stored {len(points)} vectors for {fname}")

    # Phase 3: build graph
    entities = rag.graph_rag.ingest_document(text, fname)
    logger.info(f"Graph ingestion complete for {fname}: {entities}")

    return entities

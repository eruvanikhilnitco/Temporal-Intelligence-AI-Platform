import logging
from typing import Optional

from app.error_logger import log_error, log_warning

logger = logging.getLogger(__name__)

# Lazy-init RAG to avoid crashing the backend if Qdrant/Neo4j are unavailable
_rag = None
_orchestrator = None


def _get_rag():
    global _rag
    if _rag is None:
        try:
            from services.phase1_rag import Phase1RAG
            _rag = Phase1RAG(folder_path="sample_data")
            logger.info("[RAGService] Phase1RAG initialized")
        except Exception as e:
            logger.warning(f"[RAGService] Phase1RAG init failed (Qdrant/Neo4j may be offline): {e}")
            _rag = None
    return _rag


def _get_orchestrator():
    global _orchestrator
    rag = _get_rag()
    if rag is None:
        return None
    if _orchestrator is None:
        try:
            # Use EnhancedAgentOrchestrator (extends AgentOrchestrator — OCP)
            from services.enhanced_orchestrator import EnhancedAgentOrchestrator
            _orchestrator = EnhancedAgentOrchestrator(
                phase1_rag=rag,
                graph_service=rag.graph_rag.graph,
                llm_service=rag.llm,
                cache_service=rag.cache,
                reranker=rag.reranker,
                classifier=rag.classifier,
            )
            logger.info("[RAGService] EnhancedAgentOrchestrator initialized")
        except Exception as e:
            logger.warning(f"[RAGService] Enhanced orchestrator init failed, "
                           f"falling back to base: {e}")
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
                logger.info("[RAGService] Fallback: base AgentOrchestrator initialized")
            except Exception as e2:
                logger.warning(f"[RAGService] Orchestrator init failed: {e2}")
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
    Returns a graceful message if AI backend is unavailable.
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
            log_error("RAGService", "Orchestrator query failed", exc=e,
                      extra={"question": question[:200], "role": role})

    rag = _get_rag()
    if rag is not None:
        try:
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
        except Exception as e:
            log_error("RAGService", "Phase1RAG query failed", exc=e,
                      extra={"question": question[:200], "role": role})

    return {
        "answer": "The AI retrieval service is currently unavailable. Please ensure Qdrant is running and documents have been ingested.",
        "graph_used": False,
        "confidence": 0.0,
        "query_type": "error",
        "sources": [],
        "cache_hit": False,
        "tools_used": [],
    }


def ingest_file(file_path: str) -> Optional[dict]:
    """
    Ingest a single uploaded file into Qdrant and Neo4j.
    Returns extracted entity dict or None on error.
    """
    import uuid
    from pathlib import Path
    from services.phase1_pipeline import Phase1Pipeline
    from qdrant_client.models import PointStruct

    rag = _get_rag()
    if rag is None:
        raise RuntimeError("RAG service unavailable — Qdrant may be offline.")

    pipeline = Phase1Pipeline(folder_path=str(Path(file_path).parent))

    try:
        text = pipeline.extract_text(file_path)
    except Exception as e:
        log_error("Ingest", f"Text extraction failed for {Path(file_path).name}", exc=e,
                  extra={"file_path": file_path})
        raise

    chunks = pipeline.chunk_text(text)
    fname = Path(file_path).name
    access_roles = pipeline._infer_access_roles(file_path, text)

    # Automatic metadata extraction (no hardcoding — MetadataExtractor driven)
    metadata: dict = {}
    try:
        from services.metadata_extractor import MetadataExtractor
        metadata = MetadataExtractor().extract(text, filename=fname)
        logger.info(f"[ingest] Metadata for {fname}: {metadata}")
    except Exception as e:
        logger.warning(f"[ingest] Metadata extraction failed: {e}")

    points = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        vector = rag.embedder.embed(chunk)
        payload = {
            "text": chunk,
            "file_name": fname,
            "access_roles": access_roles,
            # Metadata enrichment — stored per chunk for filtered retrieval
            "domain": metadata.get("domain", "general"),
            "doc_type": metadata.get("doc_type", "document"),
            "sensitivity": metadata.get("sensitivity", "low"),
        }
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload=payload,
            )
        )

    if points:
        rag.client.upsert(collection_name=rag.collection_name, points=points)
        logger.info(f"Stored {len(points)} vectors for {fname}")

    entities = rag.graph_rag.ingest_document(text, fname)
    logger.info(f"Graph ingestion complete for {fname}: {entities}")

    # Store document metadata in graph and build cross-document links
    try:
        graph_svc = rag.graph_rag.graph
        if metadata:
            graph_svc.store_document_metadata(fname, metadata)
        if entities:
            cross_links = graph_svc.create_cross_document_links(fname, entities)
            logger.info(f"[ingest] Created {cross_links} cross-document links for {fname}")
    except Exception as e:
        logger.warning(f"[ingest] Cross-document linking failed: {e}")

    return entities

"""
EnhancedAgentOrchestrator — extends AgentOrchestrator with:
  1. DocumentLineReaderTool  — exact line / full-document retrieval (verbatim)
  2. CrossDocumentTool       — per-document labeled retrieval for comparisons
  3. Metadata-aware context  — enriches sources with domain/sensitivity tags

SOLID:
  - Open/Closed: inherits AgentOrchestrator, overrides only affected nodes.
  - Liskov:      drop-in replacement for AgentOrchestrator.
  - DI:          DocumentReader, MetadataExtractor, QdrantClient are injected.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable

from services.agent_orchestrator import (
    AgentOrchestrator, AgentState, ToolResult,
    DocumentSearchTool, SummarizationTool,
)
from services.document_reader import DocumentReader, get_document_reader
from services.metadata_extractor import MetadataExtractor

logger = logging.getLogger(__name__)


# ── New tools ─────────────────────────────────────────────────────────────────

class DocumentLineReaderTool:
    """
    Reads exact lines or full content from uploaded documents — zero LLM involved.
    Short-circuits all retrieval for document-read queries.
    """

    def __init__(self, reader: DocumentReader):
        self.reader = reader

    def run(self, query: str) -> ToolResult:
        t0 = time.time()
        try:
            req = self.reader.parse_query(query)
            if not req.is_doc_read:
                return ToolResult("DocumentLineReaderTool", False, None,
                                  error="Not a document-read query")
            content = self.reader.read(req)
            return ToolResult(
                tool_name="DocumentLineReaderTool",
                success=True,
                data={"content": content, "request": req},
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as e:
            logger.error(f"[DocumentLineReaderTool] {e}")
            return ToolResult("DocumentLineReaderTool", False, None, error=str(e))


class SourceAnnotatedSearchTool:
    """
    Like DocumentSearchTool but returns (text, source_file) tuples.
    Enables proper attribution in cross-document queries.
    """

    def __init__(self, qdrant_client, collection_name: str, embedder):
        self.client = qdrant_client
        self.collection = collection_name
        self.embedder = embedder

    def run(self, query: str, user_role: str, top_k: int = 10, file_filter: Optional[str] = None, tenant_id: Optional[str] = None) -> ToolResult:
        t0 = time.time()
        try:
            vector = self.embedder.embed(query)
            must_conditions = []
            if user_role != "admin":
                must_conditions.append({"key": "access_roles", "match": {"value": user_role}})
            if tenant_id:
                must_conditions.append({"key": "tenant_id", "match": {"value": tenant_id}})
            if file_filter:
                must_conditions.append(
                    {"key": "file_name", "match": {"value": file_filter}}
                )
            results = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                limit=top_k,
                query_filter={"must": must_conditions} if must_conditions else None,
            )
            annotated = [
                {
                    "text": p.payload.get("text", ""),
                    "file_name": p.payload.get("file_name", "Unknown"),
                    "score": getattr(p, "score", 0.0),
                    "domain": p.payload.get("domain", "general"),
                }
                for p in results.points
                if p.payload.get("text", "").strip()
            ]
            return ToolResult(
                "SourceAnnotatedSearchTool", True, annotated,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as e:
            logger.error(f"[SourceAnnotatedSearchTool] {e}")
            return ToolResult("SourceAnnotatedSearchTool", False, [], error=str(e))


class CrossDocumentTool:
    """
    Multi-document comparison retrieval.
    Detects mentioned documents, retrieves from each separately, labels results.
    """

    COMPARE_PATTERN = re.compile(
        r"\b(?:compare|contrast|difference|similar|both|between|versus|vs\.?|"
        r"across\s+(?:documents?|files?)|multiple\s+(?:documents?|files?)|"
        r"from\s+(?:both|all|different)\s+(?:documents?|files?))\b",
        re.IGNORECASE,
    )

    def __init__(self, reader: DocumentReader, annotated_searcher: Optional[SourceAnnotatedSearchTool] = None):
        self.reader = reader
        self.searcher = annotated_searcher

    def is_cross_doc_query(self, query: str) -> bool:
        return bool(self.COMPARE_PATTERN.search(query))

    def find_mentioned_docs(self, query: str) -> List[str]:
        """
        Find uploaded filenames mentioned in the query.
        Queries Qdrant for actual file names (source of truth) so folder-upload
        prefixed names (e.g. 'folder__file.pdf') are correctly resolved.
        Falls back to filesystem listing if Qdrant is unavailable.
        """
        from pathlib import Path as _PPath
        q_lower = query.lower()
        mentioned = []

        # Primary: get unique file_names from Qdrant (always in sync with vector store)
        qdrant_files: List[str] = []
        if self.searcher:
            try:
                results, _ = self.searcher.client.scroll(
                    collection_name=self.searcher.collection,
                    limit=500,
                    with_payload=True,
                    with_vectors=False,
                )
                seen = set()
                for pt in results:
                    fn = pt.payload.get("file_name", "")
                    if fn and fn not in seen:
                        seen.add(fn)
                        qdrant_files.append(fn)
            except Exception:
                pass

        # Fallback: filesystem
        available = qdrant_files or self.reader.list_files()

        for fname in available:
            stem = _PPath(fname).stem.lower()
            words = re.split(r"[\s_\-\./\\]+", stem)
            words = [w for w in words if len(w) >= 3]
            if any(w in q_lower for w in words):
                mentioned.append(fname)

        # Deduplicate while preserving order
        seen_m: set = set()
        unique = []
        for f in mentioned:
            if f not in seen_m:
                seen_m.add(f)
                unique.append(f)
        return unique

    def build_labeled_context(self, chunks_by_file: Dict[str, List[str]]) -> str:
        """Build a context string with clear per-document labeling."""
        parts = []
        for fname, chunks in chunks_by_file.items():
            label = f"=== Document: {fname} ==="
            content = "\n---\n".join(chunks[:5])
            parts.append(f"{label}\n{content}")
        if len(chunks_by_file) > 1:
            header = (
                f"[Multi-Document Context — {len(chunks_by_file)} document(s)]\n"
                "Answer using information from ALL documents shown below.\n\n"
            )
        else:
            header = ""
        return header + "\n\n".join(parts)

    def annotate_chunks(self, annotated_chunks: List[Dict]) -> str:
        """Convert annotated chunk dicts into labeled context string."""
        by_file: Dict[str, List[str]] = {}
        for chunk in annotated_chunks:
            fname = chunk.get("file_name", "Unknown")
            text = chunk.get("text", "")
            by_file.setdefault(fname, []).append(text)
        return self.build_labeled_context(by_file)


# ── Extended state ────────────────────────────────────────────────────────────

@dataclass
class EnhancedAgentState(AgentState):
    needs_doc_read: bool = False
    doc_read_result: str = ""
    is_cross_doc: bool = False
    annotated_chunks: List[Dict] = field(default_factory=list)
    mentioned_docs: List[str] = field(default_factory=list)
    # Confidence routing
    rag_confidence_score: float = 0.0
    graph_confidence_score: float = 0.0
    routing_decision: str = "rag"   # "rag" | "graph" | "hybrid"
    # Explainability
    reasoning_trace: List[str] = field(default_factory=list)
    # Weighted fusion scores
    fused_chunks: List[Dict] = field(default_factory=list)


# ── Enhanced Orchestrator ─────────────────────────────────────────────────────

class EnhancedAgentOrchestrator(AgentOrchestrator):
    """
    Extends AgentOrchestrator with:
    - Exact document line/full-doc reading (zero hallucination)
    - Source-annotated retrieval for cross-document comparison
    - Proper context fusion labeling chunks by source document
    """

    # Intent patterns for document reading
    DOC_READ_INTENT = re.compile(
        r"\b(?:show|display|read|print|give\s+me|fetch|get|what\s+is\s+(?:in|on|there)|"
        r"what\s+does.*say|contents?\s+of|line\s+\d+|full\s+document|"
        r"entire\s+document|whole\s+document|all\s+lines|every\s+line|"
        r"view|open|see\s+the)\b",
        re.IGNORECASE,
    )

    def __init__(self, *args, doc_reader: Optional[DocumentReader] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._doc_reader = doc_reader or get_document_reader()
        self._line_tool = DocumentLineReaderTool(self._doc_reader)
        self._meta_extractor = MetadataExtractor()

        # Build source-annotated searcher if qdrant client is accessible
        self._annotated_searcher: Optional[SourceAnnotatedSearchTool] = None
        try:
            self._annotated_searcher = SourceAnnotatedSearchTool(
                qdrant_client=self.rag.client,
                collection_name=self.rag.collection_name,
                embedder=self.rag.embedder,
            )
        except Exception as e:
            logger.warning(f"[EnhancedOrchestrator] AnnotatedSearchTool unavailable: {e}")

        self._cross_tool = CrossDocumentTool(self._doc_reader, self._annotated_searcher)

    # ── Confidence-based routing ──────────────────────────────────────────────

    def _rag_confidence(self, query: str, user_role: str) -> float:
        """
        Quick Qdrant top-1 search score (cosine similarity, 0-1).
        Measures how well the vector store can answer this query.
        """
        try:
            vector = self.rag.embedder.embed(query)
            results = self.rag.client.query_points(
                collection_name=self.rag.collection_name,
                query=vector,
                limit=1,
                query_filter={"must": [{"key": "access_roles", "match": {"value": user_role}}]},
            )
            if results.points:
                return float(getattr(results.points[0], "score", 0.0))
        except Exception as e:
            logger.debug("[ConfidenceRouter] RAG confidence probe failed: %s", e)
        return 0.0

    def _graph_confidence(self, query: str) -> float:
        """
        Entity-match ratio: what fraction of query entities exist in the graph?
        Returns a 0-1 score normalised by the number of entities extracted.
        """
        try:
            if not self.graph_tool:
                return 0.0
            entities = self.graph_tool.graph.extract_entities(query)
            all_names = (
                [f"Contract {c}" for c in entities.get("contracts", [])]
                + entities.get("organizations", [])
                + entities.get("dates", [])[:2]
            )
            if not all_names:
                # No structured entities — try keyword search
                results = self.graph_tool.graph.search_entities(query.split()[0])
                return 0.4 if results else 0.0
            hits = sum(
                1 for name in all_names
                if self.graph_tool.graph.query_entity(name)
            )
            return min(hits / len(all_names), 1.0)
        except Exception as e:
            logger.debug("[ConfidenceRouter] Graph confidence probe failed: %s", e)
        return 0.0

    def _route_by_confidence(
        self, query: str, user_role: str, state: "EnhancedAgentState"
    ) -> str:
        """
        Compare RAG and Graph confidence scores and choose routing.
        Returns 'rag' | 'graph' | 'hybrid'.
        Records scores and decision in state for explainability.
        """
        rag_score = self._rag_confidence(query, user_role)
        graph_score = self._graph_confidence(query)

        state.rag_confidence_score = round(rag_score, 3)
        state.graph_confidence_score = round(graph_score, 3)
        state.reasoning_trace.append(
            f"Confidence probe → RAG:{rag_score:.3f}  Graph:{graph_score:.3f}"
        )

        margin = 0.15  # Minimum gap to prefer one over the other
        if graph_score > rag_score + margin:
            decision = "graph"
        elif rag_score > graph_score + margin:
            decision = "rag"
        else:
            decision = "hybrid"

        state.routing_decision = decision
        state.reasoning_trace.append(f"Routing decision: {decision.upper()}")
        logger.info(
            "[ConfidenceRouter] RAG=%.3f Graph=%.3f → %s",
            rag_score, graph_score, decision,
        )
        return decision

    # ── Weighted fusion ───────────────────────────────────────────────────────

    def _weighted_fusion(
        self,
        rag_chunks: List[Dict],
        graph_relations: List[Dict],
        rag_weight: float = 0.7,
        graph_weight: float = 0.3,
    ) -> List[Dict]:
        """
        Merge RAG chunks and graph relations into a single ranked list.
        Score = weight * raw_score.  Deduplicates by first 80 chars of text.
        """
        combined: List[Dict] = []

        for chunk in rag_chunks:
            combined.append({
                "text": chunk.get("text", chunk) if isinstance(chunk, dict) else chunk,
                "file_name": chunk.get("file_name", "Document") if isinstance(chunk, dict) else "Document",
                "score": float(chunk.get("score", 0.8) if isinstance(chunk, dict) else 0.8) * rag_weight,
                "origin": "rag",
            })

        for rel in graph_relations[:10]:
            text = f"{rel.get('from', '')} —[{rel.get('relation', '')}]→ {rel.get('to', '')}"
            combined.append({
                "text": text,
                "file_name": rel.get("source", "graph"),
                "score": 0.6 * graph_weight,
                "origin": "graph",
            })

        # Sort descending by weighted score
        combined.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate by text prefix
        seen: set = set()
        deduped: List[Dict] = []
        for item in combined:
            key = item["text"][:80]
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        return deduped

    # ── Overridden nodes ──────────────────────────────────────────────────────

    def _node_classify(self, state: AgentState) -> AgentState:
        """Extend base classify: detect doc-read and cross-doc intents."""
        state = super()._node_classify(state)
        state = self._ensure_enhanced(state)
        state.reasoning_trace.append(f"Query type classified as: {state.query_type}")

        # Doc-read detection — call parse_query unconditionally.
        # parse_query is cheap and handles ALL verbs (retrieve, get, fetch, show,
        # display, read, extract, give, open, view, etc.) internally.
        # Do NOT gate behind a regex here — that caused "Retrieve" to be missed.
        try:
            req = self._doc_reader.parse_query(state.query)
            if req.is_doc_read:
                state.needs_doc_read = True
                state.query_type = "document_read"
                logger.info(f"[EnhancedOrchestrator] doc-read: {req}")
        except Exception as e:
            logger.warning(f"[EnhancedOrchestrator] parse_query failed: {e}")

        # Cross-doc detection
        if not state.needs_doc_read and self._cross_tool.is_cross_doc_query(state.query):
            state.is_cross_doc = True
            state.mentioned_docs = self._cross_tool.find_mentioned_docs(state.query)
            logger.info(
                f"[EnhancedOrchestrator] cross-doc query, "
                f"mentioned docs: {state.mentioned_docs}"
            )

        return state

    def _check_document_access(self, filename: str, user_role: str) -> bool:
        """
        Check whether user_role has access to a specific document.
        Looks up the document's access_roles from Qdrant (single point scroll).
        Returns True if access is allowed, False otherwise.
        """
        if user_role == "admin":
            return True  # Admin always has access
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            results, _ = self.rag.client.scroll(
                collection_name=self.rag.collection_name,
                scroll_filter=Filter(
                    must=[FieldCondition(key="file_name", match=MatchValue(value=filename))]
                ),
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if not results:
                return False  # Document not in vector store — deny
            access_roles = results[0].payload.get("access_roles", ["admin"])
            return user_role in access_roles
        except Exception as e:
            logger.warning(f"[AccessCheck] Failed for '{filename}': {e}")
            return False  # Fail closed — deny on error

    def _node_retrieve(self, state: AgentState) -> AgentState:
        """
        Routing:
          - doc-read query   → DocumentLineReaderTool (RBAC-checked, no RAG)
          - cross-doc query  → SourceAnnotatedSearchTool per mentioned doc
          - all other        → base class retrieval
        """
        state = self._ensure_enhanced(state)

        # ── Path 1: exact document read ───────────────────────────────────────
        if state.needs_doc_read:
            result = self._line_tool.run(state.query)
            if result.success and result.data:
                req = result.data.get("request")
                filename = req.filename if req else None

                # RBAC check — deny if user doesn't have access to this document
                if filename and not self._check_document_access(filename, state.user_role):
                    state.doc_read_result = (
                        f"Access denied: you do not have permission to read '{filename}'.\n"
                        "Contact your administrator to request access."
                    )
                    state.tools_used.append("DocumentLineReaderTool")
                    state.confidence = 0.0
                    return state

                state.doc_read_result = result.data.get("content", "")
                state.tools_used.append("DocumentLineReaderTool")
                return state
            else:
                # Failed to read (file not found) — fall through to RAG
                logger.warning(f"[EnhancedOrchestrator] doc-read failed: {result.error}")
                state.needs_doc_read = False

        # ── Path 2: cross-document comparison ────────────────────────────────
        if state.is_cross_doc and self._annotated_searcher:
            state.tools_used.append("SourceAnnotatedSearchTool")

            if state.mentioned_docs:
                # Retrieve from each mentioned document separately
                for doc in state.mentioned_docs[:4]:  # cap at 4 docs
                    result = self._annotated_searcher.run(
                        state.query, state.user_role, top_k=5, file_filter=doc, tenant_id=state.tenant_id
                    )
                    if result.success:
                        state.annotated_chunks.extend(result.data)
            else:
                # No specific docs mentioned — retrieve broadly and annotate
                result = self._annotated_searcher.run(
                    state.query, state.user_role, top_k=12, tenant_id=state.tenant_id
                )
                if result.success:
                    state.annotated_chunks = result.data

            # Also copy as plain texts for reranker compatibility
            if state.annotated_chunks:
                try:
                    texts = [c["text"] for c in state.annotated_chunks]
                    state.vector_results = self.reranker.rerank(
                        state.query, texts, top_k=8
                    )
                except Exception:
                    state.vector_results = [c["text"] for c in state.annotated_chunks[:8]]
            return state

        # ── Path 3: confidence-based routing ─────────────────────────────────
        decision = self._route_by_confidence(state.query, state.user_role, state)

        if decision == "graph" and self.graph_tool:
            # Graph-primary retrieval
            graph_result = self.graph_tool.run(state.query)
            if graph_result.success:
                state.graph_context = graph_result.data.get("context", "")
                state.graph_entities = graph_result.data.get("entities", {})
                state.tools_used.append("GraphQueryTool[primary]")
                state.reasoning_trace.append("Graph-primary retrieval executed")
                # Still get some RAG context for grounding
                doc_result = self.doc_tool.run(state.query, state.user_role, state.tenant_id)
                if doc_result.success:
                    state.vector_results = doc_result.data[:3]

        elif decision == "hybrid":
            # Weighted fusion: run both and merge
            doc_result = self.doc_tool.run(state.query, state.user_role, state.tenant_id)
            rag_chunks: List[Dict] = []
            if doc_result.success and self._annotated_searcher:
                ann = self._annotated_searcher.run(state.query, state.user_role, top_k=8, tenant_id=state.tenant_id)
                rag_chunks = ann.data if ann.success else []
            elif doc_result.success:
                rag_chunks = [{"text": t, "score": 0.8} for t in (doc_result.data or [])]

            graph_rels: List[Dict] = []
            if self.graph_tool:
                g_result = self.graph_tool.run(state.query)
                if g_result.success:
                    state.graph_context = g_result.data.get("context", "")
                    graph_rels = g_result.data.get("relations", [])

            fused = self._weighted_fusion(rag_chunks, graph_rels)
            state.fused_chunks = fused
            state.vector_results = [c["text"] for c in fused[:6]]
            state.tools_used.extend(["DocumentSearchTool[hybrid]", "GraphQueryTool[hybrid]"])
            state.reasoning_trace.append(
                f"Hybrid fusion: {len(rag_chunks)} RAG + {len(graph_rels)} graph → {len(fused)} merged"
            )

        else:
            # RAG-primary (default)
            state = super()._node_retrieve(state)
            state.reasoning_trace.append("RAG-primary retrieval executed")

        return state

    def _node_fuse_context(self, state: AgentState) -> AgentState:
        """
        Context fusion:
          - doc-read: raw content (no fusion needed)
          - cross-doc: labeled chunks per document + graph context
          - standard:  base class fusion
        """
        state = self._ensure_enhanced(state)

        # Doc-read — context IS the content
        if state.needs_doc_read and state.doc_read_result:
            state.final_context = state.doc_read_result
            return state

        # Cross-doc — annotate chunks by source document
        if state.is_cross_doc and state.annotated_chunks:
            doc_context = self._cross_tool.annotate_chunks(state.annotated_chunks)

            # Add graph context if available
            graph_part = ""
            if state.graph_context:
                graph_part = f"[Knowledge Graph Relationships]\n{state.graph_context}\n\n"

            state.final_context = graph_part + doc_context
            state.sources = [
                {
                    "name": c.get("file_name", "Document"),
                    "relevance": round(float(c.get("score", 0.8)), 2),
                    "chunk": c.get("text", "")[:200],
                }
                for c in state.annotated_chunks[:6]
            ]
            return state

        # Standard fusion
        state = super()._node_fuse_context(state)

        # Re-annotate with file names from source if available
        if self._annotated_searcher and state.vector_results:
            try:
                result = self._annotated_searcher.run(
                    state.query, state.user_role, top_k=5, tenant_id=state.tenant_id
                )
                if result.success and result.data:
                    state.sources = [
                        {
                            "name": c.get("file_name", "Document"),
                            "relevance": round(float(c.get("score", 0.8)), 2),
                            "chunk": c.get("text", "")[:200],
                        }
                        for c in result.data[:5]
                    ]
            except Exception:
                pass

        return state

    def _node_generate(self, state: AgentState) -> AgentState:
        """
        - doc-read: return raw content directly (no LLM)
        - cross-doc: inject comparison instruction into prompt
        - standard:  base class generation
        """
        state = self._ensure_enhanced(state)

        if state.needs_doc_read and state.doc_read_result:
            state.answer = state.doc_read_result
            state.confidence = 99.0
            state.reasoning_trace.append("Verbatim document read — LLM bypassed")
            return state

        if state.is_cross_doc and state.final_context:
            # Structured multi-document comparison prompt
            doc_names = list({c.get("file_name", "Doc") for c in state.annotated_chunks})
            doc_section = "\n".join(f"- {d}" for d in doc_names) if doc_names else ""
            structured_prompt = (
                f"You are a precise document analyst. Answer ONLY from the provided document contexts.\n\n"
                f"Documents being compared:\n{doc_section}\n\n"
                f"{state.final_context}\n\n"
                f"Question: {state.query}\n\n"
                f"Provide your answer in this structure:\n"
                f"**Similarities:** (what the documents agree on)\n"
                f"**Differences:** (what differs between documents)\n"
                f"**Conclusion:** (direct answer to the question)\n\n"
                f"Cite the document name for every claim."
            )
            original_query = state.query
            state.query = structured_prompt
            state = super()._node_generate(state)
            state.query = original_query
            state.reasoning_trace.append(
                f"Structured multi-doc comparison across {len(doc_names)} document(s)"
            )
            return state

        state = super()._node_generate(state)
        state.reasoning_trace.append(
            f"LLM generation with {len(state.vector_results)} context chunks"
        )
        return state

    def _node_postprocess(self, state: AgentState) -> AgentState:
        state = self._ensure_enhanced(state)

        if state.needs_doc_read and state.doc_read_result:
            state.confidence = 99.0
            state.reasoning_trace.append("Confidence: 99% (verbatim read — no inference)")
            return state

        state = super()._node_postprocess(state)

        # Boost confidence for hybrid and graph routing
        if state.routing_decision == "hybrid":
            state.confidence = min(state.confidence + 8.0, 97.0)
        if state.routing_decision == "graph":
            state.confidence = min(state.confidence + 5.0, 97.0)

        if state.is_cross_doc and state.annotated_chunks:
            doc_count = len({c.get("file_name") for c in state.annotated_chunks})
            state.confidence = min(state.confidence + doc_count * 3.0, 97.0)

        state.reasoning_trace.append(
            f"Final confidence: {state.confidence}% | Route: {state.routing_decision} | "
            f"Tools: {', '.join(state.tools_used)}"
        )
        return state

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_enhanced(state: AgentState) -> "EnhancedAgentState":
        if isinstance(state, EnhancedAgentState):
            return state
        return EnhancedAgentState(
            query=state.query,
            user_role=state.user_role,
            session_id=state.session_id,
            query_type=state.query_type,
            needs_graph=state.needs_graph,
            needs_calculator=state.needs_calculator,
            vector_results=state.vector_results,
            graph_context=state.graph_context,
            graph_entities=state.graph_entities,
            calculator_results=state.calculator_results,
            final_context=state.final_context,
            answer=state.answer,
            confidence=state.confidence,
            sources=state.sources,
            latency_ms=state.latency_ms,
            tools_used=state.tools_used,
            cache_hit=state.cache_hit,
            error=state.error,
        )

    def run(self, query: str, user_role: str = "user",
            session_id: str = "",
            conversation_history=None,
            tenant_id=None) -> "EnhancedAgentState":
        t_start = time.time()
        state = EnhancedAgentState(query=query, user_role=user_role, session_id=session_id,
                                   tenant_id=tenant_id,
                                   conversation_history=conversation_history or [])

        # Skip cache for doc-read and cross-doc queries (freshness matters)
        is_doc_read_hint = bool(self.DOC_READ_INTENT.search(query))
        is_cross_doc_hint = bool(self._cross_tool.is_cross_doc_query(query))

        if not is_doc_read_hint and not is_cross_doc_hint:
            cache_key = f"{tenant_id or user_role}:{query}"
            if self.cache.exists(cache_key):
                cached = self.cache.get(cache_key)
                if isinstance(cached, dict):
                    state.answer = cached.get("answer", "")
                    state.confidence = cached.get("confidence", 75.0)
                    state.sources = cached.get("sources", [])
                    state.query_type = cached.get("query_type", "fact")
                    state.cache_hit = True
                    state.latency_ms = int((time.time() - t_start) * 1000)
                    return state
                else:
                    state.answer = str(cached)
                    state.cache_hit = True
                    state.latency_ms = int((time.time() - t_start) * 1000)
                    return state

        state = self._node_classify(state)
        state = self._node_retrieve(state)
        state = self._node_fuse_context(state)
        state = self._node_generate(state)
        state = self._node_postprocess(state)
        state.latency_ms = int((time.time() - t_start) * 1000)

        # Cache only standard queries
        if not state.needs_doc_read and not state.is_cross_doc:
            cache_key = f"{tenant_id or user_role}:{query}"
            self.cache.set(cache_key, {
                "answer": state.answer,
                "confidence": state.confidence,
                "sources": state.sources,
                "query_type": state.query_type,
            })

        return state

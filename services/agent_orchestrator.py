"""
Agent Orchestrator — Enterprise RAG pipeline.

Query Processing Pipeline:
  0. Greeting fast-path  (instant, no model)
  1. Cache lookup        (TTL 600s)
  2. Query rewriting     (LLM expansion for better recall)
  3. Intent classify     (fact / summary / calculation / relationship)
  4. Hybrid retrieval    (BM25 + vector, fused via RRF)
  5. Graph boost         (optional +20% signal from knowledge graph)
  6. Rerank              (cross-encoder, Top-K 50 → Top 10)
  7. Context build       (diversity + dedup + extractive compression)
  8. LLM generation      (grounded, source-attributed)
  9. Post-process        (confidence gate, cache write)

Agent Tools:
  HybridSearchTool  → BM25 + Qdrant vector search (fused)
  GraphQueryTool    → Knowledge graph context boost
  CalculatorTool    → Arithmetic in queries
  SummarizationTool → Long context compression
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


# ── Tool interfaces ───────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    tool_name: str
    success: bool
    data: Any
    latency_ms: int = 0
    error: Optional[str] = None


class DocumentSearchTool:
    """Vector DB retrieval via Qdrant."""

    def __init__(self, retriever: Callable):
        self.retriever = retriever

    def run(self, query: str, user_role: str, tenant_id: Optional[str] = None) -> ToolResult:
        t0 = time.time()
        try:
            results = self.retriever(query, user_role, tenant_id=tenant_id)
            return ToolResult(
                tool_name="DocumentSearchTool",
                success=True,
                data=results,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as e:
            return ToolResult("DocumentSearchTool", False, [], error=str(e))


class GraphQueryTool:
    """Neo4j relationship queries."""

    def __init__(self, graph_service):
        self.graph = graph_service

    def run(self, query: str) -> ToolResult:
        t0 = time.time()
        try:
            entities = self.graph.extract_entities(query)
            context = self.graph.build_graph_context(entities)
            results = self.graph.search_entities(query[:50])
            return ToolResult(
                tool_name="GraphQueryTool",
                success=True,
                data={"context": context, "entities": entities, "relations": results},
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as e:
            return ToolResult("GraphQueryTool", False, {}, error=str(e))


class SummarizationTool:
    """Summarizes long context before sending to LLM."""

    def run(self, texts: List[str], max_chars: int = 6000) -> ToolResult:
        t0 = time.time()
        combined = "\n\n".join(texts)
        if len(combined) <= max_chars:
            return ToolResult("SummarizationTool", True, combined,
                              latency_ms=int((time.time() - t0) * 1000))
        # Simple truncation with sentence awareness
        truncated = combined[:max_chars]
        last_period = truncated.rfind(".")
        if last_period > max_chars * 0.7:
            truncated = truncated[:last_period + 1]
        return ToolResult("SummarizationTool", True,
                          truncated + "\n[Context truncated for LLM]",
                          latency_ms=int((time.time() - t0) * 1000))


class CalculatorTool:
    """Evaluates simple arithmetic expressions found in queries."""

    EXPR_PATTERN = re.compile(
        r"(\d[\d\s\+\-\*\/\.\(\)%]{1,50}\d)"
    )

    def run(self, query: str) -> ToolResult:
        t0 = time.time()
        matches = self.EXPR_PATTERN.findall(query)
        results = []
        for expr in matches:
            try:
                # safe eval: only numbers and basic operators
                clean = re.sub(r"[^\d\+\-\*\/\.\(\)\s%]", "", expr)
                val = eval(clean, {"__builtins__": {}})
                results.append(f"{expr.strip()} = {val}")
            except Exception:
                pass
        return ToolResult("CalculatorTool", True, results,
                          latency_ms=int((time.time() - t0) * 1000))


# ── Agent state ───────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    """Immutable-style state passed between pipeline nodes."""
    query: str
    user_role: str
    session_id: str = ""
    tenant_id: Optional[str] = None          # multi-tenant isolation
    query_type: str = "fact"
    needs_graph: bool = False
    needs_calculator: bool = False
    conversation_history: List[dict] = field(default_factory=list)
    vector_results: List[str] = field(default_factory=list)
    graph_context: str = ""
    graph_entities: Dict = field(default_factory=dict)
    calculator_results: List[str] = field(default_factory=list)
    final_context: str = ""
    answer: str = ""
    confidence: float = 0.0
    sources: List[dict] = field(default_factory=list)
    latency_ms: int = 0
    tools_used: List[str] = field(default_factory=list)
    cache_hit: bool = False
    error: Optional[str] = None
    _payload_map: Dict = field(default_factory=dict)        # internal: shared Qdrant lookup cache
    _chunks_with_scores: List = field(default_factory=list)  # internal: (text, score) from retrieval
    _rewritten_query: str = ""                               # internal: LLM-expanded query


# ── Orchestrator ──────────────────────────────────────────────────────────────

class AgentOrchestrator:
    """
    Routes queries through the correct retrieval pipeline and fuses context
    before LLM generation. Mimics LangGraph's conditional edge routing.

    Routing logic:
      fact / comparison / analytical  → Vector + (Graph if needed)
      summary                         → Vector + SummarizationTool
      calculation                     → CalculatorTool + Vector
      relationship / graph            → GraphQueryTool + Vector
    """

    GRAPH_KEYWORDS = re.compile(
        r"\b(when|date|start|end|expir|relationship|connect|link|associat|"
        r"contract.?number|agree|issu|compan|organiz|provider|vendor|"
        r"amount|price|cost|value)\b",
        re.IGNORECASE,
    )
    CALC_KEYWORDS = re.compile(
        r"(\bcalculat|\bhow\s+much|\btotal|\bsum\b|\baverage|\bpercent|\d+\s*[\+\-\*\/])"
    )

    # Top-K for Stage 1 retrieval (BM25 + vector each return this many candidates)
    _STAGE1_K = 25   # 25 vector + 25 BM25 → ~30-40 unique after dedup → reranker → top 10

    def __init__(
        self,
        phase1_rag,
        graph_service=None,
        llm_service=None,
        cache_service=None,
        reranker=None,
        classifier=None,
    ):
        self.rag = phase1_rag
        self._phase1_rag = phase1_rag
        self.doc_tool = DocumentSearchTool(
            lambda q, role, tenant_id=None: phase1_rag.query(q, role, top_k=self._STAGE1_K, tenant_id=tenant_id)
        )
        self.graph_tool = GraphQueryTool(graph_service) if graph_service else None
        self.summarizer = SummarizationTool()
        self.calculator = CalculatorTool()
        self.llm = llm_service or phase1_rag.llm
        self.cache = cache_service or phase1_rag.cache
        self.reranker = reranker or phase1_rag.reranker
        self.classifier = classifier or phase1_rag.classifier

        # Hybrid search (BM25 + vector fusion) — built lazily on first query
        self._hybrid: Optional[Any] = None
        # Coverage-aware context builder
        from services.context_builder import get_context_builder
        self._ctx_builder = get_context_builder()

        # Cached payload map (text[:100] → payload) — rebuilt at most every 120s
        self._payload_cache: dict = {}
        self._payload_cache_ts: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, user_role: str = "user",
            session_id: str = "",
            conversation_history: Optional[list] = None,
            tenant_id: Optional[str] = None) -> AgentState:
        """Execute the full agent pipeline and return the final state."""
        t_start = time.time()

        state = AgentState(query=query, user_role=user_role, session_id=session_id,
                           tenant_id=tenant_id,
                           conversation_history=conversation_history or [])

        # Fast-path: greetings never need retrieval or LLM
        q_lower = query.lower().strip()
        _GREETINGS = {"hello","hi","hey","good morning","good afternoon","good evening",
                      "how are you","what's up","how do you do","nice to meet you"}
        if any(q_lower == g or q_lower.startswith(g + " ") for g in _GREETINGS):
            state.answer = self.llm.generate_answer(query, "", role=user_role)
            state.confidence = 100.0
            state.latency_ms = 0
            return state

        # Fast-path: navigation / "where is X" queries → nav_graph lookup
        nav_answer = self._try_nav_graph(query)
        if nav_answer:
            state.answer = nav_answer
            state.confidence = 90.0
            state.query_type = "navigation"
            state.latency_ms = int((time.time() - t_start) * 1000)
            return state

        # Cache key includes tenant_id so clients never see each other's cached results
        cache_key = f"{tenant_id or user_role}:{query}"
        if self.cache.exists(cache_key):
            cached = self.cache.get(cache_key)
            if isinstance(cached, dict):
                state.answer = cached.get("answer", cached)
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

        # Node 0: Query rewriting — expand short/ambiguous queries
        state = self._node_rewrite_query(state)

        # Node 1: Classify
        state = self._node_classify(state)

        # Node 2: Route to retrieval tools (hybrid BM25 + vector)
        state = self._node_retrieve(state)

        # Node 3: Context fusion via coverage-aware context builder
        state = self._node_fuse_context(state)

        # Node 4: LLM generation
        state = self._node_generate(state)

        # Node 5: Post-process
        state = self._node_postprocess(state)

        state.latency_ms = int((time.time() - t_start) * 1000)

        # Store in cache
        self.cache.set(cache_key, {
            "answer": state.answer,
            "confidence": state.confidence,
            "sources": state.sources,
            "query_type": state.query_type,
        })

        return state

    # ── Pipeline nodes ────────────────────────────────────────────────────────

    def _node_rewrite_query(self, state: AgentState) -> AgentState:
        """
        Expand/rewrite the query for better retrieval recall.
        Skips rewriting for explicit document-read queries (line reads, full doc reads)
        since those need to go verbatim to DocumentLineReaderTool.
        """
        try:
            from services.document_reader import DOC_READ_INTENT, FULL_DOC_PATTERNS, LINE_NUMBER_PATTERNS
            q = state.query
            # Skip rewrite if this is a direct document/line read request
            has_line = any(p.search(q) for p in LINE_NUMBER_PATTERNS)
            has_full = bool(FULL_DOC_PATTERNS.search(q))
            if has_line or has_full:
                return state  # preserve verbatim query for DocumentLineReaderTool
            rewritten = self.llm.rewrite_query(q)
            if rewritten and rewritten != q:
                state._rewritten_query = rewritten
                logger.info("[Orchestrator] query rewritten")
        except Exception:
            pass
        return state

    def _node_classify(self, state: AgentState) -> AgentState:
        """Determine query type and which tools are needed."""
        state.query_type = self.classifier.classify(state.query)
        state.needs_graph = bool(self.GRAPH_KEYWORDS.search(state.query))
        state.needs_calculator = bool(self.CALC_KEYWORDS.search(state.query))
        logger.info(
            "[Orchestrator] classify=%s graph=%s calc=%s",
            state.query_type, state.needs_graph, state.needs_calculator,
        )
        return state

    def _node_retrieve(self, state: AgentState) -> AgentState:
        """
        Hybrid retrieval: BM25 + vector (fused via RRF) for each sub-query,
        then cross-encoder rerank to top 10.
        Graph and calculator run in parallel threads.
        """
        retrieval_query = getattr(state, "_rewritten_query", None) or state.query
        sub_queries = self._decompose(retrieval_query)
        # Also include original query so rewrites don't drop verbatim matches
        if state.query not in sub_queries:
            sub_queries = [state.query] + sub_queries

        all_chunks_with_scores: List[tuple] = []  # (text, score)
        all_chunks_plain: List[str] = []

        # ── Initialise hybrid search (lazy, once per orchestrator lifetime) ─
        if self._hybrid is None:
            try:
                from services.hybrid_search import get_hybrid_search
                self._hybrid = get_hybrid_search(self._phase1_rag.embedder)
                # Point hybrid search at the correct collection (phase1_documents)
                self._hybrid._collection_override = getattr(
                    self._phase1_rag, "collection_name", "phase1_documents"
                )
            except Exception as e:
                logger.warning("[Orchestrator] Hybrid search init failed: %s — using vector only", e)

        futures_map: Dict = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            # Hybrid search per sub-query
            _col = getattr(self._hybrid, "_collection_override", "phase1_documents") if self._hybrid else "phase1_documents"
            for sq in sub_queries:
                if self._hybrid:
                    f = pool.submit(self._hybrid.search_with_scores, sq, self._STAGE1_K, _col)
                    futures_map[f] = ("hybrid", sq)
                else:
                    f = pool.submit(self.doc_tool.run, sq, state.user_role, state.tenant_id)
                    futures_map[f] = ("doc", sq)

            # Graph boost (secondary signal — 20-30% weight)
            if state.needs_graph and self.graph_tool:
                f = pool.submit(self.graph_tool.run, state.query)
                futures_map[f] = ("graph", state.query)

            if state.needs_calculator:
                f = pool.submit(self.calculator.run, state.query)
                futures_map[f] = ("calc", state.query)

            for future in as_completed(futures_map):
                kind, _ = futures_map[future]
                try:
                    result = future.result(timeout=15)
                except Exception as exc:
                    logger.warning("[Orchestrator] tool timeout: %s", exc)
                    continue

                if kind == "hybrid":
                    # result is List[Tuple[str, float]]
                    if result:
                        all_chunks_with_scores.extend(result)
                elif kind == "doc" and result.success and result.data:
                    for t in result.data:
                        all_chunks_with_scores.append((t, 0.5))
                elif kind == "graph" and result.success:
                    state.graph_context = result.data.get("context", "")
                    state.graph_entities = result.data.get("entities", {})
                    state.tools_used.append("GraphQueryTool")
                elif kind == "calc" and result.success and result.data:
                    state.calculator_results = result.data
                    state.tools_used.append("CalculatorTool")

        # Deduplicate while preserving best score
        seen: Dict[str, float] = {}
        for text, score in all_chunks_with_scores:
            if text not in seen or score > seen[text]:
                seen[text] = score
        unique_chunks_scored = sorted(seen.items(), key=lambda x: x[1], reverse=True)
        all_chunks_plain = [t for t, _ in unique_chunks_scored]

        # ── Rerank top candidates with cross-encoder ──────────────────────
        if all_chunks_plain:
            try:
                state._payload_map = self._fetch_payload_map(limit=250)
                doc_names = self._extract_doc_names(all_chunks_plain, state._payload_map)
                # Rerank to top 10 (more than before — context builder will trim)
                state.vector_results = self.reranker.rerank(
                    retrieval_query, all_chunks_plain, top_k=10, doc_names=doc_names
                )
                # Attach scores for context builder
                score_map = dict(unique_chunks_scored)
                state._chunks_with_scores = [
                    (t, score_map.get(t, 0.5)) for t in state.vector_results
                ]
            except Exception as e:
                logger.warning("[Orchestrator] Rerank failed: %s", e)
                state._payload_map = {}
                state.vector_results = all_chunks_plain[:10]
                state._chunks_with_scores = [(t, 0.5) for t in state.vector_results]
            state.tools_used.append("HybridSearch" if self._hybrid else "DocumentSearchTool")

        return state

    def _node_fuse_context(self, state: AgentState) -> AgentState:
        """
        Coverage-aware context builder:
          1. Deduplication (Jaccard >85%)
          2. Diversity (max 2 chunks per source file)
          3. Extractive compression per chunk
          4. Graph context prepended (20% budget)
          5. Calculator results appended
        """
        payload_map = getattr(state, "_payload_map", {}) or {}
        chunks_with_scores = getattr(state, "_chunks_with_scores", [])
        if not chunks_with_scores:
            chunks_with_scores = [(t, 0.5) for t in state.vector_results]

        # For summary queries, first combine all chunks then summarize
        if state.query_type == "summary":
            summ = self.summarizer.run(state.vector_results, max_chars=6400)
            chunks_with_scores = [(summ.data, 1.0)]
            state.tools_used.append("SummarizationTool")

        # ── Coverage-aware context builder ─────────────────────────────────
        doc_context, sources = self._ctx_builder.build(
            chunks_with_scores, payload_map=payload_map, query=state.query
        )

        # ── Prepend graph context (secondary boost, ≤20% of budget) ────────
        parts = []
        if state.graph_context:
            parts.append(f"[Knowledge Graph Context]\n{state.graph_context[:1600]}")
        if state.calculator_results:
            parts.append("[Calculations]\n" + "\n".join(state.calculator_results))
        if doc_context:
            parts.append(doc_context)

        state.final_context = "\n\n".join(parts)
        state.sources = sources
        state.tools_used.append("ContextBuilder")

        return state

    def _node_generate(self, state: AgentState) -> AgentState:
        """Call LLM with the fused context."""
        question = state.query
        if state.query_type == "summary":
            question = f"Provide a comprehensive summary. {question}"

        try:
            state.answer = self.llm.generate_answer(
                question,
                state.final_context,
                role=state.user_role,
                conversation_history=state.conversation_history or None,
            )
        except Exception as e:
            logger.error(f"[Orchestrator] LLM error: {e}")
            state.answer = "I encountered an issue generating the response. Please try again."
            state.error = str(e)

        return state

    def _node_postprocess(self, state: AgentState) -> AgentState:
        """Compute confidence score and finalize state."""
        base = 70.0
        if state.graph_context:
            base += 15.0
        if len(state.vector_results) >= 3:
            base += 8.0
        if state.cache_hit:
            base += 5.0
        if state.query_type == "fact":
            base += 3.0
        state.confidence = min(round(base, 1), 98.0)
        return state

    # ── Navigation graph fast-path ────────────────────────────────────────────

    _NAV_KEYWORDS = (
        "navigate", "navigation", "how do i go", "how to go", "how do i get to",
        "link to", "direct link", "url for", "where is the", "where can i find",
        "go to", "open the", "find the page", "take me to", "show me",
    )

    def _try_nav_graph(self, query: str) -> str:
        """
        If the query is a navigation intent, look up the nav_graph from
        all active website crawl connections and return a direct answer with URL.
        Returns empty string if nav intent not detected or no match found.
        """
        q = query.lower().strip()
        is_nav = any(kw in q for kw in self._NAV_KEYWORDS)
        if not is_nav:
            return ""

        try:
            from services.website_crawler import get_website_crawler
            crawler = get_website_crawler()
            if crawler is None:
                return ""

            # Search all active connections' nav graphs
            best_match = None
            best_score = 0

            for conn in crawler.get_connections():
                if conn.get("status") not in ("active", "done"):
                    continue
                nav_graph = conn.get("nav_graph", {})
                org = conn.get("org_name") or conn.get("url", "")

                for url, node in nav_graph.items():
                    title = (node.get("title") or "").lower()
                    # Score: how many query words match the page title
                    q_words = set(q.split()) - {"the", "a", "an", "to", "in", "of", "on", "for", "i", "how", "do", "navigate", "page", "go", "find", "where", "is"}
                    title_words = set(title.split())
                    score = len(q_words & title_words)
                    if score > best_score:
                        best_score = score
                        best_match = {
                            "url": url,
                            "title": node.get("title", url),
                            "breadcrumb": node.get("breadcrumb", []),
                            "parent": node.get("parent", ""),
                            "org": org,
                        }

            if best_match and best_score >= 1:
                title = best_match["title"]
                url = best_match["url"]
                breadcrumb = best_match.get("breadcrumb", [])
                org = best_match.get("org", "")
                parent = best_match.get("parent", "")

                # Build navigation steps
                steps = []
                if breadcrumb and len(breadcrumb) > 1:
                    for i, crumb in enumerate(breadcrumb[:-1], 1):
                        steps.append(f"{i}. Click **{crumb}**")
                    steps.append(f"{len(breadcrumb)}. You're on **{title}**")
                elif parent:
                    from urllib.parse import urlparse
                    parent_path = urlparse(parent).path.strip("/") or "home"
                    steps = [f"1. Go to the **{parent_path.capitalize()}** section", f"2. Select **{title}**"]

                nav_answer = f"Here's how to navigate to the **{title}** page"
                if org:
                    nav_answer += f" on {org}"
                nav_answer += ":\n\n"
                nav_answer += f"**Direct link:** [{url}]({url})\n\n"
                if steps:
                    nav_answer += "**Step-by-step navigation:**\n" + "\n".join(steps)

                return nav_answer

        except Exception as e:
            logger.debug("[Orchestrator] Nav graph lookup failed: %s", e)

        return ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _decompose(self, query: str) -> List[str]:
        """Simple multi-hop decomposition on 'and' conjunctions."""
        q = query.lower()
        if " and " in q:
            return [s.strip() for s in q.split(" and ") if s.strip()]
        return [query]

    def _fetch_payload_map(self, limit: int = 200) -> dict:
        """
        Returns {text_prefix_100: payload_dict}.

        First tries BM25 metadata (already in memory, zero cost).
        Falls back to a cached Qdrant scroll (TTL=120s) so repeated queries
        never pay the scroll cost more than once every 2 minutes.
        """
        # Prefer BM25 meta — already fetched, no extra I/O
        if self._hybrid is not None and getattr(self._hybrid, "_bm25_meta", None):
            try:
                with self._hybrid._bm25_lock:
                    meta = list(self._hybrid._bm25_meta)
                return {m.get("text", "")[:100]: m for m in meta if m.get("text")}
            except Exception:
                pass

        # Use cached map if fresh (< 120s old)
        if self._payload_cache and (time.time() - self._payload_cache_ts) < 120:
            return self._payload_cache

        # Fall back to Qdrant scroll
        try:
            col = getattr(self._phase1_rag, "collection_name", "phase1_documents")
            results = self._phase1_rag.embedder.qdrant.scroll(
                collection_name=col,
                scroll_filter=None,
                limit=limit,
                with_payload=True,
            )
            pmap = {r.payload.get("text", "")[:100]: r.payload for r in results[0]}
            self._payload_cache = pmap
            self._payload_cache_ts = time.time()
            return pmap
        except Exception:
            return {}

    def _extract_doc_names(self, chunks: List[str], payload_map: Optional[dict] = None) -> Optional[List[str]]:
        """Best-effort doc name list for a set of chunks using a pre-fetched payload map."""
        if payload_map is None:
            payload_map = self._fetch_payload_map(limit=50)
        if not payload_map:
            return None
        return [payload_map.get(c[:100], {}).get("file_name", "unknown") for c in chunks]

    def _source_name(self, chunk: str, index: int, payload_map: Optional[dict] = None) -> str:
        """Best-effort source name for a chunk string, using a pre-fetched payload map."""
        if payload_map is None:
            payload_map = self._fetch_payload_map()
        payload = payload_map.get(chunk[:100], {})
        fname = payload.get("file_name", "")
        line_s = payload.get("line_start")
        if fname and line_s:
            return f"{fname} (line {line_s})"
        if fname:
            return fname
        return f"Document chunk {index + 1}"

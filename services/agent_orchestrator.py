"""
Agent Orchestrator — LangGraph-style query routing pipeline.

Query Processing Pipeline:
  1. User sends query via Chat UI
  2. Query classifier categorizes query
  3. Agent Orchestrator determines execution path
  4. Retrieval modules execute:
     - Vector RAG (DocumentSearchTool)
     - Graph Query (GraphQueryTool)
     - SQL Query  (SQLQueryTool)
  5. Results are re-ranked
  6. Context fusion combines all sources
  7. Final prompt sent to LLM
  8. Response streamed to UI

Agent Tools:
  DocumentSearchTool → Vector DB retrieval (Qdrant)
  GraphQueryTool     → Neo4j queries
  SQLQueryTool       → PostgreSQL queries
  SummarizationTool  → Summarize long context
  CalculatorTool     → Arithmetic operations
"""

import logging
import re
import time
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

    def run(self, query: str, user_role: str) -> ToolResult:
        t0 = time.time()
        try:
            results = self.retriever(query, user_role)
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
    query_type: str = "fact"
    needs_graph: bool = False
    needs_calculator: bool = False
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
        self.doc_tool = DocumentSearchTool(
            lambda q, role: phase1_rag.query(q, role)
        )
        self.graph_tool = GraphQueryTool(graph_service) if graph_service else None
        self.summarizer = SummarizationTool()
        self.calculator = CalculatorTool()
        self.llm = llm_service or phase1_rag.llm
        self.cache = cache_service or phase1_rag.cache
        self.reranker = reranker or phase1_rag.reranker
        self.classifier = classifier or phase1_rag.classifier

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, query: str, user_role: str = "user",
            session_id: str = "") -> AgentState:
        """Execute the full agent pipeline and return the final state."""
        t_start = time.time()

        state = AgentState(query=query, user_role=user_role, session_id=session_id)

        # Check cache first
        cache_key = f"{user_role}:{query}"
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

        # Node 1: Classify
        state = self._node_classify(state)

        # Node 2: Route to retrieval tools
        state = self._node_retrieve(state)

        # Node 3: Context fusion
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

    def _node_classify(self, state: AgentState) -> AgentState:
        """Determine query type and which tools are needed."""
        state.query_type = self.classifier.classify(state.query)
        state.needs_graph = bool(self.GRAPH_KEYWORDS.search(state.query))
        state.needs_calculator = bool(self.CALC_KEYWORDS.search(state.query))
        logger.info(
            f"[Orchestrator] classify={state.query_type} "
            f"graph={state.needs_graph} calc={state.needs_calculator}"
        )
        return state

    def _node_retrieve(self, state: AgentState) -> AgentState:
        """Run selected retrieval tools in order."""
        # Always run vector retrieval
        doc_result = self.doc_tool.run(state.query, state.user_role)
        if doc_result.success and doc_result.data:
            # Multi-hop decomposition + reranking
            sub_queries = self._decompose(state.query)
            all_chunks = list(doc_result.data)
            for sq in sub_queries[1:]:
                sub_result = self.doc_tool.run(sq, state.user_role)
                if sub_result.success:
                    all_chunks.extend(sub_result.data)
            # Rerank
            unique_chunks = list(dict.fromkeys(all_chunks))
            try:
                state.vector_results = self.reranker.rerank(
                    state.query, unique_chunks, top_k=5
                )
            except Exception:
                state.vector_results = unique_chunks[:5]
            state.tools_used.append("DocumentSearchTool")

        # Graph retrieval (conditional)
        if state.needs_graph and self.graph_tool:
            graph_result = self.graph_tool.run(state.query)
            if graph_result.success:
                state.graph_context = graph_result.data.get("context", "")
                state.graph_entities = graph_result.data.get("entities", {})
                state.tools_used.append("GraphQueryTool")

        # Calculator (conditional)
        if state.needs_calculator:
            calc_result = self.calculator.run(state.query)
            if calc_result.success and calc_result.data:
                state.calculator_results = calc_result.data
                state.tools_used.append("CalculatorTool")

        return state

    def _node_fuse_context(self, state: AgentState) -> AgentState:
        """
        Context Fusion: merges graph + vector + calculator results
        into a single context string ordered by relevance.
        """
        parts = []

        # Graph context first (more precise for structured queries)
        if state.graph_context:
            parts.append(f"[Knowledge Graph]\n{state.graph_context}")

        # Calculator results
        if state.calculator_results:
            parts.append("[Calculations]\n" + "\n".join(state.calculator_results))

        # Vector context
        if state.vector_results:
            parts.extend(state.vector_results)

        if state.query_type == "summary":
            summ_result = self.summarizer.run(state.vector_results)
            parts = [summ_result.data]
            state.tools_used.append("SummarizationTool")

        state.final_context = "\n\n".join(parts)

        # Build sources list for frontend
        state.sources = [
            {"name": f"Document chunk {i+1}", "relevance": round(0.95 - i * 0.05, 2),
             "chunk": chunk[:200]}
            for i, chunk in enumerate(state.vector_results[:5])
        ]

        return state

    def _node_generate(self, state: AgentState) -> AgentState:
        """Call LLM with the fused context."""
        if not state.final_context:
            state.answer = "No accessible information found for your query."
            state.confidence = 0.0
            return state

        question = state.query
        if state.query_type == "summary":
            question = f"Provide a comprehensive summary. {question}"

        try:
            state.answer = self.llm.generate_answer(question, state.final_context)
        except Exception as e:
            logger.error(f"[Orchestrator] LLM error: {e}")
            state.answer = "An error occurred generating the response."
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _decompose(self, query: str) -> List[str]:
        """Simple multi-hop decomposition on 'and' conjunctions."""
        q = query.lower()
        if " and " in q:
            return [s.strip() for s in q.split(" and ") if s.strip()]
        return [query]

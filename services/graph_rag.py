"""
Phase 3 - Graph RAG
Hybrid retrieval: Vector (Qdrant) + Graph (Neo4j) → combined LLM context.
"""

import logging
import re
from typing import List, Tuple, Optional

from services.graph_service import GraphService

logger = logging.getLogger(__name__)

# Keywords that suggest the query needs graph / relationship reasoning
GRAPH_TRIGGER_KEYWORDS = [
    r"\bwhen\b", r"\bdate\b", r"\bstart\b", r"\bend\b", r"\bexpir",
    r"\brelationship\b", r"\bconnect", r"\blink\b", r"\bassociat",
    r"\bcontract\s*number\b", r"\bagree", r"\bissu",
    r"\bcompan", r"\borganiz", r"\bprovider\b", r"\bvendor\b",
    r"\bamount\b", r"\bprice\b", r"\bcost\b", r"\bvalue\b",
    r"\band\b.*\bdate\b", r"\band\b.*\bnumber\b",
]


class GraphRAG:
    """
    Hybrid retriever that combines:
      1. Vector retrieval  (Qdrant via Phase1RAG.query)
      2. Graph retrieval   (Neo4j via GraphService)

    The combined context is richer – especially for multi-hop questions
    like "What is the contract number AND its start date?"
    """

    def __init__(self):
        self.graph = GraphService()

    # ── Public API ────────────────────────────────────────────────────────────

    def needs_graph(self, question: str) -> bool:
        """Return True if the question likely benefits from graph context."""
        q = question.lower()
        return any(re.search(pat, q) for pat in GRAPH_TRIGGER_KEYWORDS)

    def retrieve(
        self,
        question: str,
        vector_contexts: List[str],
    ) -> Tuple[str, str]:
        """
        Given already-retrieved vector contexts and the original question,
        augment with graph knowledge.

        Returns:
            (combined_context, graph_summary)
            - combined_context: string ready to pass to LLM
            - graph_summary: human-readable graph findings (empty if none)
        """
        graph_summary = ""

        if not self.needs_graph(question):
            combined = "\n\n".join(vector_contexts)
            return combined, graph_summary

        # Extract entities from the vector-retrieved text to guide graph search
        all_text = " ".join(vector_contexts)
        entities = self.graph.extract_entities(all_text)

        # Also extract from the question itself
        q_entities = self.graph.extract_entities(question)
        for key in entities:
            entities[key] = list(dict.fromkeys(entities[key] + q_entities.get(key, [])))

        # Build graph context
        graph_ctx = self.graph.build_graph_context(entities)

        # Keyword search in graph for any mentioned entity fragments
        keyword_results = self._keyword_search(question)

        parts = []
        if graph_ctx:
            parts.append(f"[Graph Relationships]\n{graph_ctx}")
        if keyword_results:
            parts.append(f"[Related Entities]\n{keyword_results}")

        graph_summary = "\n\n".join(parts)

        # Merge: graph context first (more precise), then vector context
        combined_parts = []
        if graph_summary:
            combined_parts.append(graph_summary)
        combined_parts.extend(vector_contexts)
        combined_context = "\n\n".join(combined_parts)

        logger.info(
            f"[GraphRAG] Graph context: {len(graph_ctx)} chars | "
            f"Vector chunks: {len(vector_contexts)}"
        )

        return combined_context, graph_summary

    def ingest_document(self, text: str, source_doc: str) -> dict:
        """
        Extract entities from a document and store them in Neo4j.
        Call this after storing embeddings in Qdrant.

        Returns the extracted entity dict.
        """
        return self.graph.extract_and_store(text, source_doc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _keyword_search(self, question: str) -> str:
        """
        Run keyword searches against Neo4j for major nouns in the question.
        Looks for contract numbers, company names embedded in the question.
        """
        # Extract potential entity references from question
        tokens = re.findall(r"\b([A-Z][A-Z0-9\-]{2,}|[0-9]{4,})\b", question)
        lines = []
        seen = set()

        for token in tokens[:5]:  # Limit searches
            if token in seen:
                continue
            seen.add(token)

            results = self.graph.search_entities(token)
            for r in results:
                if r["relation"] and r["to"]:
                    line = f"{r['from']} --[{r['relation']}]--> {r['to']}"
                    if line not in lines:
                        lines.append(line)

        return "\n".join(lines)

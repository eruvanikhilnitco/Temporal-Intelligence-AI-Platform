"""
Reranker — Cross-encoder reranking for enterprise RAG.

Model selection (in priority order):
  1. cross-encoder/ms-marco-MiniLM-L-12-v2  (strong quality, ~120MB, default)
  2. BAAI/bge-reranker-base                  (if explicitly configured)
  3. cross-encoder/ms-marco-MiniLM-L-6-v2   (emergency fallback)

Two-stage retrieval:
  Stage 1: Hybrid BM25+Vector → Top-25 per sub-query → ~30-40 unique candidates
  Stage 2: Cross-encoder reranks to Top-10 for context builder

Batch inference:
  - Chunks truncated to _MAX_CHUNK_CHARS before scoring (no quality loss, big speedup)
  - batch_size=16 for GPU, 8 for CPU (auto-detected)
  - show_progress_bar=False to reduce I/O overhead

Diversity:
  - MAX_PER_DOC = 2 chunks per source document
  - Context builder enforces final diversity downstream
"""

import logging
from typing import List, Tuple, Optional
import os

from core.config import get_settings

logger = logging.getLogger(__name__)

MAX_PER_DOC = 2           # max chunks from same document in final top-k
_MAX_CHUNK_CHARS = 600    # truncate chunks to this before reranker inference

# Prefer the stronger L-12 variant; fall back gracefully
_PREFERRED_MODEL = "cross-encoder/ms-marco-MiniLM-L-12-v2"
_FALLBACK_MODEL  = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    def __init__(self):
        settings = get_settings()
        # Use configured model if it is one of the known fast models,
        # otherwise default to L-12 for quality
        configured = settings.reranker_model or ""
        if "MiniLM" in configured or "minilm" in configured.lower():
            model_name = configured
        else:
            model_name = _PREFERRED_MODEL

        try:
            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(model_name)
            logger.info("[Reranker] Loaded %s", model_name)
        except Exception as e:
            logger.warning("[Reranker] Failed to load %s (%s) — fallback to L-6", model_name, e)
            try:
                from sentence_transformers import CrossEncoder
                self.model = CrossEncoder(_FALLBACK_MODEL)
                logger.info("[Reranker] Fallback loaded: %s", _FALLBACK_MODEL)
            except Exception as e2:
                logger.error("[Reranker] All models failed: %s", e2)
                self.model = None

        # Detect CPU vs GPU for batch size
        try:
            import torch
            self._batch_size = 16 if torch.cuda.is_available() else 8
        except Exception:
            self._batch_size = 8

    # ── Public API ─────────────────────────────────────────────────────────────

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 10,
        doc_names: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Rerank `documents` against `query` and return the best `top_k`.
        Applies diversity filtering when doc_names is provided.
        """
        if not documents or self.model is None:
            return documents[:top_k]

        scored = self._score(query, documents)

        if doc_names and len(doc_names) == len(documents):
            return self._diverse_top_k(scored, documents, doc_names, top_k)

        return [doc for doc, _ in scored[:top_k]]

    def rerank_with_scores(
        self,
        query: str,
        documents: List[str],
        top_k: int = 10,
        doc_names: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Same as rerank() but returns (chunk_text, score) pairs."""
        if not documents or self.model is None:
            return [(d, 0.5) for d in documents[:top_k]]

        scored = self._score(query, documents)

        if doc_names and len(doc_names) == len(documents):
            top_docs = self._diverse_top_k(scored, documents, doc_names, top_k)
            score_map = {doc: s for doc, s in scored}
            return [(d, score_map.get(d, 0.0)) for d in top_docs]

        return scored[:top_k]

    # ── Internals ──────────────────────────────────────────────────────────────

    def _score(self, query: str, documents: List[str]) -> List[Tuple[str, float]]:
        """Return (doc, score) sorted descending. Truncates to _MAX_CHUNK_CHARS."""
        q_short = query[:300]
        pairs = [(q_short, doc[:_MAX_CHUNK_CHARS]) for doc in documents]
        try:
            scores = self.model.predict(
                pairs,
                batch_size=self._batch_size,
                show_progress_bar=False,
            )
        except Exception as e:
            logger.warning("[Reranker] predict failed (%s) — returning input order", e)
            return [(doc, 0.0) for doc in documents]

        return sorted(zip(documents, scores), key=lambda x: float(x[1]), reverse=True)

    def _diverse_top_k(
        self,
        scored: List[Tuple[str, float]],
        documents: List[str],
        doc_names: List[str],
        top_k: int,
    ) -> List[str]:
        """
        Greedy diversity: pick top-scored chunks while capping per-document
        contribution at MAX_PER_DOC.
        """
        doc_name_map = {doc: name for doc, name in zip(documents, doc_names)}
        doc_counts: dict = {}
        selected: List[str] = []

        for doc, _score in scored:
            if len(selected) >= top_k:
                break
            name = doc_name_map.get(doc, "unknown")
            if doc_counts.get(name, 0) < MAX_PER_DOC:
                selected.append(doc)
                doc_counts[name] = doc_counts.get(name, 0) + 1

        # Backfill without diversity constraint if we're short
        if len(selected) < top_k:
            for doc, _ in scored:
                if doc not in selected:
                    selected.append(doc)
                if len(selected) >= top_k:
                    break

        return selected

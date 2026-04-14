"""
Hybrid Search — BM25 keyword search fused with vector (Qdrant) results.

Design:
  - Stage 1A: Qdrant ANN vector search  (semantic similarity)
  - Stage 1B: In-memory BM25 index      (exact keyword / term matching)
  - Stage 2:  Reciprocal Rank Fusion    (combines both ranked lists)
  - Stage 3:  Reranker                  (cross-encoder refinement, handled upstream)

Fusion weights:  0.65 vector + 0.35 BM25  (vector-heavy but keyword-aware)
RRF constant k:  60  (standard value; smooths rank differences)

The BM25 index is built lazily on first query from Qdrant payload and kept
in memory. It refreshes automatically when the collection size grows by >5%.
"""

import logging
import re
import time
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

# Fusion weights
_VECTOR_WEIGHT = 0.65
_BM25_WEIGHT   = 0.35
_RRF_K         = 60          # Reciprocal Rank Fusion constant


def _tokenize(text: str) -> List[str]:
    """Simple whitespace+punctuation tokenizer for BM25."""
    return re.findall(r"\b\w+\b", text.lower())


class HybridSearchService:
    """
    Wraps an EmbeddingService (which holds the Qdrant client) and adds
    BM25 retrieval over the same collection.
    """

    def __init__(self, embedding_service):
        self.embedder = embedding_service
        self._bm25 = None
        self._bm25_docs: List[str] = []      # corpus: chunk texts
        self._bm25_meta: List[dict] = []     # parallel metadata list
        self._bm25_built_at = 0.0
        self._bm25_collection_size = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 15,
        collection_name: Optional[str] = None,
        score_filter: Optional[float] = None,
    ) -> List[str]:
        """
        Returns top_k chunk texts fused from vector + BM25 search.
        Falls back to pure vector if BM25 is unavailable.
        """
        col = collection_name or self.embedder.collection_name

        # Parallel retrieval ─────────────────────────────────────────────────
        vector_ranked = self._vector_search(query, top_k * 2, col)
        bm25_ranked   = self._bm25_search(query, top_k * 2, col)

        if not vector_ranked and not bm25_ranked:
            return []

        if not bm25_ranked:
            # BM25 not available — use pure vector
            if score_filter:
                vector_ranked = [(t, s) for t, s in vector_ranked if s >= score_filter]
            return [t for t, _ in vector_ranked[:top_k]]

        # Reciprocal Rank Fusion ─────────────────────────────────────────────
        fused = _reciprocal_rank_fusion(
            vector_ranked, bm25_ranked,
            w_a=_VECTOR_WEIGHT, w_b=_BM25_WEIGHT, k=_RRF_K,
        )

        results = [text for text, _ in fused[:top_k]]
        return results

    def search_with_scores(
        self,
        query: str,
        top_k: int = 15,
        collection_name: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """Same as search() but returns (text, fused_score) pairs."""
        col = collection_name or self.embedder.collection_name
        vector_ranked = self._vector_search(query, top_k * 2, col)
        bm25_ranked   = self._bm25_search(query, top_k * 2, col)

        if not vector_ranked:
            return []
        if not bm25_ranked:
            return vector_ranked[:top_k]

        return _reciprocal_rank_fusion(
            vector_ranked, bm25_ranked,
            w_a=_VECTOR_WEIGHT, w_b=_BM25_WEIGHT, k=_RRF_K,
        )[:top_k]

    # ── Vector search ──────────────────────────────────────────────────────────

    def _vector_search(
        self, query: str, top_k: int, collection_name: str
    ) -> List[Tuple[str, float]]:
        """Returns [(text, score)] from Qdrant ANN search."""
        try:
            # EmbeddingService exposes .embed(text) for single-query encoding
            query_vec = self.embedder.embed(query)
            if not query_vec:
                return []

            response = self.embedder.qdrant.query_points(
                collection_name=collection_name,
                query=query_vec,
                limit=top_k,
                with_payload=True,
                score_threshold=0.0,
            )
            results = response.points if hasattr(response, "points") else response
            return [(r.payload.get("text", ""), float(r.score)) for r in results if r.payload.get("text")]
        except Exception as e:
            logger.warning("[Hybrid] Vector search failed: %s", e)
            return []

    # ── BM25 search ────────────────────────────────────────────────────────────

    def _ensure_bm25_index(self, collection_name: str):
        """Build or refresh the BM25 index from Qdrant payload."""
        try:
            from rank_bm25 import BM25Okapi
            qdrant = self.embedder.qdrant

            # Check if refresh needed (collection grew by >5% or >5 minutes)
            try:
                info = qdrant.get_collection(collection_name)
                current_size = getattr(info, "points_count", 0) or 0
            except Exception:
                current_size = 0

            needs_rebuild = (
                self._bm25 is None
                or current_size > self._bm25_collection_size * 1.05
                or (time.time() - self._bm25_built_at) > 300
            )

            if not needs_rebuild:
                return

            # Fetch all chunks from Qdrant (paginated to handle large collections)
            all_docs: List[str] = []
            all_meta: List[dict] = []
            offset = None

            while True:
                batch, next_offset = qdrant.scroll(
                    collection_name=collection_name,
                    scroll_filter=None,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                )
                for point in batch:
                    text = point.payload.get("text", "")
                    if text:
                        all_docs.append(text)
                        all_meta.append(point.payload)

                if next_offset is None or not batch:
                    break
                offset = next_offset

            if not all_docs:
                return

            tokenized = [_tokenize(d) for d in all_docs]
            self._bm25 = BM25Okapi(tokenized)
            self._bm25_docs = all_docs
            self._bm25_meta = all_meta
            self._bm25_built_at = time.time()
            self._bm25_collection_size = current_size
            logger.info("[Hybrid] BM25 index built: %d docs", len(all_docs))

        except Exception as e:
            logger.warning("[Hybrid] BM25 index build failed: %s", e)
            self._bm25 = None

    def _bm25_search(
        self, query: str, top_k: int, collection_name: str
    ) -> List[Tuple[str, float]]:
        """Returns [(text, score)] from BM25 keyword search."""
        self._ensure_bm25_index(collection_name)
        if self._bm25 is None or not self._bm25_docs:
            return []
        try:
            tokens = _tokenize(query)
            if not tokens:
                return []
            scores = self._bm25.get_scores(tokens)
            # Pair with texts, sort descending, return top_k
            ranked = sorted(zip(self._bm25_docs, scores), key=lambda x: x[1], reverse=True)
            # Filter zero-score results
            ranked = [(t, s) for t, s in ranked if s > 0]
            return ranked[:top_k]
        except Exception as e:
            logger.warning("[Hybrid] BM25 search failed: %s", e)
            return []


# ── Reciprocal Rank Fusion ──────────────────────────────────────────────────

def _reciprocal_rank_fusion(
    ranked_a: List[Tuple[str, float]],
    ranked_b: List[Tuple[str, float]],
    w_a: float = 0.65,
    w_b: float = 0.35,
    k: int = 60,
) -> List[Tuple[str, float]]:
    """
    Combine two ranked lists using weighted RRF.
    RRF score = w_a * 1/(k+rank_a) + w_b * 1/(k+rank_b)
    """
    scores: Dict[str, float] = {}

    for rank, (text, _) in enumerate(ranked_a, start=1):
        scores[text] = scores.get(text, 0.0) + w_a * (1.0 / (k + rank))

    for rank, (text, _) in enumerate(ranked_b, start=1):
        scores[text] = scores.get(text, 0.0) + w_b * (1.0 / (k + rank))

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ── Module-level singleton ──────────────────────────────────────────────────

_hybrid_instance: Optional[HybridSearchService] = None


def get_hybrid_search(embedding_service=None) -> Optional[HybridSearchService]:
    global _hybrid_instance
    if _hybrid_instance is None:
        if embedding_service is None:
            return None
        _hybrid_instance = HybridSearchService(embedding_service)
        logger.info("[Hybrid] HybridSearchService initialized")
    return _hybrid_instance

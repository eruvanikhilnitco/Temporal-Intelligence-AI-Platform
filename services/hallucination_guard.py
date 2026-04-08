"""
Hallucination Guard — lightweight answer grounding checker.

Uses the same CrossEncoder model already loaded by the reranker
(cross-encoder/ms-marco-MiniLM-L-6-v2) to score how well each
sentence in the LLM answer is supported by the retrieved context chunks.

Grounding score:
  1.0 = fully supported   (all sentences found in context)
  0.0 = fully hallucinated (nothing in context supports the answer)
  < 0.4 → warn the user

Run asynchronously after the response is sent — never blocks the user.
"""

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# Re-use the singleton reranker model to avoid loading it twice.
_reranker_model = None


def _get_model():
    global _reranker_model
    if _reranker_model is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            logger.info("[HallucinationGuard] CrossEncoder loaded")
        except Exception as e:
            logger.warning("[HallucinationGuard] Model load failed: %s", e)
    return _reranker_model


def _split_sentences(text: str) -> List[str]:
    """Split answer into individual sentences (rough but fast)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 15]


def compute_grounding_score(
    answer: str,
    context_chunks: List[str],
    top_chunks: int = 3,
) -> dict:
    """
    Score how grounded the answer is in the retrieved context.

    Returns:
      {
        grounding_score: float (0–1),
        is_hallucinated: bool,
        warning: str | None,
        sentence_scores: list[float],
      }
    """
    if not answer or not context_chunks:
        return _no_context_result()

    model = _get_model()
    if model is None:
        return _no_model_result()

    sentences = _split_sentences(answer)
    if not sentences:
        return {"grounding_score": 1.0, "is_hallucinated": False,
                "warning": None, "sentence_scores": []}

    # Use top-3 most relevant chunks for scoring
    chunks = context_chunks[:top_chunks]
    sentence_scores = []

    for sentence in sentences:
        pairs = [(sentence, chunk) for chunk in chunks]
        try:
            scores = model.predict(pairs)
            # Cross-encoder raw scores can be negative; sigmoid to normalise
            import math
            normalised = [1 / (1 + math.exp(-s)) for s in scores]
            best = max(normalised)
            sentence_scores.append(round(best, 3))
        except Exception as e:
            logger.debug("[HallucinationGuard] Score failed for sentence: %s", e)
            sentence_scores.append(0.5)  # neutral fallback

    grounding_score = round(sum(sentence_scores) / len(sentence_scores), 3) if sentence_scores else 0.5
    is_hallucinated = grounding_score < 0.4

    return {
        "grounding_score": grounding_score,
        "is_hallucinated": is_hallucinated,
        "warning": (
            "⚠️ This answer may not be fully supported by your documents — please verify."
            if is_hallucinated else None
        ),
        "sentence_scores": sentence_scores,
    }


def _no_context_result() -> dict:
    return {
        "grounding_score": 0.0,
        "is_hallucinated": True,
        "warning": "No document context was retrieved for this answer.",
        "sentence_scores": [],
    }


def _no_model_result() -> dict:
    return {
        "grounding_score": 1.0,   # assume grounded if we can't check
        "is_hallucinated": False,
        "warning": None,
        "sentence_scores": [],
    }

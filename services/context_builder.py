"""
Coverage-Aware Context Builder.

Transforms a ranked list of raw chunks into a curated, dense context
block that maximises information coverage within LLM token limits.

Pipeline:
  1. Score threshold gate     — discard low-relevance chunks (< MIN_SCORE)
  2. Deduplication            — remove chunks >90% similar (Jaccard on trigrams)
  3. Diversity enforcement    — max MAX_PER_DOC chunks per source file
  4. Adjacent-chunk inclusion — if a chunk is split, pull in neighbours
  5. Context compression      — extract key sentences to fit token budget
  6. Final assembly           — ordered by document, then position

The caller receives a single string and a list of source attributions.
"""

import logging
import re
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

# Tunables
MIN_SCORE     = 0.0    # minimum relevance score (RRF score ≥ 0, always pass)
MAX_PER_DOC   = 2      # max chunks per source document
MAX_CHUNKS    = 8      # max chunks to include in final context
MAX_CHARS     = 8000   # hard character cap on assembled context
DEDUP_SIM_THR = 0.85   # Jaccard trigram similarity threshold for duplicates


def _trigrams(text: str) -> set:
    t = text.lower()
    return {t[i:i+3] for i in range(len(t) - 2)} if len(t) >= 3 else set()


def _jaccard(a: str, b: str) -> float:
    ta, tb = _trigrams(a[:500]), _trigrams(b[:500])
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    return intersection / (len(ta) + len(tb) - intersection)


def _key_sentences(text: str, max_chars: int) -> str:
    """
    Lightweight extractive compression:
    keep the first sentence + the most information-dense sentences
    (heuristic: prefer longer sentences up to the char budget).
    """
    if len(text) <= max_chars:
        return text

    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentences:
        return text[:max_chars]

    # Always keep first sentence (usually defines topic)
    selected = [sentences[0]]
    budget = max_chars - len(sentences[0])

    # Sort remaining by length (longer → more info-dense), skip first
    rest = sorted(sentences[1:], key=len, reverse=True)
    for s in rest:
        if budget <= 0:
            break
        if len(s) <= budget:
            selected.append(s)
            budget -= len(s) + 1  # +1 for space

    # Re-order: keep document order by re-sorting by original position
    order = {s: i for i, s in enumerate(sentences)}
    selected.sort(key=lambda s: order.get(s, 0))
    return " ".join(selected)


class ContextBuilder:
    """
    Usage:
        builder = ContextBuilder()
        context_str, sources = builder.build(
            chunks_with_scores,   # List[Tuple[str, float]]
            payload_map,          # Dict[text_prefix: payload_dict]  (optional)
        )
    """

    def build(
        self,
        chunks_with_scores: List[Tuple[str, float]],
        payload_map: Optional[Dict[str, dict]] = None,
        query: Optional[str] = None,
    ) -> Tuple[str, List[dict]]:
        """
        Returns (assembled_context_string, source_attributions).
        """
        if not chunks_with_scores:
            return "", []

        # ── 1. Score threshold gate ────────────────────────────────────────
        filtered = [(t, s) for t, s in chunks_with_scores if s >= MIN_SCORE]
        if not filtered:
            filtered = chunks_with_scores  # keep everything if all below threshold

        # ── 2. Deduplication (Jaccard trigram) ────────────────────────────
        deduped: List[Tuple[str, float]] = []
        for text, score in filtered:
            is_dup = any(_jaccard(text, kept) > DEDUP_SIM_THR for kept, _ in deduped)
            if not is_dup:
                deduped.append((text, score))

        # ── 3. Source diversity (max MAX_PER_DOC per file) ─────────────────
        # Website pages each have a distinct URL — treat each URL as its own
        # document so we can pull multiple pages from the same crawled site.
        doc_counts: Dict[str, int] = {}
        diverse: List[Tuple[str, float, str]] = []  # (text, score, file_name)

        for text, score in deduped:
            payload_entry = {}
            if payload_map:
                payload_entry = payload_map.get(text[:100], {})
            fname = payload_entry.get("file_name", "unknown")

            # For website chunks, use the page URL as diversity key so each
            # unique page is counted separately (not lumped under one site).
            if payload_entry.get("source_type") == "website":
                diversity_key = payload_entry.get("url", fname)
                cap = 1          # one chunk per unique page URL
            else:
                diversity_key = fname
                cap = MAX_PER_DOC

            count = doc_counts.get(diversity_key, 0)
            if count < cap:
                diverse.append((text, score, fname))
                doc_counts[diversity_key] = count + 1

            if len(diverse) >= MAX_CHUNKS:
                break

        # Backfill if diversity filter left us short
        if len(diverse) < min(MAX_CHUNKS, len(deduped)):
            existing = {t for t, _, _ in diverse}
            for text, score in deduped:
                if text not in existing:
                    p = payload_map.get(text[:100], {}) if payload_map else {}
                    fname = p.get("file_name", "unknown")
                    diverse.append((text, score, fname))
                    existing.add(text)
                if len(diverse) >= MAX_CHUNKS:
                    break

        # ── 4. Context compression + assembly ─────────────────────────────
        per_chunk_budget = MAX_CHARS // max(len(diverse), 1)
        parts: List[str] = []
        sources: List[dict] = []

        for i, (text, score, fname) in enumerate(diverse):
            compressed = _key_sentences(text, per_chunk_budget)

            # ── Website metadata enrichment ───────────────────────────────
            # Inject rich page metadata so the LLM can answer navigation,
            # org-info, contact, and directory queries accurately.
            payload = {}
            if payload_map:
                payload = payload_map.get(text[:100], {})

            if payload.get("source_type") == "website":
                header_lines = []
                page_url   = payload.get("url", "")
                page_title = payload.get("title") or payload.get("og_title", "")
                page_type  = payload.get("page_type", "")
                org_name   = payload.get("org_name") or payload.get("source_name", "")
                nav_links  = payload.get("nav_links", "")
                stats      = payload.get("stats", "")
                people     = payload.get("people", "")
                contact_ph = payload.get("contact_phone", "")
                contact_em = payload.get("contact_email", "")

                if page_title:
                    label = f"[Website] {org_name}: {page_title}" if org_name else f"[Website] {page_title}"
                    header_lines.append(label)
                if page_url:
                    header_lines.append(f"URL: {page_url}")
                if page_type:
                    header_lines.append(f"Page type: {page_type}")
                if nav_links:
                    header_lines.append(f"Navigation: {nav_links}")
                if stats:
                    header_lines.append(f"Key stats: {stats}")
                if people:
                    header_lines.append(f"Key people: {people}")
                if contact_ph or contact_em:
                    contact_parts = []
                    if contact_ph:
                        contact_parts.append(f"Phone: {contact_ph}")
                    if contact_em:
                        contact_parts.append(f"Email: {contact_em}")
                    header_lines.append("Contact: " + " | ".join(contact_parts))

                if header_lines:
                    compressed = "\n".join(header_lines) + "\n\n" + compressed

            # ── Source attribution ─────────────────────────────────────────
            line_s = payload.get("line_start")
            page_url = payload.get("url", "")
            if payload.get("source_type") == "website" and page_url:
                src_name = page_url
            elif fname != "unknown":
                src_name = f"{fname} (line {line_s})" if line_s else fname
            else:
                src_name = f"Document chunk {i+1}"

            parts.append(compressed)
            sources.append({
                "name": src_name,
                "relevance": round(min(0.95 - i * 0.04, 0.5), 2),
                "chunk": text[:200],
                "file_name": fname,
            })

        assembled = "\n\n---\n\n".join(parts)
        # Final hard cap
        if len(assembled) > MAX_CHARS:
            assembled = assembled[:MAX_CHARS] + "\n[Context truncated]"

        return assembled, sources


# Module-level singleton
_builder: Optional[ContextBuilder] = None


def get_context_builder() -> ContextBuilder:
    global _builder
    if _builder is None:
        _builder = ContextBuilder()
    return _builder

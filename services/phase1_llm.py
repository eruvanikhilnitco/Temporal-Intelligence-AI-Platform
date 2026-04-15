"""
LLM Service — Cohere command-r7b-12-2024 primary with OpenAI gpt-4o fallback.

Provider chain:
  1. Cohere command-r7b-12-2024  (primary — Cohere SDK v5 / ClientV2)
  2. OpenAI gpt-4o               (fallback if Cohere fails / rate-limited)
  3. Emergency static message    (both fail)

Every call returns metadata: provider_used, latency_ms, fallback_used.
Fallback events are written to the structured error log.
"""

import logging
import os
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_GREETINGS = [
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "what's up", "how do you do", "nice to meet you",
    "you are good", "you are not good", "how is your day",
]

_GREETING_REPLY = (
    "Hey there! I'm doing great, thanks for asking! "
    "I'm CortexFlow AI — your intelligent document assistant. "
    "I'm here to help you find information, answer questions about documents, "
    "and make sense of complex data. What can I help you with today?"
)

_SYSTEM_USER = (
    "You are a friendly, knowledgeable assistant helping users find information from their organisation's documents and website.\n\n"
    "GROUNDING RULES (strictly follow these):\n"
    "1. Answer ONLY from the provided document context. Never use outside knowledge or assumptions.\n"
    "2. If the answer is not in the context, say clearly: "
    "'I don't have that information in the available documents.' "
    "Do not guess, invent, or pad the answer.\n"
    "3. When you use information from a document or webpage, mention the source naturally "
    "(e.g. 'According to the Q1 Report...' or 'On the Services page...'). This helps users verify.\n"
    "4. Be warm, clear, and conversational — avoid robotic or template phrases.\n"
    "5. Keep answers focused. If the context covers only part of the question, answer that part "
    "and tell the user what is missing.\n"
    "6. Do NOT reveal raw file paths or internal chunk IDs — just the document or page name.\n"
    "7. NAVIGATION & LINKS: If the user asks for a link to a page, navigate somewhere, or asks how to "
    "reach a specific page, look for URLs in the context (website source_type chunks contain 'url' fields). "
    "Provide the direct URL if available. If not, give clear step-by-step navigation instructions "
    "(e.g. 'Go to the homepage → click Services → select Enterprise Solutions'). "
    "Never invent URLs — only use URLs that appear in the indexed content."
)

_SYSTEM_ADMIN = (
    "You are a precise technical assistant with full access to document context.\n\n"
    "GROUNDING RULES (strictly follow these):\n"
    "1. Answer ONLY from the provided document context. Do not draw on general knowledge.\n"
    "2. If information is not present in the context, say: "
    "'I don't have that information indexed yet.' Do not infer or extrapolate.\n"
    "3. Cite the source document for every factual claim — include the document name and, "
    "where available, the line range (e.g. 'Policy.pdf, lines 42–55').\n"
    "4. Format answers with bullet points or numbered lists where appropriate.\n"
    "5. If the context partially answers the question, answer what is covered and clearly "
    "identify what remains unanswered.\n"
    "6. WEBSITE CONTENT: Chunks with 'URL:' headers are from a crawled organisation website. "
    "Use these to answer questions about the organisation's services, people, stats, and structure. "
    "Include the direct URL when answering navigation or 'where is X' queries."
)

_COHERE_MODEL = "command-r7b-12-2024"
_LLM_TIMEOUT_S = 25   # hard timeout per LLM provider call


class LLMService:
    def __init__(self):
        self._cohere_client = None
        self._openai_client = None
        self._init_cohere()
        self._init_openai()

    def _init_cohere(self):
        api_key = os.getenv("COHERE_API_KEY", "").strip()
        if not api_key:
            logger.warning("[LLM] COHERE_API_KEY not set — Cohere provider disabled")
            return
        try:
            import cohere
            # SDK v5 — use ClientV2 which supports the v2 chat endpoint
            self._cohere_client = cohere.ClientV2(api_key)
            logger.info("[LLM] Cohere ClientV2 ready (model=%s)", _COHERE_MODEL)
        except Exception as e:
            logger.warning("[LLM] Cohere init failed: %s", e)

    def _init_openai(self):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return
        try:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=api_key, timeout=_LLM_TIMEOUT_S)
            logger.info("[LLM] OpenAI fallback client ready")
        except Exception as e:
            logger.warning("[LLM] OpenAI init failed: %s", e)

    # ── Query rewriting / expansion ───────────────────────────────────────────

    def rewrite_query(self, query: str) -> str:
        """
        Expand a short or ambiguous query into a richer retrieval query.
        Returns original query on any failure (never blocks the pipeline).
        Uses a fast, cheap Cohere call with a 5-second timeout.
        """
        if not self._cohere_client:
            return query

        # Only rewrite substantive queries (skip greetings / very short strings)
        if len(query.strip().split()) < 3:
            return query

        try:
            from cohere.base_client import RequestOptions
            prompt = (
                "You are a search query optimizer. Rewrite the following query to be more "
                "specific and retrieval-friendly for a RAG system. Keep it concise (1-2 sentences). "
                "Output ONLY the rewritten query, nothing else.\n\n"
                f"Original query: {query}\n\nRewritten query:"
            )
            resp = self._cohere_client.chat(
                model=_COHERE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0.0,
                request_options=RequestOptions(timeout_in_seconds=5),
            )
            rewritten = ""
            if resp.message and resp.message.content:
                rewritten = resp.message.content[0].text.strip()
            if rewritten and len(rewritten) > 10:
                logger.info("[LLM] Query rewritten: %r → %r", query[:60], rewritten[:80])
                return rewritten
        except Exception as e:
            logger.debug("[LLM] Query rewrite skipped: %s", e)

        return query

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_answer(
        self,
        query: str,
        context: str,
        role: str = "user",
        conversation_history: Optional[list] = None,
    ) -> str:
        """Backward-compatible wrapper — returns just the answer string."""
        return self.generate_answer_with_meta(query, context, role, conversation_history)["answer"]

    def generate_answer_with_meta(
        self,
        query: str,
        context: str,
        role: str = "user",
        conversation_history: Optional[list] = None,
    ) -> dict:
        """Returns {answer, provider_used, latency_ms, fallback_used}."""
        # Greeting shortcut — no LLM call needed
        q_lower = query.lower().strip()
        if any(q_lower == g or q_lower.startswith(g) for g in _GREETINGS):
            return {
                "answer": _GREETING_REPLY,
                "provider_used": "static",
                "latency_ms": 0,
                "fallback_used": False,
            }

        context = context[:8000]
        system_prompt = _SYSTEM_ADMIN if role == "admin" else _SYSTEM_USER

        # Build user message content
        parts = []
        if conversation_history:
            history_lines = []
            for turn in (conversation_history or [])[-3:]:
                r = turn.get("role", "user")
                t = turn.get("text", "")[:500]
                history_lines.append(f"{r.capitalize()}: {t}")
            if history_lines:
                parts.append("Previous conversation:\n" + "\n".join(history_lines))

        if context.strip():
            parts.append(
                f"--- DOCUMENT CONTEXT START ---\n{context}\n--- DOCUMENT CONTEXT END ---"
            )
            parts.append(
                f"Question: {query}\n\n"
                "Answer (grounded in the document context above — cite sources inline):"
            )
        else:
            parts.append(
                f"Question: {query}\n\n"
                "Note: No document context is available for this query.\nAnswer:"
            )

        user_content = "\n\n".join(parts)

        t0 = time.time()

        # ── Cohere primary (SDK v5, ClientV2) ────────────────────────────────
        if self._cohere_client:
            try:
                from cohere.base_client import RequestOptions
                response = self._cohere_client.chat(
                    model=_COHERE_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    max_tokens=1024,
                    temperature=0.1,
                    request_options=RequestOptions(timeout_in_seconds=_LLM_TIMEOUT_S),
                )
                answer = ""
                if response.message and response.message.content:
                    answer = response.message.content[0].text.strip()
                if answer:
                    return {
                        "answer": answer,
                        "provider_used": "cohere",
                        "latency_ms": int((time.time() - t0) * 1000),
                        "fallback_used": False,
                    }
            except Exception as e:
                logger.warning("[LLM] Cohere failed (%s) — trying OpenAI fallback", e)
                _log_fallback("cohere", str(e))

        # ── OpenAI fallback ───────────────────────────────────────────────────
        if self._openai_client:
            try:
                response = self._openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    max_tokens=1024,
                )
                answer = response.choices[0].message.content.strip()
                if answer:
                    return {
                        "answer": answer,
                        "provider_used": "openai_fallback",
                        "latency_ms": int((time.time() - t0) * 1000),
                        "fallback_used": True,
                    }
            except Exception as e:
                logger.error("[LLM] OpenAI fallback also failed: %s", e)
                _log_fallback("openai", str(e))

        # ── Emergency static ──────────────────────────────────────────────────
        return {
            "answer": (
                "The AI service is temporarily unavailable. "
                "Please try again in a few minutes."
            ),
            "provider_used": "emergency_fallback",
            "latency_ms": int((time.time() - t0) * 1000),
            "fallback_used": True,
        }


def _log_fallback(provider: str, reason: str):
    try:
        from app.error_logger import log_warning
        log_warning("LLM", f"{provider} provider failed — fallback triggered",
                    extra={"provider": provider, "reason": reason[:200]})
    except Exception:
        pass

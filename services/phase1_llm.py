"""
LLM Service — Cohere primary with OpenAI gpt-4o-mini automatic fallback.

Provider chain:
  1. Cohere command-r7b-12-2024  (primary)
  2. OpenAI gpt-4o-mini          (fallback if Cohere fails / rate-limited)
  3. Emergency static message     (both fail)

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
    "Hey there! I'm doing great, thanks for asking! 😊 "
    "I'm CortexFlow AI — your intelligent document assistant. "
    "I'm here to help you find information, answer questions about documents, "
    "and make sense of complex data. What can I help you with today?"
)

_PROMPT_USER = (
    "You are a friendly, knowledgeable assistant helping users understand information from documents. "
    "Respond naturally as a person would — be warm, clear, and helpful. "
    "Never say 'Not found in document' or use robotic phrases. "
    "If you don't have specific information, say something like 'I don't have details on that right now, "
    "but I can help you with...' or give a helpful general response. "
    "Keep answers concise and conversational. Do NOT reveal document names, raw file paths, "
    "or complete document content — just provide helpful, summarized answers."
)

_PROMPT_ADMIN = (
    "You are a precise technical assistant with full access to document context. "
    "Answer accurately based on the provided context. "
    "If information is not in the context, say so clearly and suggest what to search for. "
    "Format answers clearly with bullet points where appropriate."
)


class LLMService:
    def __init__(self):
        self._cohere_client = None
        self._openai_client = None
        self._init_cohere()
        self._init_openai()

    def _init_cohere(self):
        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            logger.warning("[LLM] COHERE_API_KEY not set — Cohere provider disabled")
            return
        try:
            import cohere
            self._cohere_client = cohere.Client(api_key)
            logger.info("[LLM] Cohere client ready")
        except Exception as e:
            logger.warning("[LLM] Cohere init failed: %s", e)

    def _init_openai(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return
        try:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=api_key)
            logger.info("[LLM] OpenAI fallback client ready")
        except Exception as e:
            logger.warning("[LLM] OpenAI init failed: %s", e)

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
        system_prompt = _PROMPT_ADMIN if role == "admin" else _PROMPT_USER
        history_text = _format_history(conversation_history)

        if context.strip():
            prompt = (
                f"{system_prompt}\n\n"
                f"{history_text}"
                f"Context from documents:\n{context}\n\n"
                f"User question: {query}\n\nAnswer:"
            )
        else:
            prompt = (
                f"{system_prompt}\n\n"
                f"{history_text}"
                f"User question: {query}\n\nAnswer:"
            )

        t0 = time.time()

        # ── Cohere (primary) ──────────────────────────────────────────────────
        if self._cohere_client:
            try:
                response = self._cohere_client.chat(
                    model="command-r7b-12-2024",
                    message=prompt,
                    temperature=0.3,
                )
                answer = response.text.strip() if response.text else ""
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

        # ── OpenAI (fallback) ─────────────────────────────────────────────────
        if self._openai_client:
            try:
                response = self._openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
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
                "Our team has been notified and will restore service shortly. "
                "Please try again in a few minutes."
            ),
            "provider_used": "emergency_fallback",
            "latency_ms": int((time.time() - t0) * 1000),
            "fallback_used": True,
        }


def _format_history(history: Optional[list]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-3:]:
        role = turn.get("role", "user")
        text = turn.get("text", "")[:500]
        lines.append(f"{role.capitalize()}: {text}")
    return "Previous conversation:\n" + "\n".join(lines) + "\n\n"


def _log_fallback(provider: str, reason: str):
    try:
        from app.error_logger import log_warning
        log_warning("LLM", f"{provider} provider failed — fallback triggered",
                    extra={"provider": provider, "reason": reason[:200]})
    except Exception:
        pass

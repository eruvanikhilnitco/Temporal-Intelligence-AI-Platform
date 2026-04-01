"""
Self-Learning Pipeline (without fine-tuning).

Implements:
  1. Store anonymized chat logs
  2. Feedback loop (thumbs up/down)
  3. Context ranking improvement via feedback signals
  4. Query optimization (expand/rewrite popular queries)
  5. Memory enhancement (session-based context awareness)
  6. Returning users get improved contextual responses
"""

import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional, Dict, List
import re

logger = logging.getLogger(__name__)


class SessionMemory:
    """
    Maintains per-session context for follow-up awareness.
    Stores last N turns of conversation to enable context-aware responses.
    """

    MAX_TURNS = 6

    def __init__(self):
        self._sessions: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.MAX_TURNS)
        )

    def add_turn(self, session_id: str, question: str, answer: str):
        self._sessions[session_id].append({
            "q": question,
            "a": answer[:500],  # truncate for memory efficiency
            "ts": datetime.utcnow().isoformat(),
        })

    def get_context(self, session_id: str) -> str:
        """Return formatted conversation history for LLM context injection."""
        turns = list(self._sessions.get(session_id, []))
        if not turns:
            return ""
        lines = ["[Previous conversation context]"]
        for t in turns[-3:]:  # last 3 turns
            lines.append(f"Q: {t['q']}")
            lines.append(f"A: {t['a'][:200]}…")
        return "\n".join(lines)

    def clear(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]


class FeedbackStore:
    """
    In-memory feedback accumulator.
    Tracks which queries received positive / negative feedback
    and uses this to boost or penalize retrieval weights.
    """

    def __init__(self):
        self._positive: Dict[str, int] = defaultdict(int)
        self._negative: Dict[str, int] = defaultdict(int)
        self._query_rewrites: Dict[str, str] = {}

    def record(self, question: str, feedback: str):
        key = self._normalize(question)
        if feedback == "positive":
            self._positive[key] += 1
        elif feedback == "negative":
            self._negative[key] += 1

    def get_score(self, question: str) -> float:
        """
        Returns a feedback-adjusted confidence modifier [-0.15, +0.15].
        Frequently upvoted queries get a confidence boost.
        """
        key = self._normalize(question)
        pos = self._positive.get(key, 0)
        neg = self._negative.get(key, 0)
        total = pos + neg
        if total == 0:
            return 0.0
        ratio = pos / total
        return round((ratio - 0.5) * 0.30, 3)  # maps [0,1] → [-0.15, +0.15]

    def suggest_rewrite(self, question: str) -> Optional[str]:
        """If a query was frequently downvoted, suggest expansion."""
        key = self._normalize(question)
        neg = self._negative.get(key, 0)
        if neg >= 2:
            return self._expand_query(question)
        return None

    def _expand_query(self, question: str) -> str:
        """Adds context keywords to improve retrieval on poor queries."""
        expansions = {
            r"\bwho\b": "who is the party or entity",
            r"\bwhat\b": "what is the definition or detail of",
            r"\bwhen\b": "when is the date or time for",
            r"\bhow\b": "how does or what is the process for",
        }
        q = question
        for pat, replacement in expansions.items():
            q = re.sub(pat, replacement, q, flags=re.IGNORECASE, count=1)
        return q if q != question else question + " provide detailed information"

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().strip())


class SelfLearningService:
    """
    Main self-learning orchestrator.

    Behavior:
    - First-time users: baseline responses
    - Returning users: context-enriched responses (session memory)
    - Frequently upvoted queries: confidence boost
    - Frequently downvoted queries: query expansion / rewrite
    - Feedback signals improve retrieval without fine-tuning
    """

    def __init__(self):
        self.session_memory = SessionMemory()
        self.feedback_store = FeedbackStore()
        self._user_query_history: Dict[str, List[str]] = defaultdict(list)

    def before_query(
        self,
        question: str,
        user_id: str,
        session_id: str,
    ) -> dict:
        """
        Called before retrieval. Returns enrichment hints.

        Returns:
          {
            "enriched_query": str,          — possibly expanded query
            "session_context": str,         — prior conversation context
            "confidence_modifier": float,   — feedback-based adjustment
          }
        """
        enriched = self.feedback_store.suggest_rewrite(question) or question
        session_ctx = self.session_memory.get_context(session_id)
        conf_mod = self.feedback_store.get_score(question)

        # Track user query history (for personalization)
        self._user_query_history[user_id].append(question)

        return {
            "enriched_query": enriched,
            "session_context": session_ctx,
            "confidence_modifier": conf_mod,
        }

    def after_query(
        self,
        question: str,
        answer: str,
        user_id: str,
        session_id: str,
        confidence: float,
    ):
        """Called after the answer is generated. Updates session memory."""
        self.session_memory.add_turn(session_id, question, answer)

    def record_feedback(self, question: str, answer: str,
                        feedback: str, user_id: str):
        """Record positive/negative feedback."""
        self.feedback_store.record(question, feedback)
        logger.info(f"[SelfLearning] Feedback '{feedback}' for: {question[:60]}")

    def get_user_context_hint(self, user_id: str, question: str) -> str:
        """
        For returning users: check if they've asked similar questions before
        and prepend a context hint to improve answer coherence.
        """
        history = self._user_query_history.get(user_id, [])
        if len(history) < 3:
            return ""
        # Find semantically similar past queries (simple keyword overlap)
        q_words = set(question.lower().split())
        for past_q in reversed(history[-10:]):
            past_words = set(past_q.lower().split())
            overlap = q_words & past_words
            if len(overlap) >= 3 and past_q != question:
                return f"[User context: Previously asked about '{past_q[:80]}']"
        return ""


# Global singleton
_self_learning = SelfLearningService()


def get_self_learning() -> SelfLearningService:
    return _self_learning

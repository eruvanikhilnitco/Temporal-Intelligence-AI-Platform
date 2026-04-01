"""
Security Service — Zero-Trust query enforcement.

Detects:
  - Prompt injection attacks
  - Malicious queries / jailbreak attempts
  - Data leakage patterns
  - Excessive query rates
  - Role escalation attempts
"""

import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# ── Injection / attack patterns ───────────────────────────────────────────────

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above|prior)\s+instructions?",
    r"forget\s+(everything|all|previous)",
    r"you\s+are\s+now\s+(a|an|the)",
    r"pretend\s+(you|to\s+be)",
    r"act\s+as\s+(if|a|an)",
    r"jailbreak",
    r"DAN\b",
    r"do\s+anything\s+now",
    r"system\s*prompt",
    r"reveal\s+(your|the)\s+(prompt|instructions?|system)",
    r"bypass\s+(security|filter|restriction)",
    r"override\s+(safety|filter|restriction|rule)",
    r"<\s*script\s*>",
    r"<\s*img\s+src\s*=",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"__import__",
    r"subprocess",
    r"os\.system",
    r"DROP\s+TABLE",
    r"DELETE\s+FROM",
    r"INSERT\s+INTO.*SELECT",
    r"UNION\s+SELECT",
    r";\s*--",
]

DATA_LEAKAGE_PATTERNS = [
    r"\bpassword\b.*\buser(s)?\b",
    r"\bapi[_\s]?key\b",
    r"\bsecret[_\s]?key\b",
    r"\bssn\b|\bsocial\s+security\b",
    r"\bcredit\s+card\b|\bcard\s+number\b",
    r"\bpersonal\s+identifiable\b",
    r"\bdump\s+(all|every|the)\s+(data|database|table)",
    r"\blist\s+all\s+users?\b",
    r"\bexport\s+(all|every)\b",
]

SCRAPING_PATTERNS = [
    r"(give|show|list|print|dump|output)\s+(all|every|each|the\s+entire)",
    r"repeat\s+(this|that|everything|the\s+above)\s+\d+\s*times",
    r"loop\s+(forever|infinitely)",
]

_COMPILED_INJECTION = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]
_COMPILED_LEAKAGE = [re.compile(p, re.IGNORECASE) for p in DATA_LEAKAGE_PATTERNS]
_COMPILED_SCRAPING = [re.compile(p, re.IGNORECASE) for p in SCRAPING_PATTERNS]


# ── Rate limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Sliding window rate limiter per user."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self._windows: dict = defaultdict(deque)

    def is_allowed(self, user_id: str) -> Tuple[bool, int]:
        """Returns (allowed, current_count)."""
        now = datetime.utcnow()
        cutoff = now - self.window
        q = self._windows[user_id]

        # Remove expired entries
        while q and q[0] < cutoff:
            q.popleft()

        count = len(q)
        if count >= self.max_requests:
            return False, count

        q.append(now)
        return True, count + 1


_rate_limiter = RateLimiter()


# ── Detection ─────────────────────────────────────────────────────────────────

class ThreatResult:
    def __init__(self, is_threat: bool, threat_type: Optional[str],
                 severity: str, description: str):
        self.is_threat = is_threat
        self.threat_type = threat_type
        self.severity = severity
        self.description = description


def analyze_query(
    query: str,
    user_id: str,
    user_role: str,
) -> ThreatResult:
    """
    Analyze a query for security threats.
    Returns a ThreatResult with threat classification.
    """
    # Check rate limit
    allowed, count = _rate_limiter.is_allowed(user_id)
    if not allowed:
        return ThreatResult(
            True, "rate_limit", "medium",
            f"Rate limit exceeded: {count} requests in last 60 seconds"
        )

    # Prompt injection
    for pattern in _COMPILED_INJECTION:
        if pattern.search(query):
            logger.warning(f"[Security] Prompt injection: {query[:100]}")
            return ThreatResult(
                True, "prompt_injection", "high",
                f"Prompt injection pattern detected: '{pattern.pattern[:40]}'"
            )

    # Data leakage
    for pattern in _COMPILED_LEAKAGE:
        if pattern.search(query):
            logger.warning(f"[Security] Data leakage attempt: {query[:100]}")
            return ThreatResult(
                True, "data_leakage", "high",
                "Query appears to target sensitive data"
            )

    # Scraping
    for pattern in _COMPILED_SCRAPING:
        if pattern.search(query):
            return ThreatResult(
                True, "scraping", "medium",
                "Mass data extraction pattern detected"
            )

    return ThreatResult(False, None, "none", "Clean")


def compute_user_risk(suspicious_count: int, total_queries: int) -> Tuple[int, str]:
    """
    Compute risk score (0–100) and level based on historical behavior.
    Returns (score, level).
    """
    if total_queries == 0:
        return 0, "low"

    ratio = suspicious_count / max(total_queries, 1)

    if suspicious_count >= 5 or ratio >= 0.3:
        return 90, "critical"
    elif suspicious_count >= 3 or ratio >= 0.15:
        return 65, "high"
    elif suspicious_count >= 1 or ratio >= 0.05:
        return 35, "medium"
    else:
        return 5, "low"

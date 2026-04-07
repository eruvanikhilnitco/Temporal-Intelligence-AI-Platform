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


# ── PII masking (extension — new capability) ──────────────────────────────────

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"), "SSN"),
    (re.compile(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|"
        r"3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"
    ), "CREDIT_CARD"),
    (re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"), "PASSPORT"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "IP_ADDRESS"),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "EMAIL"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "PHONE"),
]

# Attack severity map (0-10) for patterns already compiled above
_ATTACK_SEVERITY = {
    "prompt_injection": 10.0,
    "data_leakage": 8.0,
    "scraping": 5.0,
    "rate_limit": 4.0,
}


def mask_pii(text: str) -> tuple:
    """
    Replace PII in text with [TYPE_REDACTED] placeholders.
    Returns (masked_text, list_of_pii_types_found).
    Safe to call on any string before logging or storing.
    """
    found = []
    for pattern, pii_type in _PII_PATTERNS:
        if pattern.search(text):
            found.append(pii_type)
            text = pattern.sub(f"[{pii_type}_REDACTED]", text)
    return text, found


def attack_score(query: str) -> tuple:
    """
    Compute a 0-10 threat score for a query.
    Returns (score, [attack_type_labels]).
    0 = clean, 10 = critical attack pattern.
    """
    detected = []
    max_score = 0.0
    for pattern in _COMPILED_INJECTION:
        if pattern.search(query):
            detected.append("PROMPT_INJECTION")
            max_score = max(max_score, _ATTACK_SEVERITY["prompt_injection"])
    for pattern in _COMPILED_LEAKAGE:
        if pattern.search(query):
            detected.append("DATA_LEAKAGE")
            max_score = max(max_score, _ATTACK_SEVERITY["data_leakage"])
    for pattern in _COMPILED_SCRAPING:
        if pattern.search(query):
            detected.append("SCRAPING")
            max_score = max(max_score, _ATTACK_SEVERITY["scraping"])
    return max_score, list(set(detected))


def full_security_analysis(query: str, user_id: str, user_role: str) -> dict:
    """
    Combined analysis: threat detection + PII masking + attack scoring.
    Returns a dict suitable for logging and gating decisions.
    """
    threat = analyze_query(query, user_id, user_role)
    score, attacks = attack_score(query)
    masked_q, pii_found = mask_pii(query)
    risk_level = "HIGH" if score >= 7 or threat.severity == "high" else \
                 "MEDIUM" if score >= 3 or pii_found else "LOW"
    return {
        "is_threat": threat.is_threat,
        "threat_type": threat.threat_type,
        "threat_severity": threat.severity,
        "attack_score": score,
        "attack_types": attacks,
        "pii_found": pii_found,
        "masked_query": masked_q,
        "risk_level": risk_level,
        "should_block": threat.is_threat and threat.severity == "high",
        "should_warn": risk_level == "MEDIUM",
    }

"""
MetadataExtractor — automatically derives domain, doc_type, and sensitivity
metadata from document text and filename WITHOUT hardcoding domain names.

Design (SOLID — Open/Closed):
  - Extend DOMAIN_PROFILES to add new domains without touching any other code.
  - Three strategies run in priority order:
      1. Entity-based  : spaCy named-entity counts to infer domain
      2. Keyword scoring: TF-like scoring against configurable domain profiles
      3. Structural cues: document structure signals (tables, headers, lists)
  - Returns a metadata dict that is stored per-chunk in Qdrant and per-doc in graph.

Usage:
    from services.metadata_extractor import MetadataExtractor
    meta = MetadataExtractor().extract(text, filename="contract_2024.pdf")
    # → {"domain": "legal", "doc_type": "contract", "sensitivity": "high",
    #    "keywords_found": [...], "entity_counts": {...}}
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Domain profiles (extend here, never modify extractor logic) ───────────────

DOMAIN_PROFILES: Dict[str, Dict] = {
    "legal": {
        "keywords": [
            "contract", "agreement", "clause", "liability", "indemnification",
            "jurisdiction", "arbitration", "termination", "confidentiality",
            "intellectual property", "warranty", "governing law", "breach",
            "obligation", "party", "parties", "whereas", "herein", "hereof",
            "executed", "signatory", "notary", "affidavit", "deposition",
            "plaintiff", "defendant", "litigation", "subpoena", "injunction",
        ],
        "doc_types": {
            "contract": ["contract", "agreement", "mou", "memorandum", "sla"],
            "policy": ["policy", "terms", "conditions", "guidelines"],
            "legal_brief": ["brief", "motion", "complaint", "petition"],
        },
        "sensitivity_boost": 0.3,
    },
    "finance": {
        "keywords": [
            "invoice", "revenue", "profit", "loss", "balance sheet",
            "income statement", "cash flow", "budget", "expense", "tax",
            "audit", "fiscal", "quarterly", "annual report", "dividend",
            "equity", "liability", "asset", "depreciation", "amortization",
            "accounts receivable", "accounts payable", "ebitda", "roi",
            "payroll", "salary", "compensation", "reimbursement", "billing",
            "payment", "ledger", "journal entry", "reconciliation",
        ],
        "doc_types": {
            "report": ["report", "statement", "analysis", "summary"],
            "invoice": ["invoice", "receipt", "bill", "purchase order"],
            "budget": ["budget", "forecast", "projection", "plan"],
        },
        "sensitivity_boost": 0.2,
    },
    "hr": {
        "keywords": [
            "employee", "salary", "leave", "resignation", "termination",
            "onboarding", "performance review", "appraisal", "benefits",
            "recruitment", "candidate", "interview", "offer letter",
            "job description", "workforce", "headcount", "attendance",
            "overtime", "human resources", "hr", "department", "manager",
            "promotion", "demotion", "disciplinary", "grievance", "handbook",
            "vacation", "sick leave", "maternity", "paternity",
        ],
        "doc_types": {
            "policy": ["policy", "handbook", "guidelines", "code of conduct"],
            "letter": ["offer", "appointment", "resignation", "termination"],
            "review": ["review", "appraisal", "evaluation", "assessment"],
        },
        "sensitivity_boost": 0.4,
    },
    "medical": {
        "keywords": [
            "patient", "diagnosis", "treatment", "prescription", "clinical",
            "hospital", "physician", "nurse", "medication", "dosage",
            "symptoms", "lab results", "radiology", "surgery", "procedure",
            "insurance", "claim", "discharge", "admission", "icd", "cpt",
            "hipaa", "medical record", "health", "disease", "therapy",
        ],
        "doc_types": {
            "record": ["record", "report", "summary", "history"],
            "prescription": ["prescription", "rx", "medication"],
            "insurance": ["insurance", "claim", "authorization"],
        },
        "sensitivity_boost": 0.5,
    },
    "technical": {
        "keywords": [
            "api", "endpoint", "database", "server", "deployment", "docker",
            "kubernetes", "microservice", "architecture", "schema", "query",
            "function", "class", "module", "library", "framework", "sdk",
            "authentication", "authorization", "encryption", "ssl", "tls",
            "algorithm", "performance", "latency", "throughput", "pipeline",
            "ci/cd", "git", "repository", "branch", "merge", "pull request",
        ],
        "doc_types": {
            "specification": ["spec", "specification", "requirement", "design"],
            "documentation": ["documentation", "readme", "guide", "manual"],
            "report": ["report", "analysis", "benchmark", "test"],
        },
        "sensitivity_boost": 0.1,
    },
    "operations": {
        "keywords": [
            "logistics", "supply chain", "procurement", "vendor", "supplier",
            "delivery", "shipment", "inventory", "warehouse", "order",
            "purchase", "quotation", "rfp", "rfq", "bid", "tender",
            "quality", "compliance", "regulation", "standard", "audit",
            "process", "workflow", "sop", "procedure", "checklist",
        ],
        "doc_types": {
            "sop": ["sop", "procedure", "process", "workflow"],
            "procurement": ["rfp", "rfq", "bid", "tender", "quotation"],
            "report": ["report", "summary", "log", "record"],
        },
        "sensitivity_boost": 0.15,
    },
}

# Sensitivity signal words (domain-agnostic)
SENSITIVITY_SIGNALS = {
    "high": [
        "confidential", "private", "sensitive", "restricted", "secret",
        "classified", "do not distribute", "proprietary", "internal only",
        "ssn", "social security", "passport", "credit card", "bank account",
        "salary", "compensation", "medical", "patient", "hipaa", "gdpr",
    ],
    "medium": [
        "internal", "for internal use", "not for public", "draft",
        "preliminary", "pre-decisional", "deliberative",
    ],
}


class MetadataExtractor:
    """
    Extracts domain, doc_type, and sensitivity metadata from raw document text.

    Strategy (in priority order):
      1. LLM classification — Cohere/OpenAI classifies first 1000 chars (most accurate)
      2. Keyword TF scoring — fast, deterministic fallback (no LLM call)
      3. Entity counting    — regex entity signals boost domain score
      4. Structural cues    — filename and structure hints

    Open for extension: add profiles to DOMAIN_PROFILES, no code changes needed.
    """

    # ── LLM-based classification ───────────────────────────────────────────────

    @staticmethod
    def _llm_classify(text: str, filename: str = "") -> Optional[Dict]:
        """
        Ask the LLM to classify the document. Returns dict or None if unavailable.
        Uses first 1200 chars (fast, cheap) — not the full document.
        """
        snippet = text[:1200].strip()
        valid_domains = ", ".join(DOMAIN_PROFILES.keys()) + ", general"

        prompt = (
            f"Classify this document excerpt and filename. "
            f"Reply with ONLY a JSON object — no explanation.\n\n"
            f'Filename: "{filename}"\n\n'
            f"Excerpt:\n{snippet}\n\n"
            f"Return exactly this JSON structure:\n"
            f'{{"domain": "<one of: {valid_domains}>", '
            f'"doc_type": "<contract|report|policy|invoice|letter|manual|brief|review|document>", '
            f'"sensitivity": "<high|medium|low>", '
            f'"confidence": <float 0.0-1.0>}}'
        )
        try:
            import os, json as _json
            cohere_key = os.getenv("COHERE_API_KEY")
            if cohere_key:
                import cohere as _cohere
                client = _cohere.Client(cohere_key)
                resp = client.chat(
                    model="command-r7b-12-2024",
                    message=prompt,
                    temperature=0.0,
                )
                raw = resp.text.strip()
                # Strip markdown fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1].lstrip("json").strip()
                result = _json.loads(raw)
                # Validate keys
                if all(k in result for k in ("domain", "doc_type", "sensitivity")):
                    result["source"] = "llm"
                    return result
        except Exception as e:
            logger.debug("[MetadataExtractor] LLM classification failed: %s", e)
        return None

    def extract(self, text: str, filename: str = "") -> Dict:
        """
        Main entry point. Returns a metadata dict with:
          - domain       : inferred domain (legal, finance, hr, medical, technical, operations, general)
          - doc_type     : inferred document type within the domain
          - sensitivity  : high | medium | low
          - keywords_found: list of matched domain keywords
          - entity_counts : rough entity type counts from regex
          - confidence   : 0.0–1.0 score for the domain inference
        """
        text_lower = text.lower()
        fname_lower = filename.lower()

        # Step 0: LLM classification (most accurate — skip on very short texts)
        if len(text.strip()) > 200:
            llm_result = self._llm_classify(text, filename)
            if llm_result:
                # LLM succeeded — enrich with keyword evidence and return
                entity_counts = self._count_entities(text)
                _, kw_hits = self._score_keywords(
                    text_lower,
                    DOMAIN_PROFILES.get(llm_result.get("domain", "general"), {}).get("keywords", []),
                )
                return {
                    "domain": llm_result.get("domain", "general"),
                    "doc_type": llm_result.get("doc_type", "document"),
                    "sensitivity": llm_result.get("sensitivity", "low"),
                    "keywords_found": kw_hits[:10],
                    "entity_counts": entity_counts,
                    "confidence": float(llm_result.get("confidence", 0.8)),
                    "classification_source": "llm",
                }

        # Step 1: Entity-based signal (keyword fallback path)
        entity_counts = self._count_entities(text)

        # Step 2: Keyword scoring across all domain profiles
        domain_scores: Dict[str, float] = {}
        keyword_hits: Dict[str, List[str]] = {}

        for domain, profile in DOMAIN_PROFILES.items():
            score, hits = self._score_keywords(text_lower, profile["keywords"])
            # Boost if filename hints at domain (non-hardcoded — uses profile keywords)
            fname_bonus = sum(
                0.1 for kw in profile["keywords"][:10]
                if kw.replace(" ", "_") in fname_lower or kw.split()[0] in fname_lower
            )
            domain_scores[domain] = score + fname_bonus + entity_counts.get(domain, 0) * 0.05
            keyword_hits[domain] = hits

        # Step 3: Pick top domain
        best_domain = max(domain_scores, key=lambda d: domain_scores[d]) if domain_scores else "general"
        best_score = domain_scores.get(best_domain, 0.0)

        # Fallback to general if score is too low
        if best_score < 0.02:
            best_domain = "general"
            confidence = 0.0
        else:
            confidence = min(best_score * 10, 1.0)

        # Step 4: Infer doc_type within best domain
        doc_type = self._infer_doc_type(
            text_lower, fname_lower,
            DOMAIN_PROFILES.get(best_domain, {}).get("doc_types", {}),
        )

        # Step 5: Sensitivity
        sensitivity = self._infer_sensitivity(
            text_lower,
            DOMAIN_PROFILES.get(best_domain, {}).get("sensitivity_boost", 0.0),
        )

        return {
            "domain": best_domain,
            "doc_type": doc_type,
            "sensitivity": sensitivity,
            "keywords_found": keyword_hits.get(best_domain, [])[:10],
            "entity_counts": entity_counts,
            "confidence": round(confidence, 2),
            "classification_source": "keyword",
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _score_keywords(text_lower: str, keywords: List[str]):
        """
        TF-like scoring: count occurrences of each keyword, normalize by text length.
        Returns (score, list_of_matched_keywords).
        """
        word_count = max(len(text_lower.split()), 1)
        total_hits = 0
        matched: List[str] = []
        for kw in keywords:
            count = text_lower.count(kw)
            if count > 0:
                total_hits += count
                matched.append(kw)
        score = total_hits / word_count
        return score, matched

    @staticmethod
    def _infer_doc_type(text_lower: str, fname_lower: str, doc_types: Dict) -> str:
        """
        Match text and filename against doc_type patterns within the domain.
        Returns the best match or 'document'.
        """
        best = "document"
        best_count = 0
        for dtype, signals in doc_types.items():
            count = sum(
                text_lower.count(s) + (2 if s in fname_lower else 0)
                for s in signals
            )
            if count > best_count:
                best_count = count
                best = dtype
        return best

    @staticmethod
    def _infer_sensitivity(text_lower: str, domain_boost: float) -> str:
        """
        Check for sensitivity signal words to classify as high/medium/low.
        domain_boost raises baseline sensitivity for naturally sensitive domains.
        """
        high_score = sum(
            text_lower.count(w) for w in SENSITIVITY_SIGNALS["high"]
        )
        medium_score = sum(
            text_lower.count(w) for w in SENSITIVITY_SIGNALS["medium"]
        )

        # Weighted decision
        if high_score > 0 or domain_boost >= 0.4:
            return "high"
        if medium_score > 0 or domain_boost >= 0.2:
            return "medium"
        return "low"

    @staticmethod
    def _count_entities(text: str) -> Dict[str, int]:
        """
        Rough regex-based entity counting to boost domain scores.
        These are domain-agnostic signals, not hardcoded rules.
        """
        return {
            "legal": len(re.findall(
                r"\b(?:contract|agreement|clause|section|article|amendment)\b",
                text, re.IGNORECASE,
            )),
            "finance": len(re.findall(
                r"\$[\d,]+|(?:USD|EUR|GBP)\s*[\d,]+|\d+%\s*(?:tax|interest|rate)",
                text, re.IGNORECASE,
            )),
            "hr": len(re.findall(
                r"\b(?:employee|salary|leave|appraisal|recruitment)\b",
                text, re.IGNORECASE,
            )),
            "medical": len(re.findall(
                r"\b(?:patient|diagnosis|medication|prescription|clinical)\b",
                text, re.IGNORECASE,
            )),
            "technical": len(re.findall(
                r"\b(?:api|function|class|database|server|endpoint)\b",
                text, re.IGNORECASE,
            )),
            "operations": len(re.findall(
                r"\b(?:vendor|procurement|shipment|logistics|inventory)\b",
                text, re.IGNORECASE,
            )),
        }

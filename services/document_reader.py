"""
DocumentReader — reads specific lines or full content from uploaded documents
without going through vector retrieval.

SOLID:
  - Single Responsibility: only reads files, never embeds or retrieves.
  - Open/Closed: extend pattern lists to support new query formats.
  - Dependency-inverted: callers inject the upload directory path.

Supports queries like:
  "show line 5 of contracts_2024.pdf"
  "what is on line 10 from HR_Policy.docx"
  "display the full content of sample.txt"
  "show me everything in report.pdf"
  "line 3 in algonquin 2104"
  "give me line number 7 from the gas document"
"""

import logging
import re
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploaded_docs")

# ── Line number patterns (ordered by specificity) ─────────────────────────────
LINE_NUMBER_PATTERNS = [
    re.compile(r"\blines?\s+(?:number\s+)?#?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+lines?\b", re.IGNORECASE),
    re.compile(r"\blines?\s*[:\-]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bat\s+lines?\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\blines?\s+(\d+)\s+(?:in|of|from)\b", re.IGNORECASE),
    re.compile(r"\bon\s+lines?\s+(\d+)\b", re.IGNORECASE),
]

# Full document patterns
FULL_DOC_PATTERNS = re.compile(
    r"\b(?:full|complete|entire|whole|all\s+(?:lines|content|text)|"
    r"everything\s+in|show\s+(?:me\s+)?(?:all|everything)|"
    r"display\s+(?:all|the\s+full|the\s+entire|the\s+whole)|"
    r"contents?\s+of|read\s+(?:the\s+)?(?:whole|entire|full))\b",
    re.IGNORECASE,
)

# Broad document-read intent — deliberately wide, covers all natural verbs
DOC_READ_INTENT = re.compile(
    r"\b(?:lines?|show|display|read|print|give|fetch|get|retrieve|extract|pull|"
    r"return|bring|find|tell|what\s+is\s+(?:in|on|there)|"
    r"what\s+does.*say|contents?\s+of|open|view|see|access|look\s+at)\b",
    re.IGNORECASE,
)

# Word-number mappings for spelled-out ordinals
WORD_NUMBERS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12,
}


class DocumentReadRequest:
    def __init__(
        self,
        is_doc_read: bool = False,
        filename: Optional[str] = None,
        line_number: Optional[int] = None,
        is_full_doc: bool = False,
        line_range: Optional[Tuple[int, int]] = None,
    ):
        self.is_doc_read = is_doc_read
        self.filename = filename
        self.line_number = line_number
        self.is_full_doc = is_full_doc
        self.line_range = line_range

    def __repr__(self):
        return (
            f"DocReadRequest(file={self.filename}, line={self.line_number}, "
            f"full={self.is_full_doc}, range={self.line_range})"
        )


class DocumentReader:
    """
    Reads specific lines or full content from uploaded documents.
    Resolves filenames via word-overlap fuzzy matching.
    """

    def __init__(self, upload_dir: Path = UPLOAD_DIR):
        self.upload_dir = upload_dir

    # ── Public API ────────────────────────────────────────────────────────────

    def parse_query(self, query: str) -> DocumentReadRequest:
        """
        Parse a natural-language query into a DocumentReadRequest.
        Strategy:
          1. Check for document-read intent (broad)
          2. Extract line number (if any)
          3. Find filename via fuzzy word-overlap matching
          4. If line number found but no file → offer available files list
          5. If full-doc keywords found → set is_full_doc
        """
        # Broad intent check
        has_intent = bool(DOC_READ_INTENT.search(query))
        line_number = self._extract_line_number(query)
        line_range = self._extract_line_range(query)
        is_full = bool(FULL_DOC_PATTERNS.search(query)) and line_number is None and line_range is None

        # If no intent and no line number, not a doc-read query
        if not has_intent and line_number is None and line_range is None and not is_full:
            return DocumentReadRequest(is_doc_read=False)

        # Try to find the filename
        filename, score = self._find_filename_in_query(query)

        # If we have a line number but no file found, still signal doc-read
        # so the orchestrator can respond with available files
        if filename is None and (line_number or line_range or is_full):
            if has_intent:
                return DocumentReadRequest(
                    is_doc_read=True,
                    filename=None,   # caller will handle missing file
                    line_number=line_number,
                    is_full_doc=is_full,
                    line_range=line_range,
                )
            return DocumentReadRequest(is_doc_read=False)

        if filename is None:
            return DocumentReadRequest(is_doc_read=False)

        return DocumentReadRequest(
            is_doc_read=True,
            filename=filename,
            line_number=line_number,
            is_full_doc=is_full,
            line_range=line_range,
        )

    def read(self, req: DocumentReadRequest) -> str:
        """Execute a DocumentReadRequest, return verbatim text. Never raises."""
        if not req.is_doc_read:
            return "Invalid document read request."

        # No filename — list what's available
        if req.filename is None:
            available = self._list_available_files()
            if not available:
                return "No documents have been uploaded yet."
            listing = "\n".join(f"  • {f}" for f in available)
            hint = ""
            if req.line_number:
                hint = f"Please specify which document you want line {req.line_number} from.\n\n"
            return (
                f"{hint}Available uploaded documents:\n{listing}\n\n"
                "Example: \"show me line 5 of [filename]\""
            )

        file_path = self._resolve_file(req.filename)
        if file_path is None:
            available = self._list_available_files()
            avail_str = "\n".join(f"  • {f}" for f in available[:15]) or "  (none)"
            return (
                f"Document '{req.filename}' not found in uploaded documents.\n\n"
                f"Available files:\n{avail_str}"
            )

        try:
            lines = self._extract_lines(file_path)
        except Exception as e:
            logger.error(f"[DocumentReader] Failed to read {file_path}: {e}")
            return f"Could not read '{req.filename}': {str(e)}"

        if not lines:
            return f"Document '{req.filename}' appears to be empty or could not be parsed."

        # Full document
        if req.is_full_doc:
            numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))
            return (
                f"Full content of '{req.filename}' ({len(lines)} lines):\n\n"
                f"{numbered}"
            )

        # Line range
        if req.line_range:
            start, end = req.line_range
            start = max(1, start)
            end = min(len(lines), end)
            excerpt = lines[start - 1:end]
            numbered = "\n".join(f"{start + i}: {line}" for i, line in enumerate(excerpt))
            return f"Lines {start}–{end} of '{req.filename}':\n\n{numbered}"

        # Specific line
        if req.line_number is not None:
            idx = req.line_number - 1
            if idx < 0 or idx >= len(lines):
                return (
                    f"Line {req.line_number} does not exist in '{req.filename}'. "
                    f"The document has {len(lines)} lines."
                )
            exact = lines[idx]
            return (
                f"Line {req.line_number} of '{req.filename}':\n\n"
                f"{req.line_number}: {exact}"
            )

        # Default: 20-line preview
        preview = lines[:20]
        numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(preview))
        suffix = f"\n\n... ({len(lines) - 20} more lines — ask for 'full document' to see all)" if len(lines) > 20 else ""
        return f"Preview of '{req.filename}':\n\n{numbered}{suffix}"

    def list_files(self) -> List[str]:
        return self._list_available_files()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_filename_in_query(self, query: str) -> Tuple[Optional[str], float]:
        """
        Word-overlap fuzzy matching: score each uploaded file by how many of its
        stem words appear in the query. Returns (best_match, score) or (None, 0).
        """
        available = self._list_available_files()
        if not available:
            return None, 0.0

        q_lower = query.lower()
        # Tokenize query
        q_words = set(re.split(r"[\s_\-\./\\]+", q_lower))
        q_words = {w for w in q_words if len(w) >= 3}  # ≥3 chars

        best_fname: Optional[str] = None
        best_score: float = 0.0

        for fname in available:
            stem = Path(fname).stem.lower()

            # Exact stem or full name match → highest priority
            if stem in q_lower or fname.lower() in q_lower:
                return fname, 1.0

            # Word overlap scoring
            stem_words = set(re.split(r"[\s_\-\./\\]+", stem))
            stem_words = {w for w in stem_words if len(w) >= 3}
            if not stem_words:
                continue

            overlap = q_words & stem_words
            score = len(overlap) / len(stem_words)  # fraction of stem words matched

            if score > best_score:
                best_score = score
                best_fname = fname

        # Require at least 1 word match (score > 0) to confirm a file
        if best_score > 0:
            return best_fname, best_score
        return None, 0.0

    def _resolve_file(self, filename: str) -> Optional[Path]:
        p = self.upload_dir / filename
        if p.exists():
            return p
        try:
            for f in self.upload_dir.iterdir():
                if f.name.lower() == filename.lower():
                    return f
        except Exception:
            pass
        return None

    def _list_available_files(self) -> List[str]:
        try:
            return sorted(
                f.name for f in self.upload_dir.iterdir()
                if f.is_file() and not f.name.startswith(".")
            )
        except Exception:
            return []

    def _extract_lines(self, file_path: Path) -> List[str]:
        """Extract text lines. Uses raw read for text formats, pipeline for binary."""
        suffix = file_path.suffix.lower()

        if suffix in {".txt", ".md", ".csv", ".json", ".xml", ".html"}:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            return raw.splitlines()

        try:
            from services.phase1_pipeline import Phase1Pipeline
            pipeline = Phase1Pipeline(folder_path=str(file_path.parent))
            text = pipeline.extract_text(str(file_path))
            if text:
                return text.splitlines()
        except Exception as e:
            logger.warning(f"[DocumentReader] Pipeline extraction failed: {e}")

        try:
            return file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []

    @staticmethod
    def _extract_line_number(query: str) -> Optional[int]:
        """Extract line number from digit or ordinal-word form."""
        for pat in LINE_NUMBER_PATTERNS:
            m = pat.search(query)
            if m:
                try:
                    return int(m.group(1))
                except (ValueError, IndexError):
                    pass
        # Spelled-out ordinals: "the fifth line"
        q_lower = query.lower()
        for word, num in WORD_NUMBERS.items():
            if re.search(rf"\b{word}\s+lines?\b", q_lower):
                return num
        return None

    @staticmethod
    def _extract_line_range(query: str) -> Optional[Tuple[int, int]]:
        m = re.search(
            r"\blines?\s+(\d+)\s*(?:to|through|–|-|till|until)\s*(\d+)\b",
            query, re.IGNORECASE,
        )
        if m:
            return int(m.group(1)), int(m.group(2))
        return None


# ── Singleton ─────────────────────────────────────────────────────────────────
_reader: Optional[DocumentReader] = None


def get_document_reader() -> DocumentReader:
    global _reader
    if _reader is None:
        _reader = DocumentReader()
    return _reader

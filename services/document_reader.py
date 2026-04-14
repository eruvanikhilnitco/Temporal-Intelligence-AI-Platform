"""
DocumentReader — reads specific lines or full content from uploaded documents
without going through vector retrieval.

Supports:
  - Local files in uploaded_docs/
  - SharePoint / Qdrant-only files (reconstructed from stored chunks)

Query examples:
  "show line 5 of contracts_2024.pdf"
  "what is on line 10 from HR_Policy.docx"
  "give me line 4 of HR Policy Manual-v2.1 as it is"
  "display the full content of sample.txt"
  "show me everything in report.pdf"
"""

import logging
import re
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploaded_docs")

# ── Line number patterns ───────────────────────────────────────────────────────
LINE_NUMBER_PATTERNS = [
    re.compile(r"\blines?\s+(?:number\s+)?#?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+lines?\b", re.IGNORECASE),
    re.compile(r"\blines?\s*[:\-]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bat\s+lines?\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\blines?\s+(\d+)\s+(?:in|of|from)\b", re.IGNORECASE),
    re.compile(r"\bon\s+lines?\s+(\d+)\b", re.IGNORECASE),
]

FULL_DOC_PATTERNS = re.compile(
    r"\b(?:full|complete|entire|whole|all\s+(?:lines|content|text)|"
    r"everything\s+in|show\s+(?:me\s+)?(?:all|everything)|"
    r"display\s+(?:all|the\s+full|the\s+entire|the\s+whole)|"
    r"contents?\s+of|read\s+(?:the\s+)?(?:whole|entire|full))\b",
    re.IGNORECASE,
)

DOC_READ_INTENT = re.compile(
    r"\b(?:lines?|show|display|read|print|give|fetch|get|retrieve|extract|pull|"
    r"return|bring|find|tell|what\s+is\s+(?:in|on|there)|"
    r"what\s+does.*say|contents?\s+of|open|view|see|access|look\s+at)\b",
    re.IGNORECASE,
)

WORD_NUMBERS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12,
}

# Minimum fraction of stem words that must match to accept a filename
_MIN_SCORE = 0.4


class DocumentReadRequest:
    def __init__(
        self,
        is_doc_read: bool = True,
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
    Reads exact lines or full content from documents.
    Searches both the local upload directory and Qdrant (for SharePoint-ingested files).
    """

    def __init__(self, upload_dir: Path = UPLOAD_DIR):
        self.upload_dir = upload_dir
        self._qdrant_file_cache: List[str] = []
        self._qdrant_cache_ts: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def parse_query(self, query: str) -> DocumentReadRequest:
        """
        Parse a natural-language query into a DocumentReadRequest.
        Steps:
          1. Check for read intent keywords
          2. Extract line number or range
          3. Check for full-doc flag
          4. Find filename via exact then fuzzy matching
        """
        has_intent = bool(DOC_READ_INTENT.search(query))
        line_number = self._extract_line_number(query)
        line_range = self._extract_line_range(query) if line_number is None else None
        is_full = bool(FULL_DOC_PATTERNS.search(query)) and line_number is None and line_range is None

        if not has_intent and line_number is None and line_range is None and not is_full:
            return DocumentReadRequest(is_doc_read=False)

        filename, score = self._find_filename_in_query(query)

        if filename is None and (line_number or line_range or is_full):
            # We know it's a doc-read but can't identify which file
            available = self._list_available_files()
            if not available:
                return DocumentReadRequest(is_doc_read=False)
            # Pick first (or only) file when there's exactly one
            if len(available) == 1:
                filename = available[0]
            else:
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
        """Execute a DocumentReadRequest; return verbatim text. Never raises."""
        if not req.is_doc_read:
            return ""

        # No filename — list what's available
        if req.filename is None:
            available = self._list_available_files()
            if not available:
                return "No documents have been uploaded yet."
            names = "\n".join(f"  • {f}" for f in available)
            return (
                f"The following documents are available ({len(available)} files):\n\n"
                f"{names}\n\n"
                "Example: \"show me line 5 of [filename]\""
            )

        lines = self._get_lines(req.filename)
        if lines is None:
            available = self._list_available_files()
            names = "\n".join(f"  • {f}" for f in available[:10])
            return (
                f"Document '{req.filename}' not found in uploaded documents.\n\n"
                f"Available files:\n{names}"
            )
        if not lines:
            return f"Document '{req.filename}' appears to be empty or could not be parsed."

        if req.is_full_doc:
            numbered = "\n".join(f"{i+1}: {l}" for i, l in enumerate(lines))
            return (
                f"Full content of '{req.filename}' ({len(lines)} lines):\n\n"
                f"{numbered}"
            )

        if req.line_range:
            start, end = req.line_range
            start = max(1, start)
            end = min(len(lines), end)
            segment = lines[start - 1 : end]
            numbered = "\n".join(f"{i}: {l}" for i, l in zip(range(start, end + 1), segment))
            return f"Lines {start}–{end} of '{req.filename}':\n\n{numbered}"

        if req.line_number:
            if req.line_number > len(lines):
                return (
                    f"Line {req.line_number} does not exist in '{req.filename}'. "
                    f"The document has {len(lines)} lines."
                )
            line_text = lines[req.line_number - 1]
            return (
                f"Line {req.line_number} of '{req.filename}':\n\n"
                f"{line_text}"
            )

        # Preview (first 20 lines)
        preview = lines[:20]
        numbered = "\n".join(f"{i+1}: {l}" for i, l in enumerate(preview))
        suffix = f"\n\n… ({len(lines) - 20} more lines)" if len(lines) > 20 else ""
        return f"Preview of '{req.filename}':\n\n{numbered}{suffix}"

    def list_files(self) -> List[str]:
        return self._list_available_files()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_filename_in_query(self, query: str) -> Tuple[Optional[str], float]:
        """
        Match a document name from the query.
        Priority: exact substring match → high-overlap word match.
        Minimum overlap score: _MIN_SCORE (prevents single-word false positives).
        Also searches Qdrant file names (for SharePoint-ingested docs).
        """
        available = self._list_available_files()
        if not available:
            return None, 0.0

        q_lower = query.lower()
        q_words = set(re.split(r"[\s_\-\./\\]+", q_lower))
        q_words = {w for w in q_words if len(w) >= 3}

        best_fname: Optional[str] = None
        best_score: float = 0.0

        for fname in available:
            stem = Path(fname).stem.lower()

            # Exact substring match on stem or full name → highest priority
            if stem in q_lower or fname.lower() in q_lower:
                return fname, 1.0

            # Word overlap scoring
            stem_words = set(re.split(r"[\s_\-\./\\]+", stem))
            stem_words = {w for w in stem_words if len(w) >= 3}
            if not stem_words:
                continue

            overlap = q_words & stem_words
            # Score = (matched words) / (total stem words)
            # Require at least 2 matching words OR all stem words match
            score = len(overlap) / len(stem_words)

            # Reject single-word matches unless stem is a single word
            if len(overlap) < 2 and len(stem_words) > 1:
                score = 0.0

            if score >= _MIN_SCORE and score > best_score:
                best_score = score
                best_fname = fname

        if best_fname and best_score >= _MIN_SCORE:
            return best_fname, best_score
        return None, 0.0

    def _get_lines(self, filename: str) -> Optional[List[str]]:
        """
        Get text lines for a document. Tries local file first, then Qdrant.
        Returns None if file not found anywhere.
        """
        # Try local file
        file_path = self._resolve_local_file(filename)
        if file_path is not None:
            try:
                lines = self._extract_lines(file_path)
                if lines is not None:
                    return lines
            except Exception as e:
                logger.warning(f"[DocumentReader] Local read failed for '{filename}': {e}")

        # Try Qdrant chunks (SharePoint-ingested files or any file ingested via pipeline)
        qdrant_text = self._read_from_qdrant(filename)
        if qdrant_text is not None:
            return qdrant_text.splitlines()

        return None

    def _resolve_local_file(self, filename: str) -> Optional[Path]:
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
        """
        Returns all known files: local upload_dir files UNION Qdrant-indexed files.
        """
        local: List[str] = []
        try:
            local = sorted(
                f.name for f in self.upload_dir.iterdir()
                if f.is_file() and not f.name.startswith(".")
            )
        except Exception:
            pass

        qdrant_files = self._get_qdrant_filenames()

        # Merge, preserving order (local first, then Qdrant-only files)
        local_set = {f.lower() for f in local}
        combined = list(local)
        for qf in qdrant_files:
            if qf.lower() not in local_set:
                combined.append(qf)

        return combined

    def _get_qdrant_filenames(self) -> List[str]:
        """
        Get unique file_name values from Qdrant phase1_documents collection.
        Cached for 60 seconds to avoid hammering Qdrant.
        """
        import time
        now = time.time()
        if self._qdrant_file_cache and (now - self._qdrant_cache_ts) < 60:
            return self._qdrant_file_cache
        try:
            from core.config import get_settings
            from qdrant_client import QdrantClient
            settings = get_settings()
            client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
            # Use scroll to collect all unique file names
            filenames: set = set()
            offset = None
            while True:
                pts, next_off = client.scroll(
                    collection_name="phase1_documents",
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in pts:
                    fn = p.payload.get("file_name", "")
                    if fn:
                        filenames.add(fn)
                if next_off is None or not pts:
                    break
                offset = next_off
            self._qdrant_file_cache = sorted(filenames)
            self._qdrant_cache_ts = now
            return self._qdrant_file_cache
        except Exception as e:
            logger.warning(f"[DocumentReader] Qdrant filename fetch failed: {e}")
            return []

    def _read_from_qdrant(self, filename: str) -> Optional[str]:
        """
        Reconstruct document text from Qdrant chunks ordered by chunk_id / char_start.
        Returns the assembled text, or None if the file is not in Qdrant.
        """
        try:
            from core.config import get_settings
            from qdrant_client import QdrantClient
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            settings = get_settings()
            client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

            # Scroll all chunks for this file
            all_chunks = []
            offset = None
            while True:
                pts, next_off = client.scroll(
                    collection_name="phase1_documents",
                    scroll_filter=Filter(
                        must=[FieldCondition(key="file_name", match=MatchValue(value=filename))]
                    ),
                    limit=500,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                all_chunks.extend(pts)
                if next_off is None or not pts:
                    break
                offset = next_off

            if not all_chunks:
                # Try case-insensitive match
                all_pts, _ = client.scroll(
                    collection_name="phase1_documents",
                    limit=1000,
                    with_payload=True,
                    with_vectors=False,
                )
                all_chunks = [p for p in all_pts
                              if p.payload.get("file_name", "").lower() == filename.lower()]

            if not all_chunks:
                return None

            # Sort chunks by chunk_id or char_start for correct document order
            def sort_key(p):
                chunk_id = p.payload.get("chunk_id", 0)
                char_start = p.payload.get("char_start", 0)
                try:
                    return (int(chunk_id), int(char_start))
                except Exception:
                    return (0, 0)

            all_chunks.sort(key=sort_key)

            # Assemble text — join chunks with newline separator
            texts = [p.payload.get("text", "").strip() for p in all_chunks if p.payload.get("text")]
            if not texts:
                return None

            return "\n".join(texts)

        except Exception as e:
            logger.warning(f"[DocumentReader] Qdrant read failed for '{filename}': {e}")
            return None

    def _extract_lines(self, file_path: Path) -> List[str]:
        """Extract text lines from a local file."""
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

import logging
import os
import uuid
from typing import List, Dict, Optional

from services.document_parser import DocumentParser

logger = logging.getLogger(__name__)

# Lazy-load tokenizer once per process to avoid repeated disk reads
_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        try:
            from transformers import AutoTokenizer
            from core.config import get_settings
            settings = get_settings()
            _tokenizer = AutoTokenizer.from_pretrained(settings.embedding_model)
            logger.info("[Chunker] Tokenizer loaded: %s", settings.embedding_model)
        except Exception as e:
            logger.warning("[Chunker] Tokenizer load failed (%s) — using character fallback", e)
            _tokenizer = None
    return _tokenizer


class Phase1Pipeline:
    def __init__(self, folder_path: str):
        self.folder_path = folder_path
        self.parser = DocumentParser()

    # ✅ Handles both folder and single file
    def load_files(self) -> List[str]:
        if os.path.isfile(self.folder_path):
            return [self.folder_path]

        if not os.path.isdir(self.folder_path):
            raise ValueError(f"Invalid path: {self.folder_path}")

        files = []
        for file in os.listdir(self.folder_path):
            full_path = os.path.join(self.folder_path, file)
            if os.path.isfile(full_path):
                files.append(full_path)

        return files

    # ✅ Extract text
    def extract_text(self, file_path: str) -> str:
        try:
            result = self.parser.parse(file_path)

            if isinstance(result, dict):
                text = result.get("content") or result.get("text") or ""
            else:
                text = str(result)

            if not text.strip():
                print(f"[WARNING] Empty document: {file_path}")
                return None

            return text

        except Exception as e:
            print(f"[ERROR] Failed to parse {file_path}: {e}")
            return None

    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
        """Return plain chunk strings (backward-compatible). Internally uses token chunker."""
        return [c["text"] for c in self.chunk_text_with_metadata(text, chunk_size, overlap)]

    def chunk_text_with_metadata(
        self,
        text: str,
        chunk_size: int = None,
        overlap: int = None,
    ) -> List[Dict]:
        """
        Token-aware chunker. Returns list of dicts:
          {text, chunk_id, token_count, char_start, char_end, line_start, line_end}

        Uses bge-large-en-v1.5 tokenizer so chunk boundaries match exactly what
        the embedding model sees. Falls back to character-based splitting if the
        tokenizer is unavailable.

        chunk_size:  target token count per chunk (default: settings.chunk_token_size = 450)
        overlap:     overlap in tokens between consecutive chunks (default: 64)
        """
        from core.config import get_settings
        settings = get_settings()
        chunk_size = chunk_size or settings.chunk_token_size
        overlap = overlap or settings.chunk_token_overlap

        if not text or not text.strip():
            return []

        # Guard: files > 400k chars (~100k tokens) will OOM the tokenizer in one shot.
        # Use character-based chunking for those — it's lossless, just no token alignment.
        MAX_CHARS_FOR_TOKENIZER = 400_000
        if len(text) > MAX_CHARS_FOR_TOKENIZER:
            logger.warning(
                "[Chunker] Text too large for tokenizer (%d chars) — using char fallback",
                len(text),
            )
            char_size = chunk_size * 4
            char_overlap = overlap * 4
            return self._char_chunks(text, char_size, char_overlap)

        tokenizer = _get_tokenizer()
        if tokenizer is not None:
            return self._token_chunks(text, tokenizer, chunk_size, overlap)
        # Fallback: character-based (approx 4 chars/token)
        char_size = chunk_size * 4
        char_overlap = overlap * 4
        return self._char_chunks(text, char_size, char_overlap)

    # ── Token-based chunker ────────────────────────────────────────────────────

    def _token_chunks(self, text: str, tokenizer, chunk_size: int, overlap: int) -> List[Dict]:
        """Split text into overlapping token-aligned chunks with line/char metadata."""
        try:
            enc = tokenizer(
                text,
                add_special_tokens=False,
                return_offsets_mapping=True,
                truncation=False,
            )
        except Exception as e:
            logger.warning("[Chunker] Tokeniser encode failed (%s), using char fallback", e)
            return self._char_chunks(text, chunk_size * 4, overlap * 4)

        token_ids: List[int] = enc["input_ids"]
        offsets: List[tuple] = enc["offset_mapping"]  # (char_start, char_end) per token

        if not token_ids:
            return []

        chunks: List[Dict] = []
        start = 0
        total = len(token_ids)

        while start < total:
            end = min(start + chunk_size, total)

            # Char boundaries
            char_start = offsets[start][0] if offsets[start] else 0
            char_end = offsets[end - 1][1] if offsets[end - 1] else len(text)

            chunk_text = text[char_start:char_end].strip()
            if chunk_text:
                line_start = text[:char_start].count("\n") + 1
                line_end = text[:char_end].count("\n") + 1
                chunks.append({
                    "text": chunk_text,
                    "chunk_id": str(uuid.uuid4()),
                    "token_count": end - start,
                    "char_start": char_start,
                    "char_end": char_end,
                    "line_start": line_start,
                    "line_end": line_end,
                })

            start += chunk_size - overlap

        return chunks

    # ── Character fallback chunker ─────────────────────────────────────────────

    def _char_chunks(self, text: str, chunk_size: int, overlap: int) -> List[Dict]:
        """Character-based fallback when tokeniser is unavailable."""
        chunks: List[Dict] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                line_start = text[:start].count("\n") + 1
                line_end = text[:end].count("\n") + 1
                chunks.append({
                    "text": chunk_text,
                    "chunk_id": str(uuid.uuid4()),
                    "token_count": None,
                    "char_start": start,
                    "char_end": end,
                    "line_start": line_start,
                    "line_end": line_end,
                })
            start += chunk_size - overlap
        return chunks

    # ── Pipeline run ───────────────────────────────────────────────────────────
    def run(self) -> List[Dict]:
        all_chunks = []

        files = self.load_files()
        print(f"[INFO] Found {len(files)} files")

        for file in files:
            print(f"[INFO] Processing: {file}")

            text = self.extract_text(file)

            if not text:
                continue

            chunk_metas = self.chunk_text_with_metadata(text)
            print(f"[INFO] Generated {len(chunk_metas)} chunks")

            roles = self._infer_access_roles(file, text)
            fname = os.path.basename(file)

            for meta in chunk_metas:
                all_chunks.append({
                    **meta,
                    "file_name": fname,
                    "access_roles": roles,
                })

        print(f"[INFO] Total chunks created: {len(all_chunks)}")

        return all_chunks

    # RBAC — default is admin-only. Admin explicitly grants broader access via API.
    def _infer_access_roles(self, file_path: str, text: str) -> List[str]:
        """
        Default: every uploaded document starts as admin-only.
        Admin can widen access per document via PUT /admin/document/access.

        Only auto-promote if the document explicitly signals public/open intent
        (e.g., a public FAQ or press release). This avoids accidental data leakage.
        """
        text_lower = text.lower()

        # Explicitly public / open documents (opt-in only)
        PUBLIC_SIGNALS = ["public release", "press release", "for immediate release",
                          "open source", "publicly available"]
        if any(sig in text_lower for sig in PUBLIC_SIGNALS):
            return ["public", "user", "admin"]

        # Default: admin-only. Secure by default.
        return ["admin"]
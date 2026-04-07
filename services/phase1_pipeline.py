import os
from typing import List, Dict
from services.document_parser import DocumentParser


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

    # ✅ Chunking
    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += chunk_size - overlap

        return chunks

    # 🔥 UPDATED: return chunk + dynamic metadata
    def run(self) -> List[Dict]:
        all_chunks = []

        files = self.load_files()
        print(f"[INFO] Found {len(files)} files")

        for file in files:
            print(f"[INFO] Processing: {file}")

            text = self.extract_text(file)

            if not text:
                continue

            chunks = self.chunk_text(text)
            print(f"[INFO] Generated {len(chunks)} chunks")

            # 🔥 Dynamic RBAC per document
            roles = self._infer_access_roles(file, text)

            for chunk in chunks:
                all_chunks.append({
                    "text": chunk,
                    "file_name": os.path.basename(file),
                    "access_roles": roles
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
from services.phase1_pipeline import Phase1Pipeline
from services.embedding_service import EmbeddingService
from services.phase1_llm import LLMService

# Phase 2 components
from services.query_classifier import QueryClassifier
from services.reranker import Reranker
from services.multihop import MultiHopRetriever
from services.cache_service import CacheService

# Phase 3 components
from services.graph_rag import GraphRAG

from core.database import get_qdrant_connection

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
import uuid


class Phase1RAG:
    def __init__(self, folder_path: str):
        self.pipeline = Phase1Pipeline(folder_path)
        self.embedder = EmbeddingService()
        self.llm = LLMService()

        # Phase 2 components
        self.classifier = QueryClassifier()
        self.reranker = Reranker()
        self.multihop = MultiHopRetriever()
        self.cache = CacheService()

        # Phase 3 components
        self.graph_rag = GraphRAG()

        qdrant_config = get_qdrant_connection()

        self.client = QdrantClient(
            host=qdrant_config.host,
            port=qdrant_config.port
        )

        self.collection_name = "phase1_documents"

        # 🔥 FIX: only create if not exists
        self._ensure_collection()

    # ✅ NEW FUNCTION (IMPORTANT)
    def _collection_exists(self):
        collections = self.client.get_collections().collections
        return any(c.name == self.collection_name for c in collections)

    # ✅ SAFE CREATION — auto-detects model/collection dimension mismatch and recreates
    def _ensure_collection(self):
        target_dim = self.embedder.dimensions

        if self._collection_exists():
            try:
                info = self.client.get_collection(self.collection_name)
                existing_dim = info.config.params.vectors.size
                if existing_dim == target_dim:
                    print(f"[INFO] Using existing collection: {self.collection_name} (dim={target_dim})")
                    return
                else:
                    print(
                        f"[WARN] Embedding model dimension changed: existing={existing_dim}, "
                        f"model={target_dim}. Recreating collection (re-ingest documents)."
                    )
                    self.client.delete_collection(self.collection_name)
            except Exception as e:
                print(f"[WARN] Could not inspect collection ({e}), proceeding with creation.")

        print(f"[INFO] Creating collection: {self.collection_name} (dim={target_dim})")
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=target_dim,
                distance=Distance.COSINE,
            ),
        )

    # 🔥 INGEST (RUN MANUALLY ONLY)
    def ingest(self):
        items = self.pipeline.run()

        print("[INFO] Creating embeddings...")

        points = []

        for item in items:
            chunk = item["text"]

            if not chunk or not chunk.strip():
                continue

            vector = self.embedder.embed(chunk)

            payload = {
                "text": chunk,
                "file_name": item["file_name"],
                "access_roles": item["access_roles"]
            }

            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=payload
                )
            )

        if points:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )

        print(f"[INFO] Stored {len(points)} vectors in Qdrant")

        # Phase 3: extract entities and build graph for each document
        print("[INFO] Phase 3: building knowledge graph...")
        doc_texts: dict = {}
        for item in items:
            fname = item["file_name"]
            doc_texts.setdefault(fname, [])
            doc_texts[fname].append(item["text"])

        for fname, chunks in doc_texts.items():
            full_text = "\n".join(chunks)
            self.graph_rag.ingest_document(full_text, fname)

        print(f"[INFO] Phase 3: graph ingestion complete for {len(doc_texts)} document(s)")

    # 🔥 QUERY (RBAC) — returns plain text list (backward-compatible)
    def query(self, question: str, user_role: str = "user", top_k: int = 10, tenant_id: str = None):
        return [c["text"] for c in self.query_with_sources(question, user_role, top_k, tenant_id=tenant_id)]

    # SOURCE-ANNOTATED QUERY — returns list of {text, file_name, score}
    def query_with_sources(self, question: str, user_role: str = "user", top_k: int = 10, tenant_id: str = None):
        query_vector = self.embedder.embed(question)

        # Admin sees ALL documents — no RBAC filter applied (unless scoped to a tenant).
        # Non-admin roles are filtered to their own access level only.
        # API key clients always see only their own tenant's documents.
        must_filters = []

        if user_role != "admin":
            must_filters.append({"key": "access_roles", "match": {"value": user_role}})

        # Multi-tenant isolation: API key clients only see their own documents
        if tenant_id:
            must_filters.append({"key": "tenant_id", "match": {"value": tenant_id}})

        query_filter = {"must": must_filters} if must_filters else None

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )

        return [
            {
                "text": r.payload.get("text", ""),
                "file_name": r.payload.get("file_name", "Unknown"),
                "score": getattr(r, "score", 0.8),
                "domain": r.payload.get("domain", "general"),
            }
            for r in results.points
            if r.payload.get("text", "").strip()
        ]

    # 🔥 FINAL (RBAC + CACHE + INTELLIGENCE)
    def ask(self, question: str, user_role: str = "user"):
        cache_key = f"{user_role}:{question}"

        # ⚡ CACHE
        if self.cache.exists(cache_key):
            print("⚡ Cache Hit")
            return self.cache.get(cache_key)

        # 🧠 CLASSIFY
        query_type = self.classifier.classify(question)

        # 🔥 MULTI-HOP + RERANK
        contexts = self.multihop.retrieve(
            question,
            lambda q: self.query(q, user_role),
            self.reranker
        )

        if not contexts:
            return "🚫 No accessible information for your role."

        # 🔗 Phase 3: hybrid context (vector + graph)
        context_text, graph_summary = self.graph_rag.retrieve(question, contexts)

        if graph_summary:
            print(f"[Phase 3] Graph context added ({len(graph_summary)} chars)")

        # optional behavior
        if query_type == "summary":
            question = "Summarize the document"

        # 💡 LLM
        answer = self.llm.generate_answer(question, context_text)

        # ⚡ STORE CACHE
        self.cache.set(cache_key, answer)

        return answer
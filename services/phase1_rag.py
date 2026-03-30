from services.phase1_pipeline import Phase1Pipeline
from services.embedding_service import EmbeddingService
from services.phase1_llm import LLMService

# 🔥 Phase 2 components
from services.query_classifier import QueryClassifier
from services.reranker import Reranker
from services.multihop import MultiHopRetriever
from services.cache_service import CacheService  # 🔥 NEW

from core.database import get_qdrant_connection

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
import uuid


class Phase1RAG:
    def __init__(self, folder_path: str):
        self.pipeline = Phase1Pipeline(folder_path)
        self.embedder = EmbeddingService()
        self.llm = LLMService()

        # 🔥 Phase 2 components
        self.classifier = QueryClassifier()
        self.reranker = Reranker()
        self.multihop = MultiHopRetriever()
        self.cache = CacheService()  # 🔥 NEW

        qdrant_config = get_qdrant_connection()

        self.client = QdrantClient(
            host=qdrant_config.host,
            port=qdrant_config.port
        )

        self.collection_name = "phase1_documents"

        # recreate collection
        self._recreate_collection()

    # ✅ Create collection
    def _recreate_collection(self):
        try:
            self.client.delete_collection(self.collection_name)
            print(f"[INFO] Deleted old collection: {self.collection_name}")
        except:
            pass

        print(f"[INFO] Creating collection: {self.collection_name}")

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=1024,
                distance=Distance.COSINE
            )
        )

    # ✅ Ingest
    def ingest(self):
        chunks = self.pipeline.run()

        print("[INFO] Creating embeddings...")

        points = []

        for chunk in chunks:
            if not chunk or not chunk.strip():
                continue

            vector = self.embedder.embed(chunk)

            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={"text": chunk}
                )
            )

        if points:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )

        print(f"[INFO] Stored {len(points)} vectors in Qdrant")

    # ✅ Retrieval
    def query(self, question: str, top_k: int = 10):
        query_vector = self.embedder.embed(question)

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k
        )

        return [r.payload["text"] for r in results.points]

    # 🔥 FINAL FUNCTION (WITH CACHING)
    def ask(self, question: str):
        # ⚡ STEP 0: CACHE CHECK
        if self.cache.exists(question):
            print("⚡ Cache Hit")
            return self.cache.get(question)

        # 🧠 Step 1: classify
        query_type = self.classifier.classify(question)

        # 🔥 Step 2: multi-hop + rerank
        contexts = self.multihop.retrieve(
            question,
            self.query,
            self.reranker
        )

        context_text = "\n\n".join(contexts)

        # optional behavior change
        if query_type == "summary":
            question = "Summarize the document"

        # 💡 Step 3: LLM
        answer = self.llm.generate_answer(question, context_text)

        # ⚡ STEP 4: STORE IN CACHE
        self.cache.set(question, answer)

        return answer
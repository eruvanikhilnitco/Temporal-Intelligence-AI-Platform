from services.phase1_pipeline import Phase1Pipeline
from services.embedding_service import EmbeddingService
from services.phase1_llm import LLMService  # ✅ NEW

from core.database import get_qdrant_connection

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
import uuid


class Phase1RAG:
    def __init__(self, folder_path: str):
        self.pipeline = Phase1Pipeline(folder_path)
        self.embedder = EmbeddingService()
        self.llm = LLMService()  # ✅ NEW

        qdrant_config = get_qdrant_connection()

        self.client = QdrantClient(
            host=qdrant_config.host,
            port=qdrant_config.port
        )

        self.collection_name = "phase1_documents"

        # recreate collection
        self._recreate_collection()

    # ✅ Create collection with correct dimension
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

    # ✅ Ingest pipeline
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
    def query(self, question: str, top_k: int = 5):
        query_vector = self.embedder.embed(question)

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k
        )

        contexts = [r.payload["text"] for r in results.points]

        return contexts

    # 🔥 NEW: FINAL AI ANSWER FUNCTION
    def ask(self, question: str):
        contexts = self.query(question)

        # combine context
        context_text = "\n\n".join(contexts)

        # generate answer using LLM
        answer = self.llm.generate_answer(question, context_text)

        return answer
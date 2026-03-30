import logging
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from core.config import get_settings
from core.database import get_qdrant_connection

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        settings = get_settings()
        self.model_name = settings.embedding_model
        
        # Initialize sentence transformer model
        try:
            self.model = SentenceTransformer(self.model_name)
            self.dimensions = self.model.get_sentence_embedding_dimension()
            logger.info(f"Loaded embedding model: {self.model_name} (dim={self.dimensions})")
        except Exception as e:
            logger.error(f"Failed to load embedding model {self.model_name}: {e}")
            raise

        # Initialize Qdrant client
        try:
            qdrant_config = get_qdrant_connection()
            self.qdrant = QdrantClient(host=qdrant_config.host, port=qdrant_config.port)
            self.collection_name = "documents"
            self._ensure_collection()
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            self.qdrant = None

    def _ensure_collection(self):
        """Ensure the Qdrant collection exists."""
        if not self.qdrant:
            return
        
        try:
            collections = self.qdrant.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if self.collection_name not in collection_names:
                self.qdrant.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.dimensions,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to ensure Qdrant collection: {e}")

    def embed(self, text: str) -> List[float]:
        """Generate embedding for text using sentence-transformers."""
        if not text or not text.strip():
            return [0.0] * self.dimensions
        
        try:
            # Truncate very long texts
            text = text[:10000] if len(text) > 10000 else text
            embedding = self.model.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return [0.0] * self.dimensions

    def store_embedding(self, document_id: str, embedding: List[float], metadata: dict) -> bool:
        """Store embedding in Qdrant."""
        if not self.qdrant:
            logger.warning("Qdrant not available, skipping embedding storage")
            return False
        
        try:
            point = PointStruct(
                id=hash(document_id) % (2**63),  # Qdrant requires int64 IDs
                vector=embedding,
                payload={
                    "document_id": document_id,
                    **metadata
                }
            )
            self.qdrant.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store embedding in Qdrant: {e}")
            return False

    def search_similar(self, query_text: str, limit: int = 10) -> List[dict]:
        """Search for similar documents using embeddings."""
        if not self.qdrant:
            return []
        
        try:
            query_embedding = self.embed(query_text)
            results = self.qdrant.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit
            )
            return [
                {
                    "document_id": hit.payload.get("document_id"),
                    "score": hit.score,
                    **hit.payload
                }
                for hit in results
            ]
        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []

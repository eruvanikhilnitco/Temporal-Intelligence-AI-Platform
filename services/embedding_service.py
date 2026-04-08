import logging
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from core.config import get_settings
from core.database import get_qdrant_connection

logger = logging.getLogger(__name__)


class EmbeddingService:
    # Process-level embedding cache: query text → vector
    # Shared across all instances so warm restarts reuse cached vectors.
    _EMBED_CACHE: Dict[str, List[float]] = {}
    _EMBED_CACHE_MAX = 5000  # increased from 2000 — reduces re-encode under load

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
        """Ensure the Qdrant collection exists with the correct vector dimension."""
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
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.collection_name} (dim={self.dimensions})")
            else:
                # Detect dimension mismatch and recreate if model was swapped
                try:
                    info = self.qdrant.get_collection(self.collection_name)
                    existing_dim = info.config.params.vectors.size
                    if existing_dim != self.dimensions:
                        logger.warning(
                            f"[EmbeddingService] Dimension mismatch on '{self.collection_name}': "
                            f"existing={existing_dim}, model={self.dimensions}. Recreating."
                        )
                        self.qdrant.delete_collection(self.collection_name)
                        self.qdrant.create_collection(
                            collection_name=self.collection_name,
                            vectors_config=VectorParams(
                                size=self.dimensions,
                                distance=Distance.COSINE,
                            ),
                        )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to ensure Qdrant collection: {e}")

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text using sentence-transformers.

        Results are cached in a process-level dict so repeated queries (e.g.
        sub-query decomposition, cache-miss retries) skip model inference.
        """
        if not text or not text.strip():
            return [0.0] * self.dimensions

        cache_key = text[:500]  # cap key length
        if cache_key in self._EMBED_CACHE:
            return self._EMBED_CACHE[cache_key]

        try:
            text = text[:10000] if len(text) > 10000 else text
            embedding = self.model.encode(
                text,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            result = embedding.tolist()
            # Store in cache (evict oldest entry if at limit)
            if len(self._EMBED_CACHE) >= self._EMBED_CACHE_MAX:
                try:
                    self._EMBED_CACHE.pop(next(iter(self._EMBED_CACHE)))
                except StopIteration:
                    pass
            self._EMBED_CACHE[cache_key] = result
            return result
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return [0.0] * self.dimensions

    def embed_batch(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """
        Batch embedding — encodes all texts in a single model.encode() call.
        10x faster than calling embed() in a loop for documents with many chunks.
        Falls back to sequential embed() if batch fails.
        """
        if not texts:
            return []
        # Truncate each text
        texts = [t[:10000] if len(t) > 10000 else t for t in texts]
        try:
            vectors = self.model.encode(
                texts,
                normalize_embeddings=True,
                batch_size=batch_size,
                show_progress_bar=False,
            )
            return [v.tolist() for v in vectors]
        except Exception as e:
            logger.warning(f"[EmbeddingService] Batch encode failed ({e}), using sequential")
            return [self.embed(t) for t in texts]

    def store_embedding(self, document_id: str, embedding: List[float], metadata: dict) -> bool:
        """Store a single embedding in Qdrant. Prefer store_embeddings_batch for multiple points."""
        if not self.qdrant:
            logger.warning("Qdrant not available, skipping embedding storage")
            return False

        try:
            point = PointStruct(
                id=hash(document_id) % (2**63),
                vector=embedding,
                payload={"document_id": document_id, **metadata}
            )
            self.qdrant.upsert(collection_name=self.collection_name, points=[point])
            return True
        except Exception as e:
            logger.error(f"Failed to store embedding in Qdrant: {e}")
            return False

    def store_embeddings_batch(
        self,
        items: List[dict],
        batch_size: int = 256,
    ) -> int:
        """
        Bulk upsert embeddings to Qdrant — drastically faster than one-by-one upserts.

        Each item must have: document_id (str), embedding (List[float]), metadata (dict).
        Sends points in batches of `batch_size` to respect Qdrant's request size limits.
        Returns the total number of points successfully upserted.
        """
        if not self.qdrant or not items:
            return 0

        points = [
            PointStruct(
                id=hash(item["document_id"]) % (2**63),
                vector=item["embedding"],
                payload={"document_id": item["document_id"], **item.get("metadata", {})},
            )
            for item in items
        ]

        stored = 0
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            try:
                self.qdrant.upsert(collection_name=self.collection_name, points=batch)
                stored += len(batch)
            except Exception as e:
                logger.error(f"[EmbeddingService] Batch upsert failed at offset {i}: {e}")
        logger.info(f"[EmbeddingService] Batch upserted {stored}/{len(points)} points")
        return stored

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

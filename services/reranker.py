from sentence_transformers import CrossEncoder


class Reranker:
    def __init__(self):
        self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def rerank(self, query: str, documents: list, top_k: int = 3):
        pairs = [(query, doc) for doc in documents]

        scores = self.model.predict(pairs)

        scored_docs = list(zip(documents, scores))

        # sort by score descending
        ranked = sorted(scored_docs, key=lambda x: x[1], reverse=True)

        return [doc for doc, score in ranked[:top_k]]
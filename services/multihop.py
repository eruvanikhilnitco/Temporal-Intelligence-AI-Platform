class MultiHopRetriever:
    def decompose(self, query: str):
        query = query.lower()

        # simple split for multi-part questions
        if " and " in query:
            return query.split(" and ")

        return [query]

    def retrieve(self, query: str, retriever, reranker):
        sub_queries = self.decompose(query)

        all_contexts = []

        for q in sub_queries:
            retrieved = retriever(q)
            reranked = reranker.rerank(q, retrieved)

            all_contexts.extend(reranked)

        # remove duplicates
        return list(set(all_contexts))
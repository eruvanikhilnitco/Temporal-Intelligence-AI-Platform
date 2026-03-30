class QueryClassifier:
    def classify(self, query: str) -> str:
        query = query.lower()

        if "summarize" in query or "summary" in query:
            return "summary"

        elif "compare" in query or "difference" in query:
            return "comparison"

        elif "risk" in query or "analysis" in query:
            return "analytical"

        else:
            return "fact"
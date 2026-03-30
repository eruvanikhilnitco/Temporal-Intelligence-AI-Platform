import os
import cohere
from dotenv import load_dotenv

# 🔥 Load environment variables from .env
load_dotenv()


class LLMService:
    def __init__(self):
        api_key = os.getenv("COHERE_API_KEY")

        # ✅ Proper error handling
        if not api_key:
            raise ValueError("❌ COHERE_API_KEY not found. Please set it in .env or environment variables.")

        self.client = cohere.Client(api_key)

    def generate_answer(self, query: str, context: str) -> str:
        # ✅ Safety: limit context size (important for LLM performance)
        context = context[:4000]

        prompt = f"""
You are an intelligent assistant.

Answer the question strictly based on the provided context.
If the answer is not present, say "Not found in document".

Context:
{context}

Question:
{query}

Answer:
"""

        response = self.client.chat(
            model="command-r7b-12-2024",
            message=prompt,
            temperature=0.2
        )

        # ✅ Safe response extraction
        return response.text.strip() if response.text else "No response generated"
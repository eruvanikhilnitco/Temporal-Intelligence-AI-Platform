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

    def generate_answer(self, query: str, context: str, role: str = "user") -> str:
        # ✅ Safety: limit context size (important for LLM performance)
        context = context[:3000]

        # Detect greetings and conversational queries
        q_lower = query.lower().strip()
        greeting_patterns = [
            "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
            "how are you", "what's up", "how do you do", "nice to meet you",
            "you are good", "you are not good", "how is your day",
        ]
        if any(q_lower == g or q_lower.startswith(g) for g in greeting_patterns):
            return (
                "Hey there! I'm doing great, thanks for asking! 😊 "
                "I'm CortexFlow AI — your intelligent document assistant. "
                "I'm here to help you find information, answer questions about documents, "
                "and make sense of complex data. What can I help you with today?"
            )

        if role == "user":
            system_prompt = (
                "You are a friendly, knowledgeable assistant helping users understand information from documents. "
                "Respond naturally as a person would — be warm, clear, and helpful. "
                "Never say 'Not found in document' or use robotic phrases. "
                "If you don't have specific information, say something like 'I don't have details on that right now, "
                "but I can help you with...' or give a helpful general response. "
                "Keep answers concise and conversational. Do NOT reveal document names, raw file paths, "
                "or complete document content — just provide helpful, summarized answers."
            )
        else:
            system_prompt = (
                "You are a precise technical assistant with full access to document context. "
                "Answer accurately based on the provided context. "
                "If information is not in the context, say so clearly and suggest what to search for. "
                "Format answers clearly with bullet points where appropriate."
            )

        if context.strip():
            prompt = f"{system_prompt}\n\nContext from documents:\n{context}\n\nUser question: {query}\n\nAnswer:"
        else:
            prompt = f"{system_prompt}\n\nUser question: {query}\n\nAnswer:"

        response = self.client.chat(
            model="command-r7b-12-2024",
            message=prompt,
            temperature=0.3,
        )

        # ✅ Safe response extraction
        return response.text.strip() if response.text else "I'm here to help! Could you rephrase your question?"
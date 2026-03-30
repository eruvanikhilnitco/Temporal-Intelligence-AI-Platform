from fastapi import FastAPI
import redis
from qdrant_client import QdrantClient
from services.chatbot_service import ChatbotService
from sentence_transformers import SentenceTransformer
from services.phase1_rag import Phase1RAG

app = FastAPI()

# Redis
redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)

# Qdrant
qdrant = QdrantClient(host="localhost", port=6333)

chatbot = ChatbotService()

model = SentenceTransformer("all-MiniLM-L6-v2")

rag = Phase1RAG(folder_path="sample_data")


@app.get("/")
def home():
    return {"message": "Backend running 🚀"}

@app.get("/cache-test")
def cache_test():
    redis_client.set("test_key", "hello from redis")
    return {"cached_value": redis_client.get("test_key")}

@app.get("/qdrant-test")
def qdrant_test():
    collections = qdrant.get_collections()
    return {"collections": str(collections)}


# 🔥 NEW CHAT ENDPOINT
@app.get("/chat")
def chat(question: str):
    try:
        cached = redis_client.get(question)
        if cached:
            return {"source": "cache", "answer": cached}

        retrieved = rag.query(question)
        reranked = rag.reranker.rerank(question, retrieved)

        answer = rag.llm.generate_answer(question, reranked)

        redis_client.set(question, answer)

        return {"source": "generated", "answer": answer}

    except Exception as e:
        return {"error": str(e)}
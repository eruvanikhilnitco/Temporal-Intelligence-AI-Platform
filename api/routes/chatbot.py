from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any
import logging

from api.middleware.auth import require_api_key
from services.chatbot_service import ChatbotService

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[require_api_key()])

chatbot_service = ChatbotService()


class ChatMessage(BaseModel):
    question: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []


@router.post("/query", response_model=ChatResponse)
def query_chatbot(message: ChatMessage) -> ChatResponse:
    """Answer questions using hybrid retrieval + deterministic tools + optional LLM synthesis."""
    try:
        answer, sources = chatbot_service.answer_question(
            question=message.question,
            session_id=message.session_id,
        )
        # Return empty sources array (sources are not displayed in UI)
        return ChatResponse(answer=answer, sources=[])

    except Exception as e:
        logger.error(f"Chatbot error: {e}", exc_info=True)
        return ChatResponse(
            answer=f"I encountered an error processing your question: {str(e)}. Please try rephrasing your question or contact support if the issue persists.",
            sources=[]
        )

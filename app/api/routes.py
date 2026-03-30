from fastapi import APIRouter
from app.api.schemas import AskRequest, AskResponse
from app.services.rag_service import ask_rag

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/ask", response_model=AskResponse)
def ask_question(req: AskRequest):
    answer = ask_rag(req.question, req.role)
    return AskResponse(answer=answer)
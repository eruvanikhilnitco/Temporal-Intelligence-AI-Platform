from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    role: str = "user"


class AskResponse(BaseModel):
    answer: str
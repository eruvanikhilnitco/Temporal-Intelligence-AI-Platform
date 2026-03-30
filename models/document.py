from pydantic import BaseModel


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    document_type: str
    lifecycle_id: str
    entities: list[str]
    embedding_preview: list[float]
    storage_path: str

from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class AskRequest(BaseModel):
    question: str
    role: str = "user"
    session_id: Optional[str] = None


class SourceItem(BaseModel):
    name: str
    relevance: float
    chunk: str


class AskResponse(BaseModel):
    answer: str
    graph_used: bool = False
    confidence: float = 0.0
    query_type: str = "fact"
    sources: List[SourceItem] = []
    latency_ms: int = 0
    chat_log_id: Optional[str] = None
    explanation: Optional[Any] = None       # Admin-only: routing trace, confidence scores, tools
    grounding_score: Optional[float] = None # 0–1; None if no context retrieved
    grounding_warning: Optional[str] = None # Set when grounding_score < 0.4
    provider_used: Optional[str] = None     # cohere / openai_fallback / emergency_fallback
    fallback_used: bool = False


class UploadResponse(BaseModel):
    status: str
    filename: str
    message: str
    entities: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    version: str = "3.0"
    phases: List[str] = ["Phase1-RAG", "Phase2-Intelligence", "Phase3-GraphRAG"]


# ── Admin schemas ────────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    name: str
    pattern: str
    action: str = "block"
    role: str = "public"


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    pattern: Optional[str] = None
    action: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None


class RuleResponse(BaseModel):
    id: str
    name: str
    pattern: str
    action: str
    role: str
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SecurityEventCreate(BaseModel):
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    event_type: str
    severity: str = "medium"
    description: str
    query: Optional[str] = None
    ip_address: Optional[str] = None


class SecurityEventResponse(BaseModel):
    id: str
    user_email: Optional[str]
    event_type: str
    severity: str
    description: str
    query: Optional[str]
    resolved: bool
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackRequest(BaseModel):
    chat_log_id: str
    feedback: str   # "positive" or "negative"
    comment: Optional[str] = None


class ChatLogResponse(BaseModel):
    id: str
    question: str
    answer: str
    query_type: str
    graph_used: bool
    confidence: float
    sources: Optional[Any]
    feedback: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AnalyticsResponse(BaseModel):
    total_queries: int
    avg_latency_ms: float
    cache_hit_rate: float
    graph_usage_rate: float
    avg_confidence: float
    total_users: int
    active_rules: int
    security_events: int
    daily_queries: List[int]
    hourly_queries: List[int]
    retrieval_quality: List[dict]
    top_query_types: dict


class GraphNodeResponse(BaseModel):
    id: str
    name: str
    type: str
    source: Optional[str]


class GraphEdgeResponse(BaseModel):
    from_node: str
    relation: str
    to_node: str
    source: Optional[str]


class GraphDataResponse(BaseModel):
    nodes: List[GraphNodeResponse]
    edges: List[GraphEdgeResponse]
    total_nodes: int
    total_edges: int

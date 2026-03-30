from datetime import datetime

from pydantic import BaseModel, Field


class OutcomeCreate(BaseModel):
    lifecycle_id: str
    outcome_type: str
    value: float
    recorded_at: datetime = Field(default_factory=datetime.utcnow)


class OutcomeResponse(OutcomeCreate):
    outcome_id: str

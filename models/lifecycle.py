from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LifecycleEvent(BaseModel):
    event_id: str
    event_type: str
    timestamp: datetime
    summary: str


class LifecycleResponse(BaseModel):
    lifecycle_id: str
    status: str
    events: list[LifecycleEvent]
    lifecycle_type: Optional[str] = None  # e.g., "procurement", "hr", "sales", "custom"
    domain: Optional[str] = None  # e.g., "manufacturing", "healthcare", "finance"
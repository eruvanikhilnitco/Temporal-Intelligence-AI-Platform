from pydantic import BaseModel


class RiskPrediction(BaseModel):
    lifecycle_id: str
    risk_score: float
    risk_label: str
    drivers: list[str]
    explanation: str

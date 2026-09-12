from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CandidateHypothesisRead(BaseModel):
    """Serialized representation of a candidate hypothesis."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    name: str
    category: str
    trigger_reason: str
    initial_score: float
    confidence: float
    supporting_observations: list[str]
    contradicting_observations: list[str]
    missing_information: list[str]
    status: str
    created_at: datetime

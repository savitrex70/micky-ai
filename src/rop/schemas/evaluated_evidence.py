from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvaluatedEvidenceRead(BaseModel):
    """Serialized representation of evaluated evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    hypothesis_id: UUID
    observation_id: UUID | None
    entity_id: UUID | None
    rule_id: str
    relationship: str
    weight: float
    confidence: float
    reason: str
    source: str
    created_at: datetime


class EvidenceGroupedRead(BaseModel):
    """Evidence grouped by hypothesis for API response."""

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    evidence: list[EvaluatedEvidenceRead]

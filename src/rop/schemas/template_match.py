from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TemplateMatchRead(BaseModel):
    """Serialized representation of a template match result."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    template_name: str
    confidence: float
    matched_observations: list[str]
    matched_entities: list[str]
    reason: str
    candidates: list[dict[str, object]]
    created_at: datetime

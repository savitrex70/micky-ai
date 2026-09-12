from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rop.models.evidence import EvidenceStrength, EvidenceType


class EvidenceCreate(BaseModel):
    """Fields required to create evidence."""

    hypothesis_id: UUID
    session_id: UUID
    type: EvidenceType = EvidenceType.UNKNOWN
    source: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    strength: EvidenceStrength = EvidenceStrength.MODERATE


class EvidenceUpdate(BaseModel):
    """Optional fields that may be changed on evidence."""

    type: EvidenceType | None = None
    source: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    strength: EvidenceStrength | None = None


class EvidenceRead(BaseModel):
    """Serialized representation of evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hypothesis_id: UUID
    session_id: UUID
    type: EvidenceType
    source: str
    text: str
    confidence: float
    strength: EvidenceStrength
    created_at: datetime

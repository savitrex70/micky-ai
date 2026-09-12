from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ObservationCreate(BaseModel):
    """Fields required to create an observation."""

    session_id: UUID
    text: str = Field(min_length=1)
    type: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=255)


class ObservationUpdate(BaseModel):
    """Optional fields that may be changed on an observation."""

    text: str | None = Field(default=None, min_length=1)
    type: str | None = Field(default=None, min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = Field(default=None, min_length=1, max_length=255)


class ObservationRead(BaseModel):
    """Serialized representation of an observation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    text: str
    type: str
    confidence: float
    source: str
    timestamp: datetime

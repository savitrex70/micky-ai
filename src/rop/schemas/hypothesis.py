from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rop.models.hypothesis import HypothesisStatus


class HypothesisCreate(BaseModel):
    """Fields required to create a hypothesis."""

    session_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=100)
    status: HypothesisStatus = HypothesisStatus.PENDING
    likelihood_score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=0)
    reason: str | None = None


class HypothesisUpdate(BaseModel):
    """Optional fields that may be changed on a hypothesis."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    status: HypothesisStatus | None = None
    likelihood_score: float | None = Field(default=None, ge=0.0, le=1.0)
    rank: int | None = Field(default=None, ge=0)
    reason: str | None = None


class HypothesisRead(BaseModel):
    """Serialized representation of a hypothesis."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    title: str
    description: str
    category: str
    status: HypothesisStatus
    likelihood_score: float
    rank: int
    reason: str | None
    created_at: datetime
    updated_at: datetime

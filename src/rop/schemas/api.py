from typing import Any

from pydantic import BaseModel, Field

from rop.models.evidence import EvidenceStrength, EvidenceType
from rop.models.reasoning_step import StepType


class ObservationCreateRequest(BaseModel):
    """Request body for creating an observation under a session."""

    text: str = Field(min_length=1)
    type: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=255)


class HypothesisCreateRequest(BaseModel):
    """Request body for creating a hypothesis under a session."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=50)
    likelihood_score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=0)
    reason: str | None = None


class EvidenceCreateRequest(BaseModel):
    """Request body for creating evidence under a hypothesis."""

    type: EvidenceType
    source: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    strength: EvidenceStrength


class ReasoningStepCreateRequest(BaseModel):
    """Request body for creating a reasoning step under a session."""

    step_type: StepType
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    duration_ms: int = Field(ge=0)
    status: str = Field(min_length=1, max_length=50)

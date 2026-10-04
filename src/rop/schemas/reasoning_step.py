from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rop.models.reasoning_step import StepType


class ReasoningStepCreate(BaseModel):
    """Fields required to create a reasoning step."""

    session_id: UUID
    step_type: StepType
    input_data: dict[str, object] = Field(default_factory=dict)
    output_data: dict[str, object] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    duration_ms: int = Field(ge=0)
    status: str = Field(min_length=1, max_length=50)


class ReasoningStepRead(BaseModel):
    """Serialized representation of a reasoning step."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    step_number: int
    step_type: StepType
    input_data: dict[str, object]
    output_data: dict[str, object]
    confidence: float
    duration_ms: int
    status: str
    created_at: datetime

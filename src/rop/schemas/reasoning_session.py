from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ReasoningSessionCreate(BaseModel):
    """Fields required to create a reasoning session record."""

    status: str = Field(min_length=1, max_length=50)
    domain: str = Field(min_length=1, max_length=255)
    user_input: str = Field(min_length=1)
    current_stage: str = Field(min_length=1, max_length=100)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReasoningSessionUpdate(BaseModel):
    """Optional fields that may be changed on a session record."""

    status: str | None = Field(default=None, min_length=1, max_length=50)
    domain: str | None = Field(default=None, min_length=1, max_length=255)
    user_input: str | None = Field(default=None, min_length=1)
    current_stage: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class ReasoningSessionRead(BaseModel):
    """Serialized representation of a reasoning session record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    status: str
    domain: str
    user_input: str
    current_stage: str
    notes: str | None
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("metadata_", "metadata")
    )

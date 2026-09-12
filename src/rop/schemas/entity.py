from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntityCreate(BaseModel):
    """Fields required to create an entity."""

    session_id: UUID
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=255)


class EntityUpdate(BaseModel):
    """Optional fields that may be changed on an entity."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = Field(default=None, min_length=1, max_length=255)


class EntityRead(BaseModel):
    """Serialized representation of an entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    name: str
    category: str
    confidence: float
    source: str

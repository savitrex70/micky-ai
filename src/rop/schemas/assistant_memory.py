"""Typed contracts for user-controlled private memory."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryEntryType = Literal["memory", "preference"]


class MemoryCreate(BaseModel):
    """A deliberate user action to save one memory or preference."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    entry_type: MemoryEntryType = "memory"
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("title", "content")
    @classmethod
    def trim_and_validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        if any(ord(char) < 32 and char not in "\n\t" for char in cleaned):
            raise ValueError("unsupported control character")
        return cleaned


class MemoryUpdate(BaseModel):
    """A partial update to one existing entry; null is not a deletion signal."""

    model_config = ConfigDict(extra="forbid")

    entry_type: MemoryEntryType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("title", "content")
    @classmethod
    def trim_and_validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        if any(ord(char) < 32 and char not in "\n\t" for char in cleaned):
            raise ValueError("unsupported control character")
        return cleaned

    @model_validator(mode="after")
    def require_real_update(self) -> "MemoryUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("updated fields may not be null")
        return self


class MemoryRead(BaseModel):
    """Safe user-visible representation of a saved entry."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    entry_type: MemoryEntryType
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    """A bounded page of saved entries."""

    model_config = ConfigDict(extra="forbid")

    items: list[MemoryRead]
    total: int
    offset: int
    limit: int


class MemoryClearRequest(BaseModel):
    """Exact phrase required to clear every saved memory entry."""

    model_config = ConfigDict(extra="forbid")

    confirmation_phrase: str = Field(min_length=1, max_length=64)


class MemoryClearResponse(BaseModel):
    """Outcome of an explicitly confirmed clear-all request."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"] = "success"
    deleted_count: int

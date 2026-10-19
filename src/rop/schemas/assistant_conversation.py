"""Data contracts for durable assistant conversations and messages.

These are the input and read shapes the repository layer accepts and
returns. They do not define any HTTP response contract; the endpoints
that will eventually consume them are out of scope for Task 228.

A ``role`` on an assistant message is constrained to ``user`` or
``assistant``. There is deliberately no role for hidden internal
instructions, so a caller cannot smuggle such content into storage
under an innocuous-looking role name.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CONVERSATION_TITLE_LENGTH = 200
MAX_MESSAGE_CONTENT_LENGTH = 20000

AssistantMessageRole = Literal["user", "assistant"]


class AssistantConversationCreate(BaseModel):
    """Inputs for creating a new conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=MAX_CONVERSATION_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty or whitespace-only")
        return value


class AssistantConversationUpdate(BaseModel):
    """Fields that may be changed on an existing conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=MAX_CONVERSATION_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty or whitespace-only")
        return value


class AssistantConversationRead(BaseModel):
    """One conversation as the repository returns it."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class AssistantMessageCreate(BaseModel):
    """Inputs for appending a message to an existing conversation.

    ``conversation_id`` is taken from the caller's session context, not from
    this body; the repository receives it separately so the caller cannot
    accidentally attach a message to a conversation other than the one they
    are acting on.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: AssistantMessageRole
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)


class AssistantUserMessageCreate(BaseModel):
    """Public HTTP body for appending one user-authored message.

    The role is deliberately not a caller-supplied field: the public
    append endpoint always stores ``user`` messages. A caller cannot
    forge an ``assistant`` message through this body and have invented
    output appear as though Micky AI produced it. Internal code that
    persists a genuine assistant reply uses :class:`AssistantMessageCreate`
    instead; that contract keeps the role field for internal callers
    only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)

    @field_validator("content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return value


class AssistantMessageRead(BaseModel):
    """One message as the repository returns it."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: AssistantMessageRole
    content: str
    sequence: int
    created_at: datetime


__all__ = [
    "AssistantConversationCreate",
    "AssistantConversationRead",
    "AssistantConversationUpdate",
    "AssistantMessageCreate",
    "AssistantMessageRead",
    "AssistantUserMessageCreate",
    "AssistantMessageRole",
    "MAX_CONVERSATION_TITLE_LENGTH",
    "MAX_MESSAGE_CONTENT_LENGTH",
]

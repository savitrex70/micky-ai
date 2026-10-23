"""Request and response contracts for the local personal workspace."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rop.schemas.assistant import AssistantConfirmationChallenge

WorkspaceItemKind = Literal["note", "task", "reminder"]
WorkspaceChangeKind = Literal["note", "task", "reminder", "retrieval_root"]
WorkspaceChangeAction = Literal[
    "create", "update", "delete", "complete", "add", "remove"
]


class WorkspaceItemRead(BaseModel):
    """User-visible workspace item."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    kind: WorkspaceItemKind
    title: str
    content: str
    due_at: datetime | None
    timezone: str | None
    completed: bool
    created_at: datetime
    updated_at: datetime


class RetrievalRootRead(BaseModel):
    """A folder explicitly authorized for retrieval."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    path: str
    created_at: datetime


class WorkspaceChangeRequest(BaseModel):
    """Describe a proposed change; never authorizes it by itself."""

    model_config = ConfigDict(extra="forbid")

    kind: WorkspaceChangeKind
    action: WorkspaceChangeAction
    idempotency_key: UUID
    item_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=512)
    clear_content: bool = False
    due_local: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    path: str | None = Field(default=None, min_length=1, max_length=512)
    completed: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("title must not be blank")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
            if not value.isprintable():
                raise ValueError("content must be plain single-line text")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("path must not be blank")
            if not value.isprintable():
                raise ValueError("path contains unsupported characters")
        return value

    @model_validator(mode="after")
    def validate_action_shape(self) -> "WorkspaceChangeRequest":
        if self.kind == "retrieval_root":
            if self.clear_content:
                raise ValueError("clear_content is only valid for workspace items")
            if self.action == "add":
                if self.path is None or self.item_id is not None:
                    raise ValueError(
                        "folder authorization requires a path and no item ID"
                    )
            elif self.action == "remove":
                if self.item_id is None or self.path is not None:
                    raise ValueError("folder removal requires an ID and no path")
            else:
                raise ValueError("unsupported retrieval-root action")
            if any(
                value is not None
                for value in (
                    self.title,
                    self.content,
                    self.due_local,
                    self.timezone,
                    self.completed,
                )
            ):
                raise ValueError("retrieval-root actions accept only a path or item ID")
            return self

        if self.path is not None:
            raise ValueError("path is only valid for retrieval-root actions")
        if self.action not in {"create", "update", "delete", "complete"}:
            raise ValueError("unsupported workspace action")
        if self.action == "create":
            if self.item_id is not None:
                raise ValueError("create does not accept an item identifier")
            if self.title is None:
                raise ValueError("a title is required")
        else:
            if self.item_id is None:
                raise ValueError("an item identifier is required")
            if self.action == "update" and self.title is None:
                raise ValueError("an updated title is required")
        if self.clear_content and (self.action != "update" or self.content is not None):
            raise ValueError(
                "clear_content is valid only for an update with no content value"
            )
        if self.action not in {"create", "update"} and (
            self.content is not None or self.clear_content
        ):
            raise ValueError("content changes are valid only for create or update")
        if self.kind == "reminder":
            if self.action in {"create", "update"} and (
                self.due_local is None or self.timezone is None
            ):
                raise ValueError("a due time and timezone are required for a reminder")
            if self.action == "complete":
                raise ValueError("reminders are dismissed by updating or deleting them")
        elif self.due_local is not None or self.timezone is not None:
            raise ValueError("due time and timezone are only valid for reminders")
        if self.action == "complete":
            if self.kind != "task" or self.completed is None:
                raise ValueError("task completion requires a completed value")
        elif self.completed is not None:
            raise ValueError("completed is only valid for task completion")
        return self


class WorkspaceChangeResponse(BaseModel):
    """Initial outcome when preparing a protected workspace mutation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "success",
        "confirmation-required",
        "confirmation-unavailable",
        "refused",
        "unknown",
    ]
    message: str
    challenge: AssistantConfirmationChallenge | None = None


class WorkspaceReceiptRead(BaseModel):
    """Safe recovery view of an idempotent operation result."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: UUID
    status: Literal["succeeded", "not-found", "unknown"]
    message: str

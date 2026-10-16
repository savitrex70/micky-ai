"""Request and response envelopes for the local assistant web interface."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ASSISTANT_REQUEST_MAX_MESSAGE_LENGTH = 2000


class AssistantRequest(BaseModel):
    """A single user message sent from the local browser interface."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        min_length=1,
        max_length=ASSISTANT_REQUEST_MAX_MESSAGE_LENGTH,
    )

    @field_validator("message")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty or whitespace-only")
        return value


class AssistantResponse(BaseModel):
    """Response envelope for the local assistant request endpoint.

    ``success`` means a registered capability produced its predefined
    deterministic response. ``unsupported-capability`` means no registered
    capability matched the request and no action was taken.
    """

    status: Literal["success", "unsupported-capability"]
    message: str

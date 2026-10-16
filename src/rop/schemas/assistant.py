"""Request and response envelopes for the local assistant web interface."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ASSISTANT_REQUEST_MAX_MESSAGE_LENGTH = 2000

AssistantStatus = Literal[
    "success",
    "unsupported-capability",
    "clarification-required",
    "confirmation-required",
    "refused",
]
"""The honest outcomes the assistant request endpoint can report.

``success`` is the only status that carries a capability's response.
``unsupported-capability`` means no registered capability matched the
request. ``clarification-required``, ``confirmation-required``, and
``refused`` mean a capability matched but the authorization policy did not
permit it to answer, so nothing was dispatched. Every non-``success`` status
means no operation was performed and nothing was saved.
"""


class AssistantRequest(BaseModel):
    """A single user message sent from the local browser interface.

    Only a message is accepted. There is deliberately no field for a
    confirmation, an authorization, or a permission assertion: a caller
    cannot supply evidence that a user approved anything, and unexpected
    fields are rejected rather than ignored.
    """

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

    ``success`` means a registered capability was permitted by the
    authorization policy and produced its predefined deterministic
    response. ``unsupported-capability`` means no registered capability
    matched the request. The remaining three statuses describe a matched
    capability that the policy stopped: the request was understood, but it
    was not executed. A non-``success`` status is never evidence that
    anything ran.
    """

    status: AssistantStatus
    message: str

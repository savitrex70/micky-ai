"""Request and response envelopes for the local assistant web interface."""

from datetime import datetime
from typing import Literal
from uuid import UUID

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
    #: Optional saved conversation this turn belongs to. When ``None`` (the
    #: default), the endpoint preserves its historical behaviour exactly:
    #: no database session is created and nothing is persisted. When set,
    #: the endpoint verifies the conversation, dispatches the request, and
    #: persists the user/assistant pair atomically iff the response is
    #: ``success``. A caller cannot supply a role, sequence, authorization,
    #: or persistence metadata here — ``extra="forbid"`` on the model
    #: rejects any such field before the handler runs.
    conversation_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty or whitespace-only")
        return value


class AssistantConfirmationChallenge(BaseModel):
    """The display values for one newly created pending confirmation.

    These are the only challenge-related values the interface receives: the
    opaque identifier, a human-readable summary built from the stored
    operation, the short display code, and the server-issued expiry. The
    stored display-code hash, its salt, the internal database identifier,
    the stored policy fingerprint, and unrelated operation data are never
    part of this contract.
    """

    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=16, max_length=128)
    summary: str = Field(min_length=1, max_length=2000)
    display_code: str = Field(min_length=1, max_length=64)
    expires_at: datetime


class AssistantResponse(BaseModel):
    """Response envelope for the local assistant request endpoint.

    ``success`` means a registered capability was permitted by the
    authorization policy and produced its predefined deterministic
    response. ``unsupported-capability`` means no registered capability
    matched the request. The remaining three statuses describe a matched
    capability that the policy stopped: the request was understood, but it
    was not executed. A non-``success`` status is never evidence that
    anything ran.

    ``challenge`` is present only when a pending confirmation was genuinely
    created for a consequential operation. It carries the server-owned
    challenge values so the interface can display them; it is ``None`` for
    every other status, and the endpoint omits it rather than emitting a
    null field.
    """

    status: AssistantStatus
    message: str
    challenge: AssistantConfirmationChallenge | None = None

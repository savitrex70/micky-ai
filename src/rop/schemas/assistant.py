"""Request and response envelopes for the local assistant web interface."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ASSISTANT_REQUEST_MAX_MESSAGE_LENGTH = 2000

AssistantStatus = Literal[
    "success",
    "unsupported-capability",
    "clarification-required",
    "confirmation-required",
    "confirmation-unavailable",
    "refused",
]
"""The outcomes returned by the initial assistant request endpoint.

The endpoint has six statuses. ``success`` reports a successful deterministic
capability response (including approved read-only workspace operations).
``unsupported-capability``, ``clarification-required``,
``confirmation-required``, ``confirmation-unavailable``, and ``refused`` are
non-success outcomes: the request endpoint does not apply a workspace mutation
or persist a successful conversation turn on those paths. A clarification or
confirmation challenge may still be stored as server-owned pending state.
Post-confirmation outcomes belong to ``ConfirmationDecisionStatus``, not
this enum.
"""


class AssistantRequest(BaseModel):
    """A single user message sent from the local browser interface.

    A message may be tied to a saved conversation and a server-owned
    clarification continuation. There is deliberately no field for a
    confirmation or permission assertion: callers cannot supply evidence
    of approval, and unexpected fields are rejected.
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
    clarification_id: UUID | None = None
    idempotency_key: UUID | None = None

    @model_validator(mode="after")
    def check_clarification_conversation(self) -> "AssistantRequest":
        if self.clarification_id is not None and self.conversation_id is None:
            raise ValueError(
                "a clarification continuation requires a selected conversation"
            )
        return self

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


class ClarificationPrompt(BaseModel):
    """Sanitized question for one server-owned pending clarification."""

    model_config = ConfigDict(extra="forbid")

    clarification_id: UUID
    capability_identifier: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=512)
    missing_fields: list[str] = Field(min_length=1, max_length=16)


class AssistantResponse(BaseModel):
    """Response envelope for the local assistant request endpoint.

    ``success`` reports that a registered deterministic capability returned
    a successful response. ``unsupported-capability`` means no help alias or
    explicit workspace command matched. The other statuses describe
    clarification, a confirmation challenge, inability to create a challenge,
    or refusal. This endpoint does not itself apply a protected workspace
    mutation; those run only through the separate confirmation-decision
    endpoint.

    ``challenge`` is present only when a pending confirmation was genuinely
    created for a consequential workspace operation. ``clarification_prompt``
    is present only when server-owned pending clarification state was created
    for the selected conversation. The response excludes absent optional
    fields.
    """

    status: AssistantStatus
    message: str
    challenge: AssistantConfirmationChallenge | None = None
    clarification_prompt: ClarificationPrompt | None = None

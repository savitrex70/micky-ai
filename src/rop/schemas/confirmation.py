"""Request and response contracts for the confirmation decision endpoint.

These are the *only* fields a confirmation decision may carry: one decision
and, for a confirmation, the short display code. There is deliberately no
field for an operation identifier, target, scope, parameters, an
authorization scope, a policy identity or version, or a ``confirmed``
flag, so a caller cannot assert its own permission or change which action
is being decided. The stored record is the authority for that.

Nothing here mints a challenge, verifies a code, evaluates a policy, or
executes an operation: the schemas are data only, and the server-side
verification lives in :mod:`rop.services.confirmation`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_DISPLAY_CODE_INPUT_LENGTH = 64
"""Upper bound on a submitted display code.

A well-formed code is six characters; the bound only stops an oversized
body from being carried any further, and an overlong value is treated as a
wrong code rather than echoed back.
"""


class ConfirmationDecision(StrEnum):
    """The three first-class decisions a user can make about a challenge."""

    CONFIRM = "confirm"
    CANCEL = "cancel"
    REJECT = "reject"


class ConfirmationDecisionRequest(BaseModel):
    """The body of a confirmation decision.

    Unknown fields are forbidden, so a body that tries to supply an
    operation, a target, parameters, a scope, ``authorized``, or
    ``confirmed`` is rejected rather than ignored. The display code is
    required to confirm and unnecessary to cancel or reject, which must
    never assert authorization.
    """

    model_config = ConfigDict(extra="forbid")

    decision: ConfirmationDecision
    display_code: str | None = Field(
        default=None, max_length=MAX_DISPLAY_CODE_INPUT_LENGTH
    )

    @model_validator(mode="after")
    def check_display_code(self) -> ConfirmationDecisionRequest:
        if self.decision is ConfirmationDecision.CONFIRM:
            if self.display_code is None or not self.display_code.strip():
                raise ValueError("a display code is required to confirm")
        return self


class ConfirmationDecisionStatus(StrEnum):
    """The honest outcome of a decision request.

    Only ``EXECUTED`` means an executor ran and reported success. ``FAILED``
    means it ran and reported failure. ``UNKNOWN`` means it ran but its
    outcome could not be established. ``CANCELLED``, ``REJECTED``,
    ``REFUSED``, and ``UNAVAILABLE`` all mean nothing ran.
    """

    EXECUTED = "executed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"


class ConfirmationDecisionResponse(BaseModel):
    """The sanitized result of a decision request.

    The response carries no challenge identifier, no submitted code, no
    attempt count, and no material value, so every refusal is
    indistinguishable from every other refusal. ``executed`` is true only
    when an executor was invoked.
    """

    model_config = ConfigDict(extra="forbid")

    status: ConfirmationDecisionStatus
    message: str
    executed: bool


__all__ = [
    "MAX_DISPLAY_CODE_INPUT_LENGTH",
    "ConfirmationDecision",
    "ConfirmationDecisionRequest",
    "ConfirmationDecisionResponse",
    "ConfirmationDecisionStatus",
]

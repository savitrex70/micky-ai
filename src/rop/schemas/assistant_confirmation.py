"""Data lifecycle contracts for durable assistant confirmation records.

These contracts describe the storage and privacy surface of one pending
confirmation: its lifecycle status, the execution outcome that may follow
consumption, the inspection/export representation, and the deletion
result. They are data only. Nothing here mints a challenge, verifies a
confirmation, evaluates a policy, or executes an operation, and no model
in this module is a public HTTP response.

The representations are deliberately narrower than the stored record.
``AssistantConfirmationView`` omits the challenge identifier, the hashed
display code, its salt, and the retained material digest, because none of
those are needed to inspect or audit what would happen and all of them
are secret-adjacent. A record whose material values have been redacted
reports ``MaterialState.REDACTED`` so an export can distinguish "this
value was removed after the retention window" from "this operation never
carried the value", instead of inventing a substitute.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rop.schemas.authorization import (
    REASON_OUTCOMES,
    AuthorizationOutcome,
    AuthorizationReason,
    ProposedOperation,
    RiskLevel,
)

CONFIRMATION_RECORD_VERSION = "1"
"""Version of the stored confirmation-record contract."""

CONFIRMATION_RETENTION_DAYS = 30
"""Terminal records keep their material values for this many days.

Proposed in the Task 222 design and approved by the project owner with
the durable-storage decision: thirty days after a record becomes
terminal, its target, scope, and parameter values are removed and only a
salted digest of them is preserved. Pending records are never subject to
this window; their expiry belongs to the confirmation lifecycle.
"""

MAX_FAILED_CODE_ATTEMPTS = 5
"""Proposed default limit on wrong display codes per pending challenge.

The budget counts failures, so the fifth wrong code locks the challenge
and every later attempt is refused. A correct code on the fifth attempt
still succeeds.
"""

CONFIRMATION_EXPORT_FORMAT = "rop.assistant-confirmation-records"
CONFIRMATION_EXPORT_VERSION = "1"


class ConfirmationStatus(StrEnum):
    """Lifecycle states of one stored confirmation record.

    ``CONSUMED`` is the single successful transition out of ``PENDING``.
    There is deliberately no separate "confirmed" state: successful
    verification consumes the record, and duplicating that moment in a
    second status would let two pieces of code disagree about whether an
    approval had already been spent.
    """

    PENDING = "PENDING"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    LOCKED = "LOCKED"


TERMINAL_CONFIRMATION_STATUSES: frozenset[ConfirmationStatus] = frozenset(
    {
        ConfirmationStatus.CONSUMED,
        ConfirmationStatus.REJECTED,
        ConfirmationStatus.CANCELLED,
        ConfirmationStatus.EXPIRED,
        ConfirmationStatus.INVALIDATED,
        ConfirmationStatus.LOCKED,
    }
)
"""Every state a record can rest in. ``PENDING`` is the only live one."""


class ConfirmationOutcome(StrEnum):
    """What is known about execution after a record was consumed.

    ``UNKNOWN_AFTER_CONSUME`` is a real answer, not a placeholder: a crash
    between consumption and execution leaves the result unestablished, and
    it is never silently retried.
    """

    NOT_RUN = "NOT_RUN"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"
    UNKNOWN_AFTER_CONSUME = "UNKNOWN_AFTER_CONSUME"


class MaterialState(StrEnum):
    """Whether a record's material action values are present.

    ``ABSENT`` means the operation never carried a target, scope, or
    parameter. ``REDACTED`` means values existed and were removed after
    the retention window. ``RETAINED`` means they are still stored.
    """

    ABSENT = "ABSENT"
    RETAINED = "RETAINED"
    REDACTED = "REDACTED"


_HEX_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CHALLENGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class PendingConfirmationDraft(BaseModel):
    """Already validated inputs for one new pending confirmation record.

    This is a server-side input contract, never a browser one: the request
    schema that mints a challenge lives in the future workflow layer. A
    draft cannot set the lifecycle status, the timestamps that record a
    decision, the attempt counter, or the outcome, so creating a record
    can never assert that a confirmation already happened.

    The draft refuses to describe anything a confirmation could not be
    about: the risk must be ``CONSEQUENTIAL`` and the reason must map to
    ``REQUIRE_CONFIRMATION`` in the deterministic policy contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: ProposedOperation
    challenge_id: str = Field(min_length=16, max_length=128)
    display_code_hash: str = Field(min_length=64, max_length=64)
    display_code_salt: str = Field(min_length=32, max_length=64)
    policy_identity: str = Field(min_length=64, max_length=64)
    policy_version: str = Field(min_length=1, max_length=32)
    required_risk: RiskLevel
    required_reason: AuthorizationReason
    expires_at: datetime

    @field_validator("challenge_id")
    @classmethod
    def check_challenge_id(cls, value: str) -> str:
        if not _CHALLENGE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid challenge identifier")
        return value

    @field_validator("display_code_hash", "policy_identity")
    @classmethod
    def check_hex_digest(cls, value: str) -> str:
        if not _HEX_DIGEST_PATTERN.fullmatch(value):
            raise ValueError("invalid digest")
        return value

    @field_validator("display_code_salt")
    @classmethod
    def check_salt(cls, value: str) -> str:
        if len(value) % 2 != 0 or not re.fullmatch(r"[0-9a-f]+", value):
            raise ValueError("invalid salt")
        return value

    @field_validator("expires_at")
    @classmethod
    def check_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def check_confirmation_is_required(self) -> PendingConfirmationDraft:
        if self.required_risk is not RiskLevel.CONSEQUENTIAL:
            raise ValueError("confirmation requires a consequential risk")
        outcome = REASON_OUTCOMES[self.required_reason]
        if outcome is not AuthorizationOutcome.REQUIRE_CONFIRMATION:
            raise ValueError("confirmation reason must require confirmation")
        return self


class AssistantConfirmationView(BaseModel):
    """One confirmation record as inspection and export may present it.

    The challenge identifier, display-code hash, display-code salt, and
    material digest are not part of this contract and cannot be obtained
    through it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    operation_id: str
    status: ConfirmationStatus
    required_risk: RiskLevel
    required_reason: str = Field(min_length=1, max_length=64)
    policy_identity: str = Field(min_length=64, max_length=64)
    policy_version: str = Field(min_length=1, max_length=32)
    failed_code_attempts: int = Field(ge=0, le=MAX_FAILED_CODE_ATTEMPTS)
    material_state: MaterialState
    material_digest_recorded: bool
    target: str | None = None
    scope: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)
    outcome: ConfirmationOutcome | None = None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    terminal_at: datetime | None = None
    consumed_at: datetime | None = None
    redacted_at: datetime | None = None


class AssistantConfirmationExport(BaseModel):
    """A stable, self-describing export of the stored confirmation records.

    The shape is fixed by ``CONFIRMATION_EXPORT_FORMAT`` and
    ``CONFIRMATION_EXPORT_VERSION`` so a later data-control surface can
    serialize it without re-deciding what an export contains. Record
    order is the repository's deterministic order, so the same database
    state exports to the same sequence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["rop.assistant-confirmation-records"] = CONFIRMATION_EXPORT_FORMAT
    version: Literal["1"] = CONFIRMATION_EXPORT_VERSION
    generated_at: datetime
    retention_days: int = CONFIRMATION_RETENTION_DAYS
    record_count: int = Field(ge=0)
    records: tuple[AssistantConfirmationView, ...]
    notes: tuple[str, ...] = (
        "Material values are present only while a record is unredacted; "
        "material_state distinguishes retained, redacted, and absent values.",
        "Challenge identifiers, display codes, and their hashes are never "
        "included in an export.",
    )


class AssistantConfirmationDeletionResult(BaseModel):
    """How many confirmation records a deletion request actually removed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    deleted_count: int = Field(ge=0)


class RedactionResult(BaseModel):
    """How many terminal records a retention pass redacted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    redacted_count: int = Field(ge=0)


def canonical_material_values(
    *,
    target: str | None,
    scope: str | None,
    parameters: dict[str, str],
) -> bytes:
    """Return the canonical bytes of a record's material action values.

    Parameter order is not material to an authorization decision, so it
    is canonicalized here: the same operation always produces the same
    bytes, and therefore the same retained digest, regardless of the
    order in which parameters came back from the database.
    """
    payload = {
        "target": target,
        "scope": scope,
        "parameters": [[name, value] for name, value in sorted(parameters.items())],
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")

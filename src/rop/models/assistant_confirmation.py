"""Durable storage for one pending assistant-operation confirmation.

A row binds a challenge identifier to the exact operation that was
proposed - its identifier, target, scope, material parameters, and the
effective policy identity that required confirmation - plus the lifecycle
state that decides whether the approval may still be spent.

Two separations are structural rather than conventional:

* The table has no foreign keys and no ORM relationships at all, and in
  particular none to clinical reasoning data. An assistant confirmation
  is not a clinical record and must never become part of a reasoning
  session, hypothesis, evidence, provenance, or certification chain.
* No conversation content is stored. There is no user message, assistant
  reply, or model output column, and the display code is kept only as a
  salted hash.

Redaction preserves the audit record instead of deleting it: once a
terminal record passes the retention window its material values are
removed and a salted digest of them is retained, with ``material_redacted``
distinguishing "removed" from "never supplied".
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base
from rop.schemas.assistant_confirmation import (
    MAX_FAILED_CODE_ATTEMPTS,
    ConfirmationOutcome,
    ConfirmationStatus,
)

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in ConfirmationStatus)
_OUTCOME_VALUES = ", ".join(f"'{outcome.value}'" for outcome in ConfirmationOutcome)


class AssistantConfirmation(Base):
    """One stored confirmation record.

    ``status`` is the only authority on whether an approval may be spent.
    ``CONSUMED`` is the single success transition out of ``PENDING``;
    there is no competing "confirmed" flag, so two readers cannot
    disagree about whether the approval was already used.
    """

    __tablename__ = "assistant_confirmations"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="ck_assistant_confirmations_status",
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({_OUTCOME_VALUES})",
            name="ck_assistant_confirmations_outcome",
        ),
        CheckConstraint(
            "failed_code_attempts >= 0 AND "
            f"failed_code_attempts <= {MAX_FAILED_CODE_ATTEMPTS}",
            name="ck_assistant_confirmations_failed_code_attempts",
        ),
        CheckConstraint(
            "(status = 'PENDING') = (terminal_at IS NULL)",
            name="ck_assistant_confirmations_terminal_timestamp",
        ),
        CheckConstraint(
            "(status = 'PENDING') = (display_code_hash IS NOT NULL)",
            name="ck_assistant_confirmations_verifier_presence",
        ),
        CheckConstraint(
            "(display_code_hash IS NULL) = (display_code_salt IS NULL)",
            name="ck_assistant_confirmations_verifier_pair",
        ),
        CheckConstraint(
            "(material_digest IS NULL) = (material_digest_salt IS NULL)",
            name="ck_assistant_confirmations_material_digest_pair",
        ),
        CheckConstraint(
            "material_redacted = (material_digest IS NOT NULL)",
            name="ck_assistant_confirmations_redaction_digest",
        ),
        CheckConstraint(
            "NOT material_redacted OR redacted_at IS NOT NULL",
            name="ck_assistant_confirmations_redacted_at",
        ),
        UniqueConstraint(
            "challenge_id", name="uq_assistant_confirmations_challenge_id"
        ),
        Index(
            "ix_assistant_confirmations_status_terminal_at",
            "status",
            "terminal_at",
        ),
        Index("ix_assistant_confirmations_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    #: Opaque, high-entropy lookup key. Never a public export field.
    challenge_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Salted hash of the short display code; the code itself is never stored.
    #: Cleared when the record becomes terminal, because a decided record can
    #: never be confirmed again and its verifier is no longer needed.
    display_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_code_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parameters: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    #: SHA-256 of the canonical effective authorization policy (Task 222 §5.9).
    policy_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Human-readable label only; today it is always the literal "1".
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    required_risk: Mapped[str] = mapped_column(String(20), nullable=False)
    required_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    failed_code_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConfirmationStatus.PENDING.value
    )
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    material_redacted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: Salted digest of the material values, present only after redaction.
    material_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    material_digest_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

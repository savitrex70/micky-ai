"""Persistence for durable assistant confirmation records.

The repository owns storage and lifecycle bookkeeping only. It is not a
policy evaluator and it is not a confirmation endpoint: it cannot mint a
challenge, it never treats a caller's assertion as approval, and it never
executes an operation. Every transition below is a single conditional
``UPDATE`` whose predicate carries the state it expects, so two callers
racing for the same record cannot both win.

Transactions belong to the caller, as elsewhere in this package: methods
stage work and flush so constraints are checked, but only the caller
commits. A refused transition returns a falsy result instead of raising,
so "nothing happened" cannot be reported as success.

Retention and redaction
-----------------------
A terminal record keeps its material values for
``CONFIRMATION_RETENTION_DAYS`` (thirty) days after ``terminal_at``. A
retention pass removes the target, scope, and parameter values and
replaces them with ``material_digest``, a salted SHA-256 over

    b"rop.assistant-confirmation-material.v1" \\x00 salt \\x00 canonical bytes

where the canonical bytes are ``canonical_material_values``. The digest
is therefore verifiable while the values themselves are gone, and each
record has its own random salt. Pending records are never redacted by
this pass; their expiry belongs to the confirmation lifecycle.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, delete, null, select, update
from sqlalchemy.orm import Session

from rop.models.assistant_confirmation import AssistantConfirmation
from rop.schemas.assistant_confirmation import (
    CONFIRMATION_EXPORT_FORMAT,
    CONFIRMATION_EXPORT_VERSION,
    CONFIRMATION_RETENTION_DAYS,
    MAX_FAILED_CODE_ATTEMPTS,
    TERMINAL_CONFIRMATION_STATUSES,
    AssistantConfirmationDeletionResult,
    AssistantConfirmationExport,
    AssistantConfirmationView,
    ConfirmationOutcome,
    ConfirmationStatus,
    MaterialState,
    PendingConfirmationDraft,
    RedactionResult,
    canonical_material_values,
)
from rop.schemas.authorization import RiskLevel

MATERIAL_DIGEST_CONTEXT = b"rop.assistant-confirmation-material.v1"
"""Domain separator so a digest cannot be confused with another hash."""

DEFAULT_INSPECTION_LIMIT = 100
MAX_INSPECTION_LIMIT = 1000

_HEX_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ConfirmationRecordError(ValueError):
    """A confirmation-record operation was refused.

    The message is static and names no operation value, parameter, code,
    or challenge identifier, so a refused call cannot leak the material it
    was asked to store.
    """


def _checked_now(now: datetime | None) -> datetime:
    """Return a trusted, timezone-aware instant for every stored timestamp."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ConfirmationRecordError("a timezone-aware timestamp is required")
    return current.astimezone(UTC)


def _checked_identity(policy_identity: str) -> str:
    if not isinstance(policy_identity, str) or not _HEX_DIGEST_PATTERN.fullmatch(
        policy_identity
    ):
        raise ConfirmationRecordError("invalid policy identity")
    return policy_identity


def material_state(record: AssistantConfirmation) -> MaterialState:
    """Report whether a record's material values are present, gone, or absent.

    Redaction is explicit, so "removed after the retention window" is
    never reported as "this operation carried no such value".
    """
    if record.material_redacted:
        return MaterialState.REDACTED
    if record.target is None and record.scope is None and not record.parameters:
        return MaterialState.ABSENT
    return MaterialState.RETAINED


def to_view(record: AssistantConfirmation) -> AssistantConfirmationView:
    """Project a stored record onto the inspection/export contract.

    The challenge identifier, display-code hash and salt, and material
    digest are intentionally dropped here; the view is the only
    representation inspection and export may present.
    """
    return AssistantConfirmationView(
        id=record.id,
        operation_id=record.operation_id,
        status=ConfirmationStatus(record.status),
        required_risk=RiskLevel(record.required_risk),
        required_reason=record.required_reason,
        policy_identity=record.policy_identity,
        policy_version=record.policy_version,
        failed_code_attempts=record.failed_code_attempts,
        material_state=material_state(record),
        material_digest_recorded=record.material_digest is not None,
        target=record.target,
        scope=record.scope,
        parameters=dict(record.parameters or {}),
        outcome=None if record.outcome is None else ConfirmationOutcome(record.outcome),
        created_at=record.created_at,
        expires_at=record.expires_at,
        decided_at=record.decided_at,
        terminal_at=record.terminal_at,
        consumed_at=record.consumed_at,
        redacted_at=record.redacted_at,
    )


class AssistantConfirmationRepository:
    """Database operations for stored assistant confirmation records."""

    # --- creation and retrieval ------------------------------------------

    def create_pending(
        self,
        db: Session,
        draft: PendingConfirmationDraft,
        *,
        now: datetime | None = None,
    ) -> AssistantConfirmation:
        """Stage one ``PENDING`` record from validated operation data.

        The caller owns the transaction. A rejected draft raises before
        anything is staged; a constraint violation (for example a reused
        challenge identifier) raises from ``flush`` and leaves no row,
        because the caller never commits a failed unit of work.
        """
        created_at = _checked_now(now)
        if draft.expires_at <= created_at:
            raise ConfirmationRecordError("a challenge must expire in the future")

        record = AssistantConfirmation(
            challenge_id=draft.challenge_id,
            display_code_hash=draft.display_code_hash,
            display_code_salt=draft.display_code_salt,
            operation_id=draft.operation.operation_id,
            target=draft.operation.target,
            scope=draft.operation.scope,
            parameters=dict(draft.operation.parameters),
            policy_identity=_checked_identity(draft.policy_identity),
            policy_version=draft.policy_version,
            required_risk=draft.required_risk.value,
            required_reason=draft.required_reason.value,
            failed_code_attempts=0,
            status=ConfirmationStatus.PENDING.value,
            outcome=None,
            material_redacted=False,
            created_at=created_at,
            expires_at=draft.expires_at,
        )
        db.add(record)
        db.flush()
        return record

    def get_by_challenge_id(
        self, db: Session, challenge_id: str
    ) -> AssistantConfirmation | None:
        """Return the stored record for an exact challenge identifier.

        This is the internal lookup the confirmation path needs. Callers
        that present data to the user must use ``describe`` or ``to_view``
        instead of exposing the returned record.
        """
        statement = select(AssistantConfirmation).where(
            AssistantConfirmation.challenge_id == challenge_id
        )
        return db.scalars(statement).first()

    def describe(
        self, db: Session, challenge_id: str
    ) -> AssistantConfirmationView | None:
        """Return a secret-free description of one record, or ``None``."""
        record = self.get_by_challenge_id(db, challenge_id)
        return None if record is None else to_view(record)

    # --- inspection and export -------------------------------------------

    def list_records(
        self,
        db: Session,
        *,
        limit: int = DEFAULT_INSPECTION_LIMIT,
        offset: int = 0,
    ) -> list[AssistantConfirmationView]:
        """Return stored records in deterministic order for inspection.

        Ordering is by creation time and then identifier, so the same
        database state always produces the same sequence.
        """
        if limit < 0 or limit > MAX_INSPECTION_LIMIT:
            raise ConfirmationRecordError("invalid inspection limit")
        if offset < 0:
            raise ConfirmationRecordError("invalid inspection offset")
        statement = (
            select(AssistantConfirmation)
            .order_by(
                AssistantConfirmation.created_at.asc(),
                AssistantConfirmation.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [to_view(record) for record in db.scalars(statement).all()]

    def export_records(
        self,
        db: Session,
        *,
        generated_at: datetime | None = None,
        limit: int = MAX_INSPECTION_LIMIT,
        offset: int = 0,
    ) -> AssistantConfirmationExport:
        """Return a stable, self-describing export of stored records.

        Redacted records appear with ``material_state=REDACTED`` and no
        values; nothing is reconstructed on their behalf.
        """
        records = tuple(self.list_records(db, limit=limit, offset=offset))
        return AssistantConfirmationExport(
            format=CONFIRMATION_EXPORT_FORMAT,
            version=CONFIRMATION_EXPORT_VERSION,
            generated_at=_checked_now(generated_at),
            retention_days=CONFIRMATION_RETENTION_DAYS,
            record_count=len(records),
            records=records,
        )

    # --- guarded lifecycle transitions ------------------------------------

    def _transition(
        self,
        db: Session,
        challenge_id: str,
        *,
        to_status: ConfirmationStatus,
        now: datetime,
        expected_policy_identity: str | None = None,
    ) -> bool:
        """Apply one guarded transition; return True only if it won.

        The predicate carries the state the caller expects (``PENDING``,
        not yet expired, and optionally the stored policy identity), so a
        concurrent caller that already changed the record makes this
        update match zero rows instead of writing over it.
        """
        conditions = [
            AssistantConfirmation.challenge_id == challenge_id,
            AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
            AssistantConfirmation.expires_at > now,
        ]
        if expected_policy_identity is not None:
            conditions.append(
                AssistantConfirmation.policy_identity == expected_policy_identity
            )
        values: dict[str, object] = {
            "status": to_status.value,
            "decided_at": now,
            "terminal_at": now,
            # A decided record can never be confirmed again, so its code
            # verifier is no longer needed and is dropped rather than kept.
            "display_code_hash": None,
            "display_code_salt": None,
        }
        if to_status is ConfirmationStatus.CONSUMED:
            values["consumed_at"] = now
            values.pop("decided_at")
        statement = (
            update(AssistantConfirmation)
            .where(*conditions)
            .values(**values)
            .returning(AssistantConfirmation.id)
        )
        return db.execute(statement).first() is not None

    def consume(
        self,
        db: Session,
        challenge_id: str,
        *,
        expected_policy_identity: str,
        now: datetime | None = None,
    ) -> bool:
        """Spend one pending approval, exactly once, at the current policy.

        ``expected_policy_identity`` must be the fingerprint the caller
        recomputed from the effective policy it is about to evaluate
        against, not a value supplied by a client. When it differs from
        the stored identity the record is invalidated instead of
        consumed, so a rule change cannot leave an old approval usable.
        """
        current = _checked_now(now)
        identity = _checked_identity(expected_policy_identity)
        consumed = self._transition(
            db,
            challenge_id,
            to_status=ConfirmationStatus.CONSUMED,
            now=current,
            expected_policy_identity=identity,
        )
        if consumed:
            return True
        self._invalidate_on_policy_change(
            db, challenge_id, expected_policy_identity=identity, now=current
        )
        return False

    def _invalidate_on_policy_change(
        self,
        db: Session,
        challenge_id: str,
        *,
        expected_policy_identity: str,
        now: datetime,
    ) -> bool:
        """Invalidate a still-pending record whose policy identity moved."""
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.challenge_id == challenge_id,
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
                AssistantConfirmation.policy_identity != expected_policy_identity,
            )
            .values(
                status=ConfirmationStatus.INVALIDATED.value,
                decided_at=now,
                terminal_at=now,
                display_code_hash=None,
                display_code_salt=None,
            )
            .returning(AssistantConfirmation.id)
        )
        return db.execute(statement).first() is not None

    def reject(
        self,
        db: Session,
        challenge_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Reject a pending challenge explicitly."""
        return self._transition(
            db,
            challenge_id,
            to_status=ConfirmationStatus.REJECTED,
            now=_checked_now(now),
        )

    def cancel(
        self,
        db: Session,
        challenge_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Cancel a pending challenge explicitly.

        Cancelling an already decided challenge changes nothing and
        reports that nothing happened; it never revives the record.
        """
        return self._transition(
            db,
            challenge_id,
            to_status=ConfirmationStatus.CANCELLED,
            now=_checked_now(now),
        )

    def invalidate(
        self,
        db: Session,
        challenge_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Invalidate a pending challenge for any fail-closed reason."""
        return self._transition(
            db,
            challenge_id,
            to_status=ConfirmationStatus.INVALIDATED,
            now=_checked_now(now),
        )

    def record_failed_code_attempt(
        self,
        db: Session,
        challenge_id: str,
        *,
        now: datetime | None = None,
    ) -> int | None:
        """Count one wrong display code atomically and return the total.

        The increment and the lockout decision are one statement, so
        concurrent wrong guesses serialize and can never exceed the
        budget. The counter counts failures: reaching the limit sets
        ``LOCKED``, and a correct code entered before that still wins.
        Returns ``None`` when no attempt could be counted (unknown,
        expired, locked, or already decided), which is exactly the
        indistinguishable outcome a guessing caller must see.
        """
        current = _checked_now(now)
        next_attempt = AssistantConfirmation.failed_code_attempts + 1
        locked = next_attempt >= MAX_FAILED_CODE_ATTEMPTS
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.challenge_id == challenge_id,
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
                AssistantConfirmation.expires_at > current,
                AssistantConfirmation.failed_code_attempts < MAX_FAILED_CODE_ATTEMPTS,
            )
            .values(
                failed_code_attempts=next_attempt,
                status=case(
                    (locked, ConfirmationStatus.LOCKED.value),
                    else_=AssistantConfirmation.status,
                ),
                terminal_at=case(
                    (locked, current),
                    else_=AssistantConfirmation.terminal_at,
                ),
                decided_at=case(
                    (locked, current),
                    else_=AssistantConfirmation.decided_at,
                ),
                display_code_hash=case(
                    (locked, null()),
                    else_=AssistantConfirmation.display_code_hash,
                ),
                display_code_salt=case(
                    (locked, null()),
                    else_=AssistantConfirmation.display_code_salt,
                ),
            )
            .returning(AssistantConfirmation.failed_code_attempts)
        )
        row = db.execute(statement).first()
        return None if row is None else row[0]

    def record_outcome(
        self,
        db: Session,
        challenge_id: str,
        outcome: ConfirmationOutcome,
    ) -> bool:
        """Record what is known about execution after consumption.

        Only a consumed record with no recorded outcome can be updated, so
        a result cannot be overwritten and an unconsumed approval cannot
        claim one. ``UNKNOWN_AFTER_CONSUME`` is a legitimate value: a crash
        between consumption and execution is not retried.
        """
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.challenge_id == challenge_id,
                AssistantConfirmation.status == ConfirmationStatus.CONSUMED.value,
                AssistantConfirmation.outcome.is_(None),
            )
            .values(outcome=outcome.value)
            .returning(AssistantConfirmation.id)
        )
        return db.execute(statement).first() is not None

    def expire_overdue(self, db: Session, *, now: datetime | None = None) -> int:
        """Mark every pending record past its deadline as ``EXPIRED``."""
        current = _checked_now(now)
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
                AssistantConfirmation.expires_at <= current,
            )
            .values(
                status=ConfirmationStatus.EXPIRED.value,
                decided_at=current,
                terminal_at=current,
                display_code_hash=None,
                display_code_salt=None,
            )
            .returning(AssistantConfirmation.id)
        )
        return len(db.execute(statement).all())

    # --- retention and redaction ------------------------------------------

    def redact_terminal_records(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        retention_days: int = CONFIRMATION_RETENTION_DAYS,
        limit: int = 500,
    ) -> RedactionResult:
        """Redact terminal records whose retention window has elapsed.

        Runs inside the caller's transaction, is bounded by ``limit``, and
        is idempotent: rows already redacted are excluded, so re-running it
        changes nothing and never rewrites the digest, the timestamps, or
        the decision metadata.
        """
        if retention_days < 0:
            raise ConfirmationRecordError("invalid retention window")
        if limit <= 0:
            raise ConfirmationRecordError("invalid redaction limit")
        current = _checked_now(now)
        cutoff = current - timedelta(days=retention_days)

        statement = (
            select(AssistantConfirmation)
            .where(
                AssistantConfirmation.status.in_(
                    status.value for status in TERMINAL_CONFIRMATION_STATUSES
                ),
                AssistantConfirmation.material_redacted.is_(False),
                AssistantConfirmation.terminal_at.is_not(None),
                AssistantConfirmation.terminal_at <= cutoff,
            )
            .order_by(
                AssistantConfirmation.terminal_at.asc(),
                AssistantConfirmation.id.asc(),
            )
            .limit(limit)
            .with_for_update()
        )
        records = list(db.scalars(statement).all())

        for record in records:
            salt = secrets.token_hex(32)
            digest = hashlib.sha256(
                MATERIAL_DIGEST_CONTEXT
                + b"\x00"
                + bytes.fromhex(salt)
                + b"\x00"
                + canonical_material_values(
                    target=record.target,
                    scope=record.scope,
                    parameters=dict(record.parameters or {}),
                )
            ).hexdigest()
            record.target = None
            record.scope = None
            record.parameters = {}
            record.material_digest = digest
            record.material_digest_salt = salt
            record.material_redacted = True
            record.redacted_at = current

        db.flush()
        return RedactionResult(redacted_count=len(records))

    # --- deletion ---------------------------------------------------------

    def delete_by_ids(
        self, db: Session, record_ids: Sequence[UUID]
    ) -> AssistantConfirmationDeletionResult:
        """Delete the requested confirmation records from the database.

        Deletion removes the record and its material values together; it
        executes nothing, authorizes nothing, and cannot revive a consumed
        approval. The returned count is what the database actually removed.
        """
        ids = list(record_ids)
        if not ids:
            return AssistantConfirmationDeletionResult(deleted_count=0)
        statement = (
            delete(AssistantConfirmation)
            .where(AssistantConfirmation.id.in_(ids))
            .returning(AssistantConfirmation.id)
        )
        return AssistantConfirmationDeletionResult(
            deleted_count=len(db.execute(statement).all())
        )

    def delete_by_challenge_ids(
        self, db: Session, challenge_ids: Sequence[str]
    ) -> AssistantConfirmationDeletionResult:
        """Delete records by the challenge identifiers a caller already holds."""
        ids = list(challenge_ids)
        if not ids:
            return AssistantConfirmationDeletionResult(deleted_count=0)
        statement = (
            delete(AssistantConfirmation)
            .where(AssistantConfirmation.challenge_id.in_(ids))
            .returning(AssistantConfirmation.id)
        )
        return AssistantConfirmationDeletionResult(
            deleted_count=len(db.execute(statement).all())
        )

    def delete_all(self, db: Session) -> AssistantConfirmationDeletionResult:
        """Delete every stored confirmation record, including pending ones."""
        statement = delete(AssistantConfirmation).returning(AssistantConfirmation.id)
        return AssistantConfirmationDeletionResult(
            deleted_count=len(db.execute(statement).all())
        )


__all__ = [
    "AssistantConfirmationRepository",
    "ConfirmationRecordError",
    "MATERIAL_DIGEST_CONTEXT",
    "TERMINAL_CONFIRMATION_STATUSES",
    "material_state",
    "to_view",
]

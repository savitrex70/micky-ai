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
this pass; their expiry belongs to the confirmation lifecycle. A record
that never carried a target, scope, or parameter is ``ABSENT`` and is
left untouched: it has nothing to redact and never receives a digest of
an empty object.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Text, case, cast, delete, func, null, or_, select, update
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

DEFAULT_EXPIRY_SWEEP_LIMIT = 100
"""How many overdue records one maintenance sweep may expire. Bounded."""

MAX_EXPIRY_SWEEP_LIMIT = 1000
"""Upper bound on a single sweep, so no sweep can be unbounded."""

DEFAULT_REDACTION_LIMIT = 500
"""How many terminal records one retention pass redacts by default."""

MAX_REDACTION_LIMIT = 1000
"""Hard cap on a single retention pass, so no pass can be unbounded."""

_HEX_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _has_material_values():
    """SQL predicate: the record ever carried a target, scope, or parameter.

    This is the existing invariant that separates a record that never had
    material values (``ABSENT``) from one whose values are still present.
    It is used to keep absent records out of the retention batch instead
    of inventing a second "already processed" flag; an absent record has
    nothing to redact and therefore never needs to be revisited.
    """
    return or_(
        AssistantConfirmation.target.is_not(None),
        AssistantConfirmation.scope.is_not(None),
        cast(AssistantConfirmation.parameters, Text) != "{}",
    )


class ConfirmationRecordError(ValueError):
    """A confirmation-record operation was refused.

    The message is static and names no operation value, parameter, code,
    or challenge identifier, so a refused call cannot leak the material it
    was asked to store.
    """


def _checked_now(now: datetime | None) -> datetime:
    """Return a trusted, timezone-aware instant for application-level work."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ConfirmationRecordError("a timezone-aware timestamp is required")
    return current.astimezone(UTC)


def _transition_instant(now: datetime | None, db: Session):
    """Use PostgreSQL wall-clock time in production and an aware instant in tests.

    PostgreSQL transaction timestamps can become stale while a confirmation
    is being checked, so production transitions use clock_timestamp() in
    guarded SQL predicates and terminal timestamps. SQLite (used by the fast
    isolated API tests) has no clock_timestamp() function; its equivalent
    path uses a trusted, timezone-aware application instant. Explicit instants
    remain supported for deterministic tests.
    """
    if now is not None:
        return _checked_now(now)
    if db.get_bind().dialect.name == "postgresql":
        return func.clock_timestamp()
    return datetime.now(UTC)


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

    def lock_pending_for_update(
        self, db: Session, challenge_id: str
    ) -> AssistantConfirmation | None:
        """Lock the one pending record for ``challenge_id``, if any.

        ``SELECT ... FOR UPDATE`` serializes every decision that races for
        the same challenge, so a code comparison, a failure increment, and
        a consumption cannot interleave. A record another caller already
        made terminal is not returned, so at most one caller can proceed to
        consume. The lock is held until the caller's transaction ends.
        """
        statement = (
            select(AssistantConfirmation)
            .where(
                AssistantConfirmation.challenge_id == challenge_id,
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
            )
            .with_for_update()
        )
        return db.scalars(statement).first()

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
        database state always produces the same sequence. A page size
        must be positive and within ``MAX_INSPECTION_LIMIT``; an invalid
        limit is rejected here, at the repository boundary, rather than
        surfacing later as a schema-construction error.
        """
        if limit <= 0 or limit > MAX_INSPECTION_LIMIT:
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
        """Return one self-describing page of the stored records.

        Reaching ``limit`` never silently discards records: the page
        reports ``total_record_count``, the ``offset`` it started at, and
        ``has_more``/``next_offset``, so a caller can page through every
        record without guessing offsets and without mistaking a page for
        a complete export. Redacted records appear with
        ``material_state=REDACTED`` and no values; nothing is
        reconstructed on their behalf.
        """
        records = tuple(self.list_records(db, limit=limit, offset=offset))
        total = db.scalar(select(func.count()).select_from(AssistantConfirmation)) or 0
        consumed = offset + len(records)
        has_more = consumed < total
        return AssistantConfirmationExport(
            format=CONFIRMATION_EXPORT_FORMAT,
            version=CONFIRMATION_EXPORT_VERSION,
            generated_at=_checked_now(generated_at),
            retention_days=CONFIRMATION_RETENTION_DAYS,
            total_record_count=total,
            record_count=len(records),
            offset=offset,
            limit=limit,
            has_more=has_more,
            next_offset=consumed if has_more else None,
            is_complete=offset == 0 and not has_more,
            records=records,
        )

    # --- guarded lifecycle transitions ------------------------------------

    def _transition(
        self,
        db: Session,
        challenge_id: str,
        *,
        to_status: ConfirmationStatus,
        now: datetime | None,
        expected_policy_identity: str | None = None,
    ) -> bool:
        """Apply one guarded transition; return True only if it won.

        The predicate carries the state the caller expects (``PENDING``,
        not yet expired, and optionally the stored policy identity), so a
        concurrent caller that already changed the record makes this
        update match zero rows instead of writing over it.

        A transition that matches nothing may have failed only because
        the record is an overdue ``PENDING`` challenge. Rather than
        leaving an expired challenge looking live, this settles it to
        ``EXPIRED`` atomically (see ``_expire_if_overdue``) and still
        reports that the requested transition did not happen.
        """
        instant = _transition_instant(now, db)
        conditions = [
            AssistantConfirmation.challenge_id == challenge_id,
            AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
            AssistantConfirmation.expires_at > instant,
        ]
        if expected_policy_identity is not None:
            conditions.append(
                AssistantConfirmation.policy_identity == expected_policy_identity
            )
        values: dict[str, object] = {
            "status": to_status.value,
            "decided_at": instant,
            "terminal_at": instant,
            # A decided record can never be confirmed again, so its code
            # verifier is no longer needed and is dropped rather than kept.
            "display_code_hash": None,
            "display_code_salt": None,
        }
        if to_status is ConfirmationStatus.CONSUMED:
            values["consumed_at"] = instant
            values.pop("decided_at")
        statement = (
            update(AssistantConfirmation)
            .where(*conditions)
            .values(**values)
            # The guarded predicate is enforced by SQL; ORM synchronization
            # must not re-evaluate it client-side, where SQLite's naive
            # datetimes cannot be compared with the aware instant.
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.id)
        )
        if db.execute(statement).first() is not None:
            return True
        self._expire_if_overdue(db, challenge_id, now)
        return False

    def _expire_if_overdue(
        self, db: Session, challenge_id: str, now: datetime | None
    ) -> bool:
        """Expire an overdue pending challenge using the transition-time clock."""
        instant = _transition_instant(now, db)
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.challenge_id == challenge_id,
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
                AssistantConfirmation.expires_at <= instant,
            )
            .values(
                status=ConfirmationStatus.EXPIRED.value,
                decided_at=instant,
                terminal_at=instant,
                display_code_hash=None,
                display_code_salt=None,
            )
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.id)
        )
        return db.execute(statement).first() is not None

    def expire_if_overdue(
        self, db: Session, challenge_id: str, *, now: datetime | None = None
    ) -> bool:
        """Settle one overdue pending record to ``EXPIRED`` atomically.

        This is the public form of the guarded expiry used inside the
        lifecycle transitions: it only ever matches a record that is still
        ``PENDING`` and genuinely past ``expires_at``, so it can never
        overwrite a terminal state, revive a challenge, or execute
        anything.
        """
        return self._expire_if_overdue(db, challenge_id, now)

    def consume(
        self,
        db: Session,
        challenge_id: str,
        *,
        expected_policy_identity: str,
        now: datetime | None = None,
    ) -> bool:
        """Spend one pending approval at the effective policy, exactly once."""
        transition_time = None if now is None else _checked_now(now)
        identity = _checked_identity(expected_policy_identity)
        consumed = self._transition(
            db,
            challenge_id,
            to_status=ConfirmationStatus.CONSUMED,
            now=transition_time,
            expected_policy_identity=identity,
        )
        if consumed:
            return True
        self._invalidate_on_policy_change(
            db,
            challenge_id,
            expected_policy_identity=identity,
            now=transition_time,
        )
        return False

    def _invalidate_on_policy_change(
        self,
        db: Session,
        challenge_id: str,
        *,
        expected_policy_identity: str,
        now: datetime | None,
    ) -> bool:
        """Invalidate a changed-policy challenge only while it remains live."""
        instant = _transition_instant(now, db)
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.challenge_id == challenge_id,
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
                AssistantConfirmation.expires_at > instant,
                AssistantConfirmation.policy_identity != expected_policy_identity,
            )
            .values(
                status=ConfirmationStatus.INVALIDATED.value,
                decided_at=instant,
                terminal_at=instant,
                display_code_hash=None,
                display_code_salt=None,
            )
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.id)
        )
        changed = db.execute(statement).first() is not None
        if not changed:
            self._expire_if_overdue(db, challenge_id, now)
        return changed

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
            now=now,
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
            now=now,
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
            now=now,
        )

    def record_failed_code_attempt(
        self,
        db: Session,
        challenge_id: str,
        *,
        now: datetime | None = None,
    ) -> int | None:
        """Count one wrong code atomically against the actual transition time.

        The caller holds the challenge row lock while verifying the code.
        This update independently rechecks PENDING, expiry, and the attempt
        budget. If the deadline passed during verification, the attempt is
        not counted and the overdue record is settled to EXPIRED.
        """
        transition_time = None if now is None else _checked_now(now)
        current = _transition_instant(transition_time, db)
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
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.failed_code_attempts)
        )
        row = db.execute(statement).first()
        if row is None:
            self._expire_if_overdue(db, challenge_id, transition_time)
            return None
        return row[0]

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
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.id)
        )
        return db.execute(statement).first() is not None

    def mark_unestablished_outcomes(
        self,
        db: Session,
        *,
        limit: int = DEFAULT_EXPIRY_SWEEP_LIMIT,
    ) -> int:
        """Label consumed records with no established outcome as unknown.

        This is the bounded recovery sweep for the crash window between
        committing consumption and recording an execution result. It only
        *labels* records that already exist as ``UNKNOWN_AFTER_CONSUME``;
        it never executes, retries, reverts, or re-enables anything, so a
        consumed approval whose outcome was never established can never
        trigger an automatic re-execution. Ordered by consumption time then
        identifier so repeated bounded sweeps advance deterministically.
        """
        if limit <= 0 or limit > MAX_EXPIRY_SWEEP_LIMIT:
            raise ConfirmationRecordError("invalid recovery limit")
        candidate_ids = (
            select(AssistantConfirmation.id)
            .where(
                AssistantConfirmation.status == ConfirmationStatus.CONSUMED.value,
                AssistantConfirmation.outcome.is_(None),
            )
            .order_by(
                AssistantConfirmation.consumed_at.asc(),
                AssistantConfirmation.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list(db.scalars(candidate_ids).all())
        if not ids:
            return 0
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.id.in_(ids),
                AssistantConfirmation.status == ConfirmationStatus.CONSUMED.value,
                AssistantConfirmation.outcome.is_(None),
            )
            .values(outcome=ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value)
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.id)
        )
        return len(db.execute(statement).all())

    def expire_overdue(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_EXPIRY_SWEEP_LIMIT,
    ) -> int:
        """Expire up to ``limit`` overdue pending records, deterministically.

        This is the bounded maintenance sweep: one invocation expires no
        more than ``limit`` records, so it is safe to call on startup
        without holding an unbounded transaction open. Ordering is by
        deadline then identifier, so repeated sweeps advance through
        overdue records in a stable order. Candidate rows are selected
        with ``FOR UPDATE SKIP LOCKED`` and the update re-checks
        ``PENDING`` and the deadline, so a sweep races safely with
        concurrent decisions: a record cancelled, rejected, invalidated,
        or consumed first is skipped, and no terminal state is
        overwritten. It runs inside the caller's transaction.
        """
        if limit <= 0 or limit > MAX_EXPIRY_SWEEP_LIMIT:
            raise ConfirmationRecordError("invalid expiry sweep limit")
        current = _transition_instant(now, db)
        candidate_ids = (
            select(AssistantConfirmation.id)
            .where(
                AssistantConfirmation.status == ConfirmationStatus.PENDING.value,
                AssistantConfirmation.expires_at <= current,
            )
            .order_by(
                AssistantConfirmation.expires_at.asc(),
                AssistantConfirmation.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list(db.scalars(candidate_ids).all())
        if not ids:
            return 0
        statement = (
            update(AssistantConfirmation)
            .where(
                AssistantConfirmation.id.in_(ids),
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
            .execution_options(synchronize_session=False)
            .returning(AssistantConfirmation.id)
        )
        return len(db.execute(statement).all())

    # --- retention and redaction ------------------------------------------

    def redact_terminal_records(
        self,
        db: Session,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_REDACTION_LIMIT,
    ) -> RedactionResult:
        """Redact terminal records whose fixed retention window has elapsed.

        The retention window is the owner-approved
        ``CONFIRMATION_RETENTION_DAYS`` (thirty days) and is not a caller
        argument: no ordinary caller can shorten it or redact material
        values early. Runs inside the caller's transaction, is bounded by
        ``limit``, and is idempotent: already-redacted rows are excluded,
        so re-running it changes nothing and never rewrites the digest,
        the timestamps, or the decision metadata.

        ``limit`` must be positive and no larger than
        ``MAX_REDACTION_LIMIT``; an invalid value is rejected rather than
        clamped, so one call can never select, lock, or redact more than
        the hard maximum. Eligible records are ordered deterministically,
        so successive bounded passes process the remainder in order.

        Only records that actually carried a target, scope, or parameter
        are selected. A record that never had material values stays
        ``ABSENT``: it is never given a digest of an empty object, is
        never reported as redacted, and cannot occupy a slot in the
        bounded batch ahead of an older record that still holds values.
        """
        if limit <= 0 or limit > MAX_REDACTION_LIMIT:
            raise ConfirmationRecordError("invalid redaction limit")
        current = _checked_now(now)
        cutoff = current - timedelta(days=CONFIRMATION_RETENTION_DAYS)

        statement = (
            select(AssistantConfirmation)
            .where(
                AssistantConfirmation.status.in_(
                    status.value for status in TERMINAL_CONFIRMATION_STATUSES
                ),
                AssistantConfirmation.material_redacted.is_(False),
                AssistantConfirmation.terminal_at.is_not(None),
                AssistantConfirmation.terminal_at <= cutoff,
                _has_material_values(),
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

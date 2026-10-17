"""Task 224 correction tests: atomic transition expiry and startup recovery.

Companion to ``tests/test_confirmation_flow.py``. Covers the two blockers
raised in the Task 224 review:

  1. A challenge that is still valid when a decision request begins must
     not be consumed, cancelled, or rejected if its five-minute deadline
     passes during code verification or policy evaluation. The atomic
     transition evaluates expiry against PostgreSQL's ``clock_timestamp()``
     in production, so a stale request-start timestamp cannot win. The same
     protection applies to wrong-code counting.
  2. ``run_startup_recovery`` must mark consumed-without-outcome records as
     ``UNKNOWN_AFTER_CONSUME`` and expire overdue pending challenges, be
     bounded, fail closed on database failure, and never execute or retry
     anything.
"""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import AssistantConfirmation
from rop.repositories import assistant_confirmation as repo_module
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository
from rop.schemas.assistant_confirmation import (
    ConfirmationOutcome,
    ConfirmationStatus,
    PendingConfirmationDraft,
)
from rop.schemas.authorization import AuthorizationReason, RiskLevel
from rop.schemas.confirmation import ConfirmationDecision, ConfirmationDecisionStatus
from rop.services.confirmation import (
    CHALLENGE_LIFETIME,
    decide,
    run_startup_recovery,
)

# Fixtures and helpers shared with the main Task 224 test module.
from tests.test_confirmation_flow import (  # noqa: F401  (fixtures)
    NOW,
    WRITE_ID,
    RecordingExecutor,
    _demo_policy,
    _fetch,
    _issue,
    _operation,
    _registry,
    clean_database,
    db,
    pg_engine,
    repository,
)


def _make_session_factory(engine):
    def factory() -> Session:
        return Session(engine)

    return factory


@lru_cache(maxsize=1)
def _identity_for_demo() -> str:
    from rop.authorization.policy import authorization_policy_identity

    return authorization_policy_identity(_demo_policy())


def _force_repo_clock_after(monkeypatch, instant):
    """Make ``_sql_now`` always return ``instant`` regardless of its argument.

    Simulates the challenge's deadline passing between request start and
    the atomic database transition, without sleeping and without disturbing
    the deterministic clock the service still holds for its own fast-path
    check.
    """
    original = repo_module._sql_now

    def fake(now):
        return original(instant)

    monkeypatch.setattr(repo_module, "_sql_now", fake)


# ============================================================================
# Blocker 1: atomic expiry at the transition
# ============================================================================


def test_consume_refuses_when_expiry_passes_at_transition(
    db, pg_engine, monkeypatch
) -> None:
    """Valid at request start, expired at consume => EXPIRED, executor never runs."""
    issued = _issue(db)
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code
    db.commit()

    _force_repo_clock_after(
        monkeypatch, NOW + CHALLENGE_LIFETIME + timedelta(seconds=1)
    )

    executor = RecordingExecutor()
    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        now=NOW,
    )
    db.commit()

    assert result.executed is False
    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0

    record = _fetch(pg_engine, challenge_id)
    assert record is not None
    assert record.status == ConfirmationStatus.EXPIRED.value
    assert record.display_code_hash is None
    assert record.display_code_salt is None
    assert record.consumed_at is None


def test_wrong_code_at_expired_transition_marks_expired_not_locked(
    db, pg_engine, monkeypatch
) -> None:
    issued = _issue(db)
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    db.commit()

    _force_repo_clock_after(
        monkeypatch, NOW + CHALLENGE_LIFETIME + timedelta(seconds=1)
    )

    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code="ZZZZZZ",
        policy=_demo_policy(),
        executors=_registry(WRITE_ID),
        now=NOW,
    )
    db.commit()

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    record = _fetch(pg_engine, challenge_id)
    assert record is not None
    assert record.status == ConfirmationStatus.EXPIRED.value
    assert record.failed_code_attempts == 0
    assert record.display_code_hash is None


def test_cancel_at_expired_transition_marks_expired_not_cancelled(
    db, pg_engine, monkeypatch
) -> None:
    issued = _issue(db)
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    db.commit()

    _force_repo_clock_after(
        monkeypatch, NOW + CHALLENGE_LIFETIME + timedelta(seconds=1)
    )

    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CANCEL,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID),
        now=NOW,
    )
    db.commit()

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    record = _fetch(pg_engine, challenge_id)
    assert record is not None
    assert record.status == ConfirmationStatus.EXPIRED.value


def test_reject_at_expired_transition_marks_expired_not_rejected(
    db, pg_engine, monkeypatch
) -> None:
    issued = _issue(db)
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    db.commit()

    _force_repo_clock_after(
        monkeypatch, NOW + CHALLENGE_LIFETIME + timedelta(seconds=1)
    )

    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.REJECT,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID),
        now=NOW,
    )
    db.commit()

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    record = _fetch(pg_engine, challenge_id)
    assert record is not None
    assert record.status == ConfirmationStatus.EXPIRED.value


def test_consumed_at_persists_with_authoritative_time(db, pg_engine) -> None:
    issued = _issue(db)
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code
    db.commit()

    executor = RecordingExecutor()
    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        now=NOW,
    )
    db.commit()

    assert result.executed is True
    assert executor.call_count == 1
    record = _fetch(pg_engine, challenge_id)
    assert record is not None
    assert record.status == ConfirmationStatus.CONSUMED.value
    assert record.consumed_at is not None
    assert record.outcome == ConfirmationOutcome.SUCCEEDED.value


def test_replay_after_expired_transition_is_refused(db, pg_engine, monkeypatch) -> None:
    issued = _issue(db)
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code
    db.commit()

    _force_repo_clock_after(
        monkeypatch, NOW + CHALLENGE_LIFETIME + timedelta(seconds=1)
    )

    executor = RecordingExecutor()
    first = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        now=NOW,
    )
    db.commit()
    assert first.executed is False
    assert executor.call_count == 0

    second = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        now=NOW,
    )
    db.commit()
    assert second.executed is False
    assert executor.call_count == 0


# ============================================================================
# Blocker 2: startup recovery
# ============================================================================


def _create_consumed_without_outcome(db, *, identity: str) -> str:
    """Create a CONSUMED record with ``outcome=None`` using the real lifecycle."""
    draft = PendingConfirmationDraft(
        operation=_operation(),
        challenge_id=f"consumed-no-outcome-{uuid4().hex[:12]}",
        display_code_hash="f" * 64,
        display_code_salt="e" * 32,
        policy_identity=identity,
        policy_version="1",
        required_risk=RiskLevel.CONSEQUENTIAL,
        required_reason=AuthorizationReason.AUTHORIZATION_REQUIRED,
        expires_at=NOW + CHALLENGE_LIFETIME,
    )
    repo = AssistantConfirmationRepository()
    repo.create_pending(db, draft, now=NOW)
    db.flush()
    consumed = repo.consume(
        db,
        draft.challenge_id,
        expected_policy_identity=identity,
        now=NOW,
    )
    assert consumed, "fixture failed to consume the challenge"
    return draft.challenge_id


def _create_overdue_pending(db, *, identity: str) -> str:
    """Create a PENDING record whose deadline is already in the past."""
    draft = PendingConfirmationDraft(
        operation=_operation(),
        challenge_id=f"overdue-{uuid4().hex[:12]}",
        display_code_hash="a" * 64,
        display_code_salt="b" * 32,
        policy_identity=identity,
        policy_version="1",
        required_risk=RiskLevel.CONSEQUENTIAL,
        required_reason=AuthorizationReason.AUTHORIZATION_REQUIRED,
        expires_at=NOW - timedelta(minutes=5),
    )
    repo = AssistantConfirmationRepository()
    repo.create_pending(db, draft, now=NOW - timedelta(minutes=10))
    return draft.challenge_id


def test_startup_recovery_marks_unknown_and_expires_overdue(
    db, pg_engine, clean_database
) -> None:
    identity = _identity_for_demo()
    consumed_id = _create_consumed_without_outcome(db, identity=identity)
    overdue_id = _create_overdue_pending(db, identity=identity)
    db.commit()

    marked, expired = run_startup_recovery(_make_session_factory(pg_engine))
    assert marked == 1
    assert expired == 1

    with Session(pg_engine) as check:
        consumed = check.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == consumed_id
            )
        ).first()
        assert consumed is not None
        assert consumed.status == ConfirmationStatus.CONSUMED.value
        assert consumed.outcome == ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value
        assert consumed.consumed_at is not None
        # Never fabricated as success.
        assert consumed.outcome != ConfirmationOutcome.SUCCEEDED.value

        overdue = check.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == overdue_id
            )
        ).first()
        assert overdue is not None
        assert overdue.status == ConfirmationStatus.EXPIRED.value
        assert overdue.display_code_hash is None
        assert overdue.display_code_salt is None


def test_startup_recovery_is_bounded(db, pg_engine, clean_database) -> None:
    identity = _identity_for_demo()
    for _ in range(3):
        _create_consumed_without_outcome(db, identity=identity)
    db.commit()

    first_marked, first_expired = run_startup_recovery(
        _make_session_factory(pg_engine), limit=2
    )
    assert first_marked == 2
    assert first_expired == 0

    second_marked, _ = run_startup_recovery(_make_session_factory(pg_engine), limit=2)
    assert second_marked == 1


def test_startup_recovery_preserves_other_terminal_states(
    db, pg_engine, clean_database
) -> None:
    identity = _identity_for_demo()
    cancelled_id = f"cancelled-{uuid4().hex[:12]}"
    draft = PendingConfirmationDraft(
        operation=_operation(),
        challenge_id=cancelled_id,
        display_code_hash="c" * 64,
        display_code_salt="d" * 32,
        policy_identity=identity,
        policy_version="1",
        required_risk=RiskLevel.CONSEQUENTIAL,
        required_reason=AuthorizationReason.AUTHORIZATION_REQUIRED,
        expires_at=NOW + CHALLENGE_LIFETIME,
    )
    repo = AssistantConfirmationRepository()
    repo.create_pending(db, draft, now=NOW)
    db.flush()
    repo.cancel(db, cancelled_id, now=NOW)
    db.commit()

    run_startup_recovery(_make_session_factory(pg_engine))

    with Session(pg_engine) as check:
        record = check.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == cancelled_id
            )
        ).first()
        assert record is not None
        assert record.status == ConfirmationStatus.CANCELLED.value


def test_startup_recovery_session_failure_is_fail_closed() -> None:
    def failing_factory():
        raise RuntimeError("db unreachable")

    marked, expired = run_startup_recovery(failing_factory)
    assert (marked, expired) == (0, 0)


def test_startup_recovery_transaction_failure_rolls_back(
    db, pg_engine, clean_database, monkeypatch
) -> None:
    identity = _identity_for_demo()
    consumed_id = _create_consumed_without_outcome(db, identity=identity)
    db.commit()

    def boom(self, session, **kwargs):
        raise RuntimeError("sweep failed")

    monkeypatch.setattr(
        AssistantConfirmationRepository, "mark_unestablished_outcomes", boom
    )

    marked, expired = run_startup_recovery(_make_session_factory(pg_engine))
    assert (marked, expired) == (0, 0)

    with Session(pg_engine) as check:
        record = check.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == consumed_id
            )
        ).first()
        assert record is not None
        # Rollback means the record was untouched.
        assert record.status == ConfirmationStatus.CONSUMED.value
        assert record.outcome is None

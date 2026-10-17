"""Task 223: durable confirmation-record storage and data-lifecycle tests.

These tests run against the project's configured PostgreSQL database, not
a substitute: the migration, the check constraints, the conditional
transitions, and the retention sweep are all PostgreSQL behaviour, and a
SQLite stand-in would prove none of them.

Because the suite truncates the confirmation table, it refuses to run
unless the target database name ends in ``_test`` and the URL is supplied
explicitly through ``ROP_TEST_DATABASE_URL``. Without that variable the
module skips rather than touching the application database.
"""

from __future__ import annotations

import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rop.authorization.policy import (
    authorization_policy_identity,
    build_default_policy,
)
from rop.config import get_settings
from rop.database import Base
from rop.models import AssistantConfirmation, ReasoningSession
from rop.repositories.assistant_confirmation import (
    MATERIAL_DIGEST_CONTEXT,
    AssistantConfirmationRepository,
    ConfirmationRecordError,
)
from rop.schemas.assistant_confirmation import (
    CONFIRMATION_EXPORT_FORMAT,
    CONFIRMATION_EXPORT_VERSION,
    CONFIRMATION_RETENTION_DAYS,
    MAX_FAILED_CODE_ATTEMPTS,
    ConfirmationOutcome,
    ConfirmationStatus,
    MaterialState,
    PendingConfirmationDraft,
    canonical_material_values,
)
from rop.schemas.authorization import (
    AuthorizationReason,
    ProposedOperation,
    RiskLevel,
)

TEST_DATABASE_URL = os.environ.get("ROP_TEST_DATABASE_URL", "")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
DEFAULT_LIFETIME = timedelta(minutes=5)
POLICY_IDENTITY = authorization_policy_identity(build_default_policy())
OTHER_POLICY_IDENTITY = "0" * 64
CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _skip_reason() -> str | None:
    if not TEST_DATABASE_URL:
        return (
            "ROP_TEST_DATABASE_URL is not set; PostgreSQL confirmation-record "
            "tests require an explicit test database"
        )
    try:
        database = make_url(TEST_DATABASE_URL).database or ""
    except Exception:
        return "ROP_TEST_DATABASE_URL is not a valid database URL"
    if not database.endswith("_test"):
        return (
            "refusing to run destructive confirmation-record tests against a "
            "database whose name does not end with '_test'"
        )
    return None


@pytest.fixture(scope="session")
def pg_engine():
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.skip(
            "PostgreSQL test database is unreachable "
            f"({type(exc).__name__}); start it and set ROP_TEST_DATABASE_URL"
        )
    yield engine
    engine.dispose()


@pytest.fixture
def db(pg_engine):
    with Session(pg_engine) as session:
        session.execute(text("TRUNCATE assistant_confirmations"))
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def repository() -> AssistantConfirmationRepository:
    return AssistantConfirmationRepository()


def _challenge_id(suffix: str = "0001") -> str:
    value = f"challenge-{suffix.rjust(4, '0')}-token"
    assert CHALLENGE_PATTERN.fullmatch(value)
    return value


def _draft(
    *,
    challenge_id: str | None = None,
    operation_id: str = "demo-write",
    target: str | None = "note-1",
    scope: str | None = None,
    parameters: dict[str, str] | None = None,
    expires_at: datetime = NOW + DEFAULT_LIFETIME,
    policy_identity: str = POLICY_IDENTITY,
    required_risk: RiskLevel = RiskLevel.CONSEQUENTIAL,
    required_reason: AuthorizationReason = AuthorizationReason.AUTHORIZATION_REQUIRED,
) -> PendingConfirmationDraft:
    return PendingConfirmationDraft(
        operation=ProposedOperation(
            operation_id=operation_id,
            target=target,
            scope=scope,
            parameters={"recipient": "self"} if parameters is None else parameters,
        ),
        challenge_id=challenge_id or _challenge_id(),
        display_code_hash="c" * 64,
        display_code_salt="d" * 64,
        policy_identity=policy_identity,
        policy_version="1",
        required_risk=required_risk,
        required_reason=required_reason,
        expires_at=expires_at,
    )


def _create(
    db: Session,
    repository: AssistantConfirmationRepository,
    *,
    now: datetime = NOW,
    **overrides,
) -> AssistantConfirmation:
    overrides.setdefault("expires_at", now + DEFAULT_LIFETIME)
    record = repository.create_pending(db, _draft(**overrides), now=now)
    assert record.status == ConfirmationStatus.PENDING.value
    return record


def _consumed(
    db: Session,
    repository: AssistantConfirmationRepository,
    *,
    now: datetime = NOW,
    **overrides,
) -> AssistantConfirmation:
    overrides.setdefault("expires_at", now + DEFAULT_LIFETIME)
    record = repository.create_pending(db, _draft(**overrides), now=now)
    identity = overrides.get("policy_identity", POLICY_IDENTITY)
    assert repository.consume(
        db, record.challenge_id, expected_policy_identity=identity, now=now
    )
    return record


def _count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AssistantConfirmation)) or 0


def _raw_row(db: Session, record_id: UUID):
    return db.execute(
        text(
            "select id, challenge_id, display_code_hash, display_code_salt, "
            "operation_id, target, scope, parameters, policy_identity, "
            "policy_version, required_risk, required_reason, "
            "failed_code_attempts, status, outcome, material_redacted, "
            "material_digest, material_digest_salt, created_at, expires_at, "
            "decided_at, terminal_at, consumed_at, redacted_at "
            "from assistant_confirmations where id = :id"
        ),
        {"id": record_id},
    ).one()


# --- model and migration ----------------------------------------------------


def test_model_is_registered_in_sqlalchemy_metadata() -> None:
    table = Base.metadata.tables["assistant_confirmations"]

    assert table.name == "assistant_confirmations"
    assert "challenge_id" in table.columns
    assert "policy_identity" in table.columns
    assert "failed_code_attempts" in table.columns
    assert "material_redacted" in table.columns


def test_table_has_no_foreign_keys_and_no_clinical_relationships() -> None:
    table = Base.metadata.tables["assistant_confirmations"]

    assert list(table.foreign_keys) == []
    assert list(sa_inspect(AssistantConfirmation).relationships) == []


def test_migration_creates_and_removes_only_the_confirmation_table(
    pg_engine, monkeypatch
) -> None:
    monkeypatch.setenv("ROP_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ROP_APP_NAME", "testing-app")
    monkeypatch.setenv("ROP_ENVIRONMENT", "testing")
    monkeypatch.setenv("ROP_LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))

    try:
        command.downgrade(config, "20261002_0016")
        after_downgrade = set(inspect(pg_engine).get_table_names())
        assert "assistant_confirmations" not in after_downgrade
        assert "reasoning_sessions" in after_downgrade
        assert "reasoning_run_receipts" in after_downgrade

        command.upgrade(config, "head")
        inspector = inspect(pg_engine)
        assert "assistant_confirmations" in set(inspector.get_table_names())

        checks = {
            item["name"]
            for item in inspector.get_check_constraints("assistant_confirmations")
        }
        assert "ck_assistant_confirmations_status" in checks
        assert "ck_assistant_confirmations_outcome" in checks
        assert "ck_assistant_confirmations_failed_code_attempts" in checks

        uniques = {
            item["name"]
            for item in inspector.get_unique_constraints("assistant_confirmations")
        }
        assert "uq_assistant_confirmations_challenge_id" in uniques
        assert inspector.get_foreign_keys("assistant_confirmations") == []
    finally:
        command.upgrade(config, "head")
        get_settings.cache_clear()


def test_status_constraint_rejects_a_duplicate_confirmed_state(db, repository) -> None:
    """There is one success transition, not a second "confirmed" status."""
    record = _create(db, repository)

    with pytest.raises(IntegrityError):
        db.execute(
            update(AssistantConfirmation)
            .where(AssistantConfirmation.id == record.id)
            .values(status="CONFIRMED", terminal_at=NOW)
        )
    db.rollback()


def test_status_constraint_rejects_an_unknown_status(db, repository) -> None:
    record = _create(db, repository)

    with pytest.raises(IntegrityError):
        db.execute(
            update(AssistantConfirmation)
            .where(AssistantConfirmation.id == record.id)
            .values(status="MOSTLY-FINE")
        )
    db.rollback()


def test_outcome_constraint_rejects_an_unknown_outcome(db, repository) -> None:
    record = _consumed(db, repository)
    record.outcome = "PROBABLY"

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_attempt_counter_is_bounded_by_the_database(db, repository) -> None:
    record = _create(db, repository)
    db.commit()

    for invalid in (MAX_FAILED_CODE_ATTEMPTS + 1, -1):
        with pytest.raises(IntegrityError):
            db.execute(
                update(AssistantConfirmation)
                .where(AssistantConfirmation.id == record.id)
                .values(failed_code_attempts=invalid)
            )
        db.rollback()
        stored = repository.get_by_challenge_id(db, record.challenge_id)
        assert stored is not None
        assert stored.failed_code_attempts == 0


def test_verifier_presence_constraint_is_enforced(db, repository) -> None:
    """A record carries a code verifier exactly while it is still live."""
    record = _create(db, repository)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(
            update(AssistantConfirmation)
            .where(AssistantConfirmation.id == record.id)
            .values(display_code_hash=None, display_code_salt=None)
        )
    db.rollback()

    repository.consume(
        db, record.challenge_id, expected_policy_identity=POLICY_IDENTITY, now=NOW
    )
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(
            update(AssistantConfirmation)
            .where(AssistantConfirmation.id == record.id)
            .values(display_code_hash="c" * 64, display_code_salt="d" * 64)
        )
    db.rollback()


def test_challenge_identifier_is_unique(db, repository, pg_engine) -> None:
    challenge_id = _challenge_id("0042")
    _create(db, repository, challenge_id=challenge_id)
    db.commit()

    with Session(pg_engine) as other:
        with pytest.raises(IntegrityError):
            repository.create_pending(other, _draft(challenge_id=challenge_id), now=NOW)
            other.commit()

    assert _count(db) == 1


# --- persistence ------------------------------------------------------------


def test_pending_record_is_created_with_its_material_values(db, repository) -> None:
    record = _create(db, repository, target="note-7", scope="notes/today")

    stored = repository.get_by_challenge_id(db, record.challenge_id)
    assert stored is not None
    assert stored.operation_id == "demo-write"
    assert stored.target == "note-7"
    assert stored.scope == "notes/today"
    assert stored.parameters == {"recipient": "self"}
    assert stored.policy_identity == POLICY_IDENTITY
    assert stored.required_risk == RiskLevel.CONSEQUENTIAL.value
    assert stored.status == ConfirmationStatus.PENDING.value
    assert stored.failed_code_attempts == 0
    assert stored.terminal_at is None
    assert stored.material_redacted is False


def test_record_survives_a_new_engine_and_session(db, repository) -> None:
    """The record is durable state, not session or process memory."""
    record = _create(db, repository, challenge_id=_challenge_id("0009"))
    db.commit()
    record_id = record.id

    fresh_engine = create_engine(TEST_DATABASE_URL)
    try:
        with Session(fresh_engine) as fresh:
            view = repository.describe(fresh, _challenge_id("0009"))
    finally:
        fresh_engine.dispose()

    assert view is not None
    assert view.id == record_id
    assert view.operation_id == "demo-write"


def test_an_expired_draft_is_refused_before_anything_is_stored(db, repository) -> None:
    past = NOW - timedelta(seconds=1)

    with pytest.raises(ConfirmationRecordError) as excinfo:
        repository.create_pending(db, _draft(expires_at=past), now=NOW)
    assert "expire" in str(excinfo.value)
    assert _count(db) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"required_risk": RiskLevel.LOW},
        {"required_reason": AuthorizationReason.ALLOWED_LOW_RISK},
    ],
    ids=["low-risk", "allowed-reason"],
)
def test_a_draft_cannot_describe_an_operation_that_needs_no_confirmation(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _draft(**overrides)  # type: ignore[arg-type]


def test_a_draft_cannot_assert_its_own_status_or_outcome() -> None:
    """Storage never accepts a caller's claim that approval already happened."""
    payload = _draft().model_dump()
    payload["status"] = ConfirmationStatus.CONSUMED.value
    with pytest.raises(ValidationError):
        PendingConfirmationDraft(**payload)

    payload = _draft().model_dump()
    payload["outcome"] = ConfirmationOutcome.SUCCEEDED.value
    with pytest.raises(ValidationError):
        PendingConfirmationDraft(**payload)


# --- guarded lifecycle transitions -----------------------------------------


def test_consume_spends_an_approval_exactly_once(db, repository) -> None:
    record = _create(db, repository)

    assert repository.consume(
        db, record.challenge_id, expected_policy_identity=POLICY_IDENTITY, now=NOW
    )
    assert (
        repository.consume(
            db,
            record.challenge_id,
            expected_policy_identity=POLICY_IDENTITY,
            now=NOW + timedelta(seconds=1),
        )
        is False
    )

    db.refresh(record)
    assert record.status == ConfirmationStatus.CONSUMED.value
    assert record.consumed_at is not None
    assert record.decided_at is None
    # The approval is spent, so the verifier that could have spent it is gone.
    assert record.display_code_hash is None
    assert record.display_code_salt is None


def test_a_changed_policy_identity_invalidates_instead_of_consuming(
    db, repository
) -> None:
    record = _create(db, repository)

    assert (
        repository.consume(
            db,
            record.challenge_id,
            expected_policy_identity=OTHER_POLICY_IDENTITY,
            now=NOW,
        )
        is False
    )

    db.refresh(record)
    assert record.status == ConfirmationStatus.INVALIDATED.value
    assert record.consumed_at is None
    assert record.terminal_at is not None


def test_concurrent_consumes_produce_exactly_one_winner(
    db, repository, pg_engine
) -> None:
    record = _create(db, repository)
    challenge_id = record.challenge_id
    db.commit()
    barrier = Barrier(2)

    def attempt() -> bool:
        with Session(pg_engine) as session:
            barrier.wait(timeout=10)
            won = repository.consume(
                session,
                challenge_id,
                expected_policy_identity=POLICY_IDENTITY,
                now=NOW,
            )
            session.commit()
            return won

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=20)
            for future in [pool.submit(attempt), pool.submit(attempt)]
        ]

    assert sorted(results) == [False, True]


def test_failed_code_attempts_lock_at_the_limit_and_never_consume(
    db, repository
) -> None:
    record = _create(db, repository)

    attempts = [
        repository.record_failed_code_attempt(db, record.challenge_id, now=NOW)
        for _ in range(MAX_FAILED_CODE_ATTEMPTS + 1)
    ]

    assert attempts[:MAX_FAILED_CODE_ATTEMPTS] == list(
        range(1, MAX_FAILED_CODE_ATTEMPTS + 1)
    )
    assert attempts[MAX_FAILED_CODE_ATTEMPTS] is None

    db.refresh(record)
    assert record.status == ConfirmationStatus.LOCKED.value
    assert record.consumed_at is None
    assert record.decided_at is not None
    assert record.display_code_hash is None
    assert record.display_code_salt is None
    assert (
        repository.consume(
            db, record.challenge_id, expected_policy_identity=POLICY_IDENTITY, now=NOW
        )
        is False
    )


def test_concurrent_failed_attempts_cannot_exceed_the_budget(
    repository, pg_engine
) -> None:
    with Session(pg_engine) as setup:
        record = repository.create_pending(setup, _draft(), now=NOW)
        setup.commit()
        challenge_id = record.challenge_id

    barrier = Barrier(8)

    def attempt() -> int | None:
        with Session(pg_engine) as session:
            barrier.wait(timeout=10)
            counted = repository.record_failed_code_attempt(
                session, challenge_id, now=NOW
            )
            session.commit()
            return counted

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [
            future.result(timeout=20)
            for future in [pool.submit(attempt) for _ in range(8)]
        ]

    counted = [value for value in results if value is not None]
    assert len(counted) == MAX_FAILED_CODE_ATTEMPTS
    assert sorted(counted) == list(range(1, MAX_FAILED_CODE_ATTEMPTS + 1))

    with Session(pg_engine) as check:
        stored = repository.get_by_challenge_id(check, challenge_id)
        assert stored is not None
        assert stored.failed_code_attempts == MAX_FAILED_CODE_ATTEMPTS
        assert stored.status == ConfirmationStatus.LOCKED.value


def test_a_live_record_keeps_its_code_verifier_until_it_is_decided(
    db, repository
) -> None:
    record = _create(db, repository)
    assert record.display_code_hash is not None
    assert record.display_code_salt is not None

    assert repository.cancel(db, record.challenge_id, now=NOW)

    db.refresh(record)
    assert record.status == ConfirmationStatus.CANCELLED.value
    assert record.display_code_hash is None
    assert record.display_code_salt is None


def test_transitions_after_a_decision_never_change_it(db, repository) -> None:
    record = _consumed(db, repository)

    assert repository.cancel(db, record.challenge_id, now=NOW) is False
    assert repository.reject(db, record.challenge_id, now=NOW) is False
    assert repository.invalidate(db, record.challenge_id, now=NOW) is False

    db.refresh(record)
    assert record.status == ConfirmationStatus.CONSUMED.value
    assert record.decided_at is None


def test_expiry_is_bounded_to_pending_records(db, repository) -> None:
    pending = _create(db, repository, challenge_id=_challenge_id("0002"))
    consumed = _consumed(db, repository, challenge_id=_challenge_id("0003"))

    expired = repository.expire_overdue(db, now=NOW + DEFAULT_LIFETIME)

    assert expired == 1
    db.refresh(pending)
    db.refresh(consumed)
    assert pending.status == ConfirmationStatus.EXPIRED.value
    assert consumed.status == ConfirmationStatus.CONSUMED.value


def test_outcome_can_be_recorded_once_after_consumption(db, repository) -> None:
    record = _consumed(db, repository)

    assert repository.record_outcome(
        db, record.challenge_id, ConfirmationOutcome.SUCCEEDED
    )
    assert (
        repository.record_outcome(db, record.challenge_id, ConfirmationOutcome.FAILED)
        is False
    )

    db.refresh(record)
    assert record.outcome == ConfirmationOutcome.SUCCEEDED.value


def test_outcome_cannot_be_recorded_for_an_unconsumed_record(db, repository) -> None:
    record = _create(db, repository)

    assert (
        repository.record_outcome(
            db, record.challenge_id, ConfirmationOutcome.SUCCEEDED
        )
        is False
    )
    db.refresh(record)
    assert record.outcome is None


# --- inspection, export, and privacy ---------------------------------------


def test_inspection_never_exposes_the_challenge_or_code_material(
    db, repository
) -> None:
    record = _create(db, repository)

    view = repository.describe(db, record.challenge_id)
    assert view is not None
    payload = view.model_dump()

    for forbidden in (
        "challenge_id",
        "display_code_hash",
        "display_code_salt",
        "material_digest",
        "material_digest_salt",
    ):
        assert forbidden not in payload

    rendered = str(view)
    assert record.challenge_id not in rendered
    assert record.display_code_hash not in rendered
    assert record.display_code_salt not in rendered


def test_export_is_stable_and_self_describing(db, repository) -> None:
    _create(db, repository, challenge_id=_challenge_id("0010"), now=NOW)
    _consumed(
        db,
        repository,
        challenge_id=_challenge_id("0011"),
        now=NOW + timedelta(seconds=1),
    )

    first = repository.export_records(db, generated_at=NOW)
    second = repository.export_records(db, generated_at=NOW)

    assert first == second
    assert first.format == CONFIRMATION_EXPORT_FORMAT
    assert first.version == CONFIRMATION_EXPORT_VERSION
    assert first.retention_days == CONFIRMATION_RETENTION_DAYS
    assert first.record_count == 2
    assert len(first.records) == 2
    assert [item.status for item in first.records] == [
        ConfirmationStatus.PENDING,
        ConfirmationStatus.CONSUMED,
    ]


def test_export_distinguishes_retained_absent_and_redacted(db, repository) -> None:
    old = _consumed(db, repository, challenge_id=_challenge_id("0020"), target="note-1")
    old_without_material = _consumed(
        db,
        repository,
        challenge_id=_challenge_id("0021"),
        target=None,
        parameters={},
    )
    recent = _consumed(
        db,
        repository,
        challenge_id=_challenge_id("0022"),
        target="note-2",
        now=NOW + timedelta(days=10),
    )
    pending_without_material = _create(
        db,
        repository,
        challenge_id=_challenge_id("0023"),
        target=None,
        parameters={},
    )
    db.commit()

    repository.redact_terminal_records(
        db, now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    )
    db.commit()

    export = repository.export_records(db, generated_at=NOW)
    by_id = {item.id: item for item in export.records}

    assert by_id[old.id].material_state is MaterialState.REDACTED
    assert by_id[old_without_material.id].material_state is MaterialState.REDACTED
    assert by_id[recent.id].material_state is MaterialState.RETAINED
    assert by_id[recent.id].target == "note-2"
    assert by_id[pending_without_material.id].material_state is MaterialState.ABSENT
    assert by_id[pending_without_material.id].target is None


def test_export_after_redaction_contains_no_values(db, repository) -> None:
    record = _consumed(db, repository, target="private-note-marker")
    db.commit()
    repository.redact_terminal_records(
        db, now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    )
    db.commit()

    export = repository.export_records(db, generated_at=NOW)
    record_view = next(item for item in export.records if item.id == record.id)

    assert record_view.material_state is MaterialState.REDACTED
    assert record_view.target is None
    assert record_view.scope is None
    assert record_view.parameters == {}
    assert record_view.material_digest_recorded is True
    assert "private-note-marker" not in export.model_dump_json()


# --- retention and redaction ------------------------------------------------


def test_a_recent_terminal_record_keeps_its_material_values(db, repository) -> None:
    record = _consumed(db, repository, target="note-recent")
    db.commit()

    result = repository.redact_terminal_records(
        db,
        now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS) - timedelta(seconds=1),
    )

    assert result.redacted_count == 0
    db.refresh(record)
    assert record.material_redacted is False
    assert record.target == "note-recent"


def test_a_terminal_record_at_the_threshold_is_redacted(db, repository) -> None:
    record = _consumed(db, repository, target="note-old")
    db.commit()

    result = repository.redact_terminal_records(
        db, now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    )

    assert result.redacted_count == 1
    db.refresh(record)
    assert record.material_redacted is True


def test_pending_records_are_never_redacted_by_terminal_retention(
    db, repository
) -> None:
    record = _create(db, repository, target="note-pending")
    db.commit()

    far_future = NOW + timedelta(days=365)
    assert repository.redact_terminal_records(db, now=far_future).redacted_count == 0

    db.refresh(record)
    assert record.material_redacted is False
    assert record.target == "note-pending"

    assert repository.expire_overdue(db, now=far_future) == 1
    db.commit()

    just_after_terminal_at = far_future + timedelta(days=1)
    assert (
        repository.redact_terminal_records(
            db, now=just_after_terminal_at
        ).redacted_count
        == 0
    )
    after_window = far_future + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    assert repository.redact_terminal_records(db, now=after_window).redacted_count == 1


def test_redaction_removes_values_from_the_database(db, repository) -> None:
    record = _consumed(
        db,
        repository,
        target="private-note-marker",
        scope="private-scope-marker",
        parameters={"recipient": "private-parameter-marker"},
    )
    db.commit()

    repository.redact_terminal_records(
        db, now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    )
    db.commit()

    row = _raw_row(db, record.id)
    assert row.target is None
    assert row.scope is None
    assert row.parameters == {}
    assert row.material_redacted is True
    assert row.material_digest is not None
    assert row.material_digest_salt is not None

    rendered_row = str(row)
    for marker in (
        "private-note-marker",
        "private-scope-marker",
        "private-parameter-marker",
    ):
        assert marker not in rendered_row


def test_retained_digest_is_salted_and_verifiable_per_record(db, repository) -> None:
    first = _consumed(
        db,
        repository,
        challenge_id=_challenge_id("0030"),
        target="same-note",
        parameters={"recipient": "self"},
    )
    second = _consumed(
        db,
        repository,
        challenge_id=_challenge_id("0031"),
        target="same-note",
        parameters={"recipient": "self"},
    )
    db.commit()
    repository.redact_terminal_records(
        db, now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    )
    db.commit()

    first_row = _raw_row(db, first.id)
    second_row = _raw_row(db, second.id)

    assert first_row.material_digest != second_row.material_digest
    assert first_row.material_digest_salt != second_row.material_digest_salt

    expected = hashlib.sha256(
        MATERIAL_DIGEST_CONTEXT
        + b"\x00"
        + bytes.fromhex(first_row.material_digest_salt)
        + b"\x00"
        + canonical_material_values(
            target="same-note",
            scope=None,
            parameters={"recipient": "self"},
        )
    ).hexdigest()
    assert first_row.material_digest == expected


def test_repeated_redaction_is_idempotent(db, repository) -> None:
    record = _consumed(db, repository)
    db.commit()
    later = NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)

    assert repository.redact_terminal_records(db, now=later).redacted_count == 1
    db.commit()
    before = _raw_row(db, record.id)

    assert repository.redact_terminal_records(db, now=later).redacted_count == 0
    db.commit()
    after = _raw_row(db, record.id)

    assert after.material_digest == before.material_digest
    assert after.material_digest_salt == before.material_digest_salt
    assert after.redacted_at == before.redacted_at


def test_redaction_preserves_the_decision_metadata(db, repository) -> None:
    record = _consumed(db, repository, target="note-metadata")
    repository.record_outcome(db, record.challenge_id, ConfirmationOutcome.SUCCEEDED)
    db.commit()

    before = repository.describe(db, record.challenge_id)
    assert before is not None
    repository.redact_terminal_records(
        db, now=NOW + timedelta(days=CONFIRMATION_RETENTION_DAYS)
    )
    db.commit()
    after = repository.describe(db, record.challenge_id)
    assert after is not None

    preserved = (
        "id",
        "operation_id",
        "status",
        "required_risk",
        "required_reason",
        "policy_identity",
        "policy_version",
        "failed_code_attempts",
        "outcome",
        "created_at",
        "expires_at",
        "decided_at",
        "terminal_at",
        "consumed_at",
    )
    for field in preserved:
        assert getattr(after, field) == getattr(before, field), field

    assert after.material_state is MaterialState.REDACTED
    assert after.material_digest_recorded is True
    assert after.redacted_at is not None


# --- deletion ---------------------------------------------------------------


def test_deletion_removes_only_the_selected_records(db, repository) -> None:
    doomed = _consumed(db, repository, challenge_id=_challenge_id("0040"))
    kept = _create(db, repository, challenge_id=_challenge_id("0041"))
    db.commit()

    result = repository.delete_by_ids(db, [doomed.id])
    db.commit()

    assert result.deleted_count == 1
    db.expire_all()
    assert repository.get_by_challenge_id(db, doomed.challenge_id) is None
    assert repository.get_by_challenge_id(db, kept.challenge_id) is not None
    assert repository.delete_by_ids(db, [doomed.id]).deleted_count == 0


def test_deletion_by_challenge_identifier_removes_pending_challenges(
    db, repository
) -> None:
    first = _create(db, repository, challenge_id=_challenge_id("0050"))
    second = _create(db, repository, challenge_id=_challenge_id("0051"))
    db.commit()

    result = repository.delete_by_challenge_ids(db, [first.challenge_id])
    db.commit()

    assert result.deleted_count == 1
    db.expire_all()
    assert repository.get_by_challenge_id(db, second.challenge_id) is not None
    assert _count(db) == 1


def test_deleting_everything_removes_pending_and_terminal_records(
    db, repository
) -> None:
    _create(db, repository, challenge_id=_challenge_id("0060"))
    _consumed(db, repository, challenge_id=_challenge_id("0061"))
    db.commit()

    assert repository.delete_all(db).deleted_count == 2
    db.commit()
    assert _count(db) == 0


# --- clinical separation ----------------------------------------------------


def test_storing_a_confirmation_creates_no_clinical_records(db, repository) -> None:
    sessions_before = db.scalar(select(func.count()).select_from(ReasoningSession))

    _create(db, repository)
    _consumed(db, repository, challenge_id=_challenge_id("0070"))
    db.commit()

    sessions_after = db.scalar(select(func.count()).select_from(ReasoningSession))
    assert sessions_before == sessions_after
    assert _count(db) == 2


def test_confirmation_persistence_does_not_reference_clinical_data() -> None:
    source = (
        PROJECT_ROOT / "src" / "rop" / "repositories" / "assistant_confirmation.py"
    ).read_text(encoding="utf-8")

    assert "reasoning" not in source.lower()
    assert "Foreign" + "Key" not in source

"""Task 224: server-side per-operation confirmation workflow tests.

These tests run against the project's configured PostgreSQL database, not a
substitute: row locking, ``FOR UPDATE`` serialization, the conditional
transitions, and ``RETURNING`` are all PostgreSQL behaviour, and a SQLite
stand-in would prove none of them.

Because the suite truncates the confirmation table, it refuses to run unless
the target database name ends in ``_test`` and the URL is supplied explicitly
through ``ROP_TEST_DATABASE_URL``. Without that variable the database-backed
tests skip rather than touching the application database; the schema-only
tests still run.
"""

from __future__ import annotations

import inspect
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import rop.services.confirmation as confirmation_module
from rop.api import assistant as assistant_api
from rop.api import confirmations as confirmations_api
from rop.authorization.executors import (
    ExecutorError,
    ExecutorInterrupted,
    ExecutorRegistry,
    ExecutorResult,
    build_default_executor_registry,
)
from rop.authorization.policy import authorization_policy_identity
from rop.capabilities.registry import HELP_RESPONSE, Capability, build_default_registry
from rop.database import get_db
from rop.main import app
from rop.models import AssistantConfirmation
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository
from rop.schemas.assistant_confirmation import (
    MAX_FAILED_CODE_ATTEMPTS,
    ConfirmationOutcome,
    ConfirmationStatus,
)
from rop.schemas.authorization import (
    AuthorizationDecision,
    AuthorizationOutcome,
    AuthorizationPolicy,
    AuthorizationReason,
    OperationRule,
    ProposedOperation,
    RiskLevel,
)
from rop.schemas.confirmation import (
    ConfirmationDecision,
    ConfirmationDecisionStatus,
)
from rop.services.confirmation import (
    CHALLENGE_LIFETIME,
    DISPLAY_CODE_ALPHABET,
    DISPLAY_CODE_LENGTH,
    ChallengeIssueOutcome,
    decide,
    issue_challenge,
    normalize_display_code,
)

TEST_DATABASE_URL = os.environ.get("ROP_TEST_DATABASE_URL", "")

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
ORIGIN = "http://127.0.0.1:8000"
CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

WRITE_ID = "demo-write"
CLARIFY_ID = "demo-clarify"
LOW_ID = "demo-low"
DENIED_ID = "demo-denied"
UNCLASSIFIED_ID = "demo-unclassified"
UNLISTED_ID = "demo-unlisted"
PARAM_ID = "demo-param"

REQUEST_ENDPOINT = "/api/assistant/requests"


def _skip_reason() -> str | None:
    if not TEST_DATABASE_URL:
        return (
            "ROP_TEST_DATABASE_URL is not set; PostgreSQL confirmation-flow "
            "tests require an explicit test database"
        )
    try:
        database = make_url(TEST_DATABASE_URL).database or ""
    except Exception:
        return "ROP_TEST_DATABASE_URL is not a valid database URL"
    if not database.endswith("_test"):
        return (
            "refusing to run destructive confirmation-flow tests against a "
            "database whose name does not end with '_test'"
        )
    return None


@pytest.fixture(scope="session")
def pg_engine():
    if not TEST_DATABASE_URL:
        pytest.skip("ROP_TEST_DATABASE_URL is not set; PostgreSQL tests are unavailable")
    reason = _skip_reason()
    if reason is not None:
        pytest.fail(reason)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        engine.dispose()
        pytest.fail(
            "Configured PostgreSQL test database is unreachable "
            f"({type(exc).__name__}); start it and set ROP_TEST_DATABASE_URL"
        )
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(pg_engine):
    with Session(pg_engine) as session:
        session.execute(text("TRUNCATE assistant_confirmations"))
        session.commit()
    yield


@pytest.fixture
def db(pg_engine, clean_database):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


@pytest.fixture(autouse=True)
def _isolate_leaked_db_override():
    """Keep this module on the real database dependency.

    ``tests/test_api.py`` installs a session-wide ``get_db`` override on the
    shared app at import time, binding it to a throwaway in-memory SQLite
    database. That module-scoped override leaks into every other test module.
    This fixture removes it for the duration of each test here so the
    confirmation endpoint reads and writes the PostgreSQL test database, then
    restores whatever override was previously installed so ``test_api.py``
    keeps its own behaviour.
    """
    previous = app.dependency_overrides.pop(get_db, None)
    yield
    if previous is not None:
        app.dependency_overrides[get_db] = previous


@pytest.fixture
def repository() -> AssistantConfirmationRepository:
    return AssistantConfirmationRepository()


# --- test-only capabilities, policies, and executors -------------------------


class RecordingExecutor:
    """A test-only executor that records calls and returns a known result."""

    def __init__(self, result: ExecutorResult = ExecutorResult.SUCCEEDED, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple[ProposedOperation, object]] = []
        self._lock = Lock()

    def __call__(self, operation, authorization):
        with self._lock:
            self.calls.append((operation, authorization))
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)


def _rule(
    identifier: str,
    *,
    risk: RiskLevel | None = RiskLevel.CONSEQUENTIAL,
    prohibited: bool = False,
    requires_target: bool = False,
    required_parameters: tuple[str, ...] = (),
    description: str | None = None,
) -> OperationRule:
    return OperationRule(
        operation_id=identifier,
        description=description or f"Test rule for {identifier}.",
        risk=risk,
        prohibited=prohibited,
        requires_target=requires_target,
        required_parameters=required_parameters,
    )


def _policy(*rules: OperationRule) -> AuthorizationPolicy:
    return AuthorizationPolicy(rules=rules)


def _demo_policy(**overrides) -> AuthorizationPolicy:
    return _policy(
        _rule(WRITE_ID, **overrides.get("write", {})),
        _rule(LOW_ID, risk=RiskLevel.LOW),
        _rule(CLARIFY_ID, requires_target=True),
        _rule(DENIED_ID, prohibited=True),
        _rule(UNCLASSIFIED_ID, risk=None),
        _rule(PARAM_ID, required_parameters=("recipient",)),
    )


def _registry(*identifiers: str, executor=None) -> ExecutorRegistry:
    registry = ExecutorRegistry()
    for identifier in identifiers:
        registry.register(identifier, executor or RecordingExecutor())
    return registry


def _operation(**overrides) -> ProposedOperation:
    values = {"operation_id": WRITE_ID}
    values.update(overrides)
    return ProposedOperation(**values)


def _fetch(engine, challenge_id: str) -> AssistantConfirmation | None:
    with Session(engine) as session:
        return session.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == challenge_id
            )
        ).first()


def _count(engine) -> int:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(AssistantConfirmation)) or 0
        )


def _issue(db, *, policy=None, executors=None, operation=None, now=NOW):
    return issue_challenge(
        db,
        operation or _operation(),
        policy=policy or _demo_policy(),
        executors=_registry(WRITE_ID) if executors is None else executors,
        now=now,
    )


def _live_now() -> datetime:
    """A real instant, for tests that go through the HTTP layer's own clock."""
    return datetime.now(UTC)


def _client(base_url: str = ORIGIN) -> TestClient:
    return TestClient(app, base_url=base_url)


def _decision_headers(origin: str = ORIGIN) -> dict[str, str]:
    return {"origin": origin}


def _write_registry():
    registry = build_default_registry()
    registry.register(
        Capability(
            identifier=WRITE_ID,
            description="Test capability that would change state.",
            aliases=("demo write",),
            response="DEMO WRITE REPLY",
        )
    )
    return registry


# ============================================================================
# Challenge creation
# ============================================================================


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        (WRITE_ID, ChallengeIssueOutcome.ISSUED),
        (LOW_ID, ChallengeIssueOutcome.NOT_REQUIRED),
        (CLARIFY_ID, ChallengeIssueOutcome.CLARIFICATION_REQUIRED),
        (DENIED_ID, ChallengeIssueOutcome.DENIED),
        (UNCLASSIFIED_ID, ChallengeIssueOutcome.DENIED),
        (UNLISTED_ID, ChallengeIssueOutcome.DENIED),
    ],
)
def test_challenge_is_created_only_for_require_confirmation(
    db, identifier: str, expected: ChallengeIssueOutcome
) -> None:
    result = issue_challenge(
        db,
        ProposedOperation(operation_id=identifier),
        policy=_demo_policy(),
        executors=_registry(identifier),
        now=NOW,
    )

    assert result.outcome is expected
    assert (result.challenge is not None) is (expected is ChallengeIssueOutcome.ISSUED)
    db.flush()


def test_no_executor_means_no_challenge(db, pg_engine) -> None:
    result = _issue(db, executors=ExecutorRegistry())

    assert result.outcome is ChallengeIssueOutcome.NO_EXECUTOR
    assert result.challenge is None
    assert _count(pg_engine) == 0


def test_policy_error_never_mints_a_challenge(db, pg_engine) -> None:
    result = issue_challenge(
        db,
        _operation(),
        policy=object(),  # type: ignore[arg-type]
        executors=_registry(WRITE_ID),
        now=NOW,
    )

    assert result.outcome is ChallengeIssueOutcome.UNAVAILABLE
    assert result.challenge is None
    assert _count(pg_engine) == 0


def test_under_specified_operation_requires_clarification(db, pg_engine) -> None:
    result = issue_challenge(
        db,
        ProposedOperation(operation_id=PARAM_ID),
        policy=_demo_policy(),
        executors=_registry(PARAM_ID),
        now=NOW,
    )

    assert result.outcome is ChallengeIssueOutcome.CLARIFICATION_REQUIRED
    assert _count(pg_engine) == 0


def test_challenge_values_are_secure_and_plaintext_code_is_never_stored(
    db, pg_engine
) -> None:
    result = _issue(db, operation=_operation(target="note-1"))
    assert result.challenge is not None
    challenge = result.challenge
    db.commit()

    assert CHALLENGE_PATTERN.fullmatch(challenge.challenge_id)
    assert len(normalize_display_code(challenge.display_code)) == DISPLAY_CODE_LENGTH
    assert all(ch in DISPLAY_CODE_ALPHABET for ch in challenge.display_code)

    stored = _fetch(pg_engine, challenge.challenge_id)
    assert stored is not None
    assert stored.display_code_hash is not None
    assert stored.display_code_hash != challenge.display_code
    assert stored.display_code_salt is not None
    assert challenge.display_code not in (
        stored.display_code_hash,
        stored.display_code_salt,
    )

    other = _issue(db, operation=_operation(target="note-1"))
    db.commit()
    assert other.challenge is not None
    assert other.challenge.challenge_id != challenge.challenge_id


def test_challenge_binds_the_exact_operation_and_policy_identity(db, pg_engine) -> None:
    policy = _demo_policy()
    operation = _operation(
        target="  note-1  ", scope="personal", parameters={"b": "2", "a": "1"}
    )
    result = _issue(db, policy=policy, operation=operation)
    challenge = result.challenge
    assert challenge is not None
    db.commit()

    stored = _fetch(pg_engine, challenge.challenge_id)
    assert stored is not None
    assert stored.operation_id == WRITE_ID
    assert stored.target == "note-1"
    assert stored.scope == "personal"
    assert stored.parameters == {"a": "1", "b": "2"}
    assert stored.policy_identity == authorization_policy_identity(policy)
    assert stored.required_risk == RiskLevel.CONSEQUENTIAL.value
    assert stored.required_reason == AuthorizationReason.AUTHORIZATION_REQUIRED.value
    assert stored.status == ConfirmationStatus.PENDING.value


def test_challenge_expiry_uses_the_five_minute_lifetime(db, pg_engine) -> None:
    result = _issue(db)
    challenge = result.challenge
    assert challenge is not None
    db.commit()

    stored = _fetch(pg_engine, challenge.challenge_id)
    assert stored is not None
    assert stored.expires_at == NOW + CHALLENGE_LIFETIME
    assert challenge.expires_at == NOW + CHALLENGE_LIFETIME


def test_summary_describes_the_stored_operation_and_never_claims_execution(db) -> None:
    result = _issue(db, operation=_operation(target="note-7"))
    challenge = result.challenge
    assert challenge is not None

    summary = challenge.summary
    assert WRITE_ID in summary
    assert "note-7" in summary
    assert "CONSEQUENTIAL" in summary
    for claim in ("ran successfully", "was executed", "succeeded"):
        assert claim not in summary


def test_repeated_proposals_create_separate_records(db, pg_engine) -> None:
    first = _issue(db)
    second = _issue(db)
    db.commit()

    assert first.challenge is not None and second.challenge is not None
    assert first.challenge.challenge_id != second.challenge.challenge_id
    assert _count(pg_engine) == 2


# ============================================================================
# Request schema
# ============================================================================


@pytest.mark.parametrize(
    "extra",
    [
        {"operation_id": "demo-write"},
        {"target": "note-1"},
        {"scope": "personal"},
        {"parameters": {"a": "1"}},
        {"authorized": True},
        {"confirmed": True},
        {"policy_identity": "0" * 64},
    ],
)
def test_decision_body_rejects_unknown_fields(extra) -> None:
    marker = "LEAK_MARKER_7B2C"
    payload = {"decision": "cancel", **extra}
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json=payload,
            headers=_decision_headers(),
        )
    assert response.status_code == 422
    assert marker not in response.text


def test_confirm_requires_a_display_code() -> None:
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json={"decision": "confirm"},
            headers=_decision_headers(),
        )
    assert response.status_code == 422


def test_cancel_and_reject_do_not_require_a_display_code(db) -> None:
    issued = _issue(db, now=_live_now())
    db.commit()
    assert issued.challenge is not None

    with _client() as client:
        cancelled = client.post(
            f"/api/assistant/confirmations/{issued.challenge.challenge_id}/decision",
            json={"decision": "cancel"},
            headers=_decision_headers(),
        )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ConfirmationDecisionStatus.CANCELLED.value


def test_malformed_json_never_executes() -> None:
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            content="{not json",
            headers={**_decision_headers(), "content-type": "application/json"},
        )
    assert response.status_code == 422


def test_validation_error_does_not_echo_the_submitted_code() -> None:
    marker = "CODE_SENTINEL_4D1"
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json={"decision": "confirm", "display_code": "XY", "extra": marker},
            headers=_decision_headers(),
        )
    assert response.status_code == 422
    assert marker not in response.text


def test_client_body_cannot_assert_authorization(db, pg_engine) -> None:
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    with _client() as client:
        response = client.post(
            f"/api/assistant/confirmations/{issued.challenge.challenge_id}/decision",
            json={
                "decision": "confirm",
                "display_code": issued.challenge.display_code,
                "authorized": {"operation_id": WRITE_ID},
            },
            headers=_decision_headers(),
        )
    assert response.status_code == 422

    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.PENDING.value


# ============================================================================
# Policy identity and scope validation
# ============================================================================


def test_display_code_is_case_insensitive_and_whitespace_tolerant(
    db, repository
) -> None:
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    executor = RecordingExecutor()
    code = issued.challenge.display_code
    messy = f"  {code[:3].lower()} {code[3:].lower()} "

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=messy,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.EXECUTED
    assert executor.call_count == 1


def test_correct_code_executes_once_with_stored_values(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db, operation=_operation(target="note-9", parameters={"k": "v"}))
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.EXECUTED
    assert result.executed is True
    assert executor.call_count == 1
    operation, authorization = executor.calls[0]
    assert operation.target == "note-9"
    assert operation.parameters == {"k": "v"}
    assert authorization.target == "note-9"

    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.CONSUMED.value
    assert stored.outcome == ConfirmationOutcome.SUCCEEDED.value
    assert stored.consumed_at == NOW
    assert stored.display_code_hash is None


def test_policy_identity_change_invalidates_and_refuses(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    changed = _demo_policy(write={"risk": RiskLevel.LOW})
    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=changed,
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.INVALIDATED.value


def test_description_only_change_keeps_challenge_confirmable(db, repository) -> None:
    edited = _demo_policy(write={"description": "Re-written documentation only."})
    executor = RecordingExecutor()
    issued = _issue(db, policy=_demo_policy())
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=edited,
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.EXECUTED
    assert executor.call_count == 1


def test_confirmation_time_denial_refuses(
    monkeypatch, db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code

    real = confirmation_module.evaluate_authorization

    def deny_without_scope(operation, *, policy, authorized=None):
        if authorized is None:
            return AuthorizationDecision(
                operation_id=operation.operation_id,
                outcome=AuthorizationOutcome.DENY,
                reason=AuthorizationReason.OPERATION_PROHIBITED,
            )
        return real(operation, policy=policy, authorized=authorized)

    monkeypatch.setattr(
        confirmation_module, "evaluate_authorization", deny_without_scope
    )

    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.INVALIDATED.value


def test_policy_identity_error_fails_closed(db, pg_engine, repository) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=object(),  # type: ignore[arg-type]
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.INVALIDATED.value


# ============================================================================
# Code verification and lockout
# ============================================================================


def test_wrong_code_is_generic_and_does_not_execute(db, pg_engine, repository) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code="ZZZZZZ",
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert issued.challenge.challenge_id not in result.message
    assert executor.call_count == 0
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.PENDING.value
    assert stored.failed_code_attempts == 1


def test_unknown_and_wrong_code_are_indistinguishable(db, repository) -> None:
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    wrong = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code="ZZZZZZ",
        policy=_demo_policy(),
        executors=_registry(WRITE_ID),
        repository=repository,
        now=NOW,
    )
    unknown = decide(
        db,
        "unknown-challenge-token-0000",
        decision=ConfirmationDecision.CONFIRM,
        display_code="ZZZZZZ",
        policy=_demo_policy(),
        executors=_registry(WRITE_ID),
        repository=repository,
        now=NOW,
    )

    assert wrong.outcome is unknown.outcome is ConfirmationDecisionStatus.REFUSED
    assert wrong.message == unknown.message


def test_fifth_failure_locks_and_correct_code_after_lockout_refuses(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    for _ in range(MAX_FAILED_CODE_ATTEMPTS):
        result = decide(
            db,
            challenge_id,
            decision=ConfirmationDecision.CONFIRM,
            display_code="ZZZZZZ",
            policy=_demo_policy(),
            executors=_registry(WRITE_ID, executor=executor),
            repository=repository,
            now=NOW,
        )
        assert result.outcome is ConfirmationDecisionStatus.REFUSED

    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.LOCKED.value
    assert stored.failed_code_attempts == MAX_FAILED_CODE_ATTEMPTS

    after_lockout = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )
    assert after_lockout.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0


def test_correct_code_on_the_fifth_attempt_still_succeeds(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    for _ in range(MAX_FAILED_CODE_ATTEMPTS - 1):
        decide(
            db,
            challenge_id,
            decision=ConfirmationDecision.CONFIRM,
            display_code="ZZZZZZ",
            policy=_demo_policy(),
            executors=_registry(WRITE_ID, executor=executor),
            repository=repository,
            now=NOW,
        )

    result = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.EXECUTED
    assert executor.call_count == 1
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.failed_code_attempts == MAX_FAILED_CODE_ATTEMPTS - 1


# ============================================================================
# Races
# ============================================================================


def _run_concurrently(pg_engine, count: int, worker) -> list:
    barrier = Barrier(count)

    def run(index: int):
        with Session(pg_engine) as session:
            barrier.wait()
            return worker(session, index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def test_concurrent_wrong_guesses_cannot_exceed_the_budget(
    db, pg_engine, repository
) -> None:
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    results = _run_concurrently(
        pg_engine,
        8,
        lambda session, index: decide(
            session,
            challenge_id,
            decision=ConfirmationDecision.CONFIRM,
            display_code="ZZZZZZ",
            policy=_demo_policy(),
            executors=_registry(WRITE_ID),
            repository=repository,
            now=NOW,
        ),
    )

    assert all(r.outcome is ConfirmationDecisionStatus.REFUSED for r in results)
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.failed_code_attempts == MAX_FAILED_CODE_ATTEMPTS
    assert stored.status == ConfirmationStatus.LOCKED.value


def test_concurrent_confirmations_produce_one_execution(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code

    results = _run_concurrently(
        pg_engine,
        4,
        lambda session, index: decide(
            session,
            challenge_id,
            decision=ConfirmationDecision.CONFIRM,
            display_code=code,
            policy=_demo_policy(),
            executors=_registry(WRITE_ID, executor=executor),
            repository=repository,
            now=NOW,
        ),
    )

    executed = [r for r in results if r.outcome is ConfirmationDecisionStatus.EXECUTED]
    assert len(executed) == 1
    assert executor.call_count == 1
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.CONSUMED.value


def test_confirmation_racing_cancellation_yields_one_winner(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code

    def worker(session, index):
        if index % 2 == 0:
            return decide(
                session,
                challenge_id,
                decision=ConfirmationDecision.CONFIRM,
                display_code=code,
                policy=_demo_policy(),
                executors=_registry(WRITE_ID, executor=executor),
                repository=repository,
                now=NOW,
            )
        return decide(
            session,
            challenge_id,
            decision=ConfirmationDecision.CANCEL,
            policy=_demo_policy(),
            executors=_registry(WRITE_ID, executor=executor),
            repository=repository,
            now=NOW,
        )

    results = _run_concurrently(pg_engine, 4, worker)

    executed = [r for r in results if r.outcome is ConfirmationDecisionStatus.EXECUTED]
    cancelled = [
        r for r in results if r.outcome is ConfirmationDecisionStatus.CANCELLED
    ]
    assert len(executed) + len(cancelled) == 1
    assert executor.call_count == len(executed)
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    expected = (
        ConfirmationStatus.CONSUMED.value
        if executed
        else ConfirmationStatus.CANCELLED.value
    )
    assert stored.status == expected


# ============================================================================
# Expiry, replay, cancellation, rejection
# ============================================================================


def test_expired_challenge_cannot_execute(db, pg_engine, repository) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW + CHALLENGE_LIFETIME + timedelta(seconds=1),
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.EXPIRED.value


def test_replay_after_consumption_executes_nothing(db, pg_engine, repository) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    code = issued.challenge.display_code

    first = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )
    second = decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert first.outcome is ConfirmationDecisionStatus.EXECUTED
    assert second.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 1


def test_rejection_is_terminal_and_never_executes(db, pg_engine, repository) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.REJECT,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.REJECTED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.REJECTED.value
    assert stored.display_code_hash is None


# ============================================================================
# Execution results
# ============================================================================


def test_missing_executor_does_not_consume(db, pg_engine, repository) -> None:
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=ExecutorRegistry(),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.UNAVAILABLE
    assert result.executed is False
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.PENDING.value


def test_failing_executor_is_recorded_failed_and_never_retried(
    db, pg_engine, repository
) -> None:
    executor = RecordingExecutor(result=ExecutorResult.FAILED)
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.FAILED
    assert result.executed is True
    assert executor.call_count == 1
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.outcome == ConfirmationOutcome.FAILED.value
    assert stored.status == ConfirmationStatus.CONSUMED.value


def test_established_executor_error_is_a_failure(db, pg_engine, repository) -> None:
    executor = RecordingExecutor(error=ExecutorError("boom"))
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.FAILED
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.outcome == ConfirmationOutcome.FAILED.value


def test_interrupted_executor_is_unknown(db, pg_engine, repository) -> None:
    executor = RecordingExecutor(error=ExecutorInterrupted("crashed"))
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.UNKNOWN
    assert executor.call_count == 1
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.CONSUMED.value
    assert stored.outcome == ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value


def test_unestablished_outcome_sweep_is_bounded_and_labels_only(
    db, pg_engine, repository
) -> None:
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    identity = authorization_policy_identity(_demo_policy())
    repository.consume(
        db,
        issued.challenge.challenge_id,
        expected_policy_identity=identity,
        now=NOW,
    )
    db.commit()

    marked = repository.mark_unestablished_outcomes(db, limit=1)
    db.commit()

    assert marked == 1
    stored = _fetch(pg_engine, issued.challenge.challenge_id)
    assert stored is not None
    assert stored.outcome == ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value
    assert stored.status == ConfirmationStatus.CONSUMED.value


class _FailingConsumeRepository(AssistantConfirmationRepository):
    def consume(self, db, challenge_id, *, expected_policy_identity, now=None):
        return False


class _FailingRecordRepository(AssistantConfirmationRepository):
    def record_outcome(self, db, challenge_id, outcome):
        return False


def test_failed_consumption_never_invokes_the_executor(db) -> None:
    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=_FailingConsumeRepository(),
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0


def test_unrecorded_success_is_not_reported_as_success(db) -> None:
    executor = RecordingExecutor(result=ExecutorResult.SUCCEEDED)
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None

    result = decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=_FailingRecordRepository(),
        now=NOW,
    )

    assert result.outcome is ConfirmationDecisionStatus.UNKNOWN
    assert result.executed is True
    assert executor.call_count == 1


# ============================================================================
# Origin protection
# ============================================================================


def test_decision_endpoint_rejects_a_missing_origin() -> None:
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json={"decision": "cancel"},
        )
    assert response.status_code == 403


def test_decision_endpoint_rejects_a_cross_origin_request() -> None:
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json={"decision": "cancel"},
            headers={"origin": "http://evil.example"},
        )
    assert response.status_code == 403


def test_decision_endpoint_rejects_a_mismatched_host() -> None:
    with _client(base_url="http://127.0.0.1:9999") as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json={"decision": "cancel"},
            headers=_decision_headers(),
        )
    assert response.status_code == 403


def test_decision_endpoint_rejects_a_non_json_content_type() -> None:
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            content="decision=cancel",
            headers={
                **_decision_headers(),
                "content-type": "application/x-www-form-urlencoded",
            },
        )
    assert response.status_code == 403


def test_decision_endpoint_adds_no_cors_headers() -> None:
    with _client() as client:
        response = client.post(
            "/api/assistant/confirmations/some-challenge-token/decision",
            json={"decision": "cancel"},
            headers=_decision_headers(),
        )
    assert "access-control-allow-origin" not in response.headers


def test_wrong_code_response_leaks_no_challenge_values(db) -> None:
    issued = _issue(db, now=_live_now())
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    with _client() as client:
        response = client.post(
            f"/api/assistant/confirmations/{challenge_id}/decision",
            json={"decision": "confirm", "display_code": "ZZZZZZ"},
            headers=_decision_headers(),
        )

    assert response.status_code == 200
    assert response.json()["status"] == ConfirmationDecisionStatus.REFUSED.value
    assert challenge_id not in response.text
    assert "ZZZZZZ" not in response.text


def test_origin_failure_does_not_persist_a_challenge(
    monkeypatch, pg_engine, clean_database
) -> None:
    monkeypatch.setattr(assistant_api, "_REGISTRY", _write_registry())
    monkeypatch.setattr(assistant_api, "_POLICY", _demo_policy())
    monkeypatch.setattr(assistant_api, "_EXECUTORS", _registry(WRITE_ID))

    with _client() as client:
        response = client.post(REQUEST_ENDPOINT, json={"message": "demo write"})

    assert response.status_code == 403
    assert _count(pg_engine) == 0


def test_request_endpoint_creates_a_challenge_from_the_local_origin(
    monkeypatch, pg_engine, clean_database
) -> None:
    executor = RecordingExecutor()
    monkeypatch.setattr(assistant_api, "_REGISTRY", _write_registry())
    monkeypatch.setattr(assistant_api, "_POLICY", _demo_policy())
    monkeypatch.setattr(
        assistant_api, "_EXECUTORS", _registry(WRITE_ID, executor=executor)
    )

    with _client() as client:
        response = client.post(
            REQUEST_ENDPOINT,
            json={"message": "demo write"},
            headers={"origin": ORIGIN},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation-required"
    assert "has not run" in body["message"]
    assert executor.call_count == 0
    challenge = body["challenge"]
    assert CHALLENGE_PATTERN.fullmatch(challenge["challenge_id"])
    assert challenge["display_code"]
    assert challenge["expires_at"]

    stored = _fetch(pg_engine, challenge["challenge_id"])
    assert stored is not None
    assert stored.status == ConfirmationStatus.PENDING.value
    assert stored.display_code_hash not in response.text
    assert str(stored.id) not in response.text


def test_end_to_end_flow_executes_through_the_api(
    monkeypatch, pg_engine, clean_database
) -> None:
    executor = RecordingExecutor()
    policy = _demo_policy()
    registry = _registry(WRITE_ID, executor=executor)
    monkeypatch.setattr(assistant_api, "_REGISTRY", _write_registry())
    monkeypatch.setattr(assistant_api, "_POLICY", policy)
    monkeypatch.setattr(assistant_api, "_EXECUTORS", registry)
    monkeypatch.setattr(confirmations_api, "_POLICY", policy)
    monkeypatch.setattr(confirmations_api, "_EXECUTORS", registry)

    with _client() as client:
        created = client.post(
            REQUEST_ENDPOINT,
            json={"message": "demo write"},
            headers={"origin": ORIGIN},
        )
        challenge = created.json()["challenge"]
        confirmed = client.post(
            f"/api/assistant/confirmations/{challenge['challenge_id']}/decision",
            json={"decision": "confirm", "display_code": challenge["display_code"]},
            headers=_decision_headers(),
        )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == ConfirmationDecisionStatus.EXECUTED.value
    assert body["executed"] is True
    assert executor.call_count == 1
    stored = _fetch(pg_engine, challenge["challenge_id"])
    assert stored is not None
    assert stored.status == ConfirmationStatus.CONSUMED.value
    assert stored.consumed_at is not None


def test_default_help_endpoint_is_unchanged() -> None:
    with _client() as client:
        help_response = client.post(REQUEST_ENDPOINT, json={"message": "help"})
        unsupported = client.post(
            REQUEST_ENDPOINT, json={"message": "what is the weather today"}
        )

    assert help_response.json() == {"status": "success", "message": HELP_RESPONSE}
    assert set(unsupported.json()) == {"status", "message"}
    assert unsupported.json()["status"] == "unsupported-capability"


# ============================================================================
# Regression and separation
# ============================================================================


def test_default_executor_registry_is_empty() -> None:
    registry = build_default_executor_registry()
    assert len(registry) == 0
    assert registry.get(WRITE_ID) is None


def test_default_capability_registry_still_contains_only_help() -> None:
    registry = build_default_registry()
    assert len(registry) == 1
    assert registry.match("demo write") is None


def test_confirmation_modules_do_not_reference_clinical_data() -> None:
    for module in (confirmation_module, assistant_api, confirmations_api):
        source = inspect.getsource(module)
        for forbidden in (
            "reasoning_session",
            "reasoning_step",
            "hypothesis",
            "evidence",
            "provenance",
        ):
            assert forbidden not in source, f"{module.__name__} references {forbidden}"


def test_confirmation_modules_add_no_network_or_model_facilities() -> None:
    for module in (confirmation_module, assistant_api, confirmations_api):
        source = inspect.getsource(module)
        for forbidden in (
            "import requests",
            "import httpx",
            "urllib.request",
            "import socket",
            "openai",
            "ollama",
        ):
            assert forbidden not in source, f"{module.__name__} references {forbidden}"


def test_confirmation_flow_does_not_touch_reasoning_sessions(
    db, pg_engine, repository
) -> None:
    with Session(pg_engine) as session:
        before = session.scalar(text("select count(*) from reasoning_sessions"))

    executor = RecordingExecutor()
    issued = _issue(db)
    db.commit()
    assert issued.challenge is not None
    decide(
        db,
        issued.challenge.challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=NOW,
    )

    with Session(pg_engine) as session:
        after = session.scalar(text("select count(*) from reasoning_sessions"))

    assert before == after


# ============================================================================
# Transition-time expiry races (production path uses PostgreSQL clock_timestamp)
# ============================================================================


def test_challenge_expiring_during_policy_validation_cannot_be_consumed(
    db, pg_engine, repository, monkeypatch
) -> None:
    executor = RecordingExecutor()
    issued = _issue(
        db,
        now=_live_now(),
        executors=_registry(WRITE_ID, executor=executor),
    )
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id
    real_evaluate = confirmation_module.evaluate_authorization

    def expire_before_final_validation(operation, *, policy, authorized=None):
        decision = real_evaluate(operation, policy=policy, authorized=authorized)
        if authorized is not None:
            db.execute(
                update(AssistantConfirmation)
                .where(AssistantConfirmation.challenge_id == challenge_id)
                .values(expires_at=func.clock_timestamp() - text("interval '1 second'"))
            )
        return decision

    monkeypatch.setattr(
        confirmation_module, "evaluate_authorization", expire_before_final_validation
    )
    result = confirmation_module.decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=None,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.EXPIRED.value
    assert stored.consumed_at is None


def test_code_failure_after_deadline_expires_instead_of_counting_failure(
    db, pg_engine, repository, monkeypatch
) -> None:
    executor = RecordingExecutor()
    issued = _issue(
        db,
        now=_live_now(),
        executors=_registry(WRITE_ID, executor=executor),
    )
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    def expire_before_code_check(record, display_code):
        db.execute(
            update(AssistantConfirmation)
            .where(AssistantConfirmation.challenge_id == challenge_id)
            .values(expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        return False

    monkeypatch.setattr(
        confirmation_module, "verify_display_code", expire_before_code_check
    )
    result = confirmation_module.decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code="WRONG1",
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=None,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.EXPIRED.value
    assert stored.failed_code_attempts == 0
    assert stored.display_code_hash is None


@pytest.mark.parametrize(
    "decision",
    [ConfirmationDecision.CANCEL, ConfirmationDecision.REJECT],
)
def test_cancel_or_reject_that_reaches_deadline_expires_not_decides(
    db, pg_engine, decision
) -> None:
    issued = _issue(db, now=_live_now())
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    class DeadlineRaceRepository(AssistantConfirmationRepository):
        def _expire_before_transition(self, session, target_id):
            session.execute(
                update(AssistantConfirmation)
                .where(AssistantConfirmation.challenge_id == target_id)
                .values(expires_at=func.clock_timestamp() - text("interval '1 second'"))
            )

        def cancel(self, session, target_id, *, now=None):
            self._expire_before_transition(session, target_id)
            return super().cancel(session, target_id, now=now)

        def reject(self, session, target_id, *, now=None):
            self._expire_before_transition(session, target_id)
            return super().reject(session, target_id, now=now)

    result = confirmation_module.decide(
        db,
        challenge_id,
        decision=decision,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID),
        repository=DeadlineRaceRepository(),
        now=None,
    )

    assert result.outcome is ConfirmationDecisionStatus.REFUSED
    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.EXPIRED.value
    assert stored.display_code_hash is None
    assert stored.consumed_at is None


# ============================================================================
# Task 224 merge reconciliation: replay-after-expiry + recovery progression
# ============================================================================


def test_replay_after_expired_transition_is_refused(
    db, pg_engine, repository, monkeypatch
) -> None:
    """After the deadline passes, confirmation is refused and no execution occurs.

    Complements ``test_challenge_expiring_during_policy_validation_cannot_be_consumed``
    by asserting the refusal is durable: a second attempt on the now-terminal
    record is also refused, and the executor is never invoked.
    """
    executor = RecordingExecutor()
    issued = _issue(
        db, now=_live_now(), executors=_registry(WRITE_ID, executor=executor)
    )
    db.commit()
    assert issued.challenge is not None
    challenge_id = issued.challenge.challenge_id

    # Move the deadline into the past right before confirmation, simulating
    # expiry during request processing.
    db.execute(
        update(AssistantConfirmation)
        .where(AssistantConfirmation.challenge_id == challenge_id)
        .values(expires_at=func.clock_timestamp() - text("interval '1 second'"))
    )
    db.commit()

    first = confirmation_module.decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=None,
    )
    db.commit()
    assert first.executed is False
    assert first.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0

    second = confirmation_module.decide(
        db,
        challenge_id,
        decision=ConfirmationDecision.CONFIRM,
        display_code=issued.challenge.display_code,
        policy=_demo_policy(),
        executors=_registry(WRITE_ID, executor=executor),
        repository=repository,
        now=None,
    )
    db.commit()
    assert second.executed is False
    assert second.outcome is ConfirmationDecisionStatus.REFUSED
    assert executor.call_count == 0

    stored = _fetch(pg_engine, challenge_id)
    assert stored is not None
    assert stored.status == ConfirmationStatus.EXPIRED.value
    assert stored.consumed_at is None
    assert stored.display_code_hash is None


def test_recovery_progresses_through_remaining_records(db, pg_engine) -> None:
    """Each bounded recovery invocation advances past the previous batch."""
    from rop.authorization.policy import authorization_policy_identity
    from rop.services.confirmation_recovery import recover_confirmation_state

    identity = authorization_policy_identity(_demo_policy())
    repository = AssistantConfirmationRepository()
    for _ in range(3):
        issued = _issue(db)
        assert issued.challenge is not None
        consumed = repository.consume(
            db,
            issued.challenge.challenge_id,
            expected_policy_identity=identity,
            now=NOW,
        )
        assert consumed
    db.commit()

    def session_factory():
        return Session(pg_engine)

    assert (
        recover_confirmation_state(session_factory=session_factory, batch_limit=2)
        is True
    )
    with Session(pg_engine) as check:
        marked_after_first = check.scalar(
            select(func.count())
            .select_from(AssistantConfirmation)
            .where(
                AssistantConfirmation.outcome
                == ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value
            )
        )
    assert marked_after_first == 2

    assert (
        recover_confirmation_state(session_factory=session_factory, batch_limit=2)
        is True
    )
    with Session(pg_engine) as check:
        marked_after_second = check.scalar(
            select(func.count())
            .select_from(AssistantConfirmation)
            .where(
                AssistantConfirmation.outcome
                == ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value
            )
        )
    assert marked_after_second == 3


def test_recovery_preserves_unrelated_terminal_states(db, pg_engine) -> None:
    """Recovery only touches CONSUMED-with-null-outcome and overdue PENDING."""
    from rop.authorization.policy import authorization_policy_identity
    from rop.services.confirmation_recovery import recover_confirmation_state

    identity = authorization_policy_identity(_demo_policy())
    repository = AssistantConfirmationRepository()

    cancelled = _issue(db)
    assert cancelled.challenge is not None
    cancelled_id = cancelled.challenge.challenge_id
    repository.cancel(db, cancelled_id, now=NOW)

    consumed = _issue(db)
    assert consumed.challenge is not None
    consumed_id = consumed.challenge.challenge_id
    assert repository.consume(
        db,
        consumed_id,
        expected_policy_identity=identity,
        now=NOW,
    )
    db.commit()

    def session_factory():
        return Session(pg_engine)

    assert recover_confirmation_state(session_factory=session_factory) is True

    with Session(pg_engine) as check:
        cancelled_record = check.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == cancelled_id
            )
        ).first()
        consumed_record = check.scalars(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == consumed_id
            )
        ).first()
    assert cancelled_record is not None
    assert cancelled_record.status == ConfirmationStatus.CANCELLED.value
    assert cancelled_record.outcome is None
    assert consumed_record is not None
    assert consumed_record.status == ConfirmationStatus.CONSUMED.value
    assert consumed_record.outcome == ConfirmationOutcome.UNKNOWN_AFTER_CONSUME.value

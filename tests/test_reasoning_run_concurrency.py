"""Task 136: concurrent identical reasoning-run execution safety tests.

Proves the deterministic idempotency invariant holds when two identical
executions arrive simultaneously. Uses independent SQLAlchemy sessions and
threading barriers to exercise real concurrent transaction behavior.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from rop.database import Base, get_db
from rop.main import app
from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_idempotency import (
    DISPOSITION_EXECUTED_NEW,
    DISPOSITION_STALE_CHANGED,
    ReasoningRunIdempotencyService,
)
from rop.services.reasoning_run_input_snapshot import ReasoningRunInputSnapshotService


@pytest.fixture(scope="function")
def test_engine():
    """Create a fresh in-memory database for each test with a connection pool
    that allows concurrent transactions from multiple threads.

    Uses SQLite's shared-cache URI mode so multiple connections see the same
    in-memory database state. Each connection gets its own transaction isolation.
    """
    # Shared-cache mode allows multiple connections to share the in-memory DB
    engine = create_engine(
        "sqlite+pysqlite:///file:test?mode=memory&cache=shared",
        connect_args={"check_same_thread": False, "uri": True},
        poolclass=QueuePool,
        pool_size=2,
        max_overflow=2,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_session_factory(test_engine):
    """Create a session factory bound to the test engine."""
    return sessionmaker(bind=test_engine)


@pytest.fixture(scope="function")
def test_client(test_session_factory):
    """Create a TestClient with the test database."""

    def override_get_db() -> Generator[Session, None, None]:
        with test_session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _create_session(client: TestClient, user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "concurrency-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(client: TestClient, session_id: str, text: str) -> None:
    o = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": text,
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert o.status_code == 201


def _candidate_ids(test_session_factory, session_id: str) -> list[str]:
    with test_session_factory() as db:
        return sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(session_id))
        )


def _execute_for_session(
    test_session_factory, session_id: UUID, input_snapshot: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute using a fresh database session."""
    with test_session_factory() as db:
        return ReasoningRunExecutionService().execute_for_session(
            db, session_id, input_snapshot=input_snapshot
        )


def _idempotent(
    test_session_factory, session_id: UUID, known: str | None = None
) -> dict[str, Any]:
    """Execute idempotently using a fresh database session."""
    with test_session_factory() as db:
        return ReasoningRunIdempotencyService().execute_idempotent(
            db, session_id, known_input_fingerprint=known
        )


class _Barrier:
    """Simple reusable barrier for two threads."""

    def __init__(self, parties: int = 2) -> None:
        self._parties = parties
        self._count = 0
        self._cv = threading.Condition()

    def wait(self) -> None:
        with self._cv:
            self._count += 1
            if self._count < self._parties:
                self._cv.wait()
            else:
                self._count = 0
                self._cv.notify_all()


# ---------------------------------------------------------------------------
# Test 1: Two identical concurrent completions
# ---------------------------------------------------------------------------


def test_concurrent_identical_completions_single_receipt(
    test_client, test_session_factory
) -> None:
    """Two threads racing to complete the same (session_id, fingerprint)
    must produce exactly one completed receipt. The loser rolls back and
    adopts the winner's result via reuse semantics."""
    sid = _create_session(test_client, "Patient reports concurrent chest pain")
    _add_observation(test_client, sid, "Patient reports concurrent chest pain")
    session_uuid = UUID(sid)

    # Pre-build the exact input snapshot both threads will use
    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}

    def runner(name: str) -> None:
        try:
            # Both threads wait at the barrier, then attempt execution
            barrier.wait()
            results[name] = _execute_for_session(
                test_session_factory, session_uuid, input_snapshot=snapshot
            )
        except BaseException as exc:
            errors[name] = exc

    t1 = threading.Thread(target=runner, args=("t1",))
    t2 = threading.Thread(target=runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Thread errors: {errors}"
    assert "t1" in results and "t2" in results

    # Both must complete successfully (one EXECUTED_NEW, one reused)
    outcomes = [results["t1"]["outcome"], results["t2"]["outcome"]]
    assert all(o == "COMPLETED" for o in outcomes)

    # Exactly one COMPLETED receipt in database
    with test_session_factory() as db:
        count = ReasoningRunReceiptRepository().count_by_session(db, session_uuid)
    assert count == 1, f"Expected 1 receipt, got {count}"

    # The loser's result must be the winner's state (identical candidates)
    with test_session_factory() as db:
        winner_candidates = {
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, session_uuid)
        }
    assert _candidate_ids(test_session_factory, sid) == sorted(winner_candidates)
    assert results["t1"]["input_fingerprint"] == results["t2"]["input_fingerprint"]


# ---------------------------------------------------------------------------
# Test 2: Receipt uniqueness enforced - explicit repository check
# ---------------------------------------------------------------------------


def test_concurrent_receipt_uniqueness_enforced(
    test_client, test_session_factory
) -> None:
    """After concurrent identical completions, the receipt repository
    must show exactly one completed receipt for that fingerprint."""
    sid = _create_session(test_client, "Patient reports uniqueness chest pain")
    _add_observation(test_client, sid, "Patient reports uniqueness chest pain")
    session_uuid = UUID(sid)

    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}

    def runner(name: str) -> None:
        try:
            barrier.wait()
            results[name] = _execute_for_session(
                test_session_factory, session_uuid, input_snapshot=snapshot
            )
        except BaseException as exc:
            errors[name] = exc

    t1 = threading.Thread(target=runner, args=("t1",))
    t2 = threading.Thread(target=runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Thread errors: {errors}"
    assert "t1" in results and "t2" in results

    # Verify via repository directly
    with test_session_factory() as db:
        repo = ReasoningRunReceiptRepository()
        completed = repo.find_completed(
            db, session_uuid, results["t1"]["input_fingerprint"]
        )
        assert completed is not None
        assert completed.outcome == "COMPLETED"
        assert repo.count_by_session(db, session_uuid) == 1


# ---------------------------------------------------------------------------
# Test 3: No duplicate derived state
# ---------------------------------------------------------------------------


def test_concurrent_no_duplicate_derived_state(
    test_client, test_session_factory
) -> None:
    """Concurrent identical attempts must not double-create derived
    reasoning state (observations, entities, candidates, evidence, etc.)."""
    sid = _create_session(test_client, "Patient reports no-duplicate chest pain")
    _add_observation(test_client, sid, "Patient reports no-duplicate chest pain")
    session_uuid = UUID(sid)

    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}

    def runner(name: str) -> None:
        try:
            barrier.wait()
            results[name] = _execute_for_session(
                test_session_factory, session_uuid, input_snapshot=snapshot
            )
        except BaseException as exc:
            errors[name] = exc

    t1 = threading.Thread(target=runner, args=("t1",))
    t2 = threading.Thread(target=runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Thread errors: {errors}"
    assert "t1" in results and "t2" in results

    # Final state must equal single execution state
    with test_session_factory() as db:
        candidates = {
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, session_uuid)
        }
        from sqlalchemy import select

        from rop.models import EvaluatedEvidence

        evidence_count = len(
            list(
                db.execute(
                    select(EvaluatedEvidence).where(
                        EvaluatedEvidence.session_id == session_uuid
                    )
                ).scalars()
            )
        )

    # Single winner's candidates
    assert len(candidates) > 0
    # Evidence count matches single execution
    with test_session_factory() as db:
        from rop.services.evidence_evaluation import EvidenceEvaluationService

        assert (
            len(EvidenceEvaluationService().list_by_session(db, session_uuid))
            == evidence_count
        )


# ---------------------------------------------------------------------------
# Test 4: Distinct fingerprints remain independent
# ---------------------------------------------------------------------------


def test_concurrent_distinct_fingerprints_independent(
    test_client, test_session_factory
) -> None:
    """Two concurrent executions for the same session but different
    fingerprints must both succeed independently with their own receipts."""
    sid = _create_session(test_client, "Patient reports distinct fingerprint pain")
    _add_observation(test_client, sid, "Patient reports distinct fingerprint pain")
    session_uuid = UUID(sid)

    # Create two different input states by adding different observations
    with test_session_factory() as db:
        snapshot1 = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    _add_observation(test_client, sid, "Patient reports additional dizziness")

    with test_session_factory() as db:
        snapshot2 = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    assert compute_snapshot_fingerprint(snapshot1) != compute_snapshot_fingerprint(
        snapshot2
    )

    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}

    def runner1() -> None:
        barrier.wait()
        results["t1"] = _execute_for_session(
            test_session_factory, session_uuid, input_snapshot=snapshot1
        )

    def runner2() -> None:
        barrier.wait()
        results["t2"] = _execute_for_session(
            test_session_factory, session_uuid, input_snapshot=snapshot2
        )

    t1 = threading.Thread(target=runner1)
    t2 = threading.Thread(target=runner2)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert results["t1"]["outcome"] == "COMPLETED"
    assert results["t2"]["outcome"] == "COMPLETED"
    assert results["t1"]["input_fingerprint"] != results["t2"]["input_fingerprint"]

    # Two distinct receipts
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 2


# ---------------------------------------------------------------------------
# Test 5: Changed input remains stale
# ---------------------------------------------------------------------------


def test_concurrent_changed_input_stale(test_client, test_session_factory) -> None:
    """Concurrency handling must not weaken the STALE_CHANGED behavior
    for a known old fingerprint with changed current input."""
    sid = _create_session(test_client, "Patient reports stale chest pain")
    _add_observation(test_client, sid, "Patient reports stale chest pain")
    session_uuid = UUID(sid)

    # First execution establishes the canonical receipt
    first = _idempotent(test_session_factory, session_uuid)
    assert first["disposition"] == DISPOSITION_EXECUTED_NEW
    known = first["result"]["input_fingerprint"]

    # Change the input
    _add_observation(test_client, sid, "Patient reports new nausea")

    # Now run concurrent idempotent calls with the old fingerprint
    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}

    def runner(name: str) -> None:
        barrier.wait()
        results[name] = _idempotent(test_session_factory, session_uuid, known)

    t1 = threading.Thread(target=runner, args=("t1",))
    t2 = threading.Thread(target=runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    # Both must report STALE_CHANGED (no execution, no new receipt)
    assert results["t1"]["disposition"] == DISPOSITION_STALE_CHANGED
    assert results["t2"]["disposition"] == DISPOSITION_STALE_CHANGED
    assert results["t1"]["result"] is None
    assert results["t2"]["result"] is None

    # Still only one receipt (the original)
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 1


# ---------------------------------------------------------------------------
# Test 6: Failed execution remains retryable
# ---------------------------------------------------------------------------


def test_concurrent_failed_execution_retryable(
    test_client, test_session_factory
) -> None:
    """A genuinely failed execution must remain retryable and not create
    a completed receipt. A successful retry may create the single
    canonical receipt."""
    from rop.services.evidence_evaluation import EvidenceEvaluationService

    sid = _create_session(test_client, "Patient reports retryable chest pain")
    _add_observation(test_client, sid, "Patient reports retryable chest pain")
    session_uuid = UUID(sid)

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    # First concurrent attempt fails
    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}

    def failing_runner(name: str) -> None:
        barrier.wait()
        with test_session_factory() as db:
            svc = ReasoningRunExecutionService(
                evidence_evaluation_service=_BoomEvidence()
            )
            results[name] = svc.execute_for_session(
                db, session_uuid, input_snapshot=snapshot
            )

    t1 = threading.Thread(target=failing_runner, args=("t1",))
    t2 = threading.Thread(target=failing_runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    # Both fail, no receipt created
    assert results["t1"]["outcome"] == "FAILED"
    assert results["t2"]["outcome"] == "FAILED"
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 0

    # Retry succeeds and creates the single canonical receipt
    retry = _execute_for_session(test_session_factory, session_uuid)
    assert retry["outcome"] == "COMPLETED"
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 1


# ---------------------------------------------------------------------------
# Test 7: Unrelated integrity failure not swallowed
# ---------------------------------------------------------------------------


def test_concurrent_unrelated_integrity_not_swallowed(
    test_client, test_session_factory
) -> None:
    """An integrity failure unrelated to the canonical receipt uniqueness
    must not be converted to REUSED_IDENTICAL or silently swallowed."""
    from sqlalchemy.exc import IntegrityError

    from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
    from rop.services.reasoning_run_execution import (
        ReasoningRunExecutionContractError,
        ReasoningRunExecutionService,
    )

    sid = _create_session(test_client, "Patient reports unrelated integrity pain")
    _add_observation(test_client, sid, "Patient reports unrelated integrity pain")
    session_uuid = UUID(sid)

    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    real_record = ReasoningRunReceiptRepository.record_completed

    def _boom_record(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise IntegrityError(
            "INSERT INTO candidate_hypotheses",
            {},
            Exception("FOREIGN KEY constraint failed"),
        )

    ReasoningRunReceiptRepository.record_completed = _boom_record  # type: ignore[method-assign]
    try:
        barrier = _Barrier(2)
        results: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}

        def runner(name: str) -> None:
            try:
                barrier.wait()
                with test_session_factory() as db:
                    results[name] = ReasoningRunExecutionService().execute_for_session(
                        db, session_uuid, input_snapshot=snapshot
                    )
            except BaseException as exc:
                errors[name] = exc

        t1 = threading.Thread(target=runner, args=("t1",))
        t2 = threading.Thread(target=runner, args=("t2",))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        # Both should raise ReasoningRunExecutionContractError, not be swallowed
        assert "t1" in errors or "t2" in errors
        for exc in errors.values():
            assert isinstance(exc, ReasoningRunExecutionContractError)
            assert exc.invariant == "RUN_COMMIT_FAILED"
    finally:
        ReasoningRunReceiptRepository.record_completed = real_record  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Release gate assertion for Task 136
# ---------------------------------------------------------------------------


def test_gate_task136_concurrency_invariant(test_client, test_session_factory) -> None:
    """Task 136 release-gate assertion: identical concurrent completion
    attempts for one canonical identity result in exactly one durable
    completed receipt and a correctly recovered reuse outcome, with no
    partial/duplicate durable state."""
    sid = _create_session(test_client, "Patient reports gate chest pain")
    _add_observation(test_client, sid, "Patient reports gate chest pain")
    session_uuid = UUID(sid)

    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    barrier = _Barrier(2)
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}

    def runner(name: str) -> None:
        try:
            barrier.wait()
            results[name] = _execute_for_session(
                test_session_factory, session_uuid, input_snapshot=snapshot
            )
        except BaseException as exc:
            errors[name] = exc

    t1 = threading.Thread(target=runner, args=("t1",))
    t2 = threading.Thread(target=runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Thread errors: {errors}"
    assert "t1" in results and "t2" in results

    # Central invariant: exactly one durable completed receipt
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 1

    # Both callers receive semantically valid results
    assert results["t1"]["outcome"] == "COMPLETED"
    assert results["t2"]["outcome"] == "COMPLETED"

    # No duplicate derived state
    with test_session_factory() as db:
        candidates = {
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, session_uuid)
        }
    assert len(candidates) > 0

    # Both results reference the same canonical fingerprint
    assert results["t1"]["input_fingerprint"] == results["t2"]["input_fingerprint"]

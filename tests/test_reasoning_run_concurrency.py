"""Task 136: concurrent identical reasoning-run execution safety tests.
Two independent threads execute the same canonical identity through the
real executor against one shared file-backed SQLite database. SQLite is
single-writer, so parking both transactions at the receipt write would
deadlock (the parked winner holds the write locks the loser needs to
stage). The deterministic test seam instead gates the loser's first
stage write until the winner's receipt is durably committed; the loser
then reaches the real unique constraint, collides, rolls back, and
adopts the winner read-only. A spy proves the adoption path ran exactly
once, and a sequential control session proves no duplicated derived
state. No production synchronization mechanism is added.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from rop.database import Base, get_db
from rop.main import app
from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.evidence_evaluation import EvidenceEvaluationService
from rop.services.missing_information import MissingInformationService
from rop.services.reasoning_run_execution import (
    ReasoningRunExecutionContractError,
    ReasoningRunExecutionService,
    _is_receipt_identity_collision,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_idempotency import (
    DISPOSITION_EXECUTED_NEW,
    DISPOSITION_STALE_CHANGED,
    ReasoningRunIdempotencyService,
)
from rop.services.reasoning_run_input_snapshot import ReasoningRunInputSnapshotService
from rop.services.template_match import TemplateMatchService


@pytest.fixture(scope="function")
def test_engine(tmp_path):
    """Fresh file-backed SQLite database per test. A real file (not
    shared-cache memory) so the second connection's write attempts use
    the retriable busy path instead of non-retriable table locks."""
    db_path = (tmp_path / "concurrency.db").as_posix()
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=5,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_session_factory(test_engine):
    return sessionmaker(bind=test_engine)


@pytest.fixture(scope="function")
def test_client(test_session_factory):
    def override_get_db() -> Generator[Session, None, None]:
        with test_session_factory() as db:
            yield db

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


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


def _execute(
    factory, session_id: UUID, snapshot: dict[str, Any] | None = None
) -> dict[str, Any]:
    with factory() as db:
        return ReasoningRunExecutionService().execute_for_session(
            db, session_id, input_snapshot=snapshot
        )


def _idempotent(factory, session_id: UUID, known: str | None = None) -> dict[str, Any]:
    with factory() as db:
        return ReasoningRunIdempotencyService().execute_idempotent(
            db, session_id, known_input_fingerprint=known
        )


def _derived_state_signature(factory, session_uuid: UUID) -> dict[str, Any]:
    """Deterministic derived-state signature for baseline comparison:
    the missing-information items, matched template names, generated
    candidate names, and evaluated evidence count the pipeline derives.
    Row ids and timestamps are deliberately excluded: the canonical
    fingerprint is identity-scoped and differs between two physically
    distinct sessions even with identical content, so cross-session
    equivalence is asserted on derived output, not on the hash."""
    with factory() as db:
        return {
            "missing_information": sorted(
                f"{mi.template}:{mi.item}"
                for mi in MissingInformationService().list_by_session(db, session_uuid)
            ),
            "template_matches": sorted(
                tm.template_name
                for tm in TemplateMatchService().list_by_session(db, session_uuid)
            ),
            "candidate_names": sorted(
                c.name
                for c in CandidateGenerationService().list_by_session(db, session_uuid)
            ),
            "evidence_count": len(
                EvidenceEvaluationService().list_by_session(db, session_uuid)
            ),
        }


def _race_pair(
    factory,
    session_uuid: UUID,
    winner_snapshot: dict[str, Any],
    loser_snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[UUID]]:
    """Run winner and loser as independent threads and transactions.
    The loser parks at its first stage write until the winner has fully
    committed, guaranteeing the loser's receipt insert hits the real
    uniqueness constraint. Returns both results and the adoption spy
    log (session ids that entered _adopt_winner_result)."""
    loser_snapshot = loser_snapshot or winner_snapshot
    winner_committed = threading.Event()
    adoption_calls: list[UUID] = []
    original_adopt = ReasoningRunExecutionService._adopt_winner_result

    def recording_adopt(self, db, sid, state, exc):
        adoption_calls.append(sid)
        return original_adopt(self, db, sid, state, exc)

    class _GatedMissingInformation(MissingInformationService):
        def detect_and_store(self, db, session_id, observations, **kwargs):
            if not winner_committed.wait(timeout=30):
                raise RuntimeError("winner did not commit before gate timeout")
            return super().detect_and_store(db, session_id, observations, **kwargs)

    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}

    def winner_runner() -> None:
        try:
            results["winner"] = _execute(factory, session_uuid, winner_snapshot)
        except BaseException as exc:
            errors["winner"] = exc
        finally:
            winner_committed.set()

    def loser_runner() -> None:
        try:
            with factory() as db:
                loser = ReasoningRunExecutionService(
                    missing_information_service=_GatedMissingInformation()
                )
                results["loser"] = loser.execute_for_session(
                    db, session_uuid, input_snapshot=loser_snapshot
                )
        except BaseException as exc:
            errors["loser"] = exc

    with patch.object(
        ReasoningRunExecutionService, "_adopt_winner_result", recording_adopt
    ):
        t_winner = threading.Thread(target=winner_runner)
        t_loser = threading.Thread(target=loser_runner)
        t_winner.start()
        t_loser.start()
        t_winner.join(timeout=60)
        t_loser.join(timeout=60)
    assert not errors, f"thread errors: {errors}"
    return results, adoption_calls


# ---------------------------------------------------------------------------
# Direct collision-classifier tests (Task 136 correction, review point 1/9)
# ---------------------------------------------------------------------------
def test_collision_classifier_canonical_sqlite() -> None:
    exc = IntegrityError(
        "INSERT INTO reasoning_run_receipts",
        {},
        Exception(
            "UNIQUE constraint failed: reasoning_run_receipts.session_id, "
            "reasoning_run_receipts.input_fingerprint"
        ),
    )
    assert _is_receipt_identity_collision(exc) is True


def test_collision_classifier_canonical_postgres_diag() -> None:
    class _FakeDiag:
        constraint_name = "uq_reasoning_run_receipts_session_fingerprint"

    class _FakePgError(Exception):
        def __init__(self) -> None:
            self.diag = _FakeDiag()
            self.pgcode = "23505"

    exc = IntegrityError("INSERT INTO reasoning_run_receipts", {}, _FakePgError())
    assert _is_receipt_identity_collision(exc) is True


def test_collision_classifier_canonical_constraint_name_in_message() -> None:
    exc = IntegrityError(
        "INSERT INTO reasoning_run_receipts",
        {},
        Exception(
            "duplicate key value violates unique constraint "
            '"uq_reasoning_run_receipts_session_fingerprint"'
        ),
    )
    assert _is_receipt_identity_collision(exc) is True


def test_collision_classifier_rejects_unrelated_postgres_unique_violation() -> None:
    class _FakeDiag:
        constraint_name = "uq_other_table_other_identity"

    class _FakePgError(Exception):
        def __init__(self) -> None:
            self.diag = _FakeDiag()
            self.pgcode = "23505"

    exc = IntegrityError(
        "INSERT INTO reasoning_run_receipts",
        {},
        _FakePgError("duplicate key value violates unique constraint"),
    )
    assert _is_receipt_identity_collision(exc) is False

def test_collision_classifier_rejects_receipt_check_violation() -> None:
    exc = IntegrityError(
        "INSERT INTO reasoning_run_receipts",
        {},
        Exception("CHECK constraint failed: reasoning_run_receipts"),
    )
    assert _is_receipt_identity_collision(exc) is False


def test_collision_classifier_rejects_unrelated_table_fk() -> None:
    exc = IntegrityError(
        "INSERT INTO candidate_hypotheses",
        {},
        Exception("FOREIGN KEY constraint failed"),
    )
    assert _is_receipt_identity_collision(exc) is False


# ---------------------------------------------------------------------------
# Test 1 + 2: identical concurrent completions, one durable receipt
# ---------------------------------------------------------------------------
def test_concurrent_identical_completions_single_receipt(
    test_client, test_session_factory
) -> None:
    sid = _create_session(test_client, "Patient reports concurrent chest pain")
    _add_observation(test_client, sid, "Patient reports concurrent chest pain")
    session_uuid = UUID(sid)
    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    results, adoption_calls = _race_pair(test_session_factory, session_uuid, snapshot)

    assert results["winner"]["outcome"] == "COMPLETED"
    assert results["loser"]["outcome"] == "COMPLETED"
    assert (
        results["winner"]["input_fingerprint"] == results["loser"]["input_fingerprint"]
    )
    # Exactly one durable completed receipt (database is authoritative).
    with test_session_factory() as db:
        repo = ReasoningRunReceiptRepository()
        receipt = repo.find_completed(
            db, session_uuid, results["winner"]["input_fingerprint"]
        )
        assert receipt is not None
        assert receipt.outcome == "COMPLETED"
        assert repo.count_by_session(db, session_uuid) == 1
    # Exactly one normal commit (winner) and exactly one adoption (loser).
    assert len(adoption_calls) == 1
    assert adoption_calls[0] == session_uuid


# ---------------------------------------------------------------------------
# Test 3: no duplicate derived state, against a real control baseline
# ---------------------------------------------------------------------------
def test_concurrent_no_duplicate_derived_state(
    test_client, test_session_factory
) -> None:
    user_input = "Patient reports no-duplicate chest pain"

    # Control: one sequential execution on an equivalent fresh session
    # with the same deterministic input conditions.
    control_sid = _create_session(test_client, user_input)
    _add_observation(test_client, control_sid, user_input)
    control_uuid = UUID(control_sid)
    with test_session_factory() as db:
        control_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, control_uuid
        )
    control_result = _execute(test_session_factory, control_uuid, control_snapshot)
    assert control_result["outcome"] == "COMPLETED"
    control_signature = _derived_state_signature(test_session_factory, control_uuid)
    assert control_signature["candidate_names"], "control produced no candidates"

    # Target: two concurrent attempts on an equivalent fresh session.
    target_sid = _create_session(test_client, user_input)
    _add_observation(test_client, target_sid, user_input)
    target_uuid = UUID(target_sid)
    with test_session_factory() as db:
        target_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, target_uuid
        )

    results, adoption_calls = _race_pair(
        test_session_factory, target_uuid, target_snapshot
    )
    assert results["winner"]["outcome"] == "COMPLETED"
    assert results["loser"]["outcome"] == "COMPLETED"
    assert len(adoption_calls) == 1

    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, target_uuid) == 1
    # Final state equals a single execution, not two.
    target_signature = _derived_state_signature(test_session_factory, target_uuid)
    assert target_signature == control_signature


# ---------------------------------------------------------------------------
# Test 4: distinct fingerprints remain independent
# ---------------------------------------------------------------------------
def test_concurrent_distinct_fingerprints_independent(
    test_client, test_session_factory
) -> None:
    sid = _create_session(test_client, "Patient reports distinct fingerprint pain")
    _add_observation(test_client, sid, "Patient reports distinct fingerprint pain")
    session_uuid = UUID(sid)
    with test_session_factory() as db:
        snapshot1 = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)
    _add_observation(test_client, sid, "Patient reports additional dizziness")
    with test_session_factory() as db:
        snapshot2 = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)
    assert compute_snapshot_fingerprint(snapshot1) != compute_snapshot_fingerprint(
        snapshot2
    )

    results, adoption_calls = _race_pair(
        test_session_factory, session_uuid, snapshot1, loser_snapshot=snapshot2
    )

    assert results["winner"]["outcome"] == "COMPLETED"
    assert results["loser"]["outcome"] == "COMPLETED"
    assert (
        results["winner"]["input_fingerprint"] != results["loser"]["input_fingerprint"]
    )
    with test_session_factory() as db:
        repo = ReasoningRunReceiptRepository()
        assert repo.count_by_session(db, session_uuid) == 2
        assert (
            repo.find_completed(
                db, session_uuid, results["winner"]["input_fingerprint"]
            )
            is not None
        )
        assert (
            repo.find_completed(db, session_uuid, results["loser"]["input_fingerprint"])
            is not None
        )
    # No cross-identity adoption occurred.
    assert len(adoption_calls) == 0


# ---------------------------------------------------------------------------
# Test 5: changed input remains stale
# ---------------------------------------------------------------------------
def test_concurrent_changed_input_stale(test_client, test_session_factory) -> None:
    sid = _create_session(test_client, "Patient reports stale chest pain")
    _add_observation(test_client, sid, "Patient reports stale chest pain")
    session_uuid = UUID(sid)
    first = _idempotent(test_session_factory, session_uuid)
    assert first["disposition"] == DISPOSITION_EXECUTED_NEW
    known = first["result"]["input_fingerprint"]
    _add_observation(test_client, sid, "Patient reports new nausea")

    results: dict[str, dict[str, Any]] = {}

    def runner(name: str) -> None:
        results[name] = _idempotent(test_session_factory, session_uuid, known)

    t1 = threading.Thread(target=runner, args=("t1",))
    t2 = threading.Thread(target=runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert results["t1"]["disposition"] == DISPOSITION_STALE_CHANGED
    assert results["t2"]["disposition"] == DISPOSITION_STALE_CHANGED
    assert results["t1"]["result"] is None
    assert results["t2"]["result"] is None
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 1


# ---------------------------------------------------------------------------
# Test 6: failed execution remains retryable
# ---------------------------------------------------------------------------
def test_concurrent_failed_execution_retryable(
    test_client, test_session_factory
) -> None:
    sid = _create_session(test_client, "Patient reports retryable chest pain")
    _add_observation(test_client, sid, "Patient reports retryable chest pain")
    session_uuid = UUID(sid)

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    with test_session_factory() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, session_uuid)

    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}

    def failing_runner(name: str) -> None:
        try:
            with test_session_factory() as db:
                svc = ReasoningRunExecutionService(
                    evidence_evaluation_service=_BoomEvidence()
                )
                results[name] = svc.execute_for_session(
                    db, session_uuid, input_snapshot=snapshot
                )
        except BaseException as exc:
            errors[name] = exc

    t1 = threading.Thread(target=failing_runner, args=("t1",))
    t2 = threading.Thread(target=failing_runner, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)
    failures = [r for r in results.values() if r["outcome"] == "FAILED"]
    assert failures, "expected at least one FAILED outcome"
    assert not [
        r for r in results.values() if r["outcome"] == "COMPLETED"
    ], "failed attempt must not complete"
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 0
    retry = _execute(test_session_factory, session_uuid)
    assert retry["outcome"] == "COMPLETED"
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 1


# ---------------------------------------------------------------------------
# Test 7: unrelated integrity failure is not swallowed
# ---------------------------------------------------------------------------
def test_unrelated_integrity_failure_not_swallowed(
    test_client, test_session_factory
) -> None:
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
        with pytest.raises(ReasoningRunExecutionContractError) as excinfo:
            with test_session_factory() as db:
                ReasoningRunExecutionService().execute_for_session(
                    db, session_uuid, input_snapshot=snapshot
                )
        assert excinfo.value.invariant == "RUN_COMMIT_FAILED"
    finally:
        ReasoningRunReceiptRepository.record_completed = real_record  # type: ignore[method-assign]
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, session_uuid) == 0


# ---------------------------------------------------------------------------
# Release gate assertion for Task 136
# ---------------------------------------------------------------------------
def test_gate_task136_concurrency_invariant(test_client, test_session_factory) -> None:
    """Identical concurrent completion attempts for one canonical identity
    produce exactly one durable completed receipt, one winner commit, one
    loser adoption, and no duplicated derived state versus a single
    sequential control execution."""
    user_input = "Patient reports gate chest pain"

    control_sid = _create_session(test_client, user_input)
    _add_observation(test_client, control_sid, user_input)
    control_uuid = UUID(control_sid)
    with test_session_factory() as db:
        control_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, control_uuid
        )
    control_result = _execute(test_session_factory, control_uuid, control_snapshot)
    assert control_result["outcome"] == "COMPLETED"
    control_signature = _derived_state_signature(test_session_factory, control_uuid)
    assert control_signature["candidate_names"]

    target_sid = _create_session(test_client, user_input)
    _add_observation(test_client, target_sid, user_input)
    target_uuid = UUID(target_sid)
    with test_session_factory() as db:
        target_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, target_uuid
        )

    results, adoption_calls = _race_pair(
        test_session_factory, target_uuid, target_snapshot
    )

    assert results["winner"]["outcome"] == "COMPLETED"
    assert results["loser"]["outcome"] == "COMPLETED"
    assert (
        results["winner"]["input_fingerprint"] == results["loser"]["input_fingerprint"]
    )
    with test_session_factory() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, target_uuid) == 1
    assert len(adoption_calls) == 1
    target_signature = _derived_state_signature(test_session_factory, target_uuid)
    assert target_signature == control_signature


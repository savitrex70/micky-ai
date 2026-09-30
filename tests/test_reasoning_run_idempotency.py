"""Task 127: deterministic reasoning-run idempotency tests.

Proves canonical identity, identical-input reuse without state churn,
changed-input staleness, failed-first retry, and determinism. No
queues, workers, history deletion, or external services.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_idempotency import (
    DISPOSITION_EXECUTED_NEW,
    DISPOSITION_REUSED_IDENTICAL,
    DISPOSITION_STALE_CHANGED,
    ReasoningRunIdempotencyService,
    derive_run_identity,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "idempotency-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(session_id: str, text: str) -> None:
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


def _candidate_ids(session_id: str) -> list[str]:
    with TestingSessionLocal() as db:
        return sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(session_id))
        )


def _idempotent(session_id: str, known: str | None = None) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningRunIdempotencyService().execute_idempotent(
            db, UUID(session_id), known_input_fingerprint=known
        )


def test_identity_derivation_is_canonical() -> None:
    sid = UUID("12345678-1234-5678-1234-567812345678")
    assert derive_run_identity(sid, "a" * 64) == f"{sid}:{'a' * 64}"
    assert derive_run_identity(sid, "a" * 64) != derive_run_identity(sid, "b" * 64)


def _seeded_session(user_input: str) -> str:
    """Pre-seed observations so exogenous inputs are stable across runs."""
    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    return sid


def test_first_run_executes_new() -> None:
    sid = _create_session("Patient reports chest pain")
    envelope = _idempotent(sid)
    assert envelope["disposition"] == DISPOSITION_EXECUTED_NEW
    assert envelope["result"]["outcome"] == "COMPLETED"
    assert (
        envelope["current_input_fingerprint"] == envelope["result"]["input_fingerprint"]
    )


def _current_fingerprint(session_id: str) -> str:
    from rop.services.reasoning_run_fingerprint import (
        compute_snapshot_fingerprint,
    )
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    with TestingSessionLocal() as db:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, UUID(session_id)
        )
    return compute_snapshot_fingerprint(snapshot)


def test_identical_rerun_reuses_without_churn() -> None:
    from rop.repositories.reasoning_run_receipt import (
        ReasoningRunReceiptRepository,
    )

    sid = _seeded_session("Patient reports steady chest pain")
    first = _idempotent(sid)
    assert first["disposition"] == DISPOSITION_EXECUTED_NEW
    assert first["result"]["outcome"] == "COMPLETED"
    # The round-trip contract: the returned fingerprint is usable
    # directly on the next identical request.
    known = first["result"]["input_fingerprint"]
    assert known == first["current_input_fingerprint"]
    ids_before = _candidate_ids(sid)
    with TestingSessionLocal() as db:
        receipt = ReasoningRunReceiptRepository().find_completed(db, UUID(sid), known)
        assert receipt is not None
        assert receipt.input_fingerprint == known

    second = _idempotent(sid, known)
    assert second["disposition"] == DISPOSITION_REUSED_IDENTICAL
    assert second["result"]["outcome"] == "COMPLETED"
    assert second["result"]["input_fingerprint"] == known
    # Nothing was rewritten: identical candidate identities, and reuse
    # wrote no second receipt.
    assert _candidate_ids(sid) == ids_before
    with TestingSessionLocal() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, UUID(sid)) == 1


def test_matching_fingerprint_without_completed_run_executes() -> None:
    """A caller-supplied fingerprint matching current inputs proves
    nothing by itself: with no stored COMPLETED run behind it, the
    request executes anew instead of claiming reuse."""
    sid = _create_session("Patient reports unobserved chest pain")
    known = _current_fingerprint(sid)
    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        assert (
            ReasoningRunReceiptRepository().find_completed(db, UUID(sid), known) is None
        )

    envelope = _idempotent(sid, known)
    assert envelope["disposition"] == DISPOSITION_EXECUTED_NEW
    assert envelope["result"]["outcome"] == "COMPLETED"


def test_fabricated_fingerprint_never_reuses() -> None:
    sid = _create_session("Patient reports chest pain")
    first = _idempotent(sid)
    assert first["disposition"] == DISPOSITION_EXECUTED_NEW
    fabricated = "f" * 64
    assert fabricated != first["current_input_fingerprint"]

    envelope = _idempotent(sid, fabricated)
    assert envelope["disposition"] in (
        DISPOSITION_STALE_CHANGED,
        DISPOSITION_EXECUTED_NEW,
    )
    assert envelope["disposition"] != DISPOSITION_REUSED_IDENTICAL


def test_changed_input_is_stale_not_same_run() -> None:
    sid = _create_session("Patient reports chest pain")
    first = _idempotent(sid)
    known = first["current_input_fingerprint"]
    _add_observation(sid, "Patient reports new dizziness")

    stale = _idempotent(sid, known)
    assert stale["disposition"] == DISPOSITION_STALE_CHANGED
    assert stale["result"] is None
    assert stale["current_input_fingerprint"] != known

    fresh = _idempotent(sid)
    assert fresh["disposition"] == DISPOSITION_EXECUTED_NEW
    assert fresh["result"]["outcome"] == "COMPLETED"


def test_failed_first_run_then_retry() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService

    sid = _create_session("Patient reports chest pain and chills")

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    with TestingSessionLocal() as db:
        failed = ReasoningRunIdempotencyService(
            execution_service=ReasoningRunExecutionService(
                evidence_evaluation_service=_BoomEvidence()
            )
        ).execute_idempotent(db, UUID(sid))
    assert failed["disposition"] == DISPOSITION_EXECUTED_NEW
    assert failed["result"]["outcome"] == "FAILED"

    # Retrying with the failed attempt's fingerprint must execute anew:
    # no COMPLETED receipt binds it, so reuse is forbidden.
    retry_known = _idempotent(sid, failed["result"]["input_fingerprint"])
    assert retry_known["disposition"] == DISPOSITION_EXECUTED_NEW
    assert retry_known["result"]["outcome"] == "COMPLETED"

    retried = _idempotent(sid)
    assert retried["disposition"] == DISPOSITION_EXECUTED_NEW
    assert retried["result"]["outcome"] == "COMPLETED"


def test_reuse_is_deterministic() -> None:
    sid = _seeded_session("Patient reports repeatable chest pain")
    first = _idempotent(sid)
    assert first["disposition"] == DISPOSITION_EXECUTED_NEW
    known = first["result"]["input_fingerprint"]
    again = _idempotent(sid, known)
    third = _idempotent(sid, known)
    assert again["disposition"] == DISPOSITION_REUSED_IDENTICAL
    assert third["disposition"] == DISPOSITION_REUSED_IDENTICAL
    assert again["result"] == third["result"]

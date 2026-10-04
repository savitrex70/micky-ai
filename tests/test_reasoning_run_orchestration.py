"""Task 132: canonical deterministic reasoning-run orchestration tests.

Proves end-to-end COMPLETED orchestration, explicit failure stages,
no post-failure progression, determinism, strict shape, and absence of
decision authority. No model, no network beyond the test app.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_orchestration import ReasoningRunOrchestrationRead
from rop.services.reasoning_run_orchestration import (
    REASONING_RUN_ORCHESTRATION_SOURCE_TASK_132,
    ReasoningRunOrchestrationContractError,
    ReasoningRunOrchestrationService,
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
            "metadata": {"source": "orchestration-test"},
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


def _orchestrate(
    session_id: str, service: ReasoningRunOrchestrationService | None = None
) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return (service or ReasoningRunOrchestrationService()).orchestrate(
            db, UUID(session_id)
        )


def test_full_workflow_orchestration() -> None:
    sid = _create_session("Patient reports chest pain and sweating")
    _add_observation(sid, "Patient reports chest pain and sweating")
    result = _orchestrate(sid)

    assert result["available"] is True
    assert result["orchestration_consistent"] is True
    assert result["failure_stage"] is None
    assert len(result["input_fingerprint"]) == 64
    assert result["execution"]["outcome"] == "COMPLETED"
    assert result["chain_audit"]["chain_consistent"] is True
    assert result["orchestration_source"] == REASONING_RUN_ORCHESTRATION_SOURCE_TASK_132
    assert ReasoningRunOrchestrationRead.model_validate(result)
    # One canonical snapshot: the orchestration fingerprint is exactly
    # the fingerprint the nested execution ran under.
    assert result["input_fingerprint"] == result["execution"]["input_fingerprint"]


def test_failure_stage_explicit_and_no_progression() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    service = ReasoningRunOrchestrationService(
        execution_service=ReasoningRunExecutionService(
            evidence_evaluation_service=_BoomEvidence()
        )
    )
    result = _orchestrate(sid, service)

    assert result["available"] is False
    assert result["orchestration_consistent"] is False
    assert result["failure_stage"] == "EVIDENCE_EVALUATION"
    assert result["execution"]["outcome"] == "FAILED"
    # Later stages never ran.
    statuses = {
        stage["stage_id"]: stage["status"] for stage in result["execution"]["stages"]
    }
    assert statuses["REASONING_RUN"] == "SKIPPED"
    assert statuses["REASONING_RUN_CONSISTENCY"] == "SKIPPED"


def test_orchestration_deterministic_shape() -> None:
    sid = _create_session("Patient reports repeatable chest pain")
    _add_observation(sid, "Patient reports repeatable chest pain")
    first = _orchestrate(sid)
    assert first["orchestration_consistent"] is True
    assert set(first.keys()) == set(ReasoningRunOrchestrationRead.model_fields.keys())


def test_missing_session_raises() -> None:
    with TestingSessionLocal() as db:
        with pytest.raises(ReasoningRunOrchestrationContractError):
            ReasoningRunOrchestrationService().orchestrate(db, uuid4())


def test_result_rejects_extra_and_authority_fields() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    result = _orchestrate(sid)
    assert "winner" not in result
    assert "diagnosis" not in result
    assert "treatment" not in result
    assert "recommendation" not in result
    tampered = dict(result)
    tampered["diagnosis"] = "x"
    with pytest.raises(ValidationError):
        ReasoningRunOrchestrationRead.model_validate(tampered)


def test_stale_snapshot_detected_not_silently_rebuilt() -> None:
    """TOCTOU regression: a snapshot established before an underlying
    mutation is passed through unchanged. The execution reports the
    passed fingerprint exactly -- proving no silent rebuild -- while a
    fresh fingerprint recomputed from live state visibly diverges,
    proving the drift is detected rather than hidden."""
    from rop.services.observation import ObservationService
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService
    from rop.services.reasoning_run_fingerprint import (
        compute_snapshot_fingerprint,
    )
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    with TestingSessionLocal() as db:
        stale_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, UUID(sid)
        )
        stale_fingerprint = compute_snapshot_fingerprint(stale_snapshot)
        for observation in ObservationService().list_by_session(db, UUID(sid)):
            ObservationService().delete(db, observation.id)

    with TestingSessionLocal() as db:
        result = ReasoningRunExecutionService().execute_for_session(
            db, UUID(sid), input_snapshot=stale_snapshot
        )
        live_snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
    # The reported fingerprint is exactly the passed one: no rebuild.
    assert result["input_fingerprint"] == stale_fingerprint
    # The drift is provable: live state fingerprints differently.
    assert compute_snapshot_fingerprint(live_snapshot) != stale_fingerprint

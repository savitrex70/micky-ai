"""Task 128: deterministic reasoning-run replay tests.

Proves exact replay consistency, modified-state divergence, tampered
recording rejection, read-only replay, and strict result shape -- while
the existing step-log /replay endpoint keeps working. No model, no
network beyond the test app.
"""

from __future__ import annotations

import copy
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
from rop.schemas.reasoning_run_replay import ReasoningRunReplayRead
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_input_snapshot import (
    ReasoningRunInputSnapshotService,
)
from rop.services.reasoning_run_replay import (
    REASONING_RUN_REPLAY_SOURCE_TASK_128,
    ReasoningRunReplayContractError,
    ReasoningRunReplayService,
    exogenous_projection,
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
            "metadata": {"source": "replay-test"},
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


def _db() -> Any:
    gen = app.dependency_overrides[get_db]()
    return gen, next(gen)


def _snapshot(session_id: str) -> dict[str, Any]:
    gen, db = _db()
    try:
        return ReasoningRunInputSnapshotService().build_snapshot(db, UUID(session_id))
    finally:
        gen.close()


def _execute(session_id: str) -> dict[str, Any]:
    gen, db = _db()
    try:
        return ReasoningRunExecutionService().execute_for_session(db, UUID(session_id))
    finally:
        gen.close()


def _replay(
    session_id: str, result: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    gen, db = _db()
    try:
        return ReasoningRunReplayService().replay(
            db,
            UUID(session_id),
            original_result=result,
            original_snapshot=snapshot,
        )
    finally:
        gen.close()


def _seed_exogenous_session(user_input: str) -> tuple[str, dict[str, Any]]:
    """Pre-seed observations so execution reuses exogenous state."""
    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    return sid, _snapshot(sid)


def test_exact_replay_is_consistent() -> None:
    sid, Bolt1 = _seed_exogenous_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    replayed = _replay(sid, result, Bolt1)

    assert replayed["input_match"] is True
    assert replayed["divergences"] == []
    assert replayed["replay_consistent"] is True
    assert replayed["original_run_identity"].startswith(sid)
    assert replayed["replay_source"] == REASONING_RUN_REPLAY_SOURCE_TASK_128
    assert all(stage["match"] for stage in replayed["stage_comparison"])
    assert ReasoningRunReplayRead.model_validate(replayed)


def test_replay_is_read_only() -> None:
    from rop.services.candidate_generation import CandidateGenerationService

    sid, Bolt1 = _seed_exogenous_session("Patient reports steady pain")
    result = _execute(sid)
    with TestingSessionLocal() as db:
        before = sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(sid))
        )
    replayed = _replay(sid, result, Bolt1)
    assert replayed["replay_consistent"] is True
    with TestingSessionLocal() as db:
        after = sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(sid))
        )
    assert after == before


def test_modified_state_diverges() -> None:
    sid, Bolt1 = _seed_exogenous_session("Patient reports chest pain")
    result = _execute(sid)
    _add_observation(sid, "Patient reports new dizziness")
    replayed = _replay(sid, result, Bolt1)

    assert replayed["input_match"] is False
    assert "INPUT_CHANGED_SINCE_ORIGINAL" in replayed["divergences"]
    assert replayed["replay_consistent"] is False


def test_derived_state_change_diverges_despite_identical_stage_metadata() -> None:
    """A rule-output change that keeps stage IDs, order, and sources
    identical must still be detected via the canonicalized run state."""
    from rop.models import EvaluatedEvidence

    sid, pre_snapshot = _seed_exogenous_session("Patient reports chest pain")
    result = _execute(sid)
    with TestingSessionLocal() as db:
        rows = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(sid))
            .all()
        )
        assert rows
        db.delete(rows[0])
        db.commit()
    replayed = _replay(sid, result, pre_snapshot)

    assert replayed["input_match"] is True
    assert (
        "DERIVED_RUN_STATE_DIVERGED" in replayed["divergences"]
        or "DERIVED_AUDIT_STATE_DIVERGED" in replayed["divergences"]
    )
    assert replayed["replay_consistent"] is False


def test_recorded_stage_tamper_diverges() -> None:
    """Altering recorded stage sources or order is detected even when
    current state is pristine."""
    sid, pre_snapshot = _seed_exogenous_session("Patient reports chest pain")
    result = _execute(sid)

    tampered_source = copy.deepcopy(result)
    tampered_source["reasoning_run"]["stages"][0]["stage_source"] = "FORGED_SOURCE"
    replayed = _replay(sid, tampered_source, pre_snapshot)
    assert any(issue.startswith("STAGE_DIVERGED") for issue in replayed["divergences"])
    assert replayed["replay_consistent"] is False

    tampered_order = copy.deepcopy(result)
    stages = tampered_order["reasoning_run"]["stages"]
    stages[0], stages[1] = stages[1], stages[0]
    replayed = _replay(sid, tampered_order, pre_snapshot)
    assert any(issue.startswith("STAGE_DIVERGED") for issue in replayed["divergences"])
    assert replayed["replay_consistent"] is False


def test_tampered_recording_rejected() -> None:
    sid, Bolt1 = _seed_exogenous_session("Patient reports chest pain")
    result = _execute(sid)
    forged = copy.deepcopy(Bolt1)
    forged["observations"] = []
    gen, db = _db()
    try:
        with pytest.raises(ReasoningRunReplayContractError) as exc_info:
            ReasoningRunReplayService().replay(
                db,
                UUID(sid),
                original_result=result,
                original_snapshot=forged,
            )
        assert exc_info.value.invariant == "RECORD_TAMPERED"
    finally:
        gen.close()


def test_missing_recording_rejected() -> None:
    sid, _ = _seed_exogenous_session("Patient reports chest pain")
    gen, db = _db()
    try:
        with pytest.raises(ReasoningRunReplayContractError):
            ReasoningRunReplayService().replay(
                db, UUID(sid), original_result={}, original_snapshot={}
            )
    finally:
        gen.close()


def test_exogenous_projection_contract() -> None:
    sid, Bolt1 = _seed_exogenous_session("Patient reports chest pain")
    projected = exogenous_projection(Bolt1)
    assert set(projected.keys()) == {
        "session_id",
        "user_input",
        "observations",
        "entities",
    }


def test_step_log_replay_endpoint_untouched() -> None:
    sid, _ = _seed_exogenous_session("Patient reports chest pain")
    _execute(sid)
    r = client.get(f"/sessions/{sid}/replay")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

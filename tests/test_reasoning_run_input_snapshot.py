"""Task 124: canonical deterministic reasoning-run input snapshot tests.

Proves the snapshot binds all required input state, freezes it against
later database mutations, validates strictly, and drives the
executor's existence checks. No model, no network beyond the test app.
"""

from __future__ import annotations

import copy
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
from rop.schemas.reasoning_run_input_snapshot import (
    ReasoningRunInputSnapshotRead,
)
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
    ReasoningRunInputSnapshotContractError,
    ReasoningRunInputSnapshotService,
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
            "metadata": {"source": "input-snapshot-test"},
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


def test_snapshot_binds_all_required_state() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    snapshot = _snapshot(sid)

    assert set(snapshot.keys()) == set(
        ReasoningRunInputSnapshotRead.model_fields.keys()
    )
    assert snapshot["session_id"] == sid
    assert snapshot["user_input"] == "Patient reports chest pain"
    assert len(snapshot["observations"]) == 1
    assert snapshot["observations"][0]["text"] == "Patient reports chest pain"
    assert snapshot["entities"] == []
    assert snapshot["candidates"] == []
    assert snapshot["evidence"] == []
    assert snapshot["candidate_order"] == []
    assert snapshot["evidence_order"] == []
    assert snapshot["snapshot_source"] == REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124
    assert ReasoningRunInputSnapshotRead.model_validate(snapshot)


def test_snapshot_frozen_against_later_mutations() -> None:
    sid = _create_session("Patient reports headache")
    before = _snapshot(sid)
    before_copy = copy.deepcopy(before)
    _add_observation(sid, "Patient reports headache")
    after = _snapshot(sid)

    assert before == before_copy
    assert len(before["observations"]) == 0
    assert len(after["observations"]) == 1
    assert after["observations"][0]["text"] == "Patient reports headache"


def test_snapshot_schema_rejects_extra_fields() -> None:
    sid = _create_session("Patient reports fever")
    snapshot = _snapshot(sid)
    snapshot["smuggled"] = True
    with pytest.raises(ValidationError):
        ReasoningRunInputSnapshotRead.model_validate(snapshot)


def test_snapshot_missing_session_raises() -> None:
    gen, db = _db()
    try:
        with pytest.raises(ReasoningRunInputSnapshotContractError) as exc_info:
            ReasoningRunInputSnapshotService().build_snapshot(db, uuid4())
        assert exc_info.value.invariant == "SESSION_NOT_FOUND"
    finally:
        gen.close()


def test_executor_reuses_snapshot_existence_state() -> None:
    """Pre-existing observations are reused, not duplicated: the
    executor's existence check reads the canonical snapshot."""
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    assert _snapshot(sid)["observations"] is not None
    assert len(_snapshot(sid)["observations"]) == 1


def test_snapshot_after_execute_captures_run_inputs() -> None:
    sid = _create_session("Patient reports chest pain and dizziness")
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    snapshot = _snapshot(sid)
    assert len(snapshot["observations"]) > 0
    assert len(snapshot["candidates"]) > 0
    assert [c["id"] for c in snapshot["candidates"]] == snapshot["candidate_order"]
    assert [e["id"] for e in snapshot["evidence"]] == snapshot["evidence_order"]

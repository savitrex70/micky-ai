"""Task 125: deterministic reasoning-run input fingerprint tests.

Proves reproducibility, ordering normalization, per-collection
sensitivity, forged-fingerprint rejection, and result propagation. No
model, no network beyond the test app.
"""

from __future__ import annotations

import copy
import json
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
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_fingerprint import (
    compute_snapshot_fingerprint,
    verify_snapshot_fingerprint,
)
from rop.services.reasoning_run_input_snapshot import (
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
            "metadata": {"source": "fingerprint-test"},
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


def test_same_input_same_fingerprint() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    first = compute_snapshot_fingerprint(_snapshot(sid))
    second = compute_snapshot_fingerprint(_snapshot(sid))
    assert first == second
    assert len(first) == 64
    assert verify_snapshot_fingerprint(_snapshot(sid), first) == []


def test_key_ordering_normalized() -> None:
    sid = _create_session("Patient reports fever")
    snapshot = _snapshot(sid)
    shuffled = {key: snapshot[key] for key in reversed(list(snapshot.keys()))}
    assert compute_snapshot_fingerprint(shuffled) == compute_snapshot_fingerprint(
        snapshot
    )


def test_changed_observation_changes_fingerprint() -> None:
    sid = _create_session("Patient reports cough")
    _add_observation(sid, "Patient reports cough")
    before = compute_snapshot_fingerprint(_snapshot(sid))
    _add_observation(sid, "Patient reports fever")
    after = compute_snapshot_fingerprint(_snapshot(sid))
    assert before != after


def test_changed_collections_change_fingerprint() -> None:
    sid = _create_session("Patient reports chest pain and nausea")
    _add_observation(sid, "Patient reports chest pain and nausea")
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    executed = compute_snapshot_fingerprint(_snapshot(sid))

    mutated = copy.deepcopy(_snapshot(sid))
    mutated["entities"].append(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "session_id": sid,
            "name": "forged",
            "category": "x",
            "confidence": 1.0,
            "source": "forged",
        }
    )
    assert compute_snapshot_fingerprint(mutated) != executed

    mutated_missing = copy.deepcopy(_snapshot(sid))
    mutated_missing["missing_information"] = []
    if _snapshot(sid)["missing_information"]:
        assert compute_snapshot_fingerprint(mutated_missing) != executed

    reordered = copy.deepcopy(_snapshot(sid))
    if len(reordered["candidate_order"]) > 1:
        reordered["candidate_order"] = list(reversed(reordered["candidate_order"]))
        assert compute_snapshot_fingerprint(reordered) != executed


def test_forged_fingerprint_rejected() -> None:
    sid = _create_session("Patient reports dizziness")
    snapshot = _snapshot(sid)
    forged = "0" * 64
    assert forged != compute_snapshot_fingerprint(snapshot)
    issues = verify_snapshot_fingerprint(snapshot, forged)
    assert issues == ["input fingerprint mismatch: snapshot does not match run"]
    assert verify_snapshot_fingerprint(snapshot, "short") == [
        "claimed input fingerprint is malformed"
    ]


def test_fingerprint_propagated_through_result() -> None:
    sid = _create_session("Patient reports chest pain")
    pre_run_snapshot = _snapshot(sid)
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    # The fingerprint binds the exact pre-run inputs the run was
    # approved against -- not the post-run state the stages produced.
    assert result["input_fingerprint"] == compute_snapshot_fingerprint(pre_run_snapshot)
    assert (
        verify_snapshot_fingerprint(pre_run_snapshot, result["input_fingerprint"]) == []
    )


def test_repeated_execution_regenerates_distinct_fingerprint() -> None:
    """Repeat execution regenerates derived state (new candidate IDs),
    so the second run's approved inputs hash differently. Both runs
    carry well-formed fingerprints; Task 127 defines run identity over
    this distinction."""
    sid = _create_session("Patient reports stable chest pain")
    first = _execute(sid)
    second = _execute(sid)
    assert first["outcome"] == "COMPLETED"
    assert second["outcome"] == "COMPLETED"
    assert len(first["input_fingerprint"]) == 64
    assert len(second["input_fingerprint"]) == 64
    assert first["input_fingerprint"] != second["input_fingerprint"]


def test_snapshot_json_canonical_form() -> None:
    sid = _create_session("Patient reports fatigue")
    snapshot = _snapshot(sid)
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    import hashlib

    assert hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest() == compute_snapshot_fingerprint(snapshot)

"""Task 140: API tests for the canonical deterministic reasoning-run replay.

Exercises ``POST /sessions/{session_id}/reasoning-run/replay`` through the
real HTTP boundary using the existing Task 128 deterministic pipeline with
an in-memory SQLite test database. No model, no network, no provider APIs.
"""

from __future__ import annotations

import copy
import inspect
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_replay import ReasoningRunReplayRead
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
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


# ---------------------------------------------------------------------------
# Shared helpers (mirror Task 128 service-test helpers)
# ---------------------------------------------------------------------------


def _create_session(user_input: str = "Patient reports chest pain and sweating") -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "replay-api-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(session_id: str, text: str = "Patient reports chest pain") -> None:
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


def _seed_exogenous_session(
    user_input: str = "Patient reports chest pain",
) -> tuple[str, dict[str, Any]]:
    """Pre-seed observations so execution reuses exogenous state."""
    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    return sid, _snapshot(sid)


def _counts() -> dict[str, int]:
    """Row counts for every ROP table; used to prove read-only paths."""
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so UUID objects become JSON-safe strings.

    The canonical fingerprint uses ``default=str``, so UUID-to-string
    normalization is stable across the HTTP boundary.
    """
    return json.loads(json.dumps(obj, default=str))


def _post_replay(
    session_id: str, original_result: dict[str, Any], original_snapshot: dict[str, Any]
) -> Any:
    return client.post(
        f"/sessions/{session_id}/reasoning-run/replay",
        json={
            "original_result": _json_safe(original_result),
            "original_snapshot": _json_safe(original_snapshot),
        },
    )


# ---------------------------------------------------------------------------
# 1. Successful exact replay
# ---------------------------------------------------------------------------


def test_api_exact_replay_is_consistent() -> None:
    sid, pre_snapshot = _seed_exogenous_session()
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"

    response = _post_replay(sid, result, pre_snapshot)

    assert response.status_code == 200
    body = response.json()
    assert body["replay_consistent"] is True
    assert body["divergences"] == []
    assert body["input_match"] is True
    assert body["replay_source"] == "REASONING_RUN_REPLAY_TASK_128"
    assert all(stage["match"] for stage in body["stage_comparison"])

    # Response validates against the strict Task 128 read schema.
    assert ReasoningRunReplayRead.model_validate(body)


# ---------------------------------------------------------------------------
# 2. Input change
# ---------------------------------------------------------------------------


def test_api_input_change_diverges() -> None:
    sid, pre_snapshot = _seed_exogenous_session()
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"

    # Mutate exogenous state after the original recording.
    _add_observation(sid, "Patient reports new onset dizziness")

    response = _post_replay(sid, result, pre_snapshot)

    # An HTTP success — divergence is a deterministic finding, not an error.
    assert response.status_code == 200
    body = response.json()
    assert body["input_match"] is False
    assert "INPUT_CHANGED_SINCE_ORIGINAL" in body["divergences"]
    assert body["replay_consistent"] is False


# ---------------------------------------------------------------------------
# 3. Tampered recording
# ---------------------------------------------------------------------------


def test_api_tampered_recording_rejected() -> None:
    sid, pre_snapshot = _seed_exogenous_session()
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"

    # Modify the recorded snapshot without updating its fingerprint.
    forged = copy.deepcopy(pre_snapshot)
    forged["observations"] = []

    response = _post_replay(sid, result, forged)

    # RECORD_TAMPERED is a contract violation → HTTP 500 with generic detail.
    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Internal reasoning-run-replay contract violation"
    )


# ---------------------------------------------------------------------------
# 4. Missing / invalid recording
# ---------------------------------------------------------------------------


def test_api_missing_recording_rejected() -> None:
    sid, pre_snapshot = _seed_exogenous_session()

    # Empty dicts pass Pydantic but fail at the service level -> RECORD_INVALID
    # -> HTTP 500.
    response = _post_replay(sid, {}, {})
    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Internal reasoning-run-replay contract violation"
    )

    # A structurally invalid request (non-dict values) is rejected by Pydantic
    # before the service is called -> HTTP 422.
    response = client.post(
        f"/sessions/{sid}/reasoning-run/replay",
        json={
            "original_result": "not-a-dict",
            "original_snapshot": {},
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 5. Nonexistent session
# ---------------------------------------------------------------------------


def test_api_nonexistent_session_404() -> None:
    missing = str(uuid4())
    response = _post_replay(
        missing, {"input_fingerprint": "x" * 64}, {"session_id": missing}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# 6. Strict request schema
# ---------------------------------------------------------------------------


def test_api_strict_request_schema() -> None:
    sid, pre_snapshot = _seed_exogenous_session()
    result = _execute(sid)

    # An unexpected field must be rejected (extra="forbid").
    response = client.post(
        f"/sessions/{sid}/reasoning-run/replay",
        json={
            "original_result": _json_safe(result),
            "original_snapshot": _json_safe(pre_snapshot),
            "unknown_field": "rejected",
        },
    )
    assert response.status_code == 422

    # Missing required field is also rejected.
    response = client.post(
        f"/sessions/{sid}/reasoning-run/replay",
        json={"original_result": _json_safe(result)},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 7. Read-only behavior
# ---------------------------------------------------------------------------


def test_api_replay_is_read_only() -> None:
    sid, pre_snapshot = _seed_exogenous_session()
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"

    before = _counts()
    response = _post_replay(sid, result, pre_snapshot)
    after = _counts()

    assert response.status_code == 200
    assert after == before


# ---------------------------------------------------------------------------
# 8. Existing /replay regression
# ---------------------------------------------------------------------------


def test_api_step_log_replay_endpoint_untouched() -> None:
    sid, _ = _seed_exogenous_session()
    _execute(sid)

    response = client.get(f"/sessions/{sid}/replay")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# 9. Deterministic response shape
# ---------------------------------------------------------------------------


def test_api_deterministic_response_shape() -> None:
    sid, pre_snapshot = _seed_exogenous_session()
    result = _execute(sid)

    first = _post_replay(sid, result, pre_snapshot).json()
    second = _post_replay(sid, result, pre_snapshot).json()

    assert first == second
    assert ReasoningRunReplayRead.model_validate(first)
    assert ReasoningRunReplayRead.model_validate(second)


# ---------------------------------------------------------------------------
# 10. Architecture boundary — no provider integration
# ---------------------------------------------------------------------------


def test_api_no_provider_integration() -> None:
    """The canonical replay API introduces no model/provider integration.

    Scans the Task 140-specific source files and the endpoint function
    itself for forbidden provider tokens, API-key fields, or model-runtime
    calls.
    """
    repo_root = Path(__file__).resolve().parent.parent
    replay_files = [
        repo_root / "src" / "rop" / "schemas" / "reasoning_run_replay_request.py",
        repo_root / "src" / "rop" / "services" / "reasoning_run_replay.py",
        repo_root / "src" / "rop" / "schemas" / "reasoning_run_replay.py",
    ]
    forbidden = (
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "claude",
        "api_key",
        "apikey",
    )
    for path in replay_files:
        assert path.exists(), f"expected file {path} does not exist"
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{token!r} found in {path.name}"

    # The endpoint function body and signature must not reference providers.
    from rop.api.sessions import reasoning_run_replay

    endpoint_src = inspect.getsource(reasoning_run_replay).lower()
    for token in forbidden:
        assert token not in endpoint_src, f"{token!r} found in endpoint source"

    # No provider import in the sessions API module beyond what already exists.
    sessions_src = (
        (repo_root / "src" / "rop" / "api" / "sessions.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "ollama" not in sessions_src
    assert "openai" not in sessions_src
    assert "gemini" not in sessions_src
    assert "anthropic" not in sessions_src
    assert "claude" not in sessions_src

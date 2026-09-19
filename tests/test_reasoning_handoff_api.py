"""Tests for Task 059 validated reasoning handoff API.

Read-only HTTP exposure of the Task 057 handoff. The endpoint delegates
to a small orchestration service that builds the Task 055 context
exactly once and passes that exact object through Tasks 056 and 057.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.reasoning_handoff import (
    REASONING_HANDOFF_TASK_057,
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

RESPONSE_FIELDS = (
    "available",
    "handoff_consistent",
    "session_id",
    "reasoning_context",
    "context_consistency",
    "handoff_source",
)


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-059-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


# ---------------------------------------------------------------------------
# Valid case
# ---------------------------------------------------------------------------


def test_valid_session_returns_200() -> None:
    sid = _seed_full_session("Task 059 valid")
    r = client.get(f"/sessions/{sid}/reasoning-handoff")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESPONSE_FIELDS)


def test_response_source_fields() -> None:
    sid = _seed_full_session("Task 059 sources")
    payload = client.get(f"/sessions/{sid}/reasoning-handoff").json()
    assert payload["handoff_source"] == REASONING_HANDOFF_TASK_057
    assert (
        payload["reasoning_context"]["context_source"] == "REASONING_CONTEXT_TASK_055"
    )
    assert (
        payload["context_consistency"]["context_consistency_source"]
        == "REASONING_CONTEXT_CONSISTENCY_TASK_056"
    )


def test_response_has_audited_context_fingerprint() -> None:
    sid = _seed_full_session("Task 059 fingerprint")
    payload = client.get(f"/sessions/{sid}/reasoning-handoff").json()
    fp = payload["context_consistency"]["audited_context_fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_response_session_id_matches_request() -> None:
    sid = _seed_full_session("Task 059 session id")
    payload = client.get(f"/sessions/{sid}/reasoning-handoff").json()
    assert payload["session_id"] == sid


# ---------------------------------------------------------------------------
# Empty session
# ---------------------------------------------------------------------------


def test_empty_session_returns_200() -> None:
    sid = _create_session("Task 059 empty")
    r = client.get(f"/sessions/{sid}/reasoning-handoff")
    assert r.status_code == 200
    payload = r.json()
    assert payload["handoff_source"] == REASONING_HANDOFF_TASK_057
    assert "available" in payload


# ---------------------------------------------------------------------------
# Missing session
# ---------------------------------------------------------------------------


def test_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/reasoning-handoff")
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# Provenance is enforced end-to-end
# ---------------------------------------------------------------------------


def test_api_response_provenance_holds() -> None:
    """The API response must carry an audit whose
    audited_context_fingerprint matches the returned context. Use the
    service that produced both to verify, not a separately rebuilt
    context."""
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )

    sid = _seed_full_session("Task 059 provenance")
    payload = client.get(f"/sessions/{sid}/reasoning-handoff").json()

    # Recompute the fingerprint from the response's reasoning_context
    # (same object the audit was produced from) and confirm it equals
    # the audit's declared fingerprint.
    expected = ReasoningContextConsistencyService._context_fingerprint(
        payload["reasoning_context"]
    )
    assert payload["context_consistency"]["audited_context_fingerprint"] == expected


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_response_is_deterministic() -> None:
    sid = _seed_full_session("Task 059 determinism")
    first = client.get(f"/sessions/{sid}/reasoning-handoff").json()
    second = client.get(f"/sessions/{sid}/reasoning-handoff").json()
    assert first == second


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------


def test_endpoint_is_read_only() -> None:
    sid = _seed_full_session("Task 059 read-only")

    before_run = client.get(f"/sessions/{sid}/reasoning-run").json()
    before_audit = client.get(f"/sessions/{sid}/reasoning-run-consistency").json()

    for _ in range(3):
        r = client.get(f"/sessions/{sid}/reasoning-handoff")
        assert r.status_code == 200

    after_run = client.get(f"/sessions/{sid}/reasoning-run").json()
    after_audit = client.get(f"/sessions/{sid}/reasoning-run-consistency").json()
    assert after_run == before_run
    assert after_audit == before_audit


def test_endpoint_does_not_regenerate_candidates() -> None:
    sid = _seed_full_session("Task 059 no regen")
    before = client.get(f"/sessions/{sid}/candidates").json()
    r = client.get(f"/sessions/{sid}/reasoning-handoff")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/candidates").json()
    assert after == before


# ---------------------------------------------------------------------------
# Delegation: contract failure surfaces as generic 500
# ---------------------------------------------------------------------------


def test_contract_failure_returns_generic_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force the delegated handoff service to raise its contract error
    and confirm the endpoint returns 500 with a generic message, never
    the raw exception detail."""
    from rop.api import sessions as sessions_module
    from rop.services.reasoning_handoff import (
        ReasoningHandoffContractError,
    )

    sid = _seed_full_session("Task 059 forced failure")

    def boom(*_args, **_kwargs):
        raise ReasoningHandoffContractError(
            "FORCED_TEST_FAILURE", "raw internal detail must not leak"
        )

    monkeypatch.setattr(
        sessions_module.reasoning_handoff_api_service,
        "build_for_session",
        boom,
    )
    r = client.get(f"/sessions/{sid}/reasoning-handoff")
    assert r.status_code == 500
    assert "raw internal detail" not in r.json()["detail"]
    assert r.json()["detail"] == "Internal reasoning-handoff contract violation"

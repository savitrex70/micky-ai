"""Tests for Task 049 fully audited package API boundary.

Task 049 exposes Task 048's package via one POST endpoint. It is a
thin API boundary only: it delegates exclusively to Task 048 and
returns its result unchanged.
"""

from __future__ import annotations

import inspect
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.reasoning_run_execution_audit_package import (
    REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048,
    ReasoningRunExecutionAuditPackageContractError,
    ReasoningRunExecutionAuditPackageService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)
client = TestClient(app)

PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "execution_bundle",
    "bundle_consistency",
    "package_source",
)

ENDPOINT = "/sessions/{sid}/reasoning-run/execute-fully-audited"


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-049-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


# ---------------------------------------------------------------------------
# Valid endpoint
# ---------------------------------------------------------------------------


def test_valid_endpoint_returns_200() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    assert r.status_code == 200


def test_response_has_exact_package_fields() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    payload = r.json()
    assert set(payload) == set(PACKAGE_FIELDS)


def test_package_source_correct() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    payload = r.json()
    assert (
        payload["package_source"]
        == REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048
    )


def test_nested_execution_bundle_preserved() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    payload = r.json()
    bundle = payload["execution_bundle"]
    assert bundle["bundle_source"] == "REASONING_RUN_EXECUTION_BUNDLE_TASK_046"
    assert bundle["available"] is True


def test_nested_bundle_consistency_preserved() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    payload = r.json()
    consistency = payload["bundle_consistency"]
    assert consistency["available"] is True
    assert (
        consistency["bundle_consistency_source"]
        == "REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_TASK_047"
    )


def test_package_consistent_matches_task047() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    payload = r.json()
    assert payload["package_consistent"] == (
        payload["bundle_consistency"]["bundle_consistent"]
    )


def test_missing_session_returns_404() -> None:
    r = client.post(ENDPOINT.format(sid=str(uuid4())))
    assert r.status_code == 404


def test_legitimate_failed_execution_returns_200() -> None:
    """A legitimate FAILED Task 044 execution must still produce a
    valid 200 Task 048 package."""
    from rop.services.observation_extraction import ObservationExtractionService

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced")

    ObservationExtractionService.extract_and_store = boom
    try:
        sid = _create_session("Patient reports chest pain")
        r = client.post(ENDPOINT.format(sid=sid))
    finally:
        ObservationExtractionService.extract_and_store = original

    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is True
    assert payload["package_consistent"] is True
    assert payload["execution_bundle"]["execution"]["outcome"] == "FAILED"


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_task048_called_exactly_once(monkeypatch) -> None:
    calls = {"n": 0}
    original = ReasoningRunExecutionAuditPackageService.build_for_session

    def spy(self, db, session_id):
        calls["n"] += 1
        return original(self, db, session_id)

    monkeypatch.setattr(
        ReasoningRunExecutionAuditPackageService, "build_for_session", spy
    )

    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    assert r.status_code == 200
    assert calls["n"] == 1


def test_task048_result_passed_through_unchanged(monkeypatch) -> None:
    """The endpoint must return Task 048's exact result, not reconstruct
    or modify it."""
    from rop.services.reasoning_run_execution_audit_package import (
        ReasoningRunExecutionAuditPackageService,
    )

    # Build a real package to use as the canned return value.
    sid = _create_session("Patient reports chest pain")
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        canned = ReasoningRunExecutionAuditPackageService().build_for_session(
            db, UUID(sid)
        )
    finally:
        db_gen.close()

    def spy(self, db, session_id):
        return canned

    monkeypatch.setattr(
        ReasoningRunExecutionAuditPackageService,
        "build_for_session",
        spy,
    )

    r = client.post(ENDPOINT.format(sid=sid))
    assert r.status_code == 200
    # The nested contract carries UUID objects that JSON turns into
    # strings; normalize both sides to the JSON shape before comparing.
    assert r.json() == _strip_uuids(canned)


def _strip_uuids(obj):
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return [_strip_uuids(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_uuids(v) for k, v in obj.items()}
    return obj


def test_task048_contract_error_returns_500(monkeypatch) -> None:
    def boom(self, db, session_id):
        raise ReasoningRunExecutionAuditPackageContractError("TEST", "forced failure")

    monkeypatch.setattr(
        ReasoningRunExecutionAuditPackageService, "build_for_session", boom
    )

    sid = _create_session("Patient reports chest pain")
    r = client.post(ENDPOINT.format(sid=sid))
    assert r.status_code == 500
    # Generic error, never leaks raw exception detail.
    assert "forced failure" not in r.json().get("detail", "")


# ---------------------------------------------------------------------------
# No direct upstream invocation
# ---------------------------------------------------------------------------


def test_api_does_not_invoke_task044_directly() -> None:
    import rop.api.sessions as sessions_mod

    src = inspect.getsource(sessions_mod)
    # The Task 049 endpoint function specifically must not call Task 044.
    start = src.find("def execute_reasoning_run_fully_audited")
    assert start != -1
    body = src[start : start + 2000]
    assert "ReasoningRunExecutionService().execute_for_session" not in body
    assert "reasoning_run_execution_service.execute_for_session" not in body


def test_api_does_not_invoke_task045_directly() -> None:
    import rop.api.sessions as sessions_mod

    src = inspect.getsource(sessions_mod)
    start = src.find("def execute_reasoning_run_fully_audited")
    body = src[start : start + 2000]
    assert "ReasoningRunExecutionConsistencyService" not in body


def test_api_does_not_invoke_task046_directly() -> None:
    import rop.api.sessions as sessions_mod

    src = inspect.getsource(sessions_mod)
    start = src.find("def execute_reasoning_run_fully_audited")
    body = src[start : start + 2000]
    assert "reasoning_run_execution_bundle_service" not in body


def test_api_does_not_invoke_task047_directly() -> None:
    import rop.api.sessions as sessions_mod

    src = inspect.getsource(sessions_mod)
    start = src.find("def execute_reasoning_run_fully_audited")
    body = src[start : start + 2000]
    assert "ReasoningRunExecutionBundleConsistencyService" not in body
    assert "reasoning_run_execution_bundle_consistency_service" not in body


# ---------------------------------------------------------------------------
# Existing endpoints unchanged
# ---------------------------------------------------------------------------


def test_existing_execute_endpoint_unchanged() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    assert r.status_code == 200
    payload = r.json()
    # Task 044 shape.
    assert "execution_source" in payload
    assert "package_source" not in payload


def test_existing_execute_audited_endpoint_unchanged() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
    assert r.status_code == 200
    payload = r.json()
    # Task 046 shape.
    assert "bundle_source" in payload
    assert "execution" in payload
    assert "package_source" not in payload

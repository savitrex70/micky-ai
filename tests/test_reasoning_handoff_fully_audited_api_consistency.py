"""Tests for Task 066 fully audited API response consistency audit.

Task 066 audits a Task 065 HTTP response: transport metadata, session
identity, exact response shape, the nested Task 063 bundle, the nested
Task 062 package audit, the fixed source identifiers, and the provenance
binding between the nested audit and the nested package. It is pure: it
never calls the endpoint, never touches the database, never mutates the
response body.
"""

from __future__ import annotations

import copy
import inspect
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import reasoning_handoff_fully_audited_api_consistency as mod
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    ReasoningHandoffApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066,
    ReasoningHandoffFullyAuditedApiConsistencyContractError,
    ReasoningHandoffFullyAuditedApiConsistencyService,
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

ENDPOINT = "/sessions/{sid}/reasoning-handoff/fully-audited"

RESULT_FIELDS = (
    "available",
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_bundle_consistent",
    "nested_package_audit_consistent",
    "provenance_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "api_consistency_source",
    "audited_session_id",
    "audited_method",
    "audited_path",
    "audited_status_code",
    "audited_response_fingerprint",
)


def _service() -> ReasoningHandoffFullyAuditedApiConsistencyService:
    return ReasoningHandoffFullyAuditedApiConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-066-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    return sid


def _endpoint_payload(user_input: str) -> tuple[str, UUID, str, dict[str, Any]]:
    sid_str = _seed_full_session(user_input)
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"
    r = client.get(path)
    assert r.status_code == 200
    return sid_str, sid, path, r.json()


def _audit(body: dict[str, Any], sid: UUID, path: str) -> dict[str, Any]:
    return _service().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )


def _valid_audit() -> tuple[UUID, str, dict[str, Any], dict[str, Any]]:
    _sid_str, sid, path, body = _endpoint_payload("Task 066 valid")
    return sid, path, body, _audit(body, sid, path)


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_audit_shape() -> None:
    _sid, _path, _body, result = _valid_audit()
    assert set(result) == set(RESULT_FIELDS)


def test_valid_audit_is_fully_consistent() -> None:
    _sid, _path, _body, result = _valid_audit()
    assert result["available"] is True
    assert result["api_consistent"] is True
    assert result["consistency_issues"] == []
    for flag in (
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "session_consistent",
        "response_shape_consistent",
        "nested_bundle_consistent",
        "nested_package_audit_consistent",
        "provenance_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_source_is_fixed() -> None:
    _sid, _path, _body, result = _valid_audit()
    assert (
        result["api_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
    )


def test_provenance_echoes_audited_transport() -> None:
    sid, path, _body, result = _valid_audit()
    assert result["audited_session_id"] == str(sid)
    assert result["audited_method"] == "GET"
    assert result["audited_path"] == path
    assert result["audited_status_code"] == 200


def test_response_fingerprint_is_recomputable() -> None:
    _sid, _path, body, result = _valid_audit()
    expected = ReasoningHandoffFullyAuditedApiConsistencyService._response_fingerprint(
        body
    )
    assert result["audited_response_fingerprint"] == expected


def test_deterministic() -> None:
    sid, path, body, _result = _valid_audit()
    assert _audit(body, sid, path) == _audit(body, sid, path)


def test_does_not_mutate_response_body() -> None:
    sid, path, body, _result = _valid_audit()
    before = copy.deepcopy(body)
    _audit(body, sid, path)
    assert body == before


# ---------------------------------------------------------------------------
# Unauditable input
# ---------------------------------------------------------------------------


def test_missing_response_body_raises() -> None:
    sid = UUID(_create_session("Task 066 missing body"))
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        _service().build(
            session_id=sid,
            method="GET",
            path=f"/sessions/{sid}/reasoning-handoff/fully-audited",
            status_code=200,
            response_body=None,
        )
    assert ei.value.invariant == "MISSING_RESPONSE_BODY"


def test_non_mapping_response_body_raises() -> None:
    sid = UUID(_create_session("Task 066 bad body"))
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        _service().build(
            session_id=sid,
            method="GET",
            path=f"/sessions/{sid}/reasoning-handoff/fully-audited",
            status_code=200,
            response_body="not-a-mapping",  # type: ignore[arg-type]
        )
    assert ei.value.invariant == "RESPONSE_BODY_TYPE"


# ---------------------------------------------------------------------------
# Transport tampering
# ---------------------------------------------------------------------------


def _audit_with(**overrides: Any) -> dict[str, Any]:
    sid, path, body, _result = _valid_audit()
    kwargs: dict[str, Any] = {
        "session_id": sid,
        "method": "GET",
        "path": path,
        "status_code": 200,
        "response_body": body,
    }
    kwargs.update(overrides)
    return _service().build(**kwargs)


def test_wrong_method_is_reported() -> None:
    result = _audit_with(method="POST")
    assert "INVALID_METHOD" in result["consistency_issues"]
    assert result["method_consistent"] is False
    assert result["metadata_consistent"] is False
    assert result["api_consistent"] is False


def test_wrong_path_shape_is_reported() -> None:
    result = _audit_with(path="/sessions/x/reasoning-handoff")
    assert "INVALID_PATH" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_path_session_mismatch_is_reported() -> None:
    result = _audit_with(path=f"/sessions/{uuid4()}/reasoning-handoff/fully-audited")
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["metadata_consistent"] is False


def test_non_string_path_is_reported() -> None:
    result = _audit_with(path=12345)
    assert "INVALID_PATH" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_wrong_status_is_reported() -> None:
    result = _audit_with(status_code=201)
    assert "INVALID_STATUS" in result["consistency_issues"]
    assert result["status_consistent"] is False


def test_boolean_status_is_reported() -> None:
    result = _audit_with(status_code=True)
    assert "INVALID_STATUS" in result["consistency_issues"]
    assert result["status_consistent"] is False


def test_invalid_supplied_session_is_reported() -> None:
    result = _audit_with(session_id="not-a-uuid")
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False


# ---------------------------------------------------------------------------
# Session tampering
# ---------------------------------------------------------------------------


def test_response_session_mismatch_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = str(uuid4())
    result = _audit(tampered, sid, path)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["api_consistent"] is False


def test_nested_package_session_mismatch_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    other = str(uuid4())
    tampered["api_audit_package"]["session_id"] = other
    tampered["api_audit_package"]["api_consistency"]["audited_session_id"] = other
    result = _audit(tampered, sid, path)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


# ---------------------------------------------------------------------------
# Shape tampering
# ---------------------------------------------------------------------------


def test_missing_field_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    del tampered["bundle_source"]
    result = _audit(tampered, sid, path)
    assert "MISSING_RESPONSE_FIELD" in result["consistency_issues"]
    assert result["response_shape_consistent"] is False
    assert result["metadata_consistent"] is False


def test_extra_field_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["extra"] = "unexpected"
    result = _audit(tampered, sid, path)
    assert "RESPONSE_SHAPE_MISMATCH" in result["consistency_issues"]
    assert result["response_shape_consistent"] is False
    assert result["api_consistent"] is False


# ---------------------------------------------------------------------------
# Nested contracts
# ---------------------------------------------------------------------------


def test_nested_bundle_tamper_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["api_audit_package"]["method"] = "POST"
    result = _audit(tampered, sid, path)
    assert "NESTED_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistent"] is False
    assert result["api_consistent"] is False


def test_nested_bundle_consistent_false_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    result = _audit(tampered, sid, path)
    assert "NESTED_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistent"] is False


def test_nested_package_audit_tamper_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["api_audit_package_consistency"]["package_consistency_source"] = "WRONG"
    result = _audit(tampered, sid, path)
    assert "NESTED_PACKAGE_AUDIT_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_audit_consistent"] is False
    assert result["provenance_consistent"] is False


def test_nested_package_fingerprint_mismatch_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["api_audit_package_consistency"]["audited_package_fingerprint"] = "0" * 64
    result = _audit(tampered, sid, path)
    assert "NESTED_PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["api_consistent"] is False


def test_nested_package_fingerprint_compute_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing the fingerprint helper to raise must never silently pass
    the provenance check."""
    sid, path, body, _result = _valid_audit()

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("forced fingerprint failure")

    monkeypatch.setattr(
        ReasoningHandoffApiAuditPackageConsistencyService,
        "_package_fingerprint",
        boom,
    )
    result = _audit(body, sid, path)
    assert "NESTED_PACKAGE_FINGERPRINT_COMPUTE_FAILED" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["api_consistent"] is False


def test_nested_package_fingerprint_check_unavailable_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the nested audit cannot be validated, provenance must be
    explicitly unavailable -- never True."""
    sid, path, body, _result = _valid_audit()

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("forced nested validator failure")

    monkeypatch.setattr(
        ReasoningHandoffApiAuditPackageConsistencyService,
        "_validate_result",
        boom,
    )
    result = _audit(body, sid, path)
    assert "NESTED_PACKAGE_AUDIT_MISMATCH" in result["consistency_issues"]
    assert "NESTED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE" in (
        result["consistency_issues"]
    )
    assert result["nested_package_audit_consistent"] is False
    assert result["provenance_consistent"] is False
    assert result["api_consistent"] is False


def test_bundle_source_tamper_is_reported() -> None:
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    tampered["bundle_source"] = "SOMETHING_ELSE"
    result = _audit(tampered, sid, path)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["api_consistent"] is False


# ---------------------------------------------------------------------------
# Legitimate underlying inconsistency
# ---------------------------------------------------------------------------


def test_legitimately_inconsistent_handoff_is_still_api_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response whose nested handoff legitimately reports
    ``handoff_consistent = False`` still faithfully represents the Task
    063 contract, so Task 066 must report ``api_consistent = True`` and
    keep the nested bundle structurally valid."""
    import copy as _copy
    import json as _json

    from rop.api import sessions as sessions_module
    from rop.services.reasoning_context import ReasoningContextService
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )
    from rop.services.reasoning_handoff import ReasoningHandoffService

    sid_str = _seed_full_session("Task 066 legitimate inconsistency")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, sid)
    finally:
        db_gen.close()

    tampered_context = _copy.deepcopy(context)
    tampered_context["candidate_state"] = [
        {
            "id": str(uuid4()),
            "session_id": str(uuid4()),
            "name": "cross-session",
            "category": "fake",
            "trigger_reason": "test",
            "initial_score": 1.0,
            "confidence": 0.5,
            "supporting_observations": [],
            "contradicting_observations": [],
            "missing_information": [],
            "status": "pending",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    audit_055 = ReasoningContextConsistencyService().build(context=tampered_context)
    handoff = ReasoningHandoffService().build(
        reasoning_context=tampered_context,
        context_consistency=audit_055,
    )
    assert handoff["handoff_consistent"] is False
    handoff = _json.loads(_json.dumps(handoff, default=str))

    def stub(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return handoff

    orchestration = sessions_module.reasoning_handoff_fully_audited_api_service
    monkeypatch.setattr(
        orchestration.reasoning_handoff_api_service, "build_for_session", stub
    )

    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    assert body["api_audit_package"]["response"]["handoff_consistent"] is False
    assert body["bundle_consistent"] is True

    result = _audit(body, sid, path)
    assert result["api_consistent"] is True
    assert result["nested_bundle_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["consistency_issues"] == []


def test_bundle_reporting_package_inconsistency_is_still_api_consistent() -> None:
    """A structurally valid Task 063 bundle that faithfully reports an
    inconsistent nested package (``bundle_consistent = False``) is still a
    faithful API response: Task 066 must not confuse "the response
    reported a legitimate inconsistency" with "the response is
    malformed"."""
    sid, path, body, _result = _valid_audit()
    tampered = copy.deepcopy(body)
    audit = tampered["api_audit_package_consistency"]
    audit["consistency_issues"] = ["NESTED_RESPONSE_MISMATCH"]
    audit["package_consistent"] = False
    audit["nested_response_consistent"] = False
    tampered["bundle_consistent"] = False

    result = _audit(tampered, sid, path)
    assert result["api_consistent"] is True
    assert result["nested_bundle_consistent"] is True
    assert result["nested_package_audit_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["consistency_issues"] == []


# ---------------------------------------------------------------------------
# Validator: derived flags must be exactly the projection of the issues
# ---------------------------------------------------------------------------

_FLAG_INVARIANTS = (
    ("api_consistent", "API_CONSISTENT_MISMATCH"),
    ("method_consistent", "METHOD_CONSISTENT_MISMATCH"),
    ("path_consistent", "PATH_CONSISTENT_MISMATCH"),
    ("status_consistent", "STATUS_CONSISTENT_MISMATCH"),
    ("session_consistent", "SESSION_CONSISTENT_MISMATCH"),
    ("response_shape_consistent", "RESPONSE_SHAPE_CONSISTENT_MISMATCH"),
    ("nested_bundle_consistent", "NESTED_BUNDLE_CONSISTENT_MISMATCH"),
    (
        "nested_package_audit_consistent",
        "NESTED_PACKAGE_AUDIT_CONSISTENT_MISMATCH",
    ),
    ("provenance_consistent", "PROVENANCE_CONSISTENT_MISMATCH"),
    ("source_consistency", "SOURCE_CONSISTENT_MISMATCH"),
    ("metadata_consistent", "METADATA_CONSISTENT_MISMATCH"),
)


@pytest.mark.parametrize("flag,invariant", _FLAG_INVARIANTS)
def test_validate_result_rejects_tampered_derived_flag(
    flag: str, invariant: str
) -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered[flag] = not tampered[flag]
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == invariant


def test_validate_result_rejects_available_false() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered["available"] = False
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


def test_validate_result_rejects_missing_field() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    del tampered["metadata_consistent"]
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_validate_result_rejects_non_boolean_flag() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered["provenance_consistent"] = 1
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PROVENANCE_CONSISTENT_TYPE"


def test_validate_result_rejects_wrong_source() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered["api_consistency_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "INVALID_SOURCE"


def test_validate_result_rejects_duplicate_issues() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered["consistency_issues"] = ["INVALID_METHOD", "INVALID_METHOD"]
    tampered["api_consistent"] = False
    tampered["method_consistent"] = False
    tampered["metadata_consistent"] = False
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "DUPLICATE_ISSUE"


def test_validate_result_rejects_unordered_issues() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered["consistency_issues"] = ["INVALID_STATUS", "INVALID_METHOD"]
    tampered["api_consistent"] = False
    tampered["method_consistent"] = False
    tampered["status_consistent"] = False
    tampered["metadata_consistent"] = False
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "ISSUES_ORDER"


def test_validate_result_rejects_bad_fingerprint_format() -> None:
    _sid, _path, _body, result = _valid_audit()
    tampered = dict(result)
    tampered["audited_response_fingerprint"] = "NOT-HEX"
    with pytest.raises(ReasoningHandoffFullyAuditedApiConsistencyContractError) as ei:
        ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "AUDITED_RESPONSE_FINGERPRINT_FORMAT"


# ---------------------------------------------------------------------------
# Architectural assertions
# ---------------------------------------------------------------------------

_FORBIDDEN = (
    "ollama",
    "openai",
    "gemini",
    "anthropic",
    "llm",
    "provider",
    "model_name",
    "api_key",
    "rag",
    "recommendation",
)


def test_service_has_no_database_or_http_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        "get_db",
        "sqlalchemy",
        "fastapi",
        "TestClient",
        "httpx",
        "requests",
        "urllib",
    ):
        assert forbidden not in src, forbidden


def test_service_does_not_call_the_endpoint_or_build_workflows() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "rop.api.sessions",
        "build_for_session",
        "ReasoningHandoffFullyAuditedApiService",
        "ReasoningHandoffApiService",
    ):
        assert forbidden not in src, forbidden


def test_service_has_no_llm_or_provider_symbols() -> None:
    import re as _re

    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token

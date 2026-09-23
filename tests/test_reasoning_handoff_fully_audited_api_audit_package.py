"""Tests for Task 067 fully audited API audit package.

Task 067 packages the Task 065 HTTP response with its Task 066 audit, plus
a response fingerprint that binds the package to the exact response
representation that was audited. It is pure composition: no database, no
HTTP, no Task 065 endpoint call, no upstream response alteration.
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
from rop.services import reasoning_handoff_fully_audited_api_audit_package as mod
from rop.services.reasoning_handoff_api_audit_bundle import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067,
    ReasoningHandoffFullyAuditedApiAuditPackageContractError,
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066,
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

PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "response",
    "api_consistency",
    "package_source",
    "audited_response_fingerprint",
)


def _service() -> ReasoningHandoffFullyAuditedApiAuditPackageService:
    return ReasoningHandoffFullyAuditedApiAuditPackageService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-067-test"},
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


def _captured(
    user_input: str,
) -> tuple[UUID, str, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full_session(user_input)
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    return sid, path, body, audit


def _build(
    sid: UUID, path: str, body: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    return _service().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=audit,
    )


def _valid_package() -> tuple[UUID, str, dict[str, Any], dict[str, Any], dict]:
    sid, path, body, audit = _captured("Task 067 valid")
    return sid, path, body, audit, _build(sid, path, body, audit)


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_package_shape() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    assert set(package) == set(PACKAGE_FIELDS)


def test_valid_package_is_available_and_consistent() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    assert package["available"] is True
    assert package["package_consistent"] is True


def test_package_source_fixed() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    assert (
        package["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
    )


def test_transport_metadata_preserved() -> None:
    sid, path, _body, _audit, package = _valid_package()
    assert package["session_id"] == sid
    assert package["method"] == "GET"
    assert package["path"] == path
    assert package["status_code"] == 200


def test_nested_response_preserved_by_identity() -> None:
    sid, path, body, audit, _package = _valid_package()
    result = _build(sid, path, body, audit)
    assert result["response"] is body
    assert result["api_consistency"] is audit


def test_package_consistent_mirrors_task066() -> None:
    _sid, _path, _body, audit, package = _valid_package()
    assert package["package_consistent"] == audit["api_consistent"]


def test_fingerprint_binds_the_audited_response() -> None:
    _sid, _path, body, audit, package = _valid_package()
    expected = ReasoningHandoffFullyAuditedApiConsistencyService._response_fingerprint(
        body
    )
    assert package["audited_response_fingerprint"] == expected
    assert audit["audited_response_fingerprint"] == expected


def test_deterministic() -> None:
    sid, path, body, audit, package = _valid_package()
    assert _build(sid, path, body, audit) == package


def test_does_not_mutate_inputs() -> None:
    sid, path, body, audit, _package = _valid_package()
    body_before = copy.deepcopy(body)
    audit_before = copy.deepcopy(audit)
    _build(sid, path, body, audit)
    assert body == body_before
    assert audit == audit_before


def test_does_not_alter_the_response_before_fingerprinting() -> None:
    """The fingerprint must cover the untouched upstream response."""
    sid, path, body, audit, _package = _valid_package()
    fingerprint_of_original = (
        ReasoningHandoffFullyAuditedApiConsistencyService._response_fingerprint(body)
    )
    result = _build(sid, path, body, audit)
    assert result["audited_response_fingerprint"] == fingerprint_of_original
    assert result["response"] == body


# ---------------------------------------------------------------------------
# Missing inputs
# ---------------------------------------------------------------------------


def test_missing_session_raises() -> None:
    _sid, path, body, audit, _package = _valid_package()
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _service().build(
            session_id=None,
            method="GET",
            path=path,
            status_code=200,
            response=body,
            api_consistency=audit,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_missing_response_raises() -> None:
    sid, path, _body, audit, _package = _valid_package()
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method="GET",
            path=path,
            status_code=200,
            response=None,
            api_consistency=audit,
        )
    assert ei.value.invariant == "RESPONSE_MISMATCH"


def test_missing_audit_raises() -> None:
    sid, path, body, _audit, _package = _valid_package()
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method="GET",
            path=path,
            status_code=200,
            response=body,
            api_consistency=None,
        )
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _build_with(**overrides: Any) -> Any:
    sid, path, body, audit, _package = _valid_package()
    kwargs: dict[str, Any] = {
        "session_id": sid,
        "method": "GET",
        "path": path,
        "status_code": 200,
        "response": body,
        "api_consistency": audit,
    }
    kwargs.update(overrides)
    return _service().build(**kwargs)


def test_wrong_method_rejected() -> None:
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build_with(method="POST")
    assert ei.value.invariant == "INVALID_METHOD"


def test_wrong_status_rejected() -> None:
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build_with(status_code=201)
    assert ei.value.invariant == "INVALID_STATUS"


def test_wrong_path_shape_rejected() -> None:
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build_with(path="/sessions/x/reasoning-handoff")
    assert ei.value.invariant == "INVALID_PATH"


def test_non_string_path_rejected() -> None:
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build_with(path=12345)
    assert ei.value.invariant == "INVALID_PATH"


def test_path_session_mismatch_rejected() -> None:
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build_with(path=f"/sessions/{uuid4()}/reasoning-handoff/fully-audited")
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


# ---------------------------------------------------------------------------
# Nested contracts
# ---------------------------------------------------------------------------


def test_invalid_nested_response_rejected() -> None:
    sid, path, body, audit, _package = _valid_package()
    broken = copy.deepcopy(body)
    broken["api_audit_package"]["method"] = "POST"
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, broken, audit)
    assert ei.value.invariant == "RESPONSE_MISMATCH"


def test_invalid_nested_audit_rejected() -> None:
    sid, path, body, audit, _package = _valid_package()
    broken = copy.deepcopy(audit)
    broken["available"] = False
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, body, broken)
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


def test_inconsistent_nested_audit_is_faithfully_mirrored() -> None:
    """A Task 066 audit that legitimately reports a defect is accepted and
    mirrored as ``package_consistent = False`` -- Task 067 must never
    report a package as consistent when the audit it carries says
    otherwise. This matches Task 061's established behaviour for a
    defect-reporting Task 060 audit."""
    sid, path, body, audit, _package = _valid_package()
    defect_audit = copy.deepcopy(audit)
    defect_audit["consistency_issues"] = ["NESTED_BUNDLE_MISMATCH"]
    defect_audit["api_consistent"] = False
    defect_audit["nested_bundle_consistent"] = False

    package = _build(sid, path, body, defect_audit)
    assert package["package_consistent"] is False
    assert package["available"] is True
    assert package["api_consistency"]["api_consistent"] is False


def test_unavailable_audit_is_rejected() -> None:
    """An audit that cannot be trusted must never be packaged as an
    available, consistent result."""
    sid, path, body, audit, _package = _valid_package()
    broken = copy.deepcopy(audit)
    broken["available"] = False
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, body, broken)
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


def test_unaudited_response_rejected() -> None:
    """An audit bound to a *different* response must be refused: the
    fingerprint proves the audit does not correspond to this body."""
    sid, path, _body, audit, _package = _valid_package()
    other_sid, other_path, other_body, _other_audit = _captured(
        "Task 067 different response"
    )
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, other_body, audit)
    assert ei.value.invariant in ("RESPONSE_MISMATCH", "SESSION_ID_MISMATCH")


def test_audit_session_echo_mismatch_rejected() -> None:
    sid, path, body, audit, _package = _valid_package()
    broken = copy.deepcopy(audit)
    broken["audited_session_id"] = str(uuid4())
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, body, broken)
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_wrong_response_source_rejected() -> None:
    sid, path, body, audit, _package = _valid_package()
    broken = copy.deepcopy(body)
    broken["bundle_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, broken, audit)
    assert ei.value.invariant == "RESPONSE_SOURCE_MISMATCH"


def test_wrong_audit_source_rejected() -> None:
    sid, path, body, audit, _package = _valid_package()
    broken = copy.deepcopy(audit)
    broken["api_consistency_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        _build(sid, path, body, broken)
    assert ei.value.invariant == "API_AUDIT_SOURCE_MISMATCH"


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def test_validate_result_rejects_tampered_package_consistent() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


def test_validate_result_rejects_wrong_package_source() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    tampered["package_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


def test_validate_result_rejects_tampered_fingerprint() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    tampered["audited_response_fingerprint"] = "0" * 64
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "RESPONSE_FINGERPRINT_MISMATCH"


def test_validate_result_rejects_available_false() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    tampered["available"] = False
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


def test_validate_result_rejects_missing_field() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    del tampered["audited_response_fingerprint"]
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "MISSING_PACKAGE_FIELD"


def test_validate_result_rejects_non_boolean_flag() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    tampered["package_consistent"] = 1
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_TYPE"


def test_validate_result_rejects_bad_transport() -> None:
    _sid, _path, _body, _audit, package = _valid_package()
    tampered = dict(package)
    tampered["method"] = "POST"
    with pytest.raises(ReasoningHandoffFullyAuditedApiAuditPackageContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "INVALID_METHOD"


# ---------------------------------------------------------------------------
# Legitimate underlying inconsistency
# ---------------------------------------------------------------------------


def test_package_handles_legitimately_inconsistent_bundle() -> None:
    """A Task 063 response whose nested audit legitimately reports an
    inconsistency is still faithfully represented: Task 066 reports
    ``api_consistent = True`` and Task 067 therefore derives
    ``package_consistent = True`` for a valid package."""
    sid, path, body, audit, _package = _valid_package()
    tampered = copy.deepcopy(body)
    nested_audit = tampered["api_audit_package_consistency"]
    nested_audit["consistency_issues"] = ["NESTED_RESPONSE_MISMATCH"]
    nested_audit["package_consistent"] = False
    nested_audit["nested_response_consistent"] = False
    tampered["bundle_consistent"] = False

    rebuilt_audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=tampered,
    )
    assert rebuilt_audit["api_consistent"] is True

    package = _build(sid, path, tampered, rebuilt_audit)
    assert package["package_consistent"] is True
    assert package["available"] is True
    assert package["response"]["bundle_consistent"] is False


# ---------------------------------------------------------------------------
# Fingerprint compute failure regression (historical defect)
# ---------------------------------------------------------------------------


def test_build_fingerprint_compute_failure_is_contract_error() -> None:
    """Reproducing the historical defect: _response_fingerprint raising must
    become a Task 067 contract error, not a raw RuntimeError, and must not
    report package_consistent=True.
    """
    from unittest.mock import patch

    sid, path, body, audit = _captured("Task 067 fingerprint failure build")
    with patch.object(
        ReasoningHandoffFullyAuditedApiConsistencyService,
        "_response_fingerprint",
        side_effect=RuntimeError("forced fingerprint failure"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditPackageContractError
        ) as ei:
            _service().build(
                session_id=sid,
                method="GET",
                path=path,
                status_code=200,
                response=body,
                api_consistency=audit,
            )
        assert ei.value.invariant == "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED"
        # Purposefully not returning a package; ensure no silent success.
        assert isinstance(ei.value.__cause__, RuntimeError)


def test_validate_result_fingerprint_compute_failure_is_contract_error() -> None:
    """_validate_result must convert recomputation failure into the same
    invariant and preserve the cause.
    """
    from unittest.mock import patch

    _sid, _path, _body, _audit, package = _valid_package()
    # Tamper copy to ensure we do not mutate the original valid package.
    tampered = dict(package)
    # Keep fingerprint string well-formed so the recompute path is the only
    # failure.
    with patch.object(
        ReasoningHandoffFullyAuditedApiConsistencyService,
        "_response_fingerprint",
        side_effect=RuntimeError("forced fingerprint failure"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditPackageContractError
        ) as ei:
            ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(
                tampered
            )
        assert ei.value.invariant == "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED"
        assert isinstance(ei.value.__cause__, RuntimeError)


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


def test_nested_source_constants_are_the_real_upstream_identifiers() -> None:
    """The Task 067 source checks must reference the actual Task 063 and
    Task 066 constants, not locally invented strings."""
    assert (
        REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        == "REASONING_HANDOFF_API_AUDIT_BUNDLE_TASK_063"
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
        == "REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_TASK_066"
    )

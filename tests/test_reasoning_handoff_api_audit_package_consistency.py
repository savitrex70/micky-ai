"""Tests for Task 062 API audit package consistency audit.

Task 062 is a pure audit over a supplied Task 061 package. It does
not call upstream build() workflows, does not call HTTP, does not
access the database, and does not mutate its input.
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
from rop.services import (
    reasoning_handoff_api_audit_package_consistency as mod,
)
from rop.services.reasoning_handoff_api_audit_package import (
    ReasoningHandoffApiAuditPackageService,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062,
    ReasoningHandoffApiAuditPackageConsistencyContractError,
    ReasoningHandoffApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_api_consistency import (
    ReasoningHandoffApiConsistencyService,
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

RESULT_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_package_fingerprint",
)


def _service() -> ReasoningHandoffApiAuditPackageConsistencyService:
    return ReasoningHandoffApiAuditPackageConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-062-test"},
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


def _real_response_and_audit() -> (
    tuple[UUID, str, str, int, dict[str, Any], dict[str, Any]]
):
    """Call the real Task 059 endpoint and audit it with Task 060."""
    sid_str = _seed_full_session("Task 062 capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    audit = ReasoningHandoffApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    return sid, "GET", path, 200, body, audit


def _valid_package() -> dict[str, Any]:
    sid, method, path, status, body, audit = _real_response_and_audit()
    return ReasoningHandoffApiAuditPackageService().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_package_consistent() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_package_all_flags_true() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    for flag in (
        "session_consistent",
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "nested_response_consistent",
        "nested_api_consistency_consistent",
        "provenance_consistent",
        "package_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_package_consistency_source_fixed() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    assert (
        result["package_consistency_source"]
        == REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062
    )


def test_audited_package_fingerprint_present() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    fp = result["audited_package_fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_valid_but_underlying_inconsistent_package() -> None:
    """A Task 061 package whose nested response legitimately carries
    handoff_consistent=False must still produce a Task 062 audit with
    package_consistent=True -- provided the HTTP response is a
    faithful representation of that handoff (Task 060 reports
    api_consistent=True) and every Task 062 cross-check passes.

    This is the "underlying reasoning is inconsistent, but the API
    representation is faithful" case. The nested handoff is built
    through the real services so it is genuinely valid as a Task 057
    result -- it simply reports handoff_consistent=False.
    """
    from rop.services.reasoning_context import ReasoningContextService
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )
    from rop.services.reasoning_handoff import ReasoningHandoffService

    sid_str = _seed_full_session("Task 062 underlying inconsistent")
    sid = UUID(sid_str)

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, sid)
    finally:
        db_gen.close()

    # Force the reasoning context to be legitimately inconsistent by
    # injecting a cross-session candidate, then build a real handoff
    # through Task 056 and Task 057. The resulting handoff has
    # handoff_consistent=False but is a perfectly valid Task 057
    # result.
    tampered_context = copy.deepcopy(context)
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

    # Serialize the handoff the way the API would.
    import json as _json

    body = _json.loads(_json.dumps(handoff, default=str))

    # Task 060 must report api_consistent=True: the HTTP response is a
    # faithful representation of the (valid but internally
    # inconsistent) handoff.
    path = f"/sessions/{sid_str}/reasoning-handoff"
    api_audit = ReasoningHandoffApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    assert api_audit["api_consistent"] is True

    # Task 061 packages them; package_consistent = api_consistent.
    package = ReasoningHandoffApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    assert package["package_consistent"] is True

    # Task 062 confirms the package is internally consistent even
    # though the underlying handoff reports handoff_consistent=False.
    result = _service().build(package=package)
    assert result["package_consistent"] is True
    assert result["nested_response_consistent"] is True
    assert result["nested_api_consistency_consistent"] is True


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_missing_package_raises() -> None:
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        _service().build(package=None)
    assert ei.value.invariant == "MISSING_PACKAGE"


def test_non_mapping_package_raises() -> None:
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        _service().build(package="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "PACKAGE_TYPE"


def test_missing_field_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    del broken["package_source"]
    result = _service().build(package=broken)
    assert "MISSING_PACKAGE_FIELD" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_available_false_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["available"] = False
    result = _service().build(package=broken)
    assert "INVALID_PACKAGE_AVAILABLE" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def test_invalid_method_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["method"] = "POST"
    result = _service().build(package=broken)
    assert "METHOD_INVALID" in result["consistency_issues"]
    assert result["method_consistent"] is False


def test_invalid_path_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["path"] = "/wrong"
    result = _service().build(package=broken)
    assert "PATH_INVALID" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_invalid_path_uuid_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    other = str(uuid4())
    broken["path"] = f"/sessions/{other}/reasoning-handoff"
    result = _service().build(package=broken)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_invalid_status_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["status_code"] = 500
    result = _service().build(package=broken)
    assert "STATUS_CODE_INVALID" in result["consistency_issues"]
    assert result["status_consistent"] is False


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def test_invalid_session_uuid_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["session_id"] = "not-a-uuid"
    result = _service().build(package=broken)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


def test_package_session_mismatch_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["session_id"] = uuid4()
    result = _service().build(package=broken)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_path_session_mismatch_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    other = str(uuid4())
    broken["path"] = f"/sessions/{other}/reasoning-handoff"
    result = _service().build(package=broken)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_response_session_mismatch_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["response"]["session_id"] = str(uuid4())
    result = _service().build(package=broken)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_nested_reasoning_context_session_mismatch_reported() -> None:
    """Change ONLY response.reasoning_context.session_id. The
    top-level response session, supplied session, and path all stay
    at the original. Task 062 must detect SESSION_ID_MISMATCH."""
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["response"]["reasoning_context"]["session_id"] = str(uuid4())
    result = _service().build(package=broken)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_audited_session_mismatch_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["api_consistency"]["audited_session_id"] = str(uuid4())
    result = _service().build(package=broken)
    assert "AUDITED_SESSION_ID_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Transport provenance
# ---------------------------------------------------------------------------


def test_stale_audited_method_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["api_consistency"]["audited_method"] = "POST"
    result = _service().build(package=broken)
    assert "AUDITED_METHOD_MISMATCH" in result["consistency_issues"]


def test_stale_audited_path_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["api_consistency"]["audited_path"] = "/wrong"
    result = _service().build(package=broken)
    assert "AUDITED_PATH_MISMATCH" in result["consistency_issues"]


def test_stale_audited_status_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["api_consistency"]["audited_status_code"] = 500
    result = _service().build(package=broken)
    assert "AUDITED_STATUS_CODE_MISMATCH" in result["consistency_issues"]


def test_tampered_fingerprint_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    original = broken["api_consistency"]["audited_response_fingerprint"]
    broken["api_consistency"]["audited_response_fingerprint"] = (
        "0" * 64 if original != "0" * 64 else "1" * 64
    )
    result = _service().build(package=broken)
    assert "AUDITED_RESPONSE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


# ---------------------------------------------------------------------------
# Nested contracts
# ---------------------------------------------------------------------------


def test_malformed_response_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    del broken["response"]["reasoning_context"]["candidate_state"]
    result = _service().build(package=broken)
    assert "NESTED_RESPONSE_MISMATCH" in result["consistency_issues"]


def test_malformed_audit_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    del broken["api_consistency"]["audited_response_fingerprint"]
    result = _service().build(package=broken)
    assert "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Package relationship
# ---------------------------------------------------------------------------


def test_package_relationship_mismatch_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["package_consistent"] = not broken["package_consistent"]
    result = _service().build(package=broken)
    assert "PACKAGE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["package_relationship_consistent"] is False


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_response_source_mismatch_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["response"]["handoff_source"] = "SOMETHING_ELSE"
    result = _service().build(package=broken)
    assert "RESPONSE_SOURCE_MISMATCH" in result["consistency_issues"]


def test_audit_source_mismatch_reported() -> None:
    package = _valid_package()
    broken = copy.deepcopy(package)
    broken["api_consistency"]["api_consistency_source"] = "SOMETHING_ELSE"
    result = _service().build(package=broken)
    assert "API_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]


def test_package_source_mismatch_reported() -> None:
    package = _valid_package()
    broken = dict(package)
    broken["package_source"] = "SOMETHING_ELSE"
    result = _service().build(package=broken)
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# _validate_result tampering
# ---------------------------------------------------------------------------


def test_validate_result_rejects_wrong_source() -> None:
    result = _service().build(package=_valid_package())
    tampered = dict(result)
    tampered["package_consistency_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENCY_SOURCE_MISMATCH"


def test_validate_result_rejects_consistency_mismatch() -> None:
    result = _service().build(package=_valid_package())
    tampered = dict(result)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_bad_fingerprint() -> None:
    result = _service().build(package=_valid_package())
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "short"
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_does_not_mutate_package() -> None:
    package = _valid_package()
    before = copy.deepcopy(package)
    _service().build(package=package)
    assert package == before


def test_deterministic() -> None:
    package = _valid_package()
    s = _service()
    assert s.build(package=package) == s.build(package=package)


# ---------------------------------------------------------------------------
# Architectural assertions
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
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


def test_no_database_or_http_imports_in_service() -> None:
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


def test_no_api_orchestration_call_in_service() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "ReasoningHandoffApiService",
        "build_for_session",
        "rop.api.sessions",
    ):
        assert forbidden not in src, forbidden


def test_no_build_calls_to_nested_services() -> None:
    """The service may import Task 057/060/061 static validators and
    helpers, but must never invoke a build() method on any of them."""
    src = inspect.getsource(mod)
    for line in src.splitlines():
        stripped = line.strip()
        for cls in (
            "ReasoningHandoffService",
            "ReasoningHandoffApiConsistencyService",
            "ReasoningHandoffApiAuditPackageService",
        ):
            if cls in stripped and "(" in stripped:
                assert (
                    "_validate_result" in stripped
                    or "_response_fingerprint" in stripped
                    or "_package_fingerprint" in stripped
                ), stripped


def test_no_llm_or_provider_symbols_in_service() -> None:
    """Forbidden tokens must not appear as standalone identifiers.

    Word-boundary matching prevents false positives from tokens that
    legitimately appear as substrings of unrelated identifiers (e.g.
    ``llm`` inside ``fullmatch``)."""
    import re as _re

    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN_SUBSTRINGS:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token


# ---------------------------------------------------------------------------
# Final-validator hardening: tampered derived flags are rejected
# ---------------------------------------------------------------------------


def _clean_audit_result() -> dict:
    package = _valid_package()
    return _service().build(package=package)


def test_validate_result_rejects_tampered_session_consistent() -> None:
    """session_consistent=False with an empty issue list contradicts the
    derived-flag relationship and must be rejected."""
    tampered = dict(_clean_audit_result())
    tampered["session_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "SESSION_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_method_consistent() -> None:
    tampered = dict(_clean_audit_result())
    tampered["method_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "METHOD_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_path_consistent() -> None:
    tampered = dict(_clean_audit_result())
    tampered["path_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PATH_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_status_consistent() -> None:
    tampered = dict(_clean_audit_result())
    tampered["status_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "STATUS_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_nested_response_consistent() -> None:
    tampered = dict(_clean_audit_result())
    tampered["nested_response_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "NESTED_RESPONSE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_nested_api_consistency() -> None:
    tampered = dict(_clean_audit_result())
    tampered["nested_api_consistency_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "NESTED_API_CONSISTENCY_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_provenance_consistent() -> None:
    tampered = dict(_clean_audit_result())
    tampered["provenance_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PROVENANCE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_package_relationship() -> None:
    tampered = dict(_clean_audit_result())
    tampered["package_relationship_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_RELATIONSHIP_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_source_consistency() -> None:
    tampered = dict(_clean_audit_result())
    tampered["source_consistency"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "SOURCE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_metadata_consistent() -> None:
    tampered = dict(_clean_audit_result())
    tampered["metadata_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "METADATA_CONSISTENT_MISMATCH"


def test_validate_result_rejects_available_false() -> None:
    tampered = dict(_clean_audit_result())
    tampered["available"] = False
    with pytest.raises(ReasoningHandoffApiAuditPackageConsistencyContractError) as ei:
        ReasoningHandoffApiAuditPackageConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "RESULT_UNAVAILABLE"

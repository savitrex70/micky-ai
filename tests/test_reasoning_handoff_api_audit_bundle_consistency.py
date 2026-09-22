"""Tests for Task 064 API audit bundle consistency audit.

Pure audit over a supplied Task 063 bundle. Does not call upstream
build workflows, HTTP, or the database; does not mutate its input.
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
    reasoning_handoff_api_audit_bundle_consistency as mod,
)
from rop.services.reasoning_handoff_api_audit_bundle import (
    ReasoningHandoffApiAuditBundleService,
)
from rop.services.reasoning_handoff_api_audit_bundle_consistency import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_064,
    ReasoningHandoffApiAuditBundleConsistencyContractError,
    ReasoningHandoffApiAuditBundleConsistencyService,
)
from rop.services.reasoning_handoff_api_audit_package import (
    ReasoningHandoffApiAuditPackageService,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
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
    "nested_package_consistent",
    "nested_package_audit_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_bundle_fingerprint",
)


def _service() -> ReasoningHandoffApiAuditBundleConsistencyService:
    return ReasoningHandoffApiAuditBundleConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-064-test"},
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


def _valid_bundle() -> dict[str, Any]:
    sid_str = _seed_full_session("Task 064 capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    api_audit = ReasoningHandoffApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    package = ReasoningHandoffApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    package_audit = ReasoningHandoffApiAuditPackageConsistencyService().build(
        package=package
    )
    return ReasoningHandoffApiAuditBundleService().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_bundle_consistent() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_bundle_all_flags_true() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    for flag in (
        "session_consistent",
        "nested_package_consistent",
        "nested_package_audit_consistent",
        "provenance_consistent",
        "bundle_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_source_fixed() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert (
        result["package_consistency_source"]
        == REASONING_HANDOFF_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_064
    )


def test_fingerprint_present() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    fp = result["audited_bundle_fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------------------
# Contract errors
# ---------------------------------------------------------------------------


def test_missing_bundle_raises() -> None:
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        _service().build(bundle=None)
    assert ei.value.invariant == "MISSING_BUNDLE"


def test_non_mapping_bundle_raises() -> None:
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        _service().build(bundle="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "BUNDLE_TYPE"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_missing_field_reported() -> None:
    bundle = _valid_bundle()
    broken = dict(bundle)
    del broken["bundle_source"]
    result = _service().build(bundle=broken)
    assert "MISSING_BUNDLE_FIELD" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_available_false_reported() -> None:
    bundle = _valid_bundle()
    broken = dict(bundle)
    broken["available"] = False
    result = _service().build(bundle=broken)
    assert "INVALID_BUNDLE_AVAILABLE" in result["consistency_issues"]


def test_invalid_session_reported() -> None:
    bundle = _valid_bundle()
    broken = dict(bundle)
    broken["session_id"] = "not-a-uuid"
    result = _service().build(bundle=broken)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Nested contract failures
# ---------------------------------------------------------------------------


def test_malformed_package_reported() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle)
    del broken["api_audit_package"]["package_source"]
    result = _service().build(bundle=broken)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]


def test_malformed_audit_reported() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle)
    del broken["api_audit_package_consistency"]["audited_package_fingerprint"]
    result = _service().build(bundle=broken)
    assert "NESTED_PACKAGE_AUDIT_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def test_session_mismatch_reported() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle)
    broken["api_audit_package"]["session_id"] = str(uuid4())
    result = _service().build(bundle=broken)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_tampered_fingerprint_reported() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle)
    original = broken["api_audit_package_consistency"]["audited_package_fingerprint"]
    broken["api_audit_package_consistency"]["audited_package_fingerprint"] = (
        "0" * 64 if original != "0" * 64 else "1" * 64
    )
    result = _service().build(bundle=broken)
    assert "AUDITED_PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


# ---------------------------------------------------------------------------
# Bundle relationship
# ---------------------------------------------------------------------------


def test_bundle_relationship_mismatch_reported() -> None:
    bundle = _valid_bundle()
    broken = dict(bundle)
    broken["bundle_consistent"] = not broken["bundle_consistent"]
    result = _service().build(bundle=broken)
    assert "BUNDLE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["bundle_relationship_consistent"] is False


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_package_source_mismatch_reported() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle)
    broken["api_audit_package"]["package_source"] = "SOMETHING_ELSE"
    result = _service().build(bundle=broken)
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]


def test_consistency_source_mismatch_reported() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle)
    broken["api_audit_package_consistency"][
        "package_consistency_source"
    ] = "SOMETHING_ELSE"
    result = _service().build(bundle=broken)
    assert "CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]


def test_bundle_source_mismatch_reported() -> None:
    bundle = _valid_bundle()
    broken = dict(bundle)
    broken["bundle_source"] = "SOMETHING_ELSE"
    result = _service().build(bundle=broken)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# Derived-flag relationship enforcement
# ---------------------------------------------------------------------------


def _clean_result() -> dict:
    return _service().build(bundle=_valid_bundle())


def test_validate_result_rejects_tampered_session_consistent() -> None:
    tampered = dict(_clean_result())
    tampered["session_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "SESSION_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_nested_package() -> None:
    tampered = dict(_clean_result())
    tampered["nested_package_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "NESTED_PACKAGE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_nested_audit() -> None:
    tampered = dict(_clean_result())
    tampered["nested_package_audit_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "NESTED_PACKAGE_AUDIT_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_provenance() -> None:
    tampered = dict(_clean_result())
    tampered["provenance_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "PROVENANCE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_bundle_relationship() -> None:
    tampered = dict(_clean_result())
    tampered["bundle_relationship_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "BUNDLE_RELATIONSHIP_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_source_consistency() -> None:
    tampered = dict(_clean_result())
    tampered["source_consistency"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "SOURCE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_metadata() -> None:
    tampered = dict(_clean_result())
    tampered["metadata_consistent"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "METADATA_CONSISTENT_MISMATCH"


def test_validate_result_rejects_tampered_available() -> None:
    tampered = dict(_clean_result())
    tampered["available"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleConsistencyContractError) as ei:
        ReasoningHandoffApiAuditBundleConsistencyService._validate_result(tampered)
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    bundle = _valid_bundle()
    s = _service()
    assert s.build(bundle=bundle) == s.build(bundle=bundle)


def test_does_not_mutate_bundle() -> None:
    bundle = _valid_bundle()
    before = copy.deepcopy(bundle)
    _service().build(bundle=bundle)
    assert bundle == before


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


def test_no_llm_or_provider_symbols_in_service() -> None:
    import re as _re

    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token

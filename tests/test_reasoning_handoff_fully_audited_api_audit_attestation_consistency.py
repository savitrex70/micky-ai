"""Tests for Task 072 pure consistency audit of Task 071 attestation."""

from __future__ import annotations

import copy
import inspect
from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_consistency as mod,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle import (
    ReasoningHandoffFullyAuditedApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle_consistency import (
    ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_consistency import (
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

RESULT_FIELDS = (
    "available",
    "attestation_consistent",
    "session_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
    "provenance_consistent",
    "attestation_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "attestation_consistency_source",
    "audited_attestation_fingerprint",
)

ISSUE_ORDER = (
    "MISSING_ATTESTATION_FIELD",
    "INVALID_ATTESTATION_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_BUNDLE_MISMATCH",
    "NESTED_BUNDLE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
    "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
    "AUDITED_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE",
    "ATTESTATION_RELATIONSHIP_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "ATTESTATION_SOURCE_MISMATCH",
    "ATTESTATION_CONTRACT_MISMATCH",
)


def _service() -> ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService:
    return ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService()


def _check(attestation: Any) -> dict[str, Any]:
    return _service().build(attestation=attestation)


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-072-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full(user_input: str) -> str:
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


def _real_attestation() -> dict[str, Any]:
    sid_str = _seed_full("Task 072 capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    api_audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid, method="GET", path=path, status_code=200, response_body=body
    )
    package = ReasoningHandoffFullyAuditedApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    package_audit = (
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService().build(
            package=package
        )
    )
    bundle = ReasoningHandoffFullyAuditedApiAuditBundleService().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )
    consistency = ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService().build(
        bundle=bundle
    )
    return ReasoningHandoffFullyAuditedApiAuditAttestationService().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )


# -----------------------------------------------------------------------------
# Valid contract
# -----------------------------------------------------------------------------
def test_valid_attestation_accepted() -> None:
    att = _real_attestation()
    result = _check(att)
    assert result["available"] is True
    assert result["attestation_consistent"] is True
    assert result["session_consistent"] is True
    assert result["nested_bundle_consistent"] is True
    assert result["nested_bundle_consistency_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["attestation_relationship_consistent"] is True
    assert result["source_consistency"] is True
    assert result["metadata_consistent"] is True
    assert result["consistency_issues"] == []
    assert (
        result["attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
    )


def test_exact_12_fields() -> None:
    att = _real_attestation()
    result = _check(att)
    assert set(result.keys()) == set(RESULT_FIELDS)
    assert len(result) == 12


def test_pydantic_schema_validation() -> None:
    att = _real_attestation()
    result = _check(att)
    model = (
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead.model_validate(
            result
        )
    )
    assert model.available is True
    assert model.attestation_consistent is True
    assert len(model.audited_attestation_fingerprint) == 64


def test_deterministic_output() -> None:
    att = _real_attestation()
    r1 = _check(att)
    r2 = _check(att)
    assert r1 == r2


def test_deterministic_fingerprint() -> None:
    att = _real_attestation()
    r1 = _check(att)
    r2 = _check(att)
    fp = r1["audited_attestation_fingerprint"]
    assert fp == r2["audited_attestation_fingerprint"]
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)
    assert fp == att["audited_attestation_fingerprint"]


# -----------------------------------------------------------------------------
# Structural defects
# -----------------------------------------------------------------------------
def test_missing_attestation_field() -> None:
    att = _real_attestation()
    del att["session_id"]
    result = _check(att)
    assert "MISSING_ATTESTATION_FIELD" in result["consistency_issues"]
    assert result["metadata_consistent"] is False
    assert result["attestation_consistent"] is False


def test_invalid_attestation_available_false() -> None:
    att = _real_attestation()
    att["available"] = False
    result = _check(att)
    assert "INVALID_ATTESTATION_AVAILABLE" in result["consistency_issues"]
    assert result["metadata_consistent"] is False
    assert result["attestation_consistent"] is False


def test_invalid_attestation_available_non_bool() -> None:
    att = _real_attestation()
    att["available"] = "true"  # type: ignore[assignment]
    result = _check(att)
    assert "INVALID_ATTESTATION_AVAILABLE" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_invalid_session_id_structural() -> None:
    att = _real_attestation()
    att["session_id"] = "not-a-valid-uuid"
    result = _check(att)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["attestation_consistent"] is False


def test_malformed_nested_bundle() -> None:
    att = _real_attestation()
    broken_bundle = copy.deepcopy(att["api_audit_bundle"])
    broken_bundle["available"] = False
    att["api_audit_bundle"] = broken_bundle
    result = _check(att)
    assert "NESTED_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistent"] is False
    assert result["attestation_consistent"] is False


def test_malformed_nested_consistency() -> None:
    att = _real_attestation()
    broken_consistency = copy.deepcopy(att["api_audit_bundle_consistency"])
    broken_consistency["available"] = False
    att["api_audit_bundle_consistency"] = broken_consistency
    result = _check(att)
    assert "NESTED_BUNDLE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistency_consistent"] is False
    assert result["attestation_consistent"] is False


# -----------------------------------------------------------------------------
# Session validation
# -----------------------------------------------------------------------------
def test_session_id_mismatch() -> None:
    att = _real_attestation()
    att["session_id"] = uuid4()
    result = _check(att)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["attestation_consistent"] is False


def test_session_id_invalid_type() -> None:
    att = _real_attestation()
    att["session_id"] = 123456
    result = _check(att)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False


# -----------------------------------------------------------------------------
# Fingerprint provenance
# -----------------------------------------------------------------------------
def test_tampered_attestation_fingerprint() -> None:
    att = _real_attestation()
    att["audited_attestation_fingerprint"] = "0" * 64
    result = _check(att)
    assert "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["attestation_consistent"] is False


def test_forced_fingerprint_computation_failure_contract() -> None:
    att = _real_attestation()
    with patch(
        "rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency._attestation_fingerprint",
        side_effect=RuntimeError("forced failure"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
        ) as ei:
            _check(att)
        assert ei.value.invariant == "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED"
        assert isinstance(ei.value.__cause__, RuntimeError)


def test_forced_fingerprint_computation_failure_issue() -> None:
    att = _real_attestation()
    with patch(
        "rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency._expected_attestation_fingerprint",
        side_effect=RuntimeError("forced failure in expected"),
    ):
        result = _check(att)
        assert (
            "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED"
            in result["consistency_issues"]
        )
        assert result["provenance_consistent"] is False
        assert result["attestation_consistent"] is False


def test_unavailable_fingerprint_check_due_to_unusable_nested_structure() -> None:
    att = _real_attestation()
    att["api_audit_bundle"] = {"corrupt": True}
    result = _check(att)
    assert (
        "AUDITED_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["provenance_consistent"] is False
    assert result["nested_bundle_consistent"] is False


# -----------------------------------------------------------------------------
# Relationship validation
# -----------------------------------------------------------------------------
def test_attestation_relationship_mismatch() -> None:
    att = _real_attestation()
    # Invert attestation_consistent so it disagrees with Task 070 bundle_consistent
    att["attestation_consistent"] = not att["attestation_consistent"]
    result = _check(att)
    assert "ATTESTATION_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["attestation_relationship_consistent"] is False
    assert result["attestation_consistent"] is False


# -----------------------------------------------------------------------------
# Source provenance
# -----------------------------------------------------------------------------
def test_bundle_source_mismatch() -> None:
    att = _real_attestation()
    broken_bundle = copy.deepcopy(att["api_audit_bundle"])
    broken_bundle["bundle_source"] = "WRONG_SOURCE"
    att["api_audit_bundle"] = broken_bundle
    result = _check(att)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["attestation_consistent"] is False


def test_bundle_consistency_source_mismatch() -> None:
    att = _real_attestation()
    broken_consistency = copy.deepcopy(att["api_audit_bundle_consistency"])
    broken_consistency["bundle_consistency_source"] = "WRONG_SOURCE"
    att["api_audit_bundle_consistency"] = broken_consistency
    result = _check(att)
    assert "BUNDLE_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["attestation_consistent"] is False


def test_attestation_source_mismatch() -> None:
    att = _real_attestation()
    att["attestation_source"] = "WRONG_SOURCE"
    result = _check(att)
    assert "ATTESTATION_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["attestation_consistent"] is False


# -----------------------------------------------------------------------------
# Legitimate defect semantics
# -----------------------------------------------------------------------------
def _real_legitimate_defect_chain() -> dict[str, Any]:
    """Explicitly construct a genuine coherent defect chain.

    Task 069: bundle_consistent = False
    Task 070: bundle_consistent = True, consistency_issues = []
    Task 071: attestation_consistent = True
    Task 072: attestation_consistent = True
    """
    sid_str = _seed_full("Task 072 legitimate defect capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    api_audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid, method="GET", path=path, status_code=200, response_body=body
    )
    package = ReasoningHandoffFullyAuditedApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    orig_audit = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService().build(
        package=package
    )

    defect_audit = copy.deepcopy(orig_audit)
    defect_audit["consistency_issues"] = ["NESTED_RESPONSE_MISMATCH"]
    defect_audit["package_consistent"] = False
    defect_audit["nested_response_consistent"] = False
    defect_audit["session_consistent"] = True
    defect_audit["method_consistent"] = True
    defect_audit["path_consistent"] = True
    defect_audit["status_consistent"] = True
    defect_audit["nested_api_audit_consistent"] = True
    defect_audit["provenance_consistent"] = True
    defect_audit["package_relationship_consistent"] = True
    defect_audit["source_consistency"] = True
    defect_audit["metadata_consistent"] = True

    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
        defect_audit
    )

    defect_bundle = ReasoningHandoffFullyAuditedApiAuditBundleService().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=defect_audit,
    )
    assert defect_bundle["bundle_consistent"] is False

    defect_consistency = (
        ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService().build(
            bundle=defect_bundle
        )
    )
    assert defect_consistency["bundle_consistent"] is True
    assert defect_consistency["consistency_issues"] == []

    attestation = ReasoningHandoffFullyAuditedApiAuditAttestationService().build(
        session_id=sid,
        api_audit_bundle=defect_bundle,
        api_audit_bundle_consistency=defect_consistency,
    )
    assert attestation["attestation_consistent"] is True
    return attestation


def test_legitimate_defect_chain_semantics() -> None:
    att = _real_legitimate_defect_chain()
    # Confirm underlying chain properties
    assert att["api_audit_bundle"]["bundle_consistent"] is False
    assert att["api_audit_bundle_consistency"]["bundle_consistent"] is True
    assert att["attestation_consistent"] is True

    result = _check(att)
    assert result["available"] is True
    assert result["attestation_consistent"] is True
    assert result["nested_bundle_consistent"] is True
    assert result["nested_bundle_consistency_consistent"] is True
    assert result["attestation_relationship_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["source_consistency"] is True
    assert result["session_consistent"] is True
    assert result["metadata_consistent"] is True
    assert result["consistency_issues"] == []


def test_legitimate_defect_tampered_fails() -> None:
    att = _real_legitimate_defect_chain()
    att["attestation_consistent"] = False
    result = _check(att)
    assert "ATTESTATION_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["attestation_relationship_consistent"] is False
    assert result["attestation_consistent"] is False


# -----------------------------------------------------------------------------
# Issue ordering and deduplication
# -----------------------------------------------------------------------------
def test_issue_ordering_and_deduplication() -> None:
    att = _real_attestation()
    # Introduce multiple simultaneous defects
    del att["available"]
    att["session_id"] = "not-a-uuid"
    att["attestation_source"] = "WRONG_SOURCE"

    result = _check(att)
    issues = result["consistency_issues"]
    assert len(issues) == len(set(issues))  # deduplicated
    expected = [i for i in ISSUE_ORDER if i in issues]
    assert issues == expected


def test_multiple_simultaneous_defects_order() -> None:
    att = _real_attestation()
    att["available"] = False
    att["session_id"] = "bad"
    att["attestation_source"] = "BAD_SOURCE"
    broken_bundle = copy.deepcopy(att["api_audit_bundle"])
    broken_bundle["bundle_source"] = "BAD_BUNDLE_SOURCE"
    att["api_audit_bundle"] = broken_bundle

    result = _check(att)
    issues = result["consistency_issues"]
    assert issues == [i for i in ISSUE_ORDER if i in set(issues)]


# -----------------------------------------------------------------------------
# State independence
# -----------------------------------------------------------------------------
def test_repeated_validation_same_artifact() -> None:
    att = _real_attestation()
    r1 = _check(att)
    r2 = _check(att)
    r3 = _check(att)
    assert r1 == r2 == r3


def test_a_b_a_validation() -> None:
    att_a = _real_attestation()
    att_b = _real_attestation()
    r_a1 = _check(att_a)
    _ = _check(att_b)
    r_a2 = _check(att_a)
    assert r_a1 == r_a2


def test_no_module_mutable_state() -> None:
    for name in dir(mod):
        assert not name.startswith("_LAST"), f"Found mutable state: {name}"
    # Ensure no mutable module-level dictionaries or lists
    for name, val in inspect.getmembers(mod):
        if name.startswith("__"):
            continue
        if isinstance(val, (dict, list, set)):
            # Must not be module-level mutable stores
            assert name not in ("cache", "state", "store", "registry")


# -----------------------------------------------------------------------------
# Immutability
# -----------------------------------------------------------------------------
def test_attestation_input_immutability() -> None:
    att = _real_attestation()
    before = copy.deepcopy(att)
    _ = _check(att)
    assert att == before


# -----------------------------------------------------------------------------
# Architecture restrictions
# -----------------------------------------------------------------------------
def test_production_service_has_no_forbidden_symbols() -> None:
    src_file = inspect.getfile(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService
    )
    with open(src_file, encoding="utf-8") as f:
        src = f.read()

    forbidden = (
        "SessionLocal",
        "create_engine",
        "get_db",
        "sqlalchemy",
        "TestClient",
        "httpx",
        "requests",
        "urllib",
        "FastAPI",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "provider",
        "model_name",
        "api_key",
        "RAG",
    )
    for sym in forbidden:
        assert sym not in src, f"Forbidden symbol '{sym}' in production service"


def test_production_service_does_not_call_build_workflows() -> None:
    src_file = inspect.getfile(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService
    )
    with open(src_file, encoding="utf-8") as f:
        src = f.read()

    assert (
        ".build(" not in src
    ), "Production service must not call .build() on previous services"


# -----------------------------------------------------------------------------
# Fallback Task 071 contract check
# -----------------------------------------------------------------------------
def test_fallback_task_071_contract_mismatch() -> None:
    att = _real_attestation()
    # Set attestation_consistent to 1 (int instead of bool)
    # In python 1 == True so relationship check passes, but Task 071 requires bool
    att["attestation_consistent"] = 1
    result = _check(att)
    assert "ATTESTATION_CONTRACT_MISMATCH" in result["consistency_issues"]
    assert result["attestation_consistent"] is False


# -----------------------------------------------------------------------------
# Contract boundary and output validator
# -----------------------------------------------------------------------------
def test_missing_attestation_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service().build(attestation=None)
    assert ei.value.invariant == "MISSING_ATTESTATION"


def test_non_mapping_attestation_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service().build(attestation="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "ATTESTATION_TYPE"


def test_validate_result_missing_field() -> None:
    att = _real_attestation()
    result = _check(att)
    del result["available"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_validate_result_mistyped_boolean() -> None:
    att = _real_attestation()
    result = _check(att)
    result["available"] = "invalid"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "AVAILABLE_TYPE"


def test_validate_result_unavailable() -> None:
    att = _real_attestation()
    result = _check(att)
    result["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


def test_validate_result_issues_type() -> None:
    att = _real_attestation()
    result = _check(att)
    result["consistency_issues"] = "not-a-list"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "ISSUES_TYPE"


def test_validate_result_empty_string_issue() -> None:
    att = _real_attestation()
    result = _check(att)
    result["consistency_issues"] = [""]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "ISSUE_TYPE"


def test_validate_result_duplicate_issues() -> None:
    att = _real_attestation()
    result = _check(att)
    result["consistency_issues"] = [
        "SESSION_ID_INVALID",
        "SESSION_ID_INVALID",
    ]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "DUPLICATE_ISSUE"


def test_validate_result_issues_order() -> None:
    att = _real_attestation()
    result = _check(att)
    result["consistency_issues"] = [
        "ATTESTATION_SOURCE_MISMATCH",
        "MISSING_ATTESTATION_FIELD",
    ]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "ISSUES_ORDER"


def test_validate_result_invalid_source() -> None:
    att = _real_attestation()
    result = _check(att)
    result["attestation_consistency_source"] = "WRONG_SOURCE"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "INVALID_SOURCE"


def test_validate_result_attestation_consistent_mismatch() -> None:
    att = _real_attestation()
    result = _check(att)
    result["attestation_consistent"] = False  # when consistency_issues == []
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "ATTESTATION_CONSISTENT_MISMATCH"


def test_validate_result_fingerprint_format() -> None:
    att = _real_attestation()
    result = _check(att)
    result["audited_attestation_fingerprint"] = "bad-fingerprint"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result)
    assert ei.value.invariant == "AUDITED_ATTESTATION_FINGERPRINT_FORMAT"


def test_validate_result_tampered_fingerprint_with_attestation() -> None:
    att = _real_attestation()
    result = _check(att)
    result["audited_attestation_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
    ) as ei:
        _service()._validate_result(result, attestation=att)
    assert ei.value.invariant == "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH"


def test_validate_result_flag_mismatches() -> None:
    att = _real_attestation()
    result = _check(att)
    # Tamper each flag to disagree with issues == []
    flag_invariants = [
        ("session_consistent", "SESSION_CONSISTENT_MISMATCH"),
        ("nested_bundle_consistent", "NESTED_BUNDLE_CONSISTENT_MISMATCH"),
        (
            "nested_bundle_consistency_consistent",
            "NESTED_BUNDLE_CONSISTENCY_CONSISTENT_MISMATCH",
        ),
        ("provenance_consistent", "PROVENANCE_CONSISTENT_MISMATCH"),
        (
            "attestation_relationship_consistent",
            "ATTESTATION_RELATIONSHIP_CONSISTENT_MISMATCH",
        ),
        ("source_consistency", "SOURCE_CONSISTENT_MISMATCH"),
        ("metadata_consistent", "METADATA_CONSISTENT_MISMATCH"),
    ]
    for flag, invariant in flag_invariants:
        tampered = copy.deepcopy(result)
        tampered[flag] = False
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == invariant

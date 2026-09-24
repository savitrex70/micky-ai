"""Tests for Task 074 attestation-package consistency."""

from __future__ import annotations

import copy
import inspect
from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_package_consistency as mod,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService,
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


def _service() -> ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService:
    return ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-074-test"},
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


def _valid_package() -> tuple[UUID, dict[str, Any]]:
    sid_str = _seed_full("Task 074 capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()

    api_audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    api_package = ReasoningHandoffFullyAuditedApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    package_audit = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService().build(
        package=api_package
    )
    bundle = ReasoningHandoffFullyAuditedApiAuditBundleService().build(
        session_id=sid,
        api_audit_package=api_package,
        api_audit_package_consistency=package_audit,
    )
    bundle_consistency = (
        ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService().build(
            bundle=bundle
        )
    )
    attestation = ReasoningHandoffFullyAuditedApiAuditAttestationService().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=bundle_consistency,
    )
    attestation_consistency = (
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService().build(
            attestation=attestation
        )
    )
    package = ReasoningHandoffFullyAuditedApiAuditAttestationPackageService().build(
        session_id=sid,
        attestation=attestation,
        attestation_consistency=attestation_consistency,
    )
    return sid, package


def _valid_result() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid, package = _valid_package()
    return sid, package, _service().build(package=package)


def test_valid_shape_and_self_authenticating_pair() -> None:
    _sid, package, result = _valid_result()
    assert result["available"] is True
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []
    assert result["package_fingerprint"] == result["audited_package_fingerprint"]

    expected = _service()._package_fingerprint(package)
    assert result["package_fingerprint"] == expected
    assert len(result["package_fingerprint"]) == 64

    model = ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead.model_validate(
        result
    )
    assert model.package_fingerprint == model.audited_package_fingerprint


def test_deterministic_and_input_immutable() -> None:
    _sid, package, result = _valid_result()
    before = copy.deepcopy(package)
    assert _service().build(package=package) == result
    assert package == before


def test_missing_package_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service().build(package=None)
    assert ei.value.invariant == "MISSING_PACKAGE"


def test_non_mapping_package_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service().build(package="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "PACKAGE_TYPE"


@pytest.mark.parametrize(
    ("field", "invariant"),
    (
        ("package_fingerprint", "PACKAGE_FINGERPRINT_MISMATCH"),
        ("audited_package_fingerprint", "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"),
    ),
)
def test_independent_fingerprint_tampering_is_rejected(
    field: str, invariant: str
) -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered[field] = "0" * 64
    result = _service().build(package=tampered)
    assert invariant in result["consistency_issues"]
    assert result["package_consistent"] is False
    assert result["package_fingerprint"] == result["audited_package_fingerprint"]


@pytest.mark.parametrize(
    "field",
    ("package_fingerprint", "audited_package_fingerprint"),
)
def test_missing_fingerprint_field_is_rejected(field: str) -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    del tampered[field]
    result = _service().build(package=tampered)
    assert "MISSING_PACKAGE_FIELD" in result["consistency_issues"]
    assert result["package_consistent"] is False


def test_fingerprint_pair_contradiction_is_rejected() -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered["audited_package_fingerprint"] = "0" * 64
    result = _service().build(package=tampered)
    assert "AUDITED_PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["package_fingerprint"] != "0" * 64
    assert result["package_fingerprint"] == result["audited_package_fingerprint"]


@pytest.mark.parametrize(
    ("field", "value", "invariant"),
    (
        ("package_fingerprint", "A" * 64, "PACKAGE_FINGERPRINT_FORMAT"),
        ("package_fingerprint", "0" * 63, "PACKAGE_FINGERPRINT_FORMAT"),
        ("audited_package_fingerprint", "A" * 64, "AUDITED_PACKAGE_FINGERPRINT_FORMAT"),
        (
            "audited_package_fingerprint",
            "0" * 63,
            "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
        ),
    ),
)
def test_invalid_fingerprint_format_is_rejected(
    field: str, value: str, invariant: str
) -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered[field] = value
    result = _service().build(package=tampered)
    assert invariant in result["consistency_issues"]
    assert result["package_consistent"] is False


def test_package_fingerprint_recomputed_from_exact_task_073_definition() -> None:
    _sid, package, result = _valid_result()
    tampered = copy.deepcopy(package)
    original_expected = _service()._package_fingerprint(package)
    tampered["attestation"]["attestation_source"] = "still-not-valid"
    result = _service().build(package=tampered)
    expected = _service()._package_fingerprint(tampered)
    assert result["package_fingerprint"] == expected
    assert result["audited_package_fingerprint"] == expected
    assert expected != original_expected
    assert "ATTESTATION_SOURCE_MISMATCH" in result["consistency_issues"]


def test_package_consistent_is_independently_bound() -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered["package_consistent"] = not tampered["package_consistent"]
    result = _service().build(package=tampered)
    assert "PACKAGE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["package_consistent"] is False


def test_nested_attestation_tamper_is_reported() -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered["attestation"]["available"] = False
    result = _service().build(package=tampered)
    assert "NESTED_ATTESTATION_MISMATCH" in result["consistency_issues"]


def test_nested_attestation_consistency_tamper_is_reported() -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered["attestation_consistency"]["available"] = False
    result = _service().build(package=tampered)
    assert "NESTED_ATTESTATION_CONSISTENCY_MISMATCH" in result["consistency_issues"]


def test_source_tampering_is_reported() -> None:
    _sid, package, _result = _valid_result()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    result = _service().build(package=tampered)
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]


def test_forced_fingerprint_compute_failure_raises() -> None:
    _sid, package, _result = _valid_result()
    with patch(
        "rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency._expected_package_fingerprint",
        side_effect=RuntimeError("forced failure"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
        ) as ei:
            _service().build(package=package)
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_COMPUTE_FAILED"


def test_result_validator_rejects_missing_package_fingerprint() -> None:
    _sid, _package, result = _valid_result()
    tampered = dict(result)
    del tampered["package_fingerprint"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_result_validator_rejects_missing_audited_package_fingerprint() -> None:
    _sid, _package, result = _valid_result()
    tampered = dict(result)
    del tampered["audited_package_fingerprint"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_result_validator_rejects_contradictory_fingerprint_pair() -> None:
    _sid, _package, result = _valid_result()
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_PAIR_MISMATCH"


def test_result_validator_rejects_independent_package_fingerprint_tampering() -> None:
    _sid, package, result = _valid_result()
    tampered = dict(result)
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service()._validate_result(tampered, package=package)
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_MISMATCH"


def test_result_validator_rejects_independent_audited_fingerprint_tampering() -> None:
    _sid, package, result = _valid_result()
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service()._validate_result(tampered, package=package)
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"


def test_result_validator_rejects_tampered_derived_flag() -> None:
    _sid, _package, result = _valid_result()
    tampered = dict(result)
    tampered["provenance_consistent"] = not tampered["provenance_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PROVENANCE_CONSISTENT_MISMATCH"


def test_service_has_no_database_or_http_dependencies() -> None:
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
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "api_key",
        "provider",
        "model_name",
    ):
        assert forbidden not in src


def test_canonical_source_constant_value() -> None:
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074
        == "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_TASK_074"
    )

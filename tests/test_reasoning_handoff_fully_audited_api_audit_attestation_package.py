"""Tests for Task 073 fully audited attestation package."""

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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package import (
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_package as mod,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageService,
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


def _service() -> ReasoningHandoffFullyAuditedApiAuditAttestationPackageService:
    return ReasoningHandoffFullyAuditedApiAuditAttestationPackageService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-073-test"},
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


def _real_attestation_and_consistency() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full("Task 073 capture")
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
    attestation = ReasoningHandoffFullyAuditedApiAuditAttestationService().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    attestation_consistency = (
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService().build(
            attestation=attestation
        )
    )
    return sid, attestation, attestation_consistency


def test_valid_attestation_package_construction() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    pkg = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    assert pkg["available"] is True
    assert pkg["package_consistent"] is True
    assert pkg["session_id"] == sid
    assert pkg["attestation"] is att
    assert pkg["attestation_consistency"] is cons
    assert (
        pkg["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073
    )
    assert len(pkg["package_fingerprint"]) == 64

    # Pydantic validation
    model = ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead.model_validate(
        pkg
    )
    assert model.available is True
    assert model.package_consistent is True


def test_deterministic_output_and_fingerprint() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    p1 = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    p2 = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    assert p1 == p2
    assert p1["package_fingerprint"] == p2["package_fingerprint"]


def test_session_id_mismatch_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    wrong_sid = uuid4()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=wrong_sid,
            attestation=att,
            attestation_consistency=cons,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_missing_attestation_rejected() -> None:
    sid, _, cons = _real_attestation_and_consistency()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=None,
            attestation_consistency=cons,
        )
    assert ei.value.invariant == "ATTESTATION_MISMATCH"


def test_missing_attestation_consistency_rejected() -> None:
    sid, att, _ = _real_attestation_and_consistency()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=att,
            attestation_consistency=None,
        )
    assert ei.value.invariant == "ATTESTATION_CONSISTENCY_MISMATCH"


def test_malformed_attestation_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    broken_att = copy.deepcopy(att)
    broken_att["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=broken_att,
            attestation_consistency=cons,
        )
    assert ei.value.invariant == "ATTESTATION_MISMATCH"


def test_malformed_consistency_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    broken_cons = copy.deepcopy(cons)
    broken_cons["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=att,
            attestation_consistency=broken_cons,
        )
    assert ei.value.invariant == "ATTESTATION_CONSISTENCY_MISMATCH"


def test_attestation_source_mismatch_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    broken_att = copy.deepcopy(att)
    broken_att["attestation_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=broken_att,
            attestation_consistency=cons,
        )
    assert ei.value.invariant == "ATTESTATION_SOURCE_MISMATCH"


def test_consistency_source_mismatch_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    broken_cons = copy.deepcopy(cons)
    broken_cons["attestation_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=att,
            attestation_consistency=broken_cons,
        )
    assert ei.value.invariant == "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH"


def test_fingerprint_mismatch_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    broken_cons = copy.deepcopy(cons)
    broken_cons["audited_attestation_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation=att,
            attestation_consistency=broken_cons,
        )
    assert ei.value.invariant == "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH"


def test_audited_package_fingerprint_binds_to_package_fingerprint() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    pkg = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    assert pkg["audited_package_fingerprint"] == pkg["package_fingerprint"]
    assert len(pkg["audited_package_fingerprint"]) == 64


def test_tampered_audited_package_fingerprint_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    pkg = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    tampered = copy.deepcopy(pkg)
    tampered["audited_package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"


def test_invalid_audited_package_fingerprint_format_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    pkg = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    for bad in ("AB" * 32, "0" * 63, None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["audited_package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_missing_audited_package_fingerprint_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    pkg = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    tampered = copy.deepcopy(pkg)
    del tampered["audited_package_fingerprint"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "MISSING_PACKAGE_FIELD"
    with pytest.raises(ValidationError):
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead.model_validate(
            tampered
        )


def test_tampered_package_consistent_rejected() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    pkg = _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    assert pkg["package_consistent"] is True
    tampered = copy.deepcopy(pkg)
    tampered["package_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_MISMATCH"


def test_forced_fingerprint_compute_failure() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    with patch(
        "rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package._compute_package_fingerprint",
        side_effect=RuntimeError("forced failure"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError
        ) as ei:
            _service().build(
                session_id=sid,
                attestation=att,
                attestation_consistency=cons,
            )
        assert ei.value.invariant == "PACKAGE_FINGERPRINT_COMPUTE_FAILED"
        assert isinstance(ei.value.__cause__, RuntimeError)


def test_input_immutability() -> None:
    sid, att, cons = _real_attestation_and_consistency()
    before_att = copy.deepcopy(att)
    before_cons = copy.deepcopy(cons)
    _service().build(
        session_id=sid,
        attestation=att,
        attestation_consistency=cons,
    )
    assert att == before_att
    assert cons == before_cons


def test_no_module_mutable_state() -> None:
    for name in dir(mod):
        assert not name.startswith("_LAST"), f"Found mutable state: {name}"
    for name, val in inspect.getmembers(mod):
        if name.startswith("__"):
            continue
        if isinstance(val, (dict, list, set)):
            assert name not in ("cache", "state", "store", "registry")


def test_production_service_purity() -> None:
    src_file = inspect.getfile(
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageService
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

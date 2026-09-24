"""Tests for Task 071 final attestation composition boundary.

Task 071 binds Task 069 bundle with Task 070 consistency audit.
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
from rop.services import reasoning_handoff_fully_audited_api_audit_attestation as mod
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
    ReasoningHandoffFullyAuditedApiAuditAttestationContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
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

ATTESTATION_FIELDS = (
    "available",
    "attestation_consistent",
    "session_id",
    "api_audit_bundle",
    "api_audit_bundle_consistency",
    "attestation_source",
    "audited_attestation_fingerprint",
)


def _service() -> ReasoningHandoffFullyAuditedApiAuditAttestationService:
    return ReasoningHandoffFullyAuditedApiAuditAttestationService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-071-test"},
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


def _real_bundle_and_consistency() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full("Task 071 capture")
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
    return sid, bundle, consistency


def _valid_attestation() -> dict[str, Any]:
    sid, bundle, consistency = _real_bundle_and_consistency()
    return _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )


# Valid construction
def test_valid_attestation_shape() -> None:
    att = _valid_attestation()
    assert set(att) == set(ATTESTATION_FIELDS)
    assert att["available"] is True


def test_attestation_source_fixed() -> None:
    att = _valid_attestation()
    assert (
        att["attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
    )


def test_valid_uuid() -> None:
    att = _valid_attestation()
    assert isinstance(att["session_id"], UUID)


def test_deterministic() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    a1 = _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    a2 = _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    assert a1 == a2


def test_deterministic_fingerprint() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    a1 = _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    a2 = _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    assert (
        a1["audited_attestation_fingerprint"] == a2["audited_attestation_fingerprint"]
    )
    assert len(a1["audited_attestation_fingerprint"]) == 64
    assert all(c in "0123456789abcdef" for c in a1["audited_attestation_fingerprint"])


def test_input_immutability() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    before_b = copy.deepcopy(bundle)
    before_c = copy.deepcopy(consistency)
    _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    assert bundle == before_b
    assert consistency == before_c


def test_preserves_nested_by_identity() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    att = _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    assert att["api_audit_bundle"] is bundle
    assert att["api_audit_bundle_consistency"] is consistency


# Nested validation
def test_malformed_bundle_rejected() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(bundle)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid,
            api_audit_bundle=broken,
            api_audit_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "BUNDLE_MISMATCH"


def test_malformed_consistency_rejected() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(consistency)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid, api_audit_bundle=bundle, api_audit_bundle_consistency=broken
        )
    assert ei.value.invariant == "BUNDLE_CONSISTENCY_MISMATCH"


def test_nested_bundle_tampering_rejected() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(bundle)
    broken["bundle_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid,
            api_audit_bundle=broken,
            api_audit_bundle_consistency=consistency,
        )
    assert ei.value.invariant in ("BUNDLE_SOURCE_MISMATCH", "BUNDLE_MISMATCH")


def test_nested_consistency_tampering_rejected() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(consistency)
    broken["bundle_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid, api_audit_bundle=bundle, api_audit_bundle_consistency=broken
        )
    assert ei.value.invariant in (
        "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
        "BUNDLE_CONSISTENCY_MISMATCH",
    )


# Session binding
def test_invalid_session_id() -> None:
    _, bundle, consistency = _real_bundle_and_consistency()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id="not-a-uuid",
            api_audit_bundle=bundle,
            api_audit_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_session_mismatch() -> None:
    _, bundle, consistency = _real_bundle_and_consistency()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=uuid4(),
            api_audit_bundle=bundle,
            api_audit_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_matching_session_accepted() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    att = _service().build(
        session_id=sid,
        api_audit_bundle=bundle,
        api_audit_bundle_consistency=consistency,
    )
    assert att["session_id"] == sid


# Provenance
def test_wrong_bundle_source() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(bundle)
    broken["bundle_source"] = "WRONG"
    # Need to make consistency still match the original bundle's fingerprint? No, bundle_source mismatch should be caught before fingerprint
    # But to avoid fingerprint mismatch, we need to keep consistency's fingerprint consistent with original bundle
    # So this test will raise BUNDLE_SOURCE_MISMATCH
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid,
            api_audit_bundle=broken,
            api_audit_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "BUNDLE_SOURCE_MISMATCH"


def test_wrong_consistency_source() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(consistency)
    broken["bundle_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid, api_audit_bundle=bundle, api_audit_bundle_consistency=broken
        )
    assert ei.value.invariant == "BUNDLE_CONSISTENCY_SOURCE_MISMATCH"


def test_wrong_attestation_source_via_validate() -> None:
    att = _valid_attestation()
    tampered = dict(att)
    tampered["attestation_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(
            tampered
        )
    assert ei.value.invariant == "ATTESTATION_SOURCE_MISMATCH"


# Fingerprint provenance
def test_valid_bundle_fingerprint_accepted() -> None:
    att = _valid_attestation()
    assert att["attestation_consistent"] is True


def test_tampered_consistency_fingerprint_rejected() -> None:
    sid, bundle, consistency = _real_bundle_and_consistency()
    broken = copy.deepcopy(consistency)
    broken["audited_bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        _service().build(
            session_id=sid, api_audit_bundle=bundle, api_audit_bundle_consistency=broken
        )
    assert ei.value.invariant == "AUDITED_BUNDLE_FINGERPRINT_MISMATCH"


def test_forced_bundle_fingerprint_compute_failure() -> None:
    from unittest.mock import patch

    sid, bundle, consistency = _real_bundle_and_consistency()
    with patch(
        "rop.services.reasoning_handoff_fully_audited_api_audit_attestation._bundle_fingerprint",
        side_effect=RuntimeError("forced"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationContractError
        ) as ei:
            _service().build(
                session_id=sid,
                api_audit_bundle=bundle,
                api_audit_bundle_consistency=consistency,
            )
        assert ei.value.invariant == "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED"
        assert isinstance(ei.value.__cause__, RuntimeError)


def test_tampered_attestation_fingerprint_rejected() -> None:
    att = _valid_attestation()
    tampered = dict(att)
    tampered["audited_attestation_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH"


def test_forced_attestation_fingerprint_compute_failure() -> None:
    from unittest.mock import patch

    sid, bundle, consistency = _real_bundle_and_consistency()
    with patch(
        "rop.services.reasoning_handoff_fully_audited_api_audit_attestation._attestation_fingerprint",
        side_effect=RuntimeError("forced att"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationContractError
        ) as ei:
            _service().build(
                session_id=sid,
                api_audit_bundle=bundle,
                api_audit_bundle_consistency=consistency,
            )
        assert ei.value.invariant == "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED"
        assert isinstance(ei.value.__cause__, RuntimeError)


# Semantic distinction
def _real_legitimate_defect() -> (
    tuple[UUID, dict[str, Any], dict[str, Any], dict[str, Any]]
):
    """Create a coherent defect chain: bundle False, consistency True, attestation True."""
    sid, bundle, _ = _real_bundle_and_consistency()
    # Create a defect Task 068 audit: package_consistent=False with a single issue
    # This will make Task 069 bundle_consistent=False but still valid
    orig_audit = bundle["api_audit_package_consistency"]
    defect_audit = copy.deepcopy(orig_audit)
    # Set the audit to report a defect: package_consistent=False, nested_response_consistent=False
    defect_audit["consistency_issues"] = ["NESTED_RESPONSE_MISMATCH"]
    defect_audit["package_consistent"] = False
    defect_audit["nested_response_consistent"] = False
    # Ensure other flags are consistent with the issue set (only this issue)
    # From Task 068 logic: only nested_response_consistent should be False, others True
    defect_audit["session_consistent"] = True
    defect_audit["method_consistent"] = True
    defect_audit["path_consistent"] = True
    defect_audit["status_consistent"] = True
    defect_audit["nested_api_audit_consistent"] = True
    defect_audit["provenance_consistent"] = True
    defect_audit["package_relationship_consistent"] = True
    defect_audit["source_consistency"] = True
    defect_audit["metadata_consistent"] = True
    # Validate the defect audit is still internally consistent (it correctly reports a defect)
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
        defect_audit
    )
    # Now build a Task 069 bundle with this defect audit - it should have bundle_consistent=False
    package = bundle["api_audit_package"]
    defect_bundle = ReasoningHandoffFullyAuditedApiAuditBundleService().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=defect_audit,
    )
    assert defect_bundle["bundle_consistent"] is False
    # Now audit this defect bundle with Task 070 - it should be coherent (True) because the bundle correctly reports the defect
    defect_consistency = (
        ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService().build(
            bundle=defect_bundle
        )
    )
    assert defect_consistency["bundle_consistent"] is True
    assert defect_consistency["consistency_issues"] == []
    # Now the attestation should be True (follows consistency)
    return sid, defect_bundle, defect_consistency


def test_legitimate_defect_case() -> None:
    sid, defect_bundle, defect_consistency = _real_legitimate_defect()
    assert defect_bundle["bundle_consistent"] is False
    assert defect_consistency["bundle_consistent"] is True
    att = _service().build(
        session_id=sid,
        api_audit_bundle=defect_bundle,
        api_audit_bundle_consistency=defect_consistency,
    )
    assert att["attestation_consistent"] is True
    assert att["attestation_consistent"] == defect_consistency["bundle_consistent"]
    assert att["attestation_consistent"] != defect_bundle["bundle_consistent"]


def test_legitimate_defect_explicit() -> None:
    sid, defect_bundle, defect_consistency = _real_legitimate_defect()
    att = _service().build(
        session_id=sid,
        api_audit_bundle=defect_bundle,
        api_audit_bundle_consistency=defect_consistency,
    )
    assert att["attestation_consistent"] is True
    # Also verify mismatched attestation_consistent is rejected
    tampered = dict(att)
    tampered["attestation_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(
            tampered
        )
    assert ei.value.invariant == "ATTESTATION_CONSISTENCY_MISMATCH"


def test_malformed_relationship_rejected() -> None:
    att = _valid_attestation()
    tampered = dict(att)
    tampered["attestation_consistent"] = not tampered["attestation_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(
            tampered
        )
    assert ei.value.invariant == "ATTESTATION_CONSISTENCY_MISMATCH"


# Immutability/state
def test_repeated_validation_identical() -> None:
    att = _valid_attestation()
    ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(dict(att))
    ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(dict(att))
    assert att["attestation_consistent"] is True


def test_validating_a_unaffected_by_b() -> None:
    att_a = _valid_attestation()
    sid_b, bundle_b, consistency_b = _real_bundle_and_consistency()
    _ = _service().build(
        session_id=sid_b,
        api_audit_bundle=bundle_b,
        api_audit_bundle_consistency=consistency_b,
    )
    # Re-validate A
    ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(dict(att_a))
    assert att_a["attestation_consistent"] is True


def test_no_last_cache() -> None:
    src = inspect.getsource(mod)
    assert "_LAST" not in src
    assert "global" not in src


def test_no_module_level_mutable_state() -> None:
    src = inspect.getsource(mod)
    assert "_LAST" not in src


# Architecture
def test_no_database_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("SessionLocal", "create_engine", "get_db", "sqlalchemy"):
        assert forbidden not in src


def test_no_http_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("TestClient", "httpx", "requests", "urllib"):
        assert forbidden not in src


def test_no_endpoint_invocation() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "rop.api.sessions",
        "build_for_session",
        "ReasoningHandoffFullyAuditedApiService",
    ):
        assert forbidden not in src


def test_no_workflow_build_invocation() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningHandoffFullyAuditedApiAuditPackageService().build" not in src
    assert "ReasoningHandoffFullyAuditedApiAuditBundleService().build" not in src
    assert (
        "ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService().build"
        not in src
    )


def test_no_llm_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("ollama", "openai", "gemini", "anthropic", "model_name", "api_key"):
        assert token not in src
    assert "provider" not in src.split() and "rag" not in src.split()

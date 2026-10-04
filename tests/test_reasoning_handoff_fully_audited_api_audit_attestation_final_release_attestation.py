"""Tests for Task 097: final release attestation over the 095/096 bundle.

Task 097 binds the Task 095 response audit bundle with the Task 096
consistency audit into a deterministic, self-authenticating terminal
release attestation. Pure composition boundary; never touches the
database directly beyond delegation, never performs HTTP calls, never
mutates inputs, and preserves legitimate upstream defects unchanged.
"""

from __future__ import annotations

import copy
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,  # noqa: E501
)

ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError  # noqa: E501

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


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


RESULT_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_id",
    "response_bundle",
    "response_bundle_consistency",
    "final_attestation_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService()  # noqa: E501
    )


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-097-test"},
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


def _build_direct(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return _service().build_for_session(db, session_id)


def _seed_and_build() -> tuple[str, dict[str, Any]]:
    sid_str = _seed_full("Task 097 capture")
    return sid_str, _build_direct(UUID(sid_str))


def _valid_parts() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str, result = _seed_and_build()
    sid = UUID(sid_str)
    return sid, result["response_bundle"], result["response_bundle_consistency"]


def _defect_consistency(
    consistency: dict[str, Any],
) -> dict[str, Any]:
    """Derive a genuinely defect-reporting Task 096 result from a real one.

    Starts from the real Task 096 audit and reports a single non-session
    issue with all derived flags set per the Task 096 contract, then
    proves validity with the real Task 096 validator. Fingerprints are
    left untouched so upstream binding still holds.
    """
    candidates = [
        "BUNDLE_RELATIONSHIP_MISMATCH",
        "PACKAGE_FINGERPRINT_BINDING_MISMATCH",
        "RESPONSE_PACKAGE_SOURCE_MISMATCH",
        "BUNDLE_SOURCE_MISMATCH",
    ]
    last_error: Exception | None = None
    for issue in candidates:
        defect = copy.deepcopy(consistency)
        flagged = {issue}
        defect["consistency_issues"] = [issue]
        defect["available"] = True
        defect["bundle_consistent"] = False
        defect["session_consistent"] = not any(
            i in flagged for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        defect["nested_response_package_consistent"] = (
            "NESTED_RESPONSE_PACKAGE_MISMATCH" not in flagged
        )
        defect["nested_response_package_consistency_consistent"] = (
            "NESTED_RESPONSE_PACKAGE_CONSISTENCY_MISMATCH" not in flagged
        )
        defect["provenance_consistent"] = not any(
            i in flagged
            for i in (
                "BUNDLE_FINGERPRINT_FORMAT",
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "BUNDLE_FINGERPRINT_MISMATCH",
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        defect["bundle_relationship_consistent"] = not any(
            i in flagged
            for i in (
                "BUNDLE_RELATIONSHIP_MISMATCH",
                "PACKAGE_FINGERPRINT_BINDING_MISMATCH",
            )
        )
        defect["source_consistency"] = not any(
            i in flagged
            for i in (
                "RESPONSE_PACKAGE_SOURCE_MISMATCH",
                "RESPONSE_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                "BUNDLE_SOURCE_MISMATCH",
            )
        )
        defect["metadata_consistent"] = not any(
            i in flagged for i in ("MISSING_BUNDLE_FIELD", "INVALID_BUNDLE_AVAILABLE")
        )
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
                dict(defect)
            )
            if defect["session_consistent"] is True:
                return defect
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    raise AssertionError(f"could not craft Task 096 defect: {last_error}")


# --- Valid attestation ------------------------------------------------------
def test_valid_attestation_via_build_for_session() -> None:
    sid_str, result = _seed_and_build()
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["session_id"] == UUID(sid_str)
    assert (
        result["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
    )


def test_build_for_session_parity_with_direct_build() -> None:
    sid_str = _seed_full("Task 097 parity capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        via_session = _service().build_for_session(db, sid)
    direct = _service().build(
        session_id=sid,
        response_bundle=via_session["response_bundle"],
        response_bundle_consistency=via_session["response_bundle_consistency"],
    )
    assert direct == via_session


def test_exact_shape_direct() -> None:
    _, result = _seed_and_build()
    assert set(result) == set(RESULT_FIELDS)


def test_valid_flags_and_sources() -> None:
    sid_str, result = _seed_and_build()
    assert result["available"] is True
    assert result["session_id"] == UUID(sid_str)
    assert isinstance(result["final_attestation_consistent"], bool)
    assert (
        result["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
    )
    assert (
        result["response_bundle"]["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
    )
    assert (
        result["response_bundle_consistency"]["bundle_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096  # noqa: E501
    )


def test_fingerprint_format_and_self_agreement() -> None:
    _, result = _seed_and_build()
    for field in (
        "final_attestation_fingerprint",
        "audited_final_attestation_fingerprint",
    ):
        value = result[field]
        assert isinstance(value, str)
        assert len(value) == 64
        assert all(c in "0123456789abcdef" for c in value)
    assert (
        result["audited_final_attestation_fingerprint"]
        == result["final_attestation_fingerprint"]
    )


def test_schema_roundtrip() -> None:
    _, result = _seed_and_build()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead.model_validate(  # noqa: E501
        result
    )
    assert model.available is True
    assert model.session_id == result["session_id"]


def test_consistency_derived_from_upstream() -> None:
    _, result = _seed_and_build()
    expected = bool(
        result["response_bundle"].get("bundle_consistent", False)
        and result["response_bundle_consistency"].get("bundle_consistent", False)
    )
    assert result["final_attestation_consistent"] == expected


def test_provenance_preserved() -> None:
    sid, bundle, consistency = _valid_parts()
    result = _service().build(
        session_id=sid,
        response_bundle=bundle,
        response_bundle_consistency=consistency,
    )
    assert result["response_bundle"] == bundle
    assert result["response_bundle_consistency"] == consistency
    assert result["response_bundle"]["session_id"] == sid


# --- Missing / malformed nested inputs --------------------------------------
def test_missing_nested_bundle() -> None:
    _, _, consistency = _valid_parts()
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=uuid4(),
            response_bundle=None,
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_BUNDLE_MISMATCH"


def test_non_mapping_nested_bundle() -> None:
    _, _, consistency = _valid_parts()
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=uuid4(),
            response_bundle="not-a-mapping",  # type: ignore[arg-type]
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_BUNDLE_MISMATCH"


def test_malformed_nested_bundle_rejected() -> None:
    sid, bundle, consistency = _valid_parts()
    tampered = copy.deepcopy(bundle)
    del tampered["audited_bundle_fingerprint"]
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=tampered,
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_BUNDLE_MISMATCH"


def test_missing_bundle_consistency() -> None:
    sid, bundle, _ = _valid_parts()
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency=None,
        )
    assert ei.value.invariant == "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH"


def test_non_mapping_bundle_consistency() -> None:
    sid, bundle, _ = _valid_parts()
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency="not-a-mapping",  # type: ignore[arg-type]
        )
    assert ei.value.invariant == "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH"


def test_malformed_bundle_consistency_rejected() -> None:
    sid, bundle, consistency = _valid_parts()
    tampered = copy.deepcopy(consistency)
    del tampered["bundle_consistency_source"]
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency=tampered,
        )
    assert ei.value.invariant in (
        "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
        "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
    )


# --- Session binding --------------------------------------------------------
def test_session_mismatch_rejected() -> None:
    _, bundle, consistency = _valid_parts()
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=uuid4(),
            response_bundle=bundle,
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_invalid_session_id_rejected() -> None:
    _, bundle, consistency = _valid_parts()
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id="not-a-uuid",
            response_bundle=bundle,
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_consistency_session_flag_mismatch_rejected() -> None:
    sid, bundle, consistency = _valid_parts()
    tampered_consistency = copy.deepcopy(consistency)
    tampered_consistency["session_consistent"] = False
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency=tampered_consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


# --- Source binding ---------------------------------------------------------
def test_bundle_source_mismatch_rejected() -> None:
    sid, bundle, consistency = _valid_parts()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG_TASK"
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=tampered,
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_BUNDLE_SOURCE_MISMATCH"


def test_consistency_source_mismatch_rejected() -> None:
    sid, bundle, consistency = _valid_parts()
    tampered = copy.deepcopy(consistency)
    tampered["bundle_consistency_source"] = "WRONG_TASK"
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency=tampered,
        )
    assert (
        ei.value.invariant == "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH"
    )  # noqa: E501


# --- Upstream fingerprint relationship --------------------------------------
def test_upstream_bundle_fingerprint_binding_mismatch_rejected() -> None:
    sid, bundle, consistency = _valid_parts()
    tampered = copy.deepcopy(consistency)
    tampered["bundle_fingerprint"] = "0" * 64
    assert tampered["bundle_fingerprint"] != bundle["bundle_fingerprint"]
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency=tampered,
        )
    assert ei.value.invariant == "BUNDLE_FINGERPRINT_BINDING_MISMATCH"


# --- Final attestation fingerprint tampering --------------------------------
def test_attestation_fingerprint_tampering_rejected() -> None:
    _, result = _seed_and_build()
    tampered = copy.deepcopy(result)
    tampered["final_attestation_fingerprint"] = "0" * 64
    with pytest.raises(ContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_FINGERPRINT_MISMATCH"


def test_audited_attestation_fingerprint_tampering_rejected() -> None:
    _, result = _seed_and_build()
    tampered = copy.deepcopy(result)
    tampered["audited_final_attestation_fingerprint"] = "1" * 64
    with pytest.raises(ContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH"


# --- Derived consistency tampering ------------------------------------------
def test_derived_consistency_tampering_rejected() -> None:
    _, result = _seed_and_build()
    tampered = copy.deepcopy(result)
    flipped = not tampered["final_attestation_consistent"]
    tampered["final_attestation_consistent"] = flipped
    with pytest.raises(ContractError) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENT_MISMATCH"


def test_legitimate_defect_derivation_not_masked() -> None:
    _, result = _seed_and_build()
    assert result["final_attestation_consistent"] == (
        result["response_bundle"]["bundle_consistent"]
        and result["response_bundle_consistency"]["bundle_consistent"]
    )


def test_legitimate_defect_preserved() -> None:
    """A coherent defect-reporting Task 096 audit stays available/False."""
    sid, bundle, consistency = _valid_parts()
    defect = _defect_consistency(consistency)
    assert defect["bundle_consistent"] is False
    assert defect["session_consistent"] is True
    result = _service().build(
        session_id=sid,
        response_bundle=bundle,
        response_bundle_consistency=defect,
    )
    assert result["available"] is True
    assert result["final_attestation_consistent"] is False
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
        result
    )


# --- Determinism / purity ---------------------------------------------------
def test_deterministic_direct_build() -> None:
    sid_str, first = _seed_and_build()
    second = _build_direct(UUID(sid_str))
    assert first == second


def test_deterministic_repeated_build() -> None:
    sid, bundle, consistency = _valid_parts()
    first = _service().build(
        session_id=sid,
        response_bundle=bundle,
        response_bundle_consistency=consistency,
    )
    second = _service().build(
        session_id=sid,
        response_bundle=bundle,
        response_bundle_consistency=consistency,
    )
    assert first == second


def test_input_immutability() -> None:
    sid, bundle, consistency = _valid_parts()
    bundle_before = copy.deepcopy(bundle)
    consistency_before = copy.deepcopy(consistency)
    _service().build(
        session_id=sid,
        response_bundle=bundle,
        response_bundle_consistency=consistency,
    )
    assert bundle == bundle_before
    assert consistency == consistency_before


def test_forced_fingerprint_computation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid, bundle, consistency = _valid_parts()

    def _boom(_core: Any) -> str:
        raise RuntimeError("forced fingerprint failure")

    monkeypatch.setattr(mod, "_compute_final_attestation_fingerprint", _boom)
    with pytest.raises(ContractError) as ei:
        _service().build(
            session_id=sid,
            response_bundle=bundle,
            response_bundle_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED"
    assert isinstance(ei.value.__cause__, RuntimeError)

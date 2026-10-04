"""Tests for Task 082 final-attestation consistency audit.

Task 082 performs a pure, deterministic, independent consistency audit of
the Task 081 final attestation without executing Task 081, making HTTP
calls, accessing the database, or invoking external models/providers.
"""

from __future__ import annotations

import copy
import inspect
import re
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_079,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_080,  # noqa: E501
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


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


RESULT_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_consistent",
    "nested_response_bundle_consistent",
    "nested_response_bundle_consistency_consistent",
    "provenance_consistent",
    "final_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "final_attestation_consistency_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

REQUIRED_INPUT_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_id",
    "response_bundle",
    "response_bundle_consistency",
    "final_attestation_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

ISSUE_ORDER = (
    "MISSING_FINAL_ATTESTATION_FIELD",
    "INVALID_FINAL_ATTESTATION_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_RESPONSE_BUNDLE_MISMATCH",
    "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
    "FINAL_RELATIONSHIP_MISMATCH",
    "BUNDLE_FINGERPRINT_BINDING_MISMATCH",
    "RESPONSE_BUNDLE_SOURCE_MISMATCH",
    "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_CONTRACT_MISMATCH",
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService()  # noqa: E501
    )


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-082-test"},
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


def _valid_attestation() -> tuple[UUID, dict[str, Any]]:
    sid_str = _seed_full("Task 082 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        attestation = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService().build_for_session(  # noqa: E501
            db, sid
        )
    return sid, attestation


def _valid_result() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid, attestation = _valid_attestation()
    return sid, attestation, _service().build(final_attestation=attestation)


# --- Valid audit ------------------------------------------------------------
def test_valid_shape_and_flags() -> None:
    _sid, _attestation, result = _valid_result()
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["final_attestation_consistent"] is True
    assert result["consistency_issues"] == []
    assert result["session_consistent"] is True
    assert result["nested_response_bundle_consistent"] is True
    assert result["nested_response_bundle_consistency_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["final_relationship_consistent"] is True
    assert result["source_consistency"] is True
    assert result["metadata_consistent"] is True
    assert (
        result["final_attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
    )
    assert HEX64.fullmatch(result["final_attestation_fingerprint"])
    assert (
        result["audited_final_attestation_fingerprint"]
        == result["final_attestation_fingerprint"]
    )


def test_result_schema_roundtrip() -> None:
    _sid, _attestation, result = _valid_result()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead.model_validate(  # noqa: E501
        result
    )
    assert model.final_attestation_consistent is True
    assert model.consistency_issues == []


def test_independent_recomputation_matches() -> None:
    _sid, attestation, result = _valid_result()
    expected = mod._expected_final_fingerprint(attestation)
    assert result["final_attestation_fingerprint"] == expected
    assert result["audited_final_attestation_fingerprint"] == expected
    assert (
        result["final_attestation_fingerprint"]
        == attestation["final_attestation_fingerprint"]
    )


def test_missing_attestation_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        _service().build(final_attestation=None)
    assert ei.value.invariant == "MISSING_FINAL_ATTESTATION"


def test_non_mapping_attestation_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        _service().build(final_attestation="not-a-mapping")  # type: ignore[arg-type]  # noqa: E501
    assert ei.value.invariant == "FINAL_ATTESTATION_TYPE"


# --- Every required field missing -------------------------------------------
@pytest.mark.parametrize("field", REQUIRED_INPUT_FIELDS)
def test_every_required_field_missing_is_reported(field: str) -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    del tampered[field]
    result = _service().build(final_attestation=tampered)
    assert "MISSING_FINAL_ATTESTATION_FIELD" in result["consistency_issues"]
    assert result["final_attestation_consistent"] is False
    assert result["metadata_consistent"] is False


def test_duplicate_missing_fields_collapse_to_one_issue() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    del tampered["available"]
    del tampered["final_attestation_source"]
    result = _service().build(final_attestation=tampered)
    assert result["consistency_issues"].count("MISSING_FINAL_ATTESTATION_FIELD") == 1


def test_available_not_true_is_reported() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["available"] = False
    result = _service().build(final_attestation=tampered)
    assert "INVALID_FINAL_ATTESTATION_AVAILABLE" in result["consistency_issues"]
    assert result["final_attestation_consistent"] is False
    assert result["metadata_consistent"] is False


# --- Nested bundle tampering -------------------------------------------------
def test_nested_response_bundle_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle"]["bundle_consistent"] = not tampered["response_bundle"][
        "bundle_consistent"
    ]
    result = _service().build(final_attestation=tampered)
    assert "NESTED_RESPONSE_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_bundle_consistent"] is False
    assert result["final_attestation_consistent"] is False


def test_nested_response_bundle_non_mapping_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle"] = "tampered"
    result = _service().build(final_attestation=tampered)
    assert "NESTED_RESPONSE_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_bundle_consistent"] is False


def test_nested_consistency_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle_consistency"]["bundle_consistent"] = not tampered[
        "response_bundle_consistency"
    ]["bundle_consistent"]
    result = _service().build(final_attestation=tampered)
    assert "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_bundle_consistency_consistent"] is False
    assert result["final_attestation_consistent"] is False


def test_nested_consistency_non_mapping_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle_consistency"] = "tampered"
    result = _service().build(final_attestation=tampered)
    assert "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["final_attestation_consistent"] is False


# --- Session tampering -------------------------------------------------------
def test_session_id_mismatch_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["session_id"] = uuid4()
    result = _service().build(final_attestation=tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["final_attestation_consistent"] is False


def test_nested_bundle_session_mismatch_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle"]["session_id"] = uuid4()
    result = _service().build(final_attestation=tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_invalid_session_id_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(final_attestation=tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["final_attestation_consistent"] is False


# --- Source tampering --------------------------------------------------------
def test_final_attestation_source_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_source"] = "WRONG_SOURCE"
    result = _service().build(final_attestation=tampered)
    assert "FINAL_ATTESTATION_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["final_attestation_consistent"] is False


def test_nested_bundle_source_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle"]["bundle_source"] = "WRONG_SOURCE"
    result = _service().build(final_attestation=tampered)
    assert "RESPONSE_BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_nested_consistency_source_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle_consistency"][
        "bundle_consistency_source"
    ] = "WRONG_SOURCE"
    result = _service().build(final_attestation=tampered)
    assert "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# --- Fingerprint tampering ---------------------------------------------------
def test_audited_fingerprint_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["audited_final_attestation_fingerprint"] = "0" * 64
    result = _service().build(final_attestation=tampered)
    assert (
        "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    )
    assert "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["final_attestation_consistent"] is False


def test_attestation_fingerprint_tampering_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_fingerprint"] = "0" * 64
    result = _service().build(final_attestation=tampered)
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_malformed_fingerprint_format_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_fingerprint"] = "not-hex"
    result = _service().build(final_attestation=tampered)
    assert "FINAL_ATTESTATION_FINGERPRINT_FORMAT" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_malformed_audited_fingerprint_format_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["audited_final_attestation_fingerprint"] = "ZZZ"
    result = _service().build(final_attestation=tampered)
    assert (
        "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT" in result["consistency_issues"]
    )
    assert result["provenance_consistent"] is False


def test_copied_fingerprint_pair_mismatch_detected() -> None:
    _sid, attestation, _result = _valid_result()
    other_fp = "a" * 64
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_fingerprint"] = other_fp
    tampered["audited_final_attestation_fingerprint"] = "b" * 64
    result = _service().build(final_attestation=tampered)
    assert "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["final_attestation_consistent"] is False


def test_stale_fingerprint_after_content_change_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    # Real content change inside the fingerprinted core: flip the nested
    # bundle verdict. Fingerprints are left stale on purpose.
    tampered["response_bundle"]["bundle_consistent"] = not attestation[
        "response_bundle"
    ]["bundle_consistent"]
    result = _service().build(final_attestation=tampered)
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert (
        "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    )
    assert result["final_attestation_consistent"] is False


def test_bundle_fingerprint_binding_mismatch_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["response_bundle_consistency"]["bundle_fingerprint"] = "0" * 64
    result = _service().build(final_attestation=tampered)
    assert (
        "BUNDLE_FINGERPRINT_BINDING_MISMATCH" in result["consistency_issues"]
        or "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )
    assert result["final_relationship_consistent"] is False
    assert result["final_attestation_consistent"] is False


# --- Derived-flag tampering --------------------------------------------------
def test_derived_flag_tampering_rejected_by_validator() -> None:
    _sid, attestation, result = _valid_result()
    tampered_result = dict(result)
    tampered_result["session_consistent"] = not result["session_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
            tampered_result, final_attestation=attestation
        )
    assert ei.value.invariant == "SESSION_CONSISTENT_MISMATCH"


def test_derived_flags_recomputed_from_evidence() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["session_id"] = uuid4()
    result = _service().build(final_attestation=tampered)
    # caller cannot force flags True; service recomputes from evidence
    assert result["session_consistent"] is False
    assert result["final_attestation_consistent"] is False


def test_final_relationship_mismatch_detected() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_consistent"] = not attestation[
        "final_attestation_consistent"
    ]
    result = _service().build(final_attestation=tampered)
    assert "FINAL_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["final_relationship_consistent"] is False


# --- Ordering / duplicates / determinism ------------------------------------
def test_issue_ordering_is_fixed() -> None:
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    del tampered["available"]
    tampered["session_id"] = "bad"
    tampered["final_attestation_source"] = "WRONG"
    tampered["final_attestation_fingerprint"] = "bad"
    result = _service().build(final_attestation=tampered)
    issues = result["consistency_issues"]
    positions = [ISSUE_ORDER.index(i) for i in issues if i in ISSUE_ORDER]
    assert positions == sorted(positions)
    assert len(set(issues)) == len(issues)


def test_shuffled_issues_rejected_by_validator() -> None:
    _sid, attestation, result = _valid_result()
    _ = attestation
    tampered_result = copy.deepcopy(result)
    tampered_result["consistency_issues"] = [
        "FINAL_ATTESTATION_SOURCE_MISMATCH",
        "MISSING_FINAL_ATTESTATION_FIELD",
    ]
    tampered_result["final_attestation_consistent"] = False
    tampered_result["source_consistency"] = False
    tampered_result["metadata_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
            tampered_result
        )
    assert ei.value.invariant == "ISSUES_ORDER"


def test_duplicate_issues_rejected_by_validator() -> None:
    _sid, _attestation, result = _valid_result()
    tampered_result = copy.deepcopy(result)
    tampered_result["consistency_issues"] = [
        "SESSION_ID_MISMATCH",
        "SESSION_ID_MISMATCH",
    ]
    tampered_result["final_attestation_consistent"] = False
    tampered_result["session_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
            tampered_result
        )
    assert ei.value.invariant == "DUPLICATE_ISSUE"


def test_deterministic_repeated_build() -> None:
    _sid, attestation, _result = _valid_result()
    first = _service().build(final_attestation=attestation)
    second = _service().build(final_attestation=attestation)
    assert first == second


def test_no_or_fallback_between_fingerprint_fields() -> None:
    _sid, attestation, _result = _valid_result()
    only_audited = copy.deepcopy(attestation)
    del only_audited["final_attestation_fingerprint"]
    result = _service().build(final_attestation=only_audited)
    assert "MISSING_FINAL_ATTESTATION_FIELD" in result["consistency_issues"]
    assert "FINAL_ATTESTATION_FINGERPRINT_FORMAT" in result["consistency_issues"]
    assert result["final_attestation_consistent"] is False
    only_audited_missing = copy.deepcopy(attestation)
    del only_audited_missing["audited_final_attestation_fingerprint"]
    result2 = _service().build(final_attestation=only_audited_missing)
    assert "MISSING_FINAL_ATTESTATION_FIELD" in result2["consistency_issues"]
    assert (
        "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT" in result2["consistency_issues"]
    )
    assert result2["final_attestation_consistent"] is False


# --- Immutability / purity ---------------------------------------------------
def test_input_immutability() -> None:
    _sid, attestation, _result = _valid_result()
    before = copy.deepcopy(attestation)
    _service().build(final_attestation=attestation)
    assert attestation == before


def test_result_mutation_does_not_affect_rebuild() -> None:
    _sid, attestation, _result = _valid_result()
    result = _service().build(final_attestation=attestation)
    result["consistency_issues"].append("INJECTED")
    fresh = _service().build(final_attestation=attestation)
    assert fresh["consistency_issues"] == []


def test_purity_no_forbidden_tokens() -> None:
    src = inspect.getsource(mod)
    lowered = src.lower()
    for token in (
        "httpx",
        "requests",
        "get_db",
        "openai",
        "gemini",
        "anthropic",
        "ollama",
        "api_key",
    ):
        assert token not in lowered


def test_purity_no_network_or_mutation_tokens() -> None:
    src = inspect.getsource(mod)
    for token in ("urlopen", "socket", "TestClient", "SessionLocal"):
        assert token not in src


# --- Mutation verification ---------------------------------------------------
def test_mutation_verification_recomputation_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disable recomputation, confirm miss, restore, confirm detection."""
    _sid, attestation, _result = _valid_result()
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_fingerprint"] = "0" * 64
    tampered["audited_final_attestation_fingerprint"] = "0" * 64

    monkeypatch.setattr(
        mod,
        "_expected_final_fingerprint",
        lambda _final: "0" * 64,
    )
    blind = _service().build(final_attestation=tampered)
    # Disabling the recomputation removes exactly the recomputation-backed
    # detections, proving those issues depend on it. The nested Task 081
    # contract check still independently rejects the tampered input, so the
    # audit as a whole must not go blind-pass.
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" not in blind["consistency_issues"]
    assert (
        "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH"
        not in blind["consistency_issues"]
    )
    assert blind["final_attestation_consistent"] is False

    monkeypatch.undo()
    restored = _service().build(final_attestation=tampered)
    assert restored["final_attestation_consistent"] is False
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in restored["consistency_issues"]
    assert (
        "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH"
        in restored["consistency_issues"]
    )


# --- Validator boundary ------------------------------------------------------
def test_validate_result_rejects_wrong_source() -> None:
    _sid, _attestation, result = _valid_result()
    tampered_result = dict(result)
    tampered_result["final_attestation_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
            tampered_result
        )
    assert ei.value.invariant == "INVALID_SOURCE"


def test_validate_result_rejects_pair_mismatch() -> None:
    _sid, attestation, result = _valid_result()
    tampered_result = copy.deepcopy(result)
    tampered_result["audited_final_attestation_fingerprint"] = "1" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
            tampered_result, final_attestation=attestation
        )
    assert ei.value.invariant == "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH"


def test_expected_sources_are_distinct_and_fixed() -> None:
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081  # noqa: E501
        != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
    )
    assert (
        "TASK_082"
        in REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
    )
    assert (
        "TASK_079"
        in REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_079  # noqa: E501
    )
    assert (
        "TASK_080"
        in REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_080  # noqa: E501
    )

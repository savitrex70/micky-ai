"""Tests for Task 088 final-attestation-response consistency audit.

Task 088 performs a pure, deterministic, independent consistency audit of
the Task 087 final-attestation API response without executing Task 087,
making HTTP calls, accessing the database, or invoking external
models/providers.
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    _expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
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
    "response_consistent",
    "session_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
    "nested_package_consistent",
    "nested_package_consistency_consistent",
    "provenance_consistent",
    "response_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "response_consistency_source",
)

RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_attestation_bundle",
    "final_attestation_bundle_consistency",
    "response_source",
)

ISSUE_ORDER = (
    "MISSING_RESPONSE_FIELD",
    "INVALID_RESPONSE_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_BUNDLE_MISMATCH",
    "NESTED_BUNDLE_CONSISTENCY_MISMATCH",
    "NESTED_PACKAGE_MISMATCH",
    "NESTED_PACKAGE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
    "BUNDLE_FINGERPRINT_FORMAT",
    "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
    "BUNDLE_FINGERPRINT_MISMATCH",
    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
    "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
    "BUNDLE_FINGERPRINT_CHECK_UNAVAILABLE",
    "RESPONSE_RELATIONSHIP_MISMATCH",
    "RESPONSE_CONTRACT_MISMATCH",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService  # noqa: E501
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService()
    )  # noqa: E501


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-088-test"},
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


def _valid_response() -> tuple[UUID, dict[str, Any]]:
    sid_str = _seed_full("Task 088 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        response = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    return sid, response


def _valid_result() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid, response = _valid_response()
    return sid, response, _service().build(response=response)


def _check(response: dict[str, Any]) -> dict[str, Any]:
    return _service().build(response=response)


# --- Valid response ---------------------------------------------------------
def test_valid_shape_and_flags() -> None:
    _sid, _response, result = _valid_result()
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["response_consistent"] is True
    assert result["consistency_issues"] == []
    assert result["session_consistent"] is True
    assert result["nested_bundle_consistent"] is True
    assert result["nested_bundle_consistency_consistent"] is True
    assert result["nested_package_consistent"] is True
    assert result["nested_package_consistency_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["response_relationship_consistent"] is True
    assert result["source_consistency"] is True
    assert result["metadata_consistent"] is True
    assert (
        result["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
    )


def test_result_schema_roundtrip() -> None:
    _sid, _response, result = _valid_result()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead.model_validate(  # noqa: E501
        result
    )
    assert model.response_consistent is True
    assert model.consistency_issues == []


def test_fingerprint_matches_task085_definition() -> None:
    _sid, response = _valid_response()
    bundle = response["final_attestation_bundle"]
    consistency = response["final_attestation_bundle_consistency"]
    expected = _expected_bundle_fingerprint(bundle)
    assert consistency["bundle_fingerprint"] == expected
    assert consistency["audited_bundle_fingerprint"] == expected


def test_missing_response_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501
    ) as ei:
        _service().build(response=None)
    assert ei.value.invariant == "MISSING_RESPONSE"


def test_non_mapping_response_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501
    ) as ei:
        _service().build(response="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "RESPONSE_TYPE"


# --- Every required field missing -------------------------------------------
@pytest.mark.parametrize("field", RESPONSE_REQUIRED_FIELDS)
def test_every_required_field_missing_is_reported(field: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    del tampered[field]
    result = _check(tampered)
    assert "MISSING_RESPONSE_FIELD" in result["consistency_issues"]
    assert result["response_consistent"] is False
    assert result["metadata_consistent"] is False


def test_duplicate_missing_fields_collapse_to_one_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    del tampered["available"]
    del tampered["response_source"]
    result = _check(tampered)
    assert result["consistency_issues"].count("MISSING_RESPONSE_FIELD") == 1


def test_invalid_response_available_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["available"] = "yes"  # type: ignore[assignment]
    result = _check(tampered)
    assert "INVALID_RESPONSE_AVAILABLE" in result["consistency_issues"]
    assert result["available"] is True
    assert result["metadata_consistent"] is False
    assert result["response_consistent"] is False


# --- session identity --------------------------------------------------------
def test_session_id_invalid_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = "not-a-uuid"
    result = _check(tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["response_consistent"] is False


def test_session_id_mismatch_nested_bundle() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["session_id"] = uuid4()
    result = _check(tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["response_consistent"] is False


def test_bundle_consistency_session_flag_false_is_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"]["session_consistent"] = False
    result = _check(tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


# --- Nested corruptions (each level) -----------------------------------------
def test_nested_bundle_non_mapping_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = "broken"  # type: ignore[assignment]
    result = _check(tampered)
    assert "NESTED_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistent"] is False
    assert result["response_consistent"] is False


def test_nested_bundle_corruption_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    broken = copy.deepcopy(response["final_attestation_bundle"])
    broken["available"] = False
    tampered["final_attestation_bundle"] = broken
    result = _check(tampered)
    assert "NESTED_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistent"] is False


def test_nested_bundle_consistency_non_mapping_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = []  # type: ignore[assignment]
    result = _check(tampered)
    assert "NESTED_BUNDLE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistency_consistent"] is False


def test_nested_bundle_consistency_corruption_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    broken = copy.deepcopy(response["final_attestation_bundle_consistency"])
    broken["available"] = False
    tampered["final_attestation_bundle_consistency"] = broken
    result = _check(tampered)
    assert "NESTED_BUNDLE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_bundle_consistency_consistent"] is False


def test_nested_package_non_mapping_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package"] = "broken"  # type: ignore[assignment]  # noqa: E501
    result = _check(tampered)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistent"] is False
    assert result["response_consistent"] is False


def test_nested_package_corruption_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    broken = copy.deepcopy(
        response["final_attestation_bundle"]["final_attestation_package"]
    )
    broken["available"] = False
    tampered["final_attestation_bundle"]["final_attestation_package"] = broken
    result = _check(tampered)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistent"] is False


def test_nested_package_consistency_non_mapping_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package_consistency"] = []  # type: ignore[assignment]  # noqa: E501
    result = _check(tampered)
    assert "NESTED_PACKAGE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistency_consistent"] is False


def test_nested_package_consistency_corruption_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    broken = copy.deepcopy(
        response["final_attestation_bundle"]["final_attestation_package_consistency"]
    )
    broken["available"] = False
    tampered["final_attestation_bundle"][
        "final_attestation_package_consistency"
    ] = broken
    result = _check(tampered)
    assert "NESTED_PACKAGE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistency_consistent"] is False


# --- Source tampering (each level) -------------------------------------------
def test_package_source_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package"] = (
        copy.deepcopy(  # noqa: E501
            response["final_attestation_bundle"]["final_attestation_package"]
        )
    )
    tampered["final_attestation_bundle"]["final_attestation_package"][
        "package_source"
    ] = "WRONG"
    result = _check(tampered)
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["response_consistent"] is False


def test_package_consistency_source_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package_consistency"] = (
        copy.deepcopy(
            response["final_attestation_bundle"][
                "final_attestation_package_consistency"
            ]
        )
    )
    tampered["final_attestation_bundle"]["final_attestation_package_consistency"][
        "package_consistency_source"
    ] = "WRONG"
    result = _check(tampered)
    assert "PACKAGE_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_bundle_source_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["bundle_source"] = "WRONG"
    result = _check(tampered)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["response_consistent"] is False


def test_bundle_consistency_source_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"][
        "bundle_consistency_source"
    ] = "WRONG"
    result = _check(tampered)
    assert "BUNDLE_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["response_consistent"] is False


def test_response_source_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["response_source"] = "WRONG"
    result = _check(tampered)
    assert "RESPONSE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["response_consistent"] is False


# --- Fingerprint tampering ----------------------------------------------------
def test_bundle_fingerprint_format_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"][
        "bundle_fingerprint"
    ] = "not-hex"  # noqa: E501
    result = _check(tampered)
    assert "BUNDLE_FINGERPRINT_FORMAT" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


def test_audited_bundle_fingerprint_format_reports_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"][
        "audited_bundle_fingerprint"
    ] = "not-hex"
    result = _check(tampered)
    assert "AUDITED_BUNDLE_FINGERPRINT_FORMAT" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_bundle_fingerprint_tampering_flags_mismatch_and_pair() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"]["bundle_fingerprint"] = "0" * 64
    result = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


def test_audited_bundle_fingerprint_tampering_flags_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"]["audited_bundle_fingerprint"] = (
        "f" * 64
    )
    result = _check(tampered)
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_both_fingerprints_wrong_but_equal_flag_both_mismatches() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    wrong = "1" * 64
    assert (
        wrong != response["final_attestation_bundle_consistency"]["bundle_fingerprint"]
    )
    tampered["final_attestation_bundle_consistency"]["bundle_fingerprint"] = wrong
    tampered["final_attestation_bundle_consistency"][
        "audited_bundle_fingerprint"
    ] = wrong
    result = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" not in result["consistency_issues"]
    assert result["response_consistent"] is False


def test_uppercase_fingerprint_rejected_as_format() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"]["bundle_fingerprint"] = response[
        "final_attestation_bundle_consistency"
    ]["bundle_fingerprint"].upper()
    result = _check(tampered)
    assert "BUNDLE_FINGERPRINT_FORMAT" in result["consistency_issues"]


def test_stale_fingerprint_after_content_change() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    # Tamper fingerprinted CONTENT (the nested package verdict is part of
    # the bundle fingerprint core) while leaving fingerprints stale.
    # Flipping only the derived bundle_consistent flag would not alter the
    # recomputation, since fingerprints bind content, not derived verdicts.
    nested_package = copy.deepcopy(
        tampered["final_attestation_bundle"]["final_attestation_package"]
    )
    nested_package["package_consistent"] = not nested_package["package_consistent"]
    tampered["final_attestation_bundle"]["final_attestation_package"] = nested_package
    result = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


# --- Derived-flag tampering ----------------------------------------------------
def test_response_consistent_flip_flags_relationship_mismatch() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["response_consistent"] = not response["response_consistent"]
    result = _check(tampered)
    assert "RESPONSE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["response_relationship_consistent"] is False
    assert result["response_consistent"] is False


def test_coherent_defective_response_has_no_spurious_relationship_issue() -> None:
    _sid, response, _result = _valid_result()
    defective = copy.deepcopy(response)
    defective_bundle = copy.deepcopy(response["final_attestation_bundle"])
    defective_consistency = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    defective_bundle["bundle_consistent"] = False
    defective_consistency["bundle_consistent"] = False
    defective["response_consistent"] = False
    refreshed = _expected_bundle_fingerprint(defective_bundle)
    defective_consistency["bundle_fingerprint"] = refreshed
    defective_consistency["audited_bundle_fingerprint"] = refreshed
    defective["final_attestation_bundle"] = defective_bundle
    defective["final_attestation_bundle_consistency"] = defective_consistency
    result = _check(defective)
    assert "RESPONSE_RELATIONSHIP_MISMATCH" not in result["consistency_issues"]


def test_validate_result_rejects_derived_flag_mismatch() -> None:
    _sid, response, _result = _valid_result()
    bundle = copy.deepcopy(response)
    result = _check(response)
    for field in (
        "session_consistent",
        "nested_bundle_consistent",
        "nested_bundle_consistency_consistent",
        "nested_package_consistent",
        "nested_package_consistency_consistent",
        "provenance_consistent",
        "response_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        tampered = copy.deepcopy(result)
        tampered[field] = not tampered[field]
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501
        ):
            mod.ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService._validate_result(  # noqa: E501
                tampered
            )
    _ = bundle


def test_validate_result_rejects_duplicates_and_bad_order() -> None:
    _sid, _response, result = _valid_result()
    duped = copy.deepcopy(result)
    duped["consistency_issues"] = ["SESSION_ID_MISMATCH", "SESSION_ID_MISMATCH"]
    duped["response_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501
    ) as ei:
        mod.ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService._validate_result(  # noqa: E501
            duped
        )
    assert ei.value.invariant == "DUPLICATE_ISSUE"


def test_validate_result_rejects_shuffled_order() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = "not-a-uuid"
    tampered["response_source"] = "WRONG"
    result = _check(tampered)
    assert len(result["consistency_issues"]) >= 2
    shuffled = copy.deepcopy(result)
    shuffled["consistency_issues"] = list(reversed(shuffled["consistency_issues"]))
    if shuffled["consistency_issues"] != result["consistency_issues"]:
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501
        ) as ei:
            mod.ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService._validate_result(  # noqa: E501
                shuffled
            )
        assert ei.value.invariant == "ISSUES_ORDER"


# --- Ordering / determinism / immutability -------------------------------------
def test_issue_order_and_dedupe() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = "not-a-uuid"
    tampered["response_source"] = "WRONG"
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"][
        "bundle_fingerprint"
    ] = "not-hex"  # noqa: E501
    result = _check(tampered)
    issues = result["consistency_issues"]
    assert len(issues) == len(set(issues))
    assert issues == [i for i in ISSUE_ORDER if i in set(issues)]


def test_deterministic() -> None:
    _sid, response, _result = _valid_result()
    assert _check(response) == _check(response)


def test_global_cache_regression() -> None:
    _s1, r1 = _valid_response()
    before = _check(r1)
    _s2, r2 = _valid_response()
    _ = _check(r2)
    assert _check(r1) == before


def test_input_immutability() -> None:
    _sid, response, _result = _valid_result()
    before = copy.deepcopy(response)
    _check(response)
    assert response == before


def test_available_flag_is_true_even_for_flagged_response() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["response_source"] = "WRONG"
    result = _check(tampered)
    assert result["available"] is True
    assert result["response_consistent"] is False


def test_no_hidden_state_tokens() -> None:
    src = inspect.getsource(mod)
    assert "_LAST" not in src
    assert "global" not in src


# --- Purity ---------------------------------------------------------------------
def test_no_database_imports() -> None:
    src = inspect.getsource(mod)
    for token in ("get_db", "Session", "TestClient"):
        assert token not in src


def test_no_http_imports() -> None:
    src = inspect.getsource(mod)
    for token in ("TestClient", "httpx", "requests", "urlopen", "socket"):
        assert token not in src


def test_no_llm_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("ollama", "openai", "gemini", "anthropic", "api_key"):
        assert token not in src


def test_no_fingerprint_fallback() -> None:
    src = inspect.getsource(mod)
    assert 'get("bundle_fingerprint") or' not in src
    assert 'get("audited_bundle_fingerprint") or' not in src
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in src
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in src
    assert "BUNDLE_FINGERPRINT_MISMATCH" in src


def test_source_identifiers_present() -> None:
    src = inspect.getsource(mod)
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088"  # noqa: E501
        in src
    )


# --- Mutation verification of recomputation logic --------------------------------
def test_broken_recompute_is_flagged_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sid, response, _result = _valid_result()
    monkeypatch.setattr(mod, "_expected_bundle_fingerprint", lambda _b: "0" * 64)
    result = _check(response)
    assert result["response_consistent"] is False
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]


def test_recompute_monkeypatch_hides_and_restores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    wrong = "1" * 64
    assert (
        wrong != response["final_attestation_bundle_consistency"]["bundle_fingerprint"]
    )
    tampered["final_attestation_bundle_consistency"]["bundle_fingerprint"] = wrong
    tampered["final_attestation_bundle_consistency"][
        "audited_bundle_fingerprint"
    ] = wrong
    before = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in before["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in before["consistency_issues"]
    monkeypatch.setattr(mod, "_expected_bundle_fingerprint", lambda _b: wrong)
    hidden = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" not in hidden["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" not in hidden["consistency_issues"]
    monkeypatch.undo()
    restored = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in restored["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in restored["consistency_issues"]
    assert restored == before


def test_fingerprint_compute_failure_reports_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sid, response, _result = _valid_result()

    def _boom(_bundle: Any) -> str:
        raise RuntimeError("forced")

    monkeypatch.setattr(mod, "_expected_bundle_fingerprint", _boom)
    result = _check(response)
    assert result["response_consistent"] is False
    assert "BUNDLE_FINGERPRINT_COMPUTE_FAILED" in result["consistency_issues"]
    assert result["provenance_consistent"] is False

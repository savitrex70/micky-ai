"""Tests for Task 089: regression hardening of the Tasks 083-088 chain.

Covers the full chain (Task 083 package, 084 package audit, 085 bundle,
086 bundle audit, 087 response, 088 response audit) built via the real
Task 087 response service on a seeded session and audited via the real
Task 088 service. Tests only; no production code is modified here.
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle as bundle085_mod,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package as package083_mod,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response as response087_mod,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    _expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    _expected_package_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,  # noqa: E501
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


RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_attestation_bundle",
    "final_attestation_bundle_consistency",
    "response_source",
)

BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "final_attestation_package",
    "final_attestation_package_consistency",
    "bundle_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)

SOURCE_SCOPE_TO_ISSUE = {
    "083": "PACKAGE_SOURCE_MISMATCH",
    "084": "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "085": "BUNDLE_SOURCE_MISMATCH",
    "086": "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "087": "RESPONSE_SOURCE_MISMATCH",
}


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService  # noqa: E501
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService()  # noqa: E501
    )


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-089-test"},
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
    sid_str = _seed_full("Task 089 capture")
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


def _endpoint(sid: str) -> str:
    return (
        f"/sessions/{sid}/reasoning-handoff/fully-audited/" "attestation/final-response"
    )


def _api_get(sid: str) -> dict[str, Any]:
    r = client.get(_endpoint(sid))
    assert r.status_code == 200
    return r.json()


def _session_count() -> int:
    r = client.get("/sessions")
    assert r.status_code == 200
    return len(r.json())


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _with_source_tamper(response: dict[str, Any], scope: str) -> dict[str, Any]:
    tampered = copy.deepcopy(response)
    bundle = tampered["final_attestation_bundle"]
    if scope == "083":
        bundle["final_attestation_package"]["package_source"] = "WRONG"
    elif scope == "084":
        bundle["final_attestation_package_consistency"][
            "package_consistency_source"
        ] = "WRONG"
    elif scope == "085":
        bundle["bundle_source"] = "WRONG"
    elif scope == "086":
        tampered["final_attestation_bundle_consistency"][
            "bundle_consistency_source"
        ] = "WRONG"
    elif scope == "087":
        tampered["response_source"] = "WRONG"
    else:  # pragma: no cover - guarded by parametrize ids
        raise AssertionError(f"unknown scope {scope}")
    return tampered


def _with_consistency_fingerprint(
    response: dict[str, Any],
    *,
    bundle_fp: str | None = None,
    audited_fp: str | None = None,
) -> dict[str, Any]:
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    consistency = tampered["final_attestation_bundle_consistency"]
    if bundle_fp is not None:
        consistency["bundle_fingerprint"] = bundle_fp
    if audited_fp is not None:
        consistency["audited_bundle_fingerprint"] = audited_fp
    return tampered


def _differing_hex(valid: str) -> str:
    replacement = "0" if valid[0] != "0" else "1"
    wrong = replacement + valid[1:]
    assert wrong != valid
    return wrong


def _coherent_all_false_response() -> tuple[UUID, dict[str, Any]]:
    """Craft a truthful all-False chain with refreshed fingerprints."""
    sid, response = _valid_response()
    defective = copy.deepcopy(response)
    bundle = defective["final_attestation_bundle"]
    consistency086 = defective["final_attestation_bundle_consistency"]
    package083 = bundle["final_attestation_package"]
    pkg_cons084 = bundle["final_attestation_package_consistency"]
    att082 = package083["final_attestation_consistency"]

    att082["final_attestation_consistent"] = False
    att082["consistency_issues"] = ["FINAL_RELATIONSHIP_MISMATCH"]
    att082["final_relationship_consistent"] = False

    package083["package_consistent"] = False
    refreshed_pkg_fp = _expected_package_fingerprint(package083)
    package083["package_fingerprint"] = refreshed_pkg_fp
    package083["audited_package_fingerprint"] = refreshed_pkg_fp

    pkg_cons084["package_consistent"] = False
    pkg_cons084["consistency_issues"] = ["PACKAGE_RELATIONSHIP_MISMATCH"]
    pkg_cons084["package_relationship_consistent"] = False
    pkg_cons084["package_fingerprint"] = refreshed_pkg_fp
    pkg_cons084["audited_package_fingerprint"] = refreshed_pkg_fp

    bundle["bundle_consistent"] = False
    refreshed_bundle_fp = _expected_bundle_fingerprint(bundle)
    bundle["bundle_fingerprint"] = refreshed_bundle_fp
    bundle["audited_bundle_fingerprint"] = refreshed_bundle_fp

    consistency086["bundle_consistent"] = False
    consistency086["consistency_issues"] = ["BUNDLE_RELATIONSHIP_MISMATCH"]
    consistency086["bundle_relationship_consistent"] = False
    consistency086["bundle_fingerprint"] = refreshed_bundle_fp
    consistency086["audited_bundle_fingerprint"] = refreshed_bundle_fp

    defective["response_consistent"] = False
    return sid, defective


# --- Valid chain positive controls -------------------------------------------
def test_valid_chain_audits_clean() -> None:
    _sid, _response, result = _valid_result()
    assert result["available"] is True
    assert result["response_consistent"] is True
    assert result["consistency_issues"] == []
    assert (
        result["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
    )


def test_valid_chain_sources_match_task_constants() -> None:
    _sid, response, _result = _valid_result()
    bundle = response["final_attestation_bundle"]
    assert (
        bundle["final_attestation_package"]["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
    )
    assert (
        bundle["final_attestation_package_consistency"]["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
    )
    assert (
        bundle["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
    )
    assert (
        response["final_attestation_bundle_consistency"]["bundle_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086  # noqa: E501
    )
    assert (
        response["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
    )


def test_valid_chain_fingerprints_match_helpers() -> None:
    _sid, response, _result = _valid_result()
    bundle = response["final_attestation_bundle"]
    package = bundle["final_attestation_package"]
    assert _expected_bundle_fingerprint(bundle) == bundle["bundle_fingerprint"]
    assert _expected_package_fingerprint(package) == package["package_fingerprint"]


# --- Missing fields -----------------------------------------------------------
@pytest.mark.parametrize("field", RESPONSE_REQUIRED_FIELDS)
def test_envelope_required_field_missing_is_flagged(field: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    del tampered[field]
    result = _check(tampered)
    assert "MISSING_RESPONSE_FIELD" in result["consistency_issues"]
    assert result["response_consistent"] is False


@pytest.mark.parametrize("field", BUNDLE_REQUIRED_FIELDS)
def test_bundle_required_field_missing_is_flagged(field: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    del tampered["final_attestation_bundle"][field]
    result = _check(tampered)
    assert "NESTED_BUNDLE_MISMATCH" in result["consistency_issues"]
    assert result["response_consistent"] is False


# --- Wrong types ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("target", "bad_value", "issue"),
    [
        ("bundle", "broken", "NESTED_BUNDLE_MISMATCH"),
        ("bundle_consistency", [], "NESTED_BUNDLE_CONSISTENCY_MISMATCH"),
        ("package", "broken", "NESTED_PACKAGE_MISMATCH"),
        ("package_consistency", [], "NESTED_PACKAGE_CONSISTENCY_MISMATCH"),
    ],
)
def test_non_mapping_nested_is_flagged(target: str, bad_value: Any, issue: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    if target == "bundle":
        tampered["final_attestation_bundle"] = bad_value
    elif target == "bundle_consistency":
        tampered["final_attestation_bundle_consistency"] = bad_value
    elif target == "package":
        tampered["final_attestation_bundle"] = copy.deepcopy(
            response["final_attestation_bundle"]
        )
        tampered["final_attestation_bundle"]["final_attestation_package"] = bad_value
    else:
        tampered["final_attestation_bundle"] = copy.deepcopy(
            response["final_attestation_bundle"]
        )
        tampered["final_attestation_bundle"][
            "final_attestation_package_consistency"
        ] = bad_value
    result = _check(tampered)
    assert issue in result["consistency_issues"]
    assert result["response_consistent"] is False


def test_envelope_available_non_bool_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["available"] = "yes"  # type: ignore[assignment]
    result = _check(tampered)
    assert "INVALID_RESPONSE_AVAILABLE" in result["consistency_issues"]
    assert result["response_consistent"] is False


def test_envelope_response_consistent_non_bool_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["response_consistent"] = "yes"  # type: ignore[assignment]
    result = _check(tampered)
    assert "RESPONSE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["response_consistent"] is False


@pytest.mark.parametrize("bad_sid", ["not-a-uuid", 12345])
def test_envelope_session_non_uuid_is_invalid(bad_sid: Any) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = bad_sid
    result = _check(tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["response_consistent"] is False


# --- Wrong UUIDs ------------------------------------------------------------------
def test_response_session_mismatch_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = uuid4()
    result = _check(tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["response_consistent"] is False


def test_bundle_session_mismatch_is_flagged() -> None:
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


def test_package_session_mismatch_flags_nested_package() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package"] = copy.deepcopy(
        response["final_attestation_bundle"]["final_attestation_package"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package"][
        "session_id"
    ] = uuid4()
    result = _check(tampered)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistent"] is False
    assert result["response_consistent"] is False


def test_bundle_consistency_session_flag_false_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    tampered["final_attestation_bundle_consistency"]["session_consistent"] = False
    result = _check(tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["response_consistent"] is False


def test_package_consistency_session_flag_false_is_flagged() -> None:
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
        "session_consistent"
    ] = False
    result = _check(tampered)
    assert "NESTED_PACKAGE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistency_consistent"] is False
    assert result["response_consistent"] is False


# --- Wrong source constants -------------------------------------------------------
@pytest.mark.parametrize("scope", ["083", "084", "085", "086", "087"])
def test_wrong_source_constant_is_flagged(scope: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = _with_source_tamper(response, scope)
    result = _check(tampered)
    assert SOURCE_SCOPE_TO_ISSUE[scope] in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["response_consistent"] is False


# --- Fingerprint format and binding -------------------------------------------------
@pytest.mark.parametrize(
    ("field", "issue"),
    [
        ("bundle_fingerprint", "BUNDLE_FINGERPRINT_FORMAT"),
        ("audited_bundle_fingerprint", "AUDITED_BUNDLE_FINGERPRINT_FORMAT"),
    ],
)
def test_uppercase_fingerprint_is_rejected(field: str, issue: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle_consistency"] = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    original = response["final_attestation_bundle_consistency"][field]
    tampered["final_attestation_bundle_consistency"][field] = original.upper()
    result = _check(tampered)
    assert issue in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


@pytest.mark.parametrize("length", [63, 65])
@pytest.mark.parametrize(
    ("field", "issue"),
    [
        ("bundle_fingerprint", "BUNDLE_FINGERPRINT_FORMAT"),
        ("audited_bundle_fingerprint", "AUDITED_BUNDLE_FINGERPRINT_FORMAT"),
    ],
)
def test_short_and_long_fingerprint_is_rejected(
    field: str, issue: str, length: int
) -> None:
    _sid, response, _result = _valid_result()
    kwarg = "bundle_fp" if field == "bundle_fingerprint" else "audited_fp"
    tampered = _with_consistency_fingerprint(response, **{kwarg: "a" * length})
    result = _check(tampered)
    assert issue in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


def test_mismatched_bundle_fingerprint_flags_pair() -> None:
    _sid, response, _result = _valid_result()
    valid = response["final_attestation_bundle_consistency"]["bundle_fingerprint"]
    tampered = _with_consistency_fingerprint(response, bundle_fp=_differing_hex(valid))
    result = _check(tampered)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


def test_mismatched_audited_fingerprint_flags_pair() -> None:
    _sid, response, _result = _valid_result()
    valid = response["final_attestation_bundle_consistency"][
        "audited_bundle_fingerprint"
    ]
    tampered = _with_consistency_fingerprint(response, audited_fp=_differing_hex(valid))
    result = _check(tampered)
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["response_consistent"] is False


def test_stale_fingerprint_after_nested_change_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
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


def test_deep_tamper_at_081_level_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    package = copy.deepcopy(
        tampered["final_attestation_bundle"]["final_attestation_package"]
    )
    attestation = copy.deepcopy(package["final_attestation"])
    attestation["response_bundle"] = "broken"  # type: ignore[assignment]
    package["final_attestation"] = attestation
    tampered["final_attestation_bundle"]["final_attestation_package"] = package
    result = _check(tampered)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistent"] is False
    assert result["response_consistent"] is False


def test_deep_tamper_at_082_level_is_flagged() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["final_attestation_bundle"] = copy.deepcopy(
        response["final_attestation_bundle"]
    )
    package = copy.deepcopy(
        tampered["final_attestation_bundle"]["final_attestation_package"]
    )
    consistency082 = copy.deepcopy(package["final_attestation_consistency"])
    consistency082["final_attestation_consistent"] = not consistency082[
        "final_attestation_consistent"
    ]
    package["final_attestation_consistency"] = consistency082
    tampered["final_attestation_bundle"]["final_attestation_package"] = package
    result = _check(tampered)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistent"] is False
    assert result["response_consistent"] is False


# --- Task 088 result validation ------------------------------------------------------
def test_validate_result_rejects_duplicate_issues() -> None:
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


def test_validate_result_rejects_reordered_issues() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = "not-a-uuid"
    tampered["response_source"] = "WRONG"
    result = _check(tampered)
    assert len(result["consistency_issues"]) >= 2
    shuffled = copy.deepcopy(result)
    shuffled["consistency_issues"] = list(reversed(shuffled["consistency_issues"]))
    assert shuffled["consistency_issues"] != result["consistency_issues"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501
    ) as ei:
        mod.ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService._validate_result(  # noqa: E501
            shuffled
        )
    assert ei.value.invariant == "ISSUES_ORDER"


# --- Legitimate defect preservation ------------------------------------
def test_coherent_all_false_defect_preserved_without_issues() -> None:
    _sid, defective = _coherent_all_false_response()
    assert defective["response_consistent"] is False
    assert defective["final_attestation_bundle"]["bundle_consistent"] is False
    assert (
        defective["final_attestation_bundle_consistency"]["bundle_consistent"] is False
    )
    before = copy.deepcopy(defective)
    result = _check(defective)
    assert result["consistency_issues"] == []
    assert result["available"] is True
    assert result["response_consistent"] is True
    assert defective == before


# --- API read-only behaviour -------------------------------------------------
def test_repeated_gets_do_not_write_sessions() -> None:
    sid = _seed_full("Task 089 write check")
    before = _session_count()
    for _ in range(3):
        r = client.get(_endpoint(sid))
        assert r.status_code == 200
    assert _session_count() == before


def test_api_get_matches_direct_build() -> None:
    sid_str = _seed_full("Task 089 api match")
    with TestingSessionLocal() as db:
        direct = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, UUID(sid_str)
        )
    payload = _api_get(sid_str)
    assert payload == _jsonable(direct)
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead.model_validate(  # noqa: E501
        payload
    )
    assert str(model.session_id) == sid_str


def test_deterministic_builds_and_gets() -> None:
    sid_str = _seed_full("Task 089 determinism")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        first = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    with TestingSessionLocal() as db:
        second = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    assert second == first
    assert _api_get(sid_str) == _api_get(sid_str)
    assert _api_get(sid_str) == _jsonable(first)
    assert _check(first) == _check(first)


def test_audit_does_not_mutate_input() -> None:
    _sid, response, _result = _valid_result()
    before = copy.deepcopy(response)
    _check(response)
    assert response == before


# --- No internal HTTP/model/cache dependency -----------------------------------
@pytest.mark.parametrize("module", [package083_mod, bundle085_mod, response087_mod])
def test_no_database_or_http_tokens(module: Any) -> None:
    src = inspect.getsource(module)
    for token in ("get_db", "TestClient", "httpx", "requests"):
        assert token not in src
    for token in ("urlopen", "socket"):
        assert token not in src


@pytest.mark.parametrize("module", [package083_mod, bundle085_mod, response087_mod])
def test_no_model_provider_tokens(module: Any) -> None:
    src = inspect.getsource(module).lower()
    for token in ("openai", "gemini", "anthropic", "ollama", "api_key"):
        assert token not in src

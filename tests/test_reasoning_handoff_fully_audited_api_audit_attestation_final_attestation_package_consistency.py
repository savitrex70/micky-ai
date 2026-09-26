"""Tests for Task 084 final-attestation-package consistency audit.

Task 084 performs a pure, deterministic, independent consistency audit of
a Task 083 final attestation package: required fields, availability,
session binding, the nested Task 081 final attestation, the nested
Task 082 consistency audit, relationship, sources, and both mandatory
package fingerprint fields -- independently recomputed, exactly equal to
each other, and exactly equal to the freshly recomputed fingerprint. It
never uses one fingerprint field as a fallback for the other.
"""

from __future__ import annotations

import copy
import inspect
import re as _re
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
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
    "package_consistent",
    "session_consistent",
    "nested_final_attestation_consistent",
    "nested_final_attestation_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)

PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "final_attestation",
    "final_attestation_consistency",
    "package_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService  # noqa: E501
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService()  # noqa: E501
    )


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-084-test"},
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
    sid_str = _seed_full("Task 084 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        final = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService().build_for_session(  # noqa: E501
            db, sid
        )
    consistency = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService().build(  # noqa: E501
        final_attestation=final
    )
    package = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build(  # noqa: E501
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    return sid, package


def _audit(package: dict[str, Any]) -> dict[str, Any]:
    return _service().build(package=package)


def _valid_audit() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid, package = _valid_package()
    return sid, package, _audit(package)


def _tampered(mutate: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (audit result, tampered package) for a mutated package."""
    _sid, package, _result = _valid_audit()
    broken = copy.deepcopy(package)
    mutate(broken)
    return _audit(broken), broken


# ---------------------------------------------------------------------------
# Valid audit
# ---------------------------------------------------------------------------


def test_valid_audit_shape_and_flags() -> None:
    _sid, _package, result = _valid_audit()
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []
    for flag in (
        "session_consistent",
        "nested_final_attestation_consistent",
        "nested_final_attestation_consistency_consistent",
        "provenance_consistent",
        "package_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_source_is_fixed() -> None:
    _sid, _package, result = _valid_audit()
    assert (
        result["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
    )


def test_fingerprints_are_recomputed_and_equal() -> None:
    _sid, package, result = _valid_audit()
    expected = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._package_fingerprint(  # noqa: E501
        package
    )
    assert result["package_fingerprint"] == expected
    assert result["audited_package_fingerprint"] == expected
    assert result["package_fingerprint"] == result["audited_package_fingerprint"]
    for field in ("package_fingerprint", "audited_package_fingerprint"):
        assert _re.fullmatch(r"[0-9a-f]{64}", result[field]), field


def test_result_schema_roundtrip() -> None:
    _sid, _package, result = _valid_audit()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead.model_validate(  # noqa: E501
        result
    )
    assert model.package_consistent is True
    assert model.consistency_issues == []


def test_deterministic() -> None:
    _sid, package, _result = _valid_audit()
    assert _audit(package) == _audit(package)


def test_does_not_mutate_package() -> None:
    _sid, package, _result = _valid_audit()
    before = copy.deepcopy(package)
    _audit(package)
    assert package == before


# ---------------------------------------------------------------------------
# Unauditable input
# ---------------------------------------------------------------------------


def test_missing_package_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        _service().build(package=None)
    assert ei.value.invariant == "MISSING_PACKAGE"


def test_non_mapping_package_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        _service().build(package="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "PACKAGE_TYPE"


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", PACKAGE_REQUIRED_FIELDS)
def test_every_required_field_missing_is_reported(field: str) -> None:
    _sid, package, _result = _valid_audit()
    broken = copy.deepcopy(package)
    del broken[field]
    result = _audit(broken)
    assert "MISSING_PACKAGE_FIELD" in result["consistency_issues"]
    assert result["package_consistent"] is False
    assert result["metadata_consistent"] is False


def test_duplicate_missing_fields_collapse_to_one_issue() -> None:
    result, _package = _tampered(
        lambda p: (p.pop("available"), p.pop("package_source"))
    )
    assert result["consistency_issues"].count("MISSING_PACKAGE_FIELD") == 1


def test_unavailable_package_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"available": False}))
    assert "INVALID_PACKAGE_AVAILABLE" in result["consistency_issues"]
    assert result["metadata_consistent"] is False
    assert result["package_consistent"] is False


# ---------------------------------------------------------------------------
# Session binding
# ---------------------------------------------------------------------------


def test_invalid_session_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"session_id": "not-a-uuid"}))
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["package_consistent"] is False


def test_package_session_mismatch_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"session_id": str(uuid4())}))
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["package_consistent"] is False


def test_nested_final_session_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["final_attestation"].update({"session_id": str(uuid4())})
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_nested_consistency_session_flag_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["final_attestation_consistency"].update(
            {"session_consistent": False}
        )
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["package_consistent"] is False


# ---------------------------------------------------------------------------
# Nested contracts
# ---------------------------------------------------------------------------


def test_nested_final_tamper_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["final_attestation"].update({"available": False})
    )
    assert "NESTED_FINAL_ATTESTATION_MISMATCH" in result["consistency_issues"]
    assert result["nested_final_attestation_consistent"] is False
    assert result["package_consistent"] is False


def test_nested_final_non_mapping_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p.update({"final_attestation": "not-a-mapping"})
    )
    assert "NESTED_FINAL_ATTESTATION_MISMATCH" in result["consistency_issues"]
    assert result["nested_final_attestation_consistent"] is False


def test_nested_consistency_tamper_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["final_attestation_consistency"].update({"available": False})
    )
    assert (
        "NESTED_FINAL_ATTESTATION_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )
    assert result["nested_final_attestation_consistency_consistent"] is False
    assert result["package_consistent"] is False


def test_nested_consistency_non_mapping_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p.update({"final_attestation_consistency": "nope"})
    )
    assert (
        "NESTED_FINAL_ATTESTATION_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )
    assert result["nested_final_attestation_consistency_consistent"] is False


# ---------------------------------------------------------------------------
# Fingerprints: format, independence, no or-fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ("package_fingerprint", "audited_package_fingerprint")
)
@pytest.mark.parametrize("bad", ("NOT-HEX", "A" * 64, "abc", "", 0, None))
def test_malformed_fingerprint_is_reported(field: str, bad: Any) -> None:
    result, _package = _tampered(lambda p: p.update({field: bad}))
    expected_issue = (
        "PACKAGE_FINGERPRINT_FORMAT"
        if field == "package_fingerprint"
        else "AUDITED_PACKAGE_FINGERPRINT_FORMAT"
    )
    assert expected_issue in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False


def test_package_fingerprint_tamper_does_not_use_audited_fallback() -> None:
    """Each fingerprint field is checked independently against the
    recomputed value: tampering only ``package_fingerprint`` must flag
    that field without implicating the untouched audited field."""
    result, _package = _tampered(lambda p: p.update({"package_fingerprint": "0" * 64}))
    assert "PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_PACKAGE_FINGERPRINT_MISMATCH" not in result["consistency_issues"]
    assert "PACKAGE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False


def test_audited_fingerprint_tamper_does_not_use_package_fallback() -> None:
    """Mirror of the above: tampering only ``audited_package_fingerprint``
    must flag that field without implicating the untouched field."""
    result, _package = _tampered(
        lambda p: p.update({"audited_package_fingerprint": "0" * 64})
    )
    assert "AUDITED_PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "PACKAGE_FINGERPRINT_MISMATCH" not in result["consistency_issues"]
    assert "PACKAGE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False


def test_source_tamper_still_flags_fingerprint_mismatch() -> None:
    """Tampering nested content changes the recomputed fingerprint, so
    both stored fields mismatch even though neither was touched
    directly -- the audit recomputes, it does not echo."""
    result, _package = _tampered(
        lambda p: p["final_attestation"].update({"final_attestation_source": "WRONG"})
    )
    assert "NESTED_FINAL_ATTESTATION_MISMATCH" in result["consistency_issues"]
    assert "PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["package_consistent"] is False


# ---------------------------------------------------------------------------
# Relationship and sources
# ---------------------------------------------------------------------------


def test_package_relationship_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p.update({"package_consistent": not p["package_consistent"]})
    )
    assert "PACKAGE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["package_relationship_consistent"] is False
    assert result["package_consistent"] is False


def test_package_source_mismatch_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"package_source": "WRONG"}))
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["package_consistent"] is False


def test_nested_final_source_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["final_attestation"].update({"final_attestation_source": "WRONG"})
    )
    assert "FINAL_ATTESTATION_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["package_consistent"] is False


def test_nested_consistency_source_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["final_attestation_consistency"].update(
            {"final_attestation_consistency_source": "WRONG"}
        )
    )
    assert (
        "FINAL_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    )
    assert result["source_consistency"] is False
    assert result["package_consistent"] is False


def test_nested_sources_carry_expected_task_identifiers() -> None:
    _sid, package, _result = _valid_audit()
    assert (
        package["final_attestation"]["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081  # noqa: E501
    )
    assert (
        package["final_attestation_consistency"]["final_attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
    )
    assert (
        package["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
    )


# ---------------------------------------------------------------------------
# Issue ordering and duplicate prevention
# ---------------------------------------------------------------------------


def test_issues_are_deduplicated_and_ordered() -> None:
    _sid, package, _result = _valid_audit()
    broken = copy.deepcopy(package)
    del broken["available"]
    del broken["package_source"]
    broken["package_fingerprint"] = "NOT-HEX"
    broken["audited_package_fingerprint"] = "ALSO-BAD"
    result = _audit(broken)
    issues = result["consistency_issues"]
    assert len(issues) == len(set(issues))
    assert issues == [
        "MISSING_PACKAGE_FIELD",
        "INVALID_PACKAGE_AVAILABLE",
        "PACKAGE_FINGERPRINT_FORMAT",
        "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
        "PACKAGE_SOURCE_MISMATCH",
    ]
    assert result["package_consistent"] is False


def test_validate_result_rejects_unordered_issues() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["consistency_issues"] = [
        "PACKAGE_SOURCE_MISMATCH",
        "MISSING_PACKAGE_FIELD",
    ]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "ISSUES_ORDER"


def test_validate_result_rejects_duplicate_issues() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["consistency_issues"] = [
        "PACKAGE_SOURCE_MISMATCH",
        "PACKAGE_SOURCE_MISMATCH",
    ]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "DUPLICATE_ISSUE"


# ---------------------------------------------------------------------------
# Validator: derived flags must be exactly the projection of the issues
# ---------------------------------------------------------------------------

_FLAG_INVARIANTS = (
    ("package_consistent", "PACKAGE_CONSISTENT_MISMATCH"),
    ("session_consistent", "SESSION_CONSISTENT_MISMATCH"),
    (
        "nested_final_attestation_consistent",
        "NESTED_FINAL_ATTESTATION_CONSISTENT_MISMATCH",
    ),
    (
        "nested_final_attestation_consistency_consistent",
        "NESTED_FINAL_ATTESTATION_CONSISTENCY_CONSISTENT_MISMATCH",
    ),
    ("provenance_consistent", "PROVENANCE_CONSISTENT_MISMATCH"),
    (
        "package_relationship_consistent",
        "PACKAGE_RELATIONSHIP_CONSISTENT_MISMATCH",
    ),
    ("source_consistency", "SOURCE_CONSISTENT_MISMATCH"),
    ("metadata_consistent", "METADATA_CONSISTENT_MISMATCH"),
)


@pytest.mark.parametrize("flag,invariant", _FLAG_INVARIANTS)
def test_validate_result_rejects_tampered_derived_flag(
    flag: str, invariant: str
) -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered[flag] = not tampered[flag]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == invariant


def test_validate_result_rejects_missing_field() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    del tampered["metadata_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_validate_result_rejects_non_boolean_flag() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["provenance_consistent"] = 1
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "PROVENANCE_CONSISTENT_TYPE"


def test_validate_result_rejects_available_false() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


def test_validate_result_rejects_wrong_source() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["package_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "INVALID_SOURCE"


def test_validate_result_rejects_bad_fingerprint_format() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "NOT-HEX"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_validate_result_rejects_fingerprint_pair_mismatch() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "f" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_PAIR_MISMATCH"


# ---------------------------------------------------------------------------
# Recomputation is required (mutation verification)
# ---------------------------------------------------------------------------


def test_recomputation_is_required_for_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing the fingerprint recompute helper to return a wrong but
    well-formed value must surface as fingerprint mismatches -- proving
    the audit recomputes instead of echoing the stored fields."""
    _sid, package, _result = _valid_audit()

    def wrong(_package: Any) -> str:
        return "f" * 64

    monkeypatch.setattr(mod, "_expected_package_fingerprint", wrong)
    result = _audit(package)
    assert "PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_PACKAGE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False
    assert result["package_fingerprint"] == "f" * 64
    assert result["audited_package_fingerprint"] == "f" * 64


def test_validator_recomputes_against_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result whose fingerprints no longer match a fresh recomputation
    for the audited package must be rejected."""
    _sid, package, result = _valid_audit()

    def wrong(_package: Any) -> str:
        return "e" * 64

    monkeypatch.setattr(mod, "_expected_package_fingerprint", wrong)
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
            result, package=package
        )
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_MISMATCH"


# ---------------------------------------------------------------------------
# Architectural assertions: purity and no or-fallback
# ---------------------------------------------------------------------------


def test_service_has_no_database_or_http_symbols() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "get_db",
        "httpx",
        "requests",
        "TestClient",
        "urlopen",
        "socket",
    ):
        assert forbidden not in src, forbidden
    assert "Session" not in src


def test_service_has_no_model_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("openai", "gemini", "anthropic", "ollama", "api_key"):
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token


def test_service_has_no_fingerprint_or_fallback() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "package_fp or",
        "audited_package_fp or",
        "package_fingerprint or",
        "or audited_package_fp",
        "or package_fp",
        "or expected_fp",
    ):
        assert forbidden not in src, forbidden


def test_canonical_source_constant_value() -> None:
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
        == "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_TASK_084"  # noqa: E501
    )

"""Tests for Task 068 fully audited API audit package consistency.

Task 068 independently audits a Task 067 package: package structure,
availability, session / method / path / status consistency, the nested
Task 063 bundle, the nested Task 066 audit, response-fingerprint
provenance, the package/audit relationship, sources, and metadata. It is
pure: no database, no HTTP, no endpoint call, no build-workflow
invocation, no mutation.
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
    reasoning_handoff_fully_audited_api_audit_package_consistency as mod,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068,
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError,
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

ENDPOINT = "/sessions/{sid}/reasoning-handoff/fully-audited"

RESULT_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_audit_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_package_fingerprint",
)


def _service() -> ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService:
    return ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-068-test"},
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


def _valid_package() -> tuple[UUID, str, dict[str, Any], dict[str, Any], dict]:
    sid_str = _seed_full_session("Task 068 valid")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff/fully-audited"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    package = ReasoningHandoffFullyAuditedApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=audit,
    )
    return sid, path, body, audit, package


def _audit(package: dict[str, Any]) -> dict[str, Any]:
    return _service().build(package=package)


def _valid_audit() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid, _path, _body, _api_audit, package = _valid_package()
    return sid, package, _audit(package)


def _tampered(mutate: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (audit result, tampered package) for a mutated package."""
    _sid, package, _result = _valid_audit()
    broken = copy.deepcopy(package)
    mutate(broken)
    return _audit(broken), broken


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_audit_shape() -> None:
    _sid, _package, result = _valid_audit()
    assert set(result) == set(RESULT_FIELDS)


def test_valid_audit_is_fully_consistent() -> None:
    _sid, _package, result = _valid_audit()
    assert result["available"] is True
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []
    for flag in (
        "session_consistent",
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "nested_response_consistent",
        "nested_api_audit_consistent",
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
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068
    )


def test_package_fingerprint_is_recomputable() -> None:
    _sid, package, result = _valid_audit()
    service = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService
    expected = service._package_fingerprint(package)
    assert result["audited_package_fingerprint"] == expected
    assert isinstance(result["audited_package_fingerprint"], str)
    assert len(result["audited_package_fingerprint"]) == 64


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
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        _service().build(package=None)
    assert ei.value.invariant == "MISSING_PACKAGE"


def test_non_mapping_package_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        _service().build(package="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "PACKAGE_TYPE"


def test_own_fingerprint_compute_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit's own package-fingerprint attestation must never be
    silently omitted."""
    _sid, package, _result = _valid_audit()

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("forced fingerprint failure")

    monkeypatch.setattr(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService,
        "_package_fingerprint",
        boom,
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        _audit(package)
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED"


# ---------------------------------------------------------------------------
# Structure / availability
# ---------------------------------------------------------------------------


def test_missing_field_is_reported() -> None:
    result, _package = _tampered(lambda p: p.pop("audited_response_fingerprint"))
    assert "MISSING_PACKAGE_FIELD" in result["consistency_issues"]
    assert result["metadata_consistent"] is False
    assert result["package_consistent"] is False


def test_unavailable_package_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"available": False}))
    assert "INVALID_PACKAGE_AVAILABLE" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_invalid_session_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"session_id": "not-a-uuid"}))
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_session_mismatch_against_response_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["response"].update({"session_id": str(uuid4())})
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_session_mismatch_against_path_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p.update(
            {"path": f"/sessions/{uuid4()}/reasoning-handoff/fully-audited"}
        )
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    # The path shape itself is still a valid Task 065 route, but the
    # nested audit's audited_path echo no longer matches it.
    assert "PATH_INVALID" not in result["consistency_issues"]
    assert "AUDITED_PATH_MISMATCH" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_audited_session_echo_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["api_consistency"].update({"audited_session_id": str(uuid4())})
    )
    assert "AUDITED_SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


# ---------------------------------------------------------------------------
# Transport metadata
# ---------------------------------------------------------------------------


def test_wrong_method_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"method": "POST"}))
    assert "METHOD_INVALID" in result["consistency_issues"]
    assert result["method_consistent"] is False


def test_wrong_path_shape_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p.update({"path": "/sessions/x/reasoning-handoff"})
    )
    assert "PATH_INVALID" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_wrong_status_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"status_code": 201}))
    assert "STATUS_CODE_INVALID" in result["consistency_issues"]
    assert result["status_consistent"] is False


def test_audited_method_mismatch_is_reported() -> None:
    """The nested audit's echoed method drifting from the package's
    declared method must be caught even though the package method itself
    is the correct GET."""
    result, _package = _tampered(
        lambda p: p["api_consistency"].update({"audited_method": "POST"})
    )
    assert "AUDITED_METHOD_MISMATCH" in result["consistency_issues"]
    assert result["method_consistent"] is False
    assert "METHOD_INVALID" not in result["consistency_issues"]
    assert result["package_consistent"] is False


def test_audited_path_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["api_consistency"].update({"audited_path": "/elsewhere"})
    )
    assert "AUDITED_PATH_MISMATCH" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_audited_status_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["api_consistency"].update({"audited_status_code": 201})
    )
    assert "AUDITED_STATUS_CODE_MISMATCH" in result["consistency_issues"]
    assert result["status_consistent"] is False


# ---------------------------------------------------------------------------
# Nested contracts
# ---------------------------------------------------------------------------


def test_nested_response_tamper_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["response"]["api_audit_package"].update({"method": "POST"})
    )
    assert "NESTED_RESPONSE_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_consistent"] is False
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False


def test_nested_response_non_mapping_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"response": "not-a-mapping"}))
    assert "NESTED_RESPONSE_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_consistent"] is False


def test_nested_api_audit_tamper_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["api_consistency"].update({"api_consistency_source": "WRONG"})
    )
    assert "NESTED_API_AUDIT_MISMATCH" in result["consistency_issues"]
    assert result["nested_api_audit_consistent"] is False
    assert result["provenance_consistent"] is False


def test_nested_api_audit_non_mapping_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"api_consistency": "nope"}))
    assert "NESTED_API_AUDIT_MISMATCH" in result["consistency_issues"]
    assert result["nested_api_audit_consistent"] is False


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_response_fingerprint_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p.update({"audited_response_fingerprint": "0" * 64})
    )
    assert "AUDITED_RESPONSE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False


def test_nested_audit_fingerprint_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["api_consistency"].update(
            {"audited_response_fingerprint": "0" * 64}
        )
    )
    assert "AUDITED_RESPONSE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_response_swapped_after_fingerprinting_is_reported() -> None:
    """A response replaced *after* the audit was taken must be caught: the
    declared fingerprint no longer matches the carried body, even though
    the substituted body is itself a structurally valid Task 063 bundle."""
    _sid_a, package, _result = _valid_audit()
    _sid_b, other_package, _other_result = _valid_audit()

    swapped = copy.deepcopy(package)
    swapped["response"] = copy.deepcopy(other_package["response"])

    result = _audit(swapped)
    assert "AUDITED_RESPONSE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False
    # The substituted bundle is internally valid, so this is purely a
    # provenance failure -- not a nested-contract failure.
    assert "NESTED_RESPONSE_MISMATCH" not in result["consistency_issues"]


def test_response_fingerprint_compute_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing the response-fingerprint helper to raise must never
    silently pass the provenance check."""
    _sid, package, _result = _valid_audit()

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("forced response fingerprint failure")

    monkeypatch.setattr(
        ReasoningHandoffFullyAuditedApiConsistencyService,
        "_response_fingerprint",
        boom,
    )
    result = _audit(package)
    assert "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["package_consistent"] is False


def test_provenance_check_unavailable_when_nested_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the nested contracts cannot be validated, provenance must be
    explicitly unavailable -- never True."""
    _sid, package, _result = _valid_audit()

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("forced nested validator failure")

    monkeypatch.setattr(
        ReasoningHandoffFullyAuditedApiConsistencyService,
        "_validate_result",
        boom,
    )
    result = _audit(package)
    assert "NESTED_API_AUDIT_MISMATCH" in result["consistency_issues"]
    assert (
        "AUDITED_RESPONSE_FINGERPRINT_CHECK_UNAVAILABLE" in result["consistency_issues"]
    )
    assert result["nested_api_audit_consistent"] is False
    assert result["provenance_consistent"] is False


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


def test_response_source_mismatch_is_reported() -> None:
    result, _package = _tampered(
        lambda p: p["response"].update({"bundle_source": "WRONG"})
    )
    assert "RESPONSE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_package_source_mismatch_is_reported() -> None:
    result, _package = _tampered(lambda p: p.update({"package_source": "WRONG"}))
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_contract_fallback_reports_otherwise_invisible_defect() -> None:
    """A defect that only Task 067's own validator can see (because it
    strips every direct signal) must still surface through the fallback."""
    _sid, package, _result = _valid_audit()
    broken = copy.deepcopy(package)
    # A valid GET/200 path, but the nested audit no longer agrees with the
    # declared fingerprint in a way Task 068 re-derives directly; here we
    # instead break the nested audit's own contract indirectly by giving
    # the package a response whose nested bundle contract differs from
    # what Task 067's validator requires.
    broken["response"]["api_audit_package"]["api_consistency"][
        "audited_response_fingerprint"
    ] = ("1" * 64)
    result = _audit(broken)
    assert result["package_consistent"] is False


# ---------------------------------------------------------------------------
# Legitimate underlying inconsistency
# ---------------------------------------------------------------------------


def test_valid_package_carrying_a_defect_report_is_still_consistent() -> None:
    """A Task 067 package that faithfully carries a defect-reporting Task
    066 audit is internally consistent: Task 068 must report
    ``package_consistent = True`` for it. This is the distinction between
    "the package is malformed" and "the package reports a legitimate
    inconsistency"."""
    sid, path, body, _audit_result, _package = _valid_package()
    tampered = copy.deepcopy(body)
    nested_audit = tampered["api_audit_package_consistency"]
    nested_audit["consistency_issues"] = ["NESTED_RESPONSE_MISMATCH"]
    nested_audit["package_consistent"] = False
    nested_audit["nested_response_consistent"] = False
    tampered["bundle_consistent"] = False

    api_audit = ReasoningHandoffFullyAuditedApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=tampered,
    )
    assert api_audit["api_consistent"] is True

    package = ReasoningHandoffFullyAuditedApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=tampered,
        api_consistency=api_audit,
    )
    assert package["package_consistent"] is True

    result = _audit(package)
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []


def test_defect_reporting_audit_package_stays_distinguishable() -> None:
    """A malformed API package (fingerprint/relationship broken) must be
    distinguishable from a valid package that merely reports a defect."""
    _sid, package, _result = _valid_audit()
    defect_audit = copy.deepcopy(package["api_consistency"])
    defect_audit["consistency_issues"] = ["NESTED_BUNDLE_MISMATCH"]
    defect_audit["api_consistent"] = False
    defect_audit["nested_bundle_consistent"] = False
    honest = copy.deepcopy(package)
    honest["api_consistency"] = defect_audit
    honest["package_consistent"] = False

    honest_result = _audit(honest)
    assert honest_result["package_consistent"] is True

    malformed = copy.deepcopy(honest)
    malformed["audited_response_fingerprint"] = "0" * 64
    malformed_result = _audit(malformed)
    assert malformed_result["package_consistent"] is False
    assert "AUDITED_RESPONSE_FINGERPRINT_MISMATCH" in (
        malformed_result["consistency_issues"]
    )


# ---------------------------------------------------------------------------
# Validator: derived flags must be exactly the projection of the issues
# ---------------------------------------------------------------------------

_FLAG_INVARIANTS = (
    ("package_consistent", "PACKAGE_CONSISTENT_MISMATCH"),
    ("session_consistent", "SESSION_CONSISTENT_MISMATCH"),
    ("method_consistent", "METHOD_CONSISTENT_MISMATCH"),
    ("path_consistent", "PATH_CONSISTENT_MISMATCH"),
    ("status_consistent", "STATUS_CONSISTENT_MISMATCH"),
    ("nested_response_consistent", "NESTED_RESPONSE_CONSISTENT_MISMATCH"),
    ("nested_api_audit_consistent", "NESTED_API_AUDIT_CONSISTENT_MISMATCH"),
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
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        (
            ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
                tampered
            )
        )
    assert ei.value.invariant == invariant


def test_validate_result_rejects_missing_field() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    del tampered["metadata_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_validate_result_rejects_non_boolean_flag() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["provenance_consistent"] = 1
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "PROVENANCE_CONSISTENT_TYPE"


def test_validate_result_rejects_available_false() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


def test_validate_result_rejects_wrong_source() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["package_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "INVALID_SOURCE"


def test_validate_result_rejects_bad_fingerprint_format() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "NOT-HEX"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_validate_result_rejects_tampered_valid_fingerprint() -> None:
    """Tampering the fingerprint with another valid 64-char hex must be
    rejected via binding check, not just format validation."""
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    # Use a different valid hex digest to simulate post-build tampering
    tampered["audited_package_fingerprint"] = "0" * 64
    assert (
        tampered["audited_package_fingerprint"] != result["audited_package_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"


def test_validate_result_rejects_tampered_valid_fingerprint_alternative() -> None:
    """Another valid hex variant must also be rejected."""
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["audited_package_fingerprint"] = "f" * 64
    assert (
        tampered["audited_package_fingerprint"] != result["audited_package_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"


def test_validate_result_fingerprint_recompute_failure_is_contract_error() -> None:
    """If fingerprint recomputation fails, validator must convert it to a
    contract error with chained cause, not leak raw exception."""
    from unittest.mock import patch

    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    with patch.object(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService,
        "_package_fingerprint",
        side_effect=RuntimeError("forced package fingerprint failure"),
    ):
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
        ) as ei:
            ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
                tampered
            )
        assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED"
        assert isinstance(ei.value.__cause__, RuntimeError)


def test_validate_result_rejects_duplicate_issues() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["consistency_issues"] = ["METHOD_INVALID", "METHOD_INVALID"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "DUPLICATE_ISSUE"


def test_validate_result_rejects_unordered_issues() -> None:
    _sid, _package, result = _valid_audit()
    tampered = dict(result)
    tampered["consistency_issues"] = ["STATUS_CODE_INVALID", "METHOD_INVALID"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "ISSUES_ORDER"


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


def test_service_has_no_database_or_http_imports() -> None:
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


def test_service_does_not_call_the_endpoint_or_build_workflows() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "rop.api.sessions",
        "build_for_session",
        "ReasoningHandoffFullyAuditedApiService",
        "ReasoningHandoffApiService",
    ):
        assert forbidden not in src, forbidden


def test_service_has_no_llm_or_provider_symbols() -> None:
    import re as _re

    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token


def test_canonical_source_constant_value() -> None:
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068
        == "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_TASK_068"
    )

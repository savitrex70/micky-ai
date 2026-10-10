"""Tests for the Task 180/181 final-attestation consistency boundary."""

from __future__ import annotations

import copy
import inspect

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180,
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181,
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182,
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService,
)

_SERVICE = ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService
_T180_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
_T181_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
)
_T182_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182  # noqa: E501


def _attestation(status: str = "CERTIFIED", session_id: str = "session-1"):
    blocked = status == "BLOCKED"
    unavailable = status == "UNAVAILABLE"
    bundle_status = {
        "CERTIFIED": "READY",
        "BLOCKED": "BLOCKED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[status]
    audit_status = "UNAVAILABLE" if unavailable else "CONSISTENT"
    consistency_status = "UNAVAILABLE" if unavailable else "CONSISTENT"
    findings = (
        ["INSUFFICIENT_EVIDENCE"]
        if unavailable
        else (["BLOCKING_EVIDENCE"] if blocked else [])
    )
    return ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
        session_id=session_id,
        attestation_status=status,
        certified=status == "CERTIFIED",
        blocked=blocked,
        available=not unavailable,
        bundle_status=bundle_status,
        bundle_audit_status=audit_status,
        bundle_audit_consistency_status=consistency_status,
        finding_count=len(findings),
        findings=findings,
        attestation_source=_T180_SOURCE,
    )


def _audit(
    status: str = "CERTIFIED",
    verdict: str = "CONSISTENT",
    session_id: str = "session-1",
    expected_status: str | None = None,
):
    findings = (
        ["AUDIT_CONTRADICTION"]
        if verdict == "INCONSISTENT"
        else (["AUDIT_UNAVAILABLE"] if verdict == "UNAVAILABLE" else [])
    )
    return ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
        session_id="" if verdict == "UNAVAILABLE" else session_id,
        attestation_audit_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_attestation_status=status,
        expected_attestation_status=expected_status or status,
        finding_count=len(findings),
        findings=findings,
        audit_source=_T181_SOURCE,
    )


def _verify(attestation=None, audit=None):
    return _SERVICE.verify(
        attestation=attestation or _attestation(),
        audit=audit or _audit(),
    )


@pytest.mark.parametrize("status", ["CERTIFIED", "BLOCKED", "UNAVAILABLE"])
def test_matching_known_statuses_are_consistent(status: str) -> None:
    result = _verify(_attestation(status), _audit(status))
    assert result["attestation_consistency_status"] == "CONSISTENT"
    assert result["published_attestation_status"] == status
    assert result["expected_attestation_status"] == status
    assert result["findings"] == []
    assert result["session_id"] == "session-1"
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead.model_validate(
        result
    )


@pytest.mark.parametrize("status", ["BLOCKED", "UNAVAILABLE"])
def test_forged_status_is_inconsistent(status: str) -> None:
    payload = _attestation().model_dump()
    payload["attestation_status"] = status
    payload["certified"] = status == "CERTIFIED"
    payload["blocked"] = status == "BLOCKED"
    result = _verify(payload, _audit("CERTIFIED"))
    assert result["attestation_consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]


def test_unknown_published_status_is_unavailable_not_mismatch() -> None:
    result = _verify({"attestation_status": "FUTURE_STATUS"}, _audit())
    assert result["attestation_consistency_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert result["findings"] == ["ATTESTATION_INVALID"]


def test_unreadable_published_status_is_unavailable() -> None:
    result = _verify({"attestation_status": []}, _audit())
    assert result["attestation_consistency_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None
    assert result["findings"] == ["ATTESTATION_INVALID"]


def test_unavailable_audit_is_not_a_business_status_mismatch() -> None:
    result = _verify(_attestation("UNAVAILABLE"), _audit("UNAVAILABLE", "UNAVAILABLE"))
    assert result["attestation_consistency_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] == "UNAVAILABLE"
    assert "AUDIT_UNAVAILABLE" in result["findings"]
    assert "SESSION_MISMATCH" not in result["findings"]


def test_audit_disagreement_is_inconsistent() -> None:
    result = _verify(
        _attestation("CERTIFIED"),
        _audit("BLOCKED", "INCONSISTENT", expected_status="CERTIFIED"),
    )
    assert result["attestation_consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]
    assert "AUDIT_INCONSISTENT" in result["findings"]


def test_attestation_source_mismatch_is_detected() -> None:
    payload = _attestation().model_dump()
    payload["attestation_source"] = "FORGED_SOURCE"
    result = _verify(payload, _audit())
    assert result["attestation_consistency_status"] == "INCONSISTENT"
    assert "ATTESTATION_SOURCE_INVALID" in result["findings"]


def test_session_mismatch_is_inconsistent() -> None:
    result = _verify(_attestation(session_id="detached"), _audit())
    assert result["attestation_consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in result["findings"]


def test_mutated_model_is_revalidated_and_not_mutated() -> None:
    attestation = _attestation()
    attestation.finding_count = 4
    before = copy.deepcopy(attestation.__dict__)
    result = _verify(attestation, _audit())
    assert result["attestation_consistency_status"] == "UNAVAILABLE"
    assert "ATTESTATION_INVALID" in result["findings"]
    assert attestation.__dict__ == before


def test_wrong_input_types_are_unavailable() -> None:
    result = _verify("not-an-attestation", _audit())
    assert result["attestation_consistency_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None

    result = _verify(_attestation(), "not-an-audit")
    assert result["attestation_consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_findings_are_deterministic_and_inputs_immutable() -> None:
    attestation = _attestation(session_id="detached")
    audit = _audit("BLOCKED", "INCONSISTENT")
    attestation_before = attestation.model_dump()
    audit_before = audit.model_dump()
    first = _verify(attestation, audit)
    second = _verify(attestation, audit)
    assert first == second
    assert first["findings"] == sorted(set(first["findings"]))
    assert attestation.model_dump() == attestation_before
    assert audit.model_dump() == audit_before


def test_schema_rejects_incoherent_and_extra_data() -> None:
    result = _verify()
    result["extra"] = True
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead.model_validate(
            result
        )

    result = _verify()
    result["finding_count"] = 1
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead.model_validate(
            result
        )


def test_service_has_no_upstream_or_io_dependencies() -> None:
    source = inspect.getsource(_SERVICE)
    for forbidden in (
        "requests",
        "httpx",
        "sqlalchemy",
        "ReasoningRunStage7ReleaseReadinessFinalAttestationService",
        "ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService",
    ):
        assert forbidden not in source

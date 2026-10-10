"""Focused tests for the Task 183 final release-gate projection."""

from __future__ import annotations

import copy
import inspect

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
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
from rop.services.reasoning_run_stage_7_final_release_gate_projection import (
    ReasoningRunStage7FinalReleaseGateProjectionService,
)

_SERVICE = ReasoningRunStage7FinalReleaseGateProjectionService
_PROJECTION_SOURCE = REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
_SESSION_ID = "session-183"


def _attestation(status: str = "CERTIFIED"):
    unavailable = status == "UNAVAILABLE"
    blocked = status == "BLOCKED"
    bundle_status = {
        "CERTIFIED": "READY",
        "BLOCKED": "BLOCKED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[status]
    audit_status = "UNAVAILABLE" if unavailable else "CONSISTENT"
    consistency_status = "UNAVAILABLE" if unavailable else "CONSISTENT"
    findings = (
        ["ATTESTATION_UNAVAILABLE"]
        if unavailable
        else (["BLOCKING_EVIDENCE"] if blocked else [])
    )
    return ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
        session_id=_SESSION_ID,
        attestation_status=status,
        certified=status == "CERTIFIED",
        blocked=blocked,
        available=not unavailable,
        bundle_status=bundle_status,
        bundle_audit_status=audit_status,
        bundle_audit_consistency_status=consistency_status,
        finding_count=len(findings),
        findings=findings,
        attestation_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
        ),
    )


def _audit(
    status: str = "CERTIFIED",
    verdict: str = "CONSISTENT",
    session_id: str = _SESSION_ID,
):
    findings = (
        ["AUDIT_CONTRADICTION"]
        if verdict == "INCONSISTENT"
        else (["AUDIT_UNAVAILABLE"] if verdict == "UNAVAILABLE" else [])
    )
    return ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
        session_id=session_id,
        attestation_audit_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_attestation_status=status,
        expected_attestation_status=status,
        finding_count=len(findings),
        findings=findings,
        audit_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
        ),
    )


def _consistency(
    status: str = "CERTIFIED",
    verdict: str = "CONSISTENT",
    session_id: str = _SESSION_ID,
):
    findings = (
        ["CONSISTENCY_CONTRADICTION"]
        if verdict == "INCONSISTENT"
        else (["CONSISTENCY_UNAVAILABLE"] if verdict == "UNAVAILABLE" else [])
    )
    return ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead(
        session_id="" if verdict == "UNAVAILABLE" else session_id,
        attestation_consistency_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_attestation_status=status,
        expected_attestation_status=status,
        finding_count=len(findings),
        findings=findings,
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182
        ),
    )


def _chain(status: str = "CERTIFIED", audit_verdict: str = "CONSISTENT"):
    return (
        _attestation(status),
        _audit(status, audit_verdict),
        _consistency(status, audit_verdict),
    )


def _project(attestation=None, audit=None, consistency=None):
    return _SERVICE.project(
        attestation=attestation or _attestation(),
        audit=audit or _audit(),
        consistency=consistency or _consistency(),
    )


def test_schema_forbids_extra_fields_and_requires_canonical_source() -> None:
    payload = {
        "session_id": _SESSION_ID,
        "gate_status": "READY",
        "attestation_status": "CERTIFIED",
        "attestation_audit_status": "CONSISTENT",
        "consistency_status": "CONSISTENT",
        "finding_count": 0,
        "findings": [],
        "projection_source": _PROJECTION_SOURCE,
    }
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalReleaseGateProjectionRead(
            **payload, extra_field="not allowed"
        )
    payload["projection_source"] = "FORGED"
    with pytest.raises(ValidationError, match="canonical Task 183 source"):
        ReasoningRunStage7FinalReleaseGateProjectionRead(**payload)


def test_schema_enforces_status_and_finding_coherence() -> None:
    payload = {
        "session_id": _SESSION_ID,
        "gate_status": "READY",
        "attestation_status": "CERTIFIED",
        "attestation_audit_status": "CONSISTENT",
        "consistency_status": "CONSISTENT",
        "finding_count": 0,
        "findings": [],
        "projection_source": _PROJECTION_SOURCE,
    }
    invalid = dict(payload, gate_status="UNAVAILABLE")
    with pytest.raises(ValidationError, match="UNAVAILABLE requires"):
        ReasoningRunStage7FinalReleaseGateProjectionRead(**invalid)
    invalid = dict(payload, gate_status="BLOCKED")
    with pytest.raises(ValidationError, match="BLOCKED requires"):
        ReasoningRunStage7FinalReleaseGateProjectionRead(**invalid)
    invalid = dict(payload, findings=["Z", "A"], finding_count=2)
    with pytest.raises(ValidationError, match="findings must be sorted"):
        ReasoningRunStage7FinalReleaseGateProjectionRead(**invalid)


def test_certified_chain_projects_ready() -> None:
    result = _project()
    assert result == {
        "session_id": _SESSION_ID,
        "gate_status": "READY",
        "attestation_status": "CERTIFIED",
        "attestation_audit_status": "CONSISTENT",
        "consistency_status": "CONSISTENT",
        "finding_count": 0,
        "findings": [],
        "projection_source": _PROJECTION_SOURCE,
    }


@pytest.mark.parametrize(
    ("attestation_status", "audit_verdict", "consistency_verdict"),
    [
        ("BLOCKED", "CONSISTENT", "CONSISTENT"),
        ("CERTIFIED", "INCONSISTENT", "INCONSISTENT"),
        ("CERTIFIED", "CONSISTENT", "INCONSISTENT"),
    ],
)
def test_readable_blocking_evidence_projects_blocked(
    attestation_status: str, audit_verdict: str, consistency_verdict: str
) -> None:
    result = _SERVICE.project(
        attestation=_attestation(attestation_status),
        audit=_audit(attestation_status, audit_verdict),
        consistency=_consistency(attestation_status, consistency_verdict),
    )
    assert result["gate_status"] == "BLOCKED"


def test_unavailable_evidence_projects_unavailable() -> None:
    result = _SERVICE.project(
        attestation=_attestation("UNAVAILABLE"),
        audit=_audit("UNAVAILABLE", "UNAVAILABLE"),
        consistency=_consistency("UNAVAILABLE", "UNAVAILABLE"),
    )
    assert result["gate_status"] == "UNAVAILABLE"
    assert result["finding_count"] > 0
    assert result["findings"] == sorted(set(result["findings"]))


def test_detects_session_mismatch() -> None:
    attestation = _attestation()
    audit = _audit(session_id="detached")
    consistency = _consistency()
    result = _SERVICE.project(
        attestation=attestation, audit=audit, consistency=consistency
    )
    assert result["gate_status"] == "UNAVAILABLE"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]


def test_revalidation_rejects_mutated_input_sources() -> None:
    attestation = _attestation()
    attestation.attestation_source = "FORGED_SOURCE"
    audit = _audit()
    audit.audit_source = "FORGED_SOURCE"
    result = _SERVICE.project(
        attestation=attestation, audit=audit, consistency=_consistency()
    )
    assert result["gate_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_revalidation_rejects_mutated_task_182_source() -> None:
    consistency = _consistency()
    consistency.consistency_source = "FORGED_SOURCE"
    result = _SERVICE.project(
        attestation=_attestation(), audit=_audit(), consistency=consistency
    )
    assert result["gate_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_wrong_types_and_mutated_models_are_unavailable() -> None:
    result = _SERVICE.project(
        attestation=None,  # type: ignore[arg-type]
        audit=_audit(),
        consistency=_consistency(),
    )
    assert result["gate_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]

    attestation = _attestation()
    attestation.finding_count = 7
    result = _SERVICE.project(
        attestation=attestation, audit=_audit(), consistency=_consistency()
    )
    assert result["gate_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_inputs_are_immutable_and_projection_is_deterministic() -> None:
    inputs = _chain()
    before = copy.deepcopy([model.model_dump() for model in inputs])
    first = _SERVICE.project(
        attestation=inputs[0], audit=inputs[1], consistency=inputs[2]
    )
    second = _SERVICE.project(
        attestation=inputs[0], audit=inputs[1], consistency=inputs[2]
    )
    assert first == second
    assert [model.model_dump() for model in inputs] == before


def test_service_has_no_upstream_or_io_behavior() -> None:
    import rop.services.reasoning_run_stage_7_final_release_gate_projection as module

    source = inspect.getsource(module).lower()
    for forbidden in (
        "rop.services",
        "sqlite",
        "postgres",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "import os",
        "openai",
        "ollama",
    ):
        assert forbidden not in source, forbidden

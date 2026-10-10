"""Focused tests for the Task 184 independent final release-gate audit."""

from __future__ import annotations

import copy
import inspect

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
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
from rop.services.reasoning_run_stage_7_final_release_gate_audit import (
    ReasoningRunStage7FinalReleaseGateAuditService,
)

_SERVICE = ReasoningRunStage7FinalReleaseGateAuditService
_SESSION = "session-184"


def _attestation(status: str = "CERTIFIED"):
    blocked = status == "BLOCKED"
    unavailable = status == "UNAVAILABLE"
    findings = (
        ["BLOCKING_EVIDENCE"]
        if blocked
        else (["ATTESTATION_UNAVAILABLE"] if unavailable else [])
    )
    return ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
        session_id=_SESSION,
        attestation_status=status,
        certified=status == "CERTIFIED",
        blocked=blocked,
        available=not unavailable,
        bundle_status={
            "CERTIFIED": "READY",
            "BLOCKED": "BLOCKED",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        bundle_audit_status="UNAVAILABLE" if unavailable else "CONSISTENT",
        bundle_audit_consistency_status="UNAVAILABLE" if unavailable else "CONSISTENT",
        finding_count=len(findings),
        findings=findings,
        attestation_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
        ),
    )


def _audit(status: str = "CERTIFIED", verdict: str = "CONSISTENT"):
    published = status if status in {"CERTIFIED", "BLOCKED", "UNAVAILABLE"} else None
    findings = (
        ["AUDIT_CONTRADICTION"]
        if verdict == "INCONSISTENT"
        else (["AUDIT_UNAVAILABLE"] if verdict == "UNAVAILABLE" else [])
    )
    if published is None:
        findings.append("ATTESTATION_INVALID")
    return ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
        session_id="" if verdict == "UNAVAILABLE" else _SESSION,
        attestation_audit_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_attestation_status=published,
        expected_attestation_status=status,
        finding_count=len(findings),
        findings=sorted(findings),
        audit_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
        ),
    )


def _consistency(status: str = "CERTIFIED", verdict: str = "CONSISTENT"):
    published = status if status in {"CERTIFIED", "BLOCKED", "UNAVAILABLE"} else None
    findings = (
        ["CONSISTENCY_CONTRADICTION"]
        if verdict == "INCONSISTENT"
        else (["CONSISTENCY_UNAVAILABLE"] if verdict == "UNAVAILABLE" else [])
    )
    if published is None:
        findings.append("ATTESTATION_INVALID")
    return ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead(
        session_id="" if verdict == "UNAVAILABLE" else _SESSION,
        attestation_consistency_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_attestation_status=published,
        expected_attestation_status=status,
        finding_count=len(findings),
        findings=sorted(findings),
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182
        ),
    )


def _projection(
    gate: str = "READY",
    attestation_status: str = "CERTIFIED",
    audit_status: str = "CONSISTENT",
    consistency_status: str = "CONSISTENT",
):
    findings = []
    if gate == "BLOCKED":
        findings = ["BLOCKING_EVIDENCE"]
    elif gate == "UNAVAILABLE":
        findings = ["GATE_EVIDENCE_UNAVAILABLE"]
    return ReasoningRunStage7FinalReleaseGateProjectionRead(
        session_id=_SESSION,
        gate_status=gate,
        attestation_status=attestation_status,
        attestation_audit_status=audit_status,
        consistency_status=consistency_status,
        finding_count=len(findings),
        findings=findings,
        projection_source=(
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
        ),
    )


def _audit_gate(
    projection=None, attestation=None, audit=None, consistency=None
) -> dict[str, object]:
    return _SERVICE.audit(
        attestation=attestation or _attestation(),
        audit=audit or _audit(),
        consistency=consistency or _consistency(),
        projection=projection or _projection(),
    )


def test_strict_audit_schema_enforces_source_and_coherence() -> None:
    payload = {
        "session_id": _SESSION,
        "gate_audit_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "published_gate_status": "READY",
        "expected_gate_status": "READY",
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    }
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalReleaseGateAuditRead(**payload, extra_field=True)
    invalid = dict(payload, audit_source="FORGED")
    with pytest.raises(ValidationError, match="canonical Task 184 source"):
        ReasoningRunStage7FinalReleaseGateAuditRead(**invalid)
    invalid = dict(
        payload,
        gate_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        session_id="",
    )
    with pytest.raises(ValidationError, match="UNAVAILABLE requires"):
        ReasoningRunStage7FinalReleaseGateAuditRead(**invalid)
    invalid = dict(payload, findings=["Z", "A"], finding_count=2)
    with pytest.raises(ValidationError, match="findings must be sorted"):
        ReasoningRunStage7FinalReleaseGateAuditRead(**invalid)
    invalid = dict(
        payload,
        session_id=_SESSION,
        gate_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_gate_status=None,
        findings=["PROJECTION_INVALID"],
        finding_count=1,
    )
    with pytest.raises(ValidationError, match="must not claim a session"):
        ReasoningRunStage7FinalReleaseGateAuditRead(**invalid)


def test_certified_chain_independently_audits_ready_projection() -> None:
    result = _audit_gate()
    assert result == {
        "session_id": _SESSION,
        "gate_audit_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "published_gate_status": "READY",
        "expected_gate_status": "READY",
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    }


def test_readable_blocking_evidence_can_be_consistently_projected() -> None:
    blocked_attestation = _attestation("BLOCKED")
    blocked_audit = _audit("BLOCKED")
    blocked_consistency = _consistency("BLOCKED")
    result = _audit_gate(
        projection=_projection("BLOCKED", "BLOCKED", "CONSISTENT", "CONSISTENT"),
        attestation=blocked_attestation,
        audit=blocked_audit,
        consistency=blocked_consistency,
    )
    assert result["gate_audit_status"] == "CONSISTENT"
    assert result["expected_gate_status"] == "BLOCKED"


@pytest.mark.parametrize(
    ("audit_verdict", "consistency_verdict"),
    [("INCONSISTENT", "CONSISTENT"), ("CONSISTENT", "INCONSISTENT")],
)
def test_upstream_contradiction_proves_blocked_gate(
    audit_verdict: str, consistency_verdict: str
) -> None:
    result = _audit_gate(
        projection=_projection(
            "BLOCKED", "CERTIFIED", audit_verdict, consistency_verdict
        ),
        attestation=_attestation(),
        audit=_audit("CERTIFIED", audit_verdict),
        consistency=_consistency("CERTIFIED", consistency_verdict),
    )
    assert result["gate_audit_status"] == "CONSISTENT"
    assert result["expected_gate_status"] == "BLOCKED"


def test_detects_projection_status_echo_and_session_contradictions() -> None:
    payload = _projection().model_dump()
    payload.update(
        gate_status="BLOCKED",
        attestation_status="BLOCKED",
        session_id="detached",
        finding_count=1,
        findings=["CLAIMED_BLOCK"],
    )
    result = _audit_gate(projection=payload)
    assert result["gate_audit_status"] == "INCONSISTENT"
    assert result["expected_gate_status"] == "READY"
    assert {
        "GATE_STATUS_MISMATCH",
        "UPSTREAM_STATUS_MISMATCH",
        "SESSION_BINDING_MISMATCH",
    }.issubset(result["findings"])


def test_upstream_unavailable_is_not_fabricated_as_contradiction() -> None:
    attestation = _attestation("UNAVAILABLE")
    audit = _audit("UNAVAILABLE", "UNAVAILABLE")
    consistency = _consistency("UNAVAILABLE", "UNAVAILABLE")
    projection = _projection("UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE")
    result = _audit_gate(
        projection=projection,
        attestation=attestation,
        audit=audit,
        consistency=consistency,
    )
    assert result["gate_audit_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert "AUDIT_UNAVAILABLE" in result["findings"]
    assert "CONSISTENCY_UNAVAILABLE" in result["findings"]


def test_unknown_projection_status_is_not_reported_as_unavailable_claim() -> None:
    payload = _projection().model_dump()
    payload["gate_status"] = "UNKNOWN"
    result = _audit_gate(projection=payload)
    assert result["gate_audit_status"] == "UNAVAILABLE"
    assert result["published_gate_status"] is None
    assert result["session_id"] == ""
    assert "PROJECTION_INVALID" in result["findings"]


def test_revalidates_mutated_records_and_preserves_semantic_source_conflict() -> None:
    attestation = _attestation()
    attestation.attestation_source = "FORGED"
    result = _audit_gate(attestation=attestation)
    assert result["gate_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_SOURCE_INVALID" in result["findings"]

    attestation = _attestation()
    attestation.finding_count = 4
    result = _audit_gate(attestation=attestation)
    assert result["gate_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_INVARIANT_INVALID" in result["findings"]


def test_invalid_field_level_upstream_input_is_unavailable() -> None:
    attestation = _attestation()
    attestation.attestation_status = "UNKNOWN"
    result = _audit_gate(attestation=attestation)
    assert result["gate_audit_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]
    assert result["published_gate_status"] == "READY"


def test_inputs_are_immutable_and_result_is_deterministic() -> None:
    inputs = (_attestation(), _audit(), _consistency(), _projection())
    before = copy.deepcopy([model.model_dump() for model in inputs])
    first = _audit_gate(
        projection=inputs[3],
        attestation=inputs[0],
        audit=inputs[1],
        consistency=inputs[2],
    )
    second = _audit_gate(
        projection=inputs[3],
        attestation=inputs[0],
        audit=inputs[1],
        consistency=inputs[2],
    )
    assert first == second
    assert [model.model_dump() for model in inputs] == before
    assert first["findings"] == sorted(set(first["findings"]))


def test_service_has_no_upstream_service_or_io_behavior() -> None:
    import rop.services.reasoning_run_stage_7_final_release_gate_audit as module

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

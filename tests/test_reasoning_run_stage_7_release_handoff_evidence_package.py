"""Focused tests for Task 186 release-handoff evidence packaging."""

from __future__ import annotations

import copy
import inspect

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185,
    ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package import (
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186,
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageService,
)

_SERVICE = ReasoningRunStage7ReleaseHandoffEvidencePackageService
_SESSION = "handoff-session-186"
_CHILD_PREFIX = {"projection": "183", "audit": "184", "consistency": "185"}


def _projection(status: str = "READY"):
    findings = ["GATE_BLOCKED"] if status == "BLOCKED" else []
    if status == "UNAVAILABLE":
        findings = ["GATE_UNAVAILABLE"]
    return ReasoningRunStage7FinalReleaseGateProjectionRead(
        session_id=_SESSION,
        gate_status=status,
        attestation_status={
            "READY": "CERTIFIED",
            "BLOCKED": "BLOCKED",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        attestation_audit_status={
            "READY": "CONSISTENT",
            "BLOCKED": "INCONSISTENT",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        consistency_status=("UNAVAILABLE" if status == "UNAVAILABLE" else "CONSISTENT"),
        finding_count=len(findings),
        findings=findings,
        projection_source=(
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
        ),
    )


def _audit(
    status: str = "READY",
    verdict: str = "CONSISTENT",
    *,
    session_id: str | None = None,
):
    findings = [] if verdict == "CONSISTENT" else [f"AUDIT_{verdict}"]
    return ReasoningRunStage7FinalReleaseGateAuditRead(
        session_id=(
            session_id
            if session_id is not None
            else ("" if verdict == "UNAVAILABLE" else _SESSION)
        ),
        gate_audit_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_gate_status=status,
        expected_gate_status=status,
        finding_count=len(findings),
        findings=findings,
        audit_source=REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    )


def _consistency(status: str = "READY", verdict: str = "CONSISTENT"):
    findings = [] if verdict == "CONSISTENT" else [f"CONSISTENCY_{verdict}"]
    return ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(
        session_id="" if verdict == "UNAVAILABLE" else _SESSION,
        gate_consistency_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_gate_status=status,
        expected_gate_status=status,
        finding_count=len(findings),
        findings=findings,
        consistency_source=(
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
        ),
    )


def _inputs():
    return {
        "projection": _projection(),
        "audit": _audit(),
        "consistency": _consistency(),
    }


def test_ready_chain_assembles_verbatim_and_deterministically():
    inputs = _inputs()
    first = _SERVICE.assemble(**inputs)
    second = _SERVICE.assemble(**inputs)
    assert first == second
    assert first["package_status"] == "READY"
    assert first["session_id"] == _SESSION
    assert first["finding_count"] == 0
    assert first["findings"] == []
    assert first["package_source"] == (
        REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186
    )
    assert first["t183_projection_source"] == (
        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
    )
    assert first["t183_attestation_status"] == "CERTIFIED"
    assert first["t183_attestation_audit_status"] == "CONSISTENT"
    assert first["t183_consistency_status"] == "CONSISTENT"
    assert first["t184_audit_source"] == (
        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184
    )
    assert first["t185_consistency_source"] == (
        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
    )
    assert (
        first["t183_findings"] == first["t184_findings"] == first["t185_findings"] == []
    )


def test_explicit_readable_blocking_evidence_yields_blocked_package():
    inputs = _inputs()
    inputs["projection"] = _projection("BLOCKED")
    inputs["audit"] = _audit("BLOCKED")
    inputs["consistency"] = _consistency("BLOCKED")
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "BLOCKED"
    assert result["t183_gate_status"] == "BLOCKED"
    assert result["t183_attestation_status"] == "BLOCKED"
    assert result["t183_attestation_audit_status"] == "INCONSISTENT"
    assert result["t183_consistency_status"] == "CONSISTENT"
    assert "GATE_BLOCKED" in result["t183_findings"]
    assert "EXPLICIT_BLOCKING_GATE_EVIDENCE" in result["findings"]


def test_unavailable_audit_is_preserved_and_makes_package_unavailable():
    inputs = _inputs()
    inputs["audit"] = _audit("READY", "UNAVAILABLE")
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result["t184_gate_audit_status"] == "UNAVAILABLE"
    assert result["t184_session_id"] == ""
    assert result["t184_findings"] == ["AUDIT_UNAVAILABLE"]
    assert "T184_AUDIT_UNAVAILABLE" in result["findings"]
    assert result["t184_valid"] is True


def test_valid_unavailable_projection_and_audit_remain_unavailable():
    inputs = {
        "projection": _projection("UNAVAILABLE"),
        "audit": _audit("UNAVAILABLE", "UNAVAILABLE"),
        "consistency": _consistency("UNAVAILABLE", "UNAVAILABLE"),
    }
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result["t183_valid"] is True
    assert result["t183_gate_status"] == "UNAVAILABLE"
    assert result["t183_attestation_status"] == "UNAVAILABLE"
    assert result["t184_valid"] is True
    assert result["t184_gate_audit_status"] == "UNAVAILABLE"
    assert result["t185_valid"] is True
    assert result["t185_gate_consistency_status"] == "UNAVAILABLE"


@pytest.mark.parametrize("child", ["projection", "audit", "consistency"])
def test_wrong_child_type_is_unavailable(child):
    inputs = _inputs()
    inputs[child] = object()
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result[f"t{_CHILD_PREFIX[child]}_valid"] is False


@pytest.mark.parametrize(
    ("child", "field", "value"),
    [
        ("projection", "gate_status", "FORGED"),
        ("audit", "expected_gate_status", "FORGED"),
        ("consistency", "consistent", "true"),
    ],
)
def test_malformed_post_construction_mutation_is_unavailable(child, field, value):
    inputs = _inputs()
    setattr(inputs[child], field, value)
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result[f"t{_CHILD_PREFIX[child]}_valid"] is False


@pytest.mark.parametrize(
    ("child", "field", "value"),
    [
        ("projection", "finding_count", 1),
        ("audit", "available", False),
        ("consistency", "finding_count", 3),
    ],
)
def test_semantic_mutation_is_revalidated_and_cannot_be_ready(child, field, value):
    inputs = _inputs()
    setattr(inputs[child], field, value)
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result[f"t{_CHILD_PREFIX[child]}_valid"] is False
    assert f"T{_CHILD_PREFIX[child]}_EVIDENCE_INVALID" in result["findings"]


def test_invalid_blocked_projection_is_unavailable_without_other_blocking_evidence():
    inputs = _inputs()
    inputs["projection"] = _projection("BLOCKED")
    inputs["projection"].finding_count = 0
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result["t183_valid"] is False
    assert "EXPLICIT_BLOCKING_GATE_EVIDENCE" not in result["findings"]


def test_noncanonical_sources_and_unbound_statuses_cannot_be_ready():
    inputs = _inputs()
    inputs["audit"].audit_source = "FORGED"
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result["t184_audit_source"] == "FORGED"
    assert "CHILD_SOURCE_MISMATCH" in result["findings"]

    inputs = _inputs()
    inputs["consistency"].session_id = "other-session"
    result = _SERVICE.assemble(**inputs)
    assert result["package_status"] == "UNAVAILABLE"
    assert result["t185_session_id"] == "other-session"
    assert "CHILD_SESSION_MISMATCH" in result["findings"]


def test_inputs_are_not_mutated():
    inputs = _inputs()
    before = copy.deepcopy({name: value.model_dump() for name, value in inputs.items()})
    _SERVICE.assemble(**inputs)
    after = {name: value.model_dump() for name, value in inputs.items()}
    assert after == before


def test_package_schema_enforces_sources_counts_and_verdict():
    package = _SERVICE.assemble(**_inputs())
    assert ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(package)
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(
            {**package, "extra": True}
        )
    with pytest.raises(ValidationError, match="t184_finding_count"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(
            {**package, "t184_finding_count": 1}
        )
    with pytest.raises(ValidationError, match="canonical Task 186 source"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(
            {**package, "package_source": "FORGED"}
        )
    with pytest.raises(ValidationError, match="preserve the common child session"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(
            {**package, "session_id": ""}
        )


def test_service_does_not_import_or_call_upstream_services():
    source = inspect.getsource(_SERVICE)
    assert "reasoning_run_stage_7_final_release_gate_projection" not in source
    assert "reasoning_run_stage_7_final_release_gate_audit" not in source
    assert "reasoning_run_stage_7_final_release_gate_audit_consistency" not in source
    assert "provider" in source.lower()
    assert "database" in source.lower()
    assert "network" in source.lower()

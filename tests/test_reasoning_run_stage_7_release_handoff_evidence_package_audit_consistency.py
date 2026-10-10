"""Focused tests for Task 188 handoff-package audit consistency."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

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
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188,
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService,
)

_SERVICE = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService
_SESSION = "release-handoff-audit-session-188"
_SOURCE_188 = REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188  # noqa: E501


def _chain(status: str = "READY", session_id: str = _SESSION):
    if status == "READY":
        attestation, audit_status, consistency_status, findings = (
            "CERTIFIED",
            "CONSISTENT",
            "CONSISTENT",
            [],
        )
    elif status == "BLOCKED":
        attestation, audit_status, consistency_status, findings = (
            "BLOCKED",
            "CONSISTENT",
            "CONSISTENT",
            ["GATE_BLOCKED"],
        )
    else:
        attestation, audit_status, consistency_status, findings = (
            "UNAVAILABLE",
            "CONSISTENT",
            "CONSISTENT",
            ["GATE_UNAVAILABLE"],
        )
    projection = ReasoningRunStage7FinalReleaseGateProjectionRead(
        session_id=session_id,
        gate_status=status,
        attestation_status=attestation,
        attestation_audit_status=audit_status,
        consistency_status=consistency_status,
        finding_count=len(findings),
        findings=findings,
        projection_source=REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    )
    audit = ReasoningRunStage7FinalReleaseGateAuditRead(
        session_id=session_id,
        gate_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_gate_status=status,
        expected_gate_status=status,
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    )
    consistency = ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(
        session_id=session_id,
        gate_consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        published_gate_status=status,
        expected_gate_status=status,
        finding_count=0,
        findings=[],
        consistency_source=REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185,
    )
    return projection, audit, consistency


def _pair(status: str = "READY"):
    children = _chain(status)
    package = ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
        projection=children[0], audit=children[1], consistency=children[2]
    )
    if package["package_status"] == "UNAVAILABLE":
        audit_result = {
            "session_id": package["session_id"],
            "package_audit_status": "CONSISTENT",
            "available": True,
            "consistent": True,
            "published_package_status": "UNAVAILABLE",
            "expected_package_status": "UNAVAILABLE",
            "finding_count": 0,
            "findings": [],
            "audit_source": REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,  # noqa: E501
        }
    else:
        audit_result = (
            ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
                projection=children[0],
                audit=children[1],
                consistency=children[2],
                package=package,
            )
        )
    return (
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(package),
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead.model_validate(
            audit_result
        ),
    )


def _result(package, audit):
    return _SERVICE.verify(package=package, audit=audit)


def test_schema_is_strict_and_enforces_projection_invariants():
    payload = {
        "session_id": _SESSION,
        "consistency_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "finding_count": 0,
        "findings": [],
        "consistency_source": _SOURCE_188,
    }
    assert ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead(
        **payload
    )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead(
            **payload, extra_field=True
        )
    with pytest.raises(ValidationError, match="canonical Task 188 source"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead(
            **{**payload, "consistency_source": "FORGED"}
        )
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead(
            **{**payload, "available": False}
        )
    with pytest.raises(ValidationError, match="findings must be sorted"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead(
            **{
                **payload,
                "consistency_status": "INCONSISTENT",
                "consistent": False,
                "finding_count": 2,
                "findings": ["Z", "A"],
            }
        )


@pytest.mark.parametrize("package_status", ["READY", "BLOCKED", "UNAVAILABLE"])
def test_successful_audit_is_bound_for_each_package_status(package_status: str):
    package, audit = _pair(package_status)
    assert package.package_status == package_status
    result = _result(package, audit)
    assert result == {
        "session_id": _SESSION,
        "consistency_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "finding_count": 0,
        "findings": [],
        "consistency_source": _SOURCE_188,
    }


def test_unavailable_audit_is_distinct_from_successful_audit_of_unavailable_package():
    package, _ = _pair("UNAVAILABLE")
    audit = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
        session_id="",
        package_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_package_status=None,
        expected_package_status="UNAVAILABLE",
        finding_count=1,
        findings=["PACKAGE_INVALID"],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,
    )
    result = _result(package, audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["AUDIT_UNAVAILABLE"]


def test_status_contradiction_is_not_hidden_by_unavailable_session_binding():
    package, _ = _pair("UNAVAILABLE")
    audit = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
        session_id="",
        package_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_package_status="UNAVAILABLE",
        expected_package_status="BLOCKED",
        finding_count=1,
        findings=["PACKAGE_STATUS_MISMATCH"],
        audit_source=(
            REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187
        ),
    )
    result = _result(package, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["session_id"] == ""
    assert "EXPECTED_STATUS_CONTRADICTION" in result["findings"]
    assert "SESSION_BINDING_UNAVAILABLE" in result["findings"]
    assert result["session_id"] == ""


def test_contract_valid_status_contradictions_are_inconsistent():
    package, _ = _pair("READY")
    audit = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
        session_id=_SESSION,
        package_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_package_status="READY",
        expected_package_status="BLOCKED",
        finding_count=1,
        findings=["STATUS_MISMATCH"],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,
    )
    result = _result(package, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["consistent"] is False
    assert result["findings"] == sorted(set(result["findings"]))
    assert "EXPECTED_STATUS_CONTRADICTION" in result["findings"]
    assert "AUDIT_STATUS_NOT_CONSISTENT" in result["findings"]


def test_source_and_session_mismatches_are_reported_deterministically():
    package, audit = _pair()
    package.package_source = "FORGED_PACKAGE_SOURCE"
    audit.audit_source = "FORGED_AUDIT_SOURCE"
    audit.session_id = "another-session"
    result = _result(package, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PACKAGE_SOURCE_MISMATCH" in result["findings"]
    assert "AUDIT_SOURCE_MISMATCH" in result["findings"]
    assert "SESSION_MISMATCH" in result["findings"]
    assert "PACKAGE_CONTRACT_INVALID" in result["findings"]
    assert "AUDIT_CONTRACT_INVALID" in result["findings"]
    assert result["findings"] == sorted(set(result["findings"]))


def test_mutated_forged_status_is_inconsistent_and_input_is_not_mutated():
    package, audit = _pair()
    package.package_status = "BLOCKED"
    before_package = copy.deepcopy(package.__dict__)
    before_audit = copy.deepcopy(audit.__dict__)
    result = _result(package, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]
    assert "PACKAGE_CONTRACT_INVALID" in result["findings"]
    assert package.__dict__ == before_package
    assert audit.__dict__ == before_audit


def test_malformed_evidence_and_wrong_types_are_unavailable():
    package, audit = _pair()
    package.findings = [42]
    result = _result(package, audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert "PACKAGE_UNREADABLE" in result["findings"]
    assert _result(package, object())["consistency_status"] == "UNAVAILABLE"
    assert _result({}, audit)["consistency_status"] == "UNAVAILABLE"


def test_mutated_count_is_readable_but_contract_invalid():
    package, audit = _pair()
    audit.finding_count = 3
    result = _result(package, audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert "FINDING_COUNT_MISMATCH" in result["findings"]
    assert "AUDIT_CONTRACT_INVALID" in result["findings"]


def test_forged_audit_flags_are_inconsistent():
    package, audit = _pair()
    audit.available = False
    result = _result(package, audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert "AUDIT_CONTRACT_INVALID" in result["findings"]


def test_missing_session_binding_is_unavailable():
    package, audit = _pair()
    package.session_id = ""
    result = _result(package, audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert set(result["findings"]) == {
        "PACKAGE_CONTRACT_INVALID",
        "SESSION_BINDING_UNAVAILABLE",
    }


def test_verification_is_deterministic():
    package, audit = _pair("BLOCKED")
    first = _result(package, audit)
    second = _result(package, audit)
    assert first == second
    assert first["finding_count"] == len(first["findings"])
    assert first["findings"] == sorted(set(first["findings"]))


def test_service_is_independent_of_task_186_and_187_services_and_io():
    source_path = (
        Path(__file__).parents[1]
        / "src"
        / "rop"
        / "services"
        / "reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(
        module.startswith("rop.services.")
        and module.endswith(
            (
                "reasoning_run_stage_7_release_handoff_evidence_package",
                "reasoning_run_stage_7_release_handoff_evidence_package_audit",
            )
        )
        for module in imported_modules
    )
    assert not any(
        module.startswith(
            ("sqlalchemy", "httpx", "requests", "rop.providers", "rop.repositories")
        )
        for module in imported_modules
    )

"""Focused tests for Task 187's independent handoff-package audit."""

from __future__ import annotations

import ast
import copy
import inspect
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
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService,
)

_SERVICE = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService
_ASSEMBLER = ReasoningRunStage7ReleaseHandoffEvidencePackageService
_SESSION = "handoff-audit-session-187"


def _projection(status: str = "READY", session_id: str = _SESSION):
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
            "INCONSISTENT",
            "CONSISTENT",
            ["GATE_BLOCKED"],
        )
    else:
        attestation, audit_status, consistency_status, findings = (
            "UNAVAILABLE",
            "UNAVAILABLE",
            "UNAVAILABLE",
            ["GATE_UNAVAILABLE"],
        )
    return ReasoningRunStage7FinalReleaseGateProjectionRead(
        session_id=session_id,
        gate_status=status,
        attestation_status=attestation,
        attestation_audit_status=audit_status,
        consistency_status=consistency_status,
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
    published: str | None = None,
    expected: str | None = None,
):
    findings = [] if verdict == "CONSISTENT" else [f"AUDIT_{verdict}"]
    if published is None:
        published = status
    if expected is None:
        expected = status
    if published != expected and verdict != "UNAVAILABLE":
        findings.append("STATUS_MISMATCH")
    return ReasoningRunStage7FinalReleaseGateAuditRead(
        session_id=(
            ""
            if verdict == "UNAVAILABLE"
            else (session_id if session_id is not None else _SESSION)
        ),
        gate_audit_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_gate_status=published,
        expected_gate_status=expected,
        finding_count=len(findings),
        findings=sorted(findings),
        audit_source=REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    )


def _consistency(
    status: str = "READY",
    verdict: str = "CONSISTENT",
    *,
    session_id: str | None = None,
    published: str | None = None,
    expected: str | None = None,
):
    findings = [] if verdict == "CONSISTENT" else [f"CONSISTENCY_{verdict}"]
    if published is None:
        published = status
    if expected is None:
        expected = status
    if published != expected and verdict != "UNAVAILABLE":
        findings.append("STATUS_MISMATCH")
    return ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(
        session_id=(
            ""
            if verdict == "UNAVAILABLE"
            else (session_id if session_id is not None else _SESSION)
        ),
        gate_consistency_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_gate_status=published,
        expected_gate_status=expected,
        finding_count=len(findings),
        findings=sorted(findings),
        consistency_source=(
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
        ),
    )


def _evidence(
    status: str = "READY",
    *,
    audit: ReasoningRunStage7FinalReleaseGateAuditRead | None = None,
    consistency: ReasoningRunStage7FinalReleaseGateAuditConsistencyRead | None = None,
    projection_session: str = _SESSION,
):
    return {
        "projection": _projection(status, projection_session),
        "audit": audit or _audit(status),
        "consistency": consistency or _consistency(status),
    }


def _package(evidence: dict[str, object]):
    """Compose Task 186 externally, as a caller of the independent audit would."""
    return _ASSEMBLER.assemble(
        projection=evidence["projection"],
        audit=evidence["audit"],
        consistency=evidence["consistency"],
    )


def _audit_package(evidence: dict[str, object], package: object):
    return _SERVICE.audit(**evidence, package=package)


def test_schema_is_strict_and_enforces_verdict_findings_and_source():
    payload = {
        "session_id": _SESSION,
        "package_audit_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "published_package_status": "READY",
        "expected_package_status": "READY",
        "finding_count": 0,
        "findings": [],
        "audit_source": (
            REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187
        ),
    }
    assert ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(**payload)
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
            **payload, unexpected=True
        )
    with pytest.raises(ValidationError, match="canonical Task 187 source"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
            **{**payload, "audit_source": "FORGED"}
        )
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
            **{**payload, "available": False}
        )
    with pytest.raises(ValidationError, match="findings must be sorted"):
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(
            **{**payload, "finding_count": 2, "findings": ["Z", "A"]}
        )


@pytest.mark.parametrize("status", ["READY", "BLOCKED"])
def test_exact_ready_or_blocked_package_is_consistent(status: str):
    evidence = _evidence(status)
    package = _package(evidence)
    result = _audit_package(evidence, package)
    expected = "READY" if status == "READY" else "BLOCKED"
    assert result["package_audit_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["published_package_status"] == expected
    assert result["expected_package_status"] == expected
    assert result["session_id"] == _SESSION
    assert result["finding_count"] == 0
    assert result["findings"] == []


def test_valid_unavailable_child_remains_unavailable_without_false_conflict():
    evidence = _evidence(
        audit=_audit("READY", "UNAVAILABLE"),
    )
    package = _package(evidence)
    result = _audit_package(evidence, package)
    assert package["package_status"] == "UNAVAILABLE"
    assert result["package_audit_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["published_package_status"] == "UNAVAILABLE"
    assert result["expected_package_status"] == "UNAVAILABLE"
    assert "SESSION_BINDING_MISMATCH" not in result["findings"]


def test_valid_unavailable_projection_is_not_promoted_to_ready():
    evidence = _evidence("UNAVAILABLE")
    package = _package(evidence)
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "UNAVAILABLE"
    assert result["expected_package_status"] == "UNAVAILABLE"
    assert result["published_package_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""


def test_separate_status_contradiction_is_not_hidden_by_unavailable_child():
    evidence = _evidence(
        audit=_audit(
            "READY",
            "UNAVAILABLE",
            published="READY",
            expected="BLOCKED",
        )
    )
    package = _package(evidence)
    result = _audit_package(evidence, package)
    assert package["package_status"] == "BLOCKED"
    assert result["package_audit_status"] == "INCONSISTENT"
    assert {
        "CHILD_STATUS_MISMATCH",
        "T184_AUDIT_UNAVAILABLE",
    }.issubset(result["findings"])


@pytest.mark.parametrize(
    ("evidence", "forged_status", "expected_status"),
    [
        (_evidence("BLOCKED"), "READY", "BLOCKED"),
        (_evidence("READY"), "BLOCKED", "READY"),
        (
            _evidence("READY"),
            "UNAVAILABLE",
            "READY",
        ),
    ],
)
def test_forged_package_status_is_inconsistent(
    evidence: dict[str, object], forged_status: str, expected_status: str
):
    package = _package(evidence)
    package["package_status"] = forged_status
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "INCONSISTENT"
    assert result["published_package_status"] == forged_status
    assert result["expected_package_status"] == expected_status
    assert "PACKAGE_STATUS_MISMATCH" in result["findings"]


@pytest.mark.parametrize(
    ("evidence", "finding"),
    [
        (
            _evidence(
                audit=_audit(
                    "READY", "INCONSISTENT", published="READY", expected="BLOCKED"
                )
            ),
            "CHILD_STATUS_MISMATCH",
        ),
        (
            _evidence(
                consistency=_consistency(
                    "READY", "INCONSISTENT", published="READY", expected="BLOCKED"
                )
            ),
            "CHILD_STATUS_MISMATCH",
        ),
    ],
)
def test_status_echo_mismatch_is_inconsistent(evidence, finding: str):
    result = _audit_package(evidence, _package(evidence))
    assert result["package_audit_status"] == "INCONSISTENT"
    assert finding in result["findings"]


def test_available_child_session_mismatch_is_inconsistent():
    evidence = _evidence(audit=_audit("READY", session_id="other-session"))
    result = _audit_package(evidence, _package(evidence))
    assert result["package_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]


@pytest.mark.parametrize(
    ("child", "field", "value"),
    [
        ("projection", "gate_status", "FORGED"),
        ("audit", "available", "true"),
        ("consistency", "finding_count", "0"),
    ],
)
def test_malformed_or_wrong_typed_child_evidence_is_unavailable(
    child: str, field: str, value: object
):
    evidence = _evidence()
    setattr(evidence[child], field, value)
    package = _package(evidence)
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "UNAVAILABLE"
    assert result["published_package_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]


@pytest.mark.parametrize("child", ["projection", "audit", "consistency"])
def test_wrong_child_object_type_is_unavailable(child: str):
    evidence = _evidence()
    evidence[child] = object()
    result = _audit_package(evidence, _package(evidence))
    assert result["package_audit_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]


def test_post_construction_package_mutation_is_detected():
    evidence = _evidence()
    package = _package(evidence)
    package["t183_attestation_status"] = "BLOCKED"
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "INCONSISTENT"
    assert "T183_EVIDENCE_MISMATCH" in result["findings"]


def test_child_findings_are_preserved_as_package_evidence():
    evidence = _evidence("BLOCKED")
    package = _package(evidence)
    assert package["t183_findings"] == ["GATE_BLOCKED"]
    package["t183_findings"] = []
    package["t183_finding_count"] = 0
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "INCONSISTENT"
    assert "T183_EVIDENCE_MISMATCH" in result["findings"]
    assert result["finding_count"] == len(result["findings"])
    assert result["findings"] == sorted(set(result["findings"]))


def test_post_construction_child_invariant_mutation_is_detected():
    evidence = _evidence()
    evidence["projection"].finding_count = 1
    result = _audit_package(evidence, _package(evidence))
    assert result["package_audit_status"] == "INCONSISTENT"
    assert "CHILD_INVARIANT_INVALID" in result["findings"]


def test_rejects_package_wrong_type_and_malformed_status():
    evidence = _evidence()
    wrong_type = _audit_package(evidence, object())
    assert wrong_type["package_audit_status"] == "UNAVAILABLE"
    assert wrong_type["published_package_status"] is None
    assert "PACKAGE_INVALID" in wrong_type["findings"]

    malformed = _package(evidence)
    malformed["package_status"] = "FORGED"
    malformed_result = _audit_package(evidence, malformed)
    assert malformed_result["package_audit_status"] == "UNAVAILABLE"
    assert malformed_result["published_package_status"] is None
    assert "PACKAGE_INVALID" in malformed_result["findings"]


def test_rejects_forged_canonical_sources_and_package_evidence_loss():
    evidence = _evidence()
    package = _package(evidence)
    package["package_source"] = "FORGED"
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "INCONSISTENT"
    assert "PACKAGE_SOURCE_INVALID" in result["findings"]

    package = _package(evidence)
    package["t183_projection_source"] = "FORGED"
    result = _audit_package(evidence, package)
    assert result["package_audit_status"] == "INCONSISTENT"
    assert "T183_EVIDENCE_MISMATCH" in result["findings"]


def test_audit_is_deterministic_and_does_not_mutate_any_input():
    evidence = _evidence()
    package = _package(evidence)
    before_evidence = {key: value.model_dump() for key, value in evidence.items()}
    before_package = copy.deepcopy(package)
    first = _audit_package(evidence, package)
    second = _audit_package(evidence, package)
    assert first == second
    assert {
        key: value.model_dump() for key, value in evidence.items()
    } == before_evidence
    assert package == before_package


def test_service_has_no_task_services_providers_or_io_dependencies():
    source = Path(inspect.getfile(_SERVICE)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    imports.extend(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert not any(".services." in imported for imported in imports)
    assert not any(
        token in source
        for token in (
            "open(",
            "Path(",
            "httpx",
            "requests.",
            "subprocess",
            "sqlalchemy",
        )
    )
    assert "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186" in (
        source
    )
    assert (
        "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187"
        in (source)
    )
    schema_source = Path(
        inspect.getfile(ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead)
    ).read_text(encoding="utf-8")
    assert 'extra="forbid"' in schema_source
    assert (
        "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186"
        in source
    )

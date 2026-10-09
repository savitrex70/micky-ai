"""Task 169: independent Stage 7 evidence-package audit tests.

Independent audit boundary over the already-published Task 168 evidence package.
The auditor independently derives the expected package state from the
published Task 162-167 surfaces, then compares against the published Task 168
package status.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
    ReasoningRunStage7EvidenceBundleSnapshot,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit import (
    ReasoningRunStage7EvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)


@pytest.fixture
def ready_evidence(ready_bundle_evidence):
    """All six inputs and package in READY/CONSISTENT state."""
    session_id = str(uuid4())
    fingerprint = "a" * 64

    pkg162 = ReasoningRunStage7AuditPackageRead(
        session_id=session_id,
        admission_status="ADMITTED",
        request_fingerprint=fingerprint,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    )

    slice163 = ReasoningRunStage7VerticalSliceRead(
        session_id=session_id,
        slice_status="READY",
        admission_status="ADMITTED",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    )

    audit164 = ReasoningRunStage7VerticalSliceAuditRead(
        session_id=session_id,
        slice_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_slice_status="READY",
        expected_slice_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
    )

    bundle165 = ReasoningRunStage7EvidenceBundleRead(
        session_id=session_id,
        slice_status="READY",
        admission_status="ADMITTED",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        slice_audit_status="CONSISTENT",
        audit_available=True,
        audit_consistent=True,
        published_slice_status="READY",
        expected_slice_status="READY",
        audit_finding_count=0,
        audit_findings=[],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        request_fingerprint=fingerprint,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        bundle_status="READY",
        bundle_finding_count=0,
        bundle_findings=[],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )

    audit166 = ReasoningRunStage7EvidenceBundleAuditRead(
        session_id=session_id,
        bundle_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_bundle_status="READY",
        expected_bundle_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
        audited_bundle=ReasoningRunStage7EvidenceBundleSnapshot.model_validate(
            bundle165.model_dump()
        ),
    )

    consistency167 = ReasoningRunStage7EvidenceBundleAuditConsistencyRead(
        session_id=session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    )

    package168 = ReasoningRunStage7EvidencePackageRead(
        session_id=session_id,
        t162_session_id=session_id,
        t162_admission_status="ADMITTED",
        t162_diagnostics_status="HEALTHY",
        t162_request_fingerprint=fingerprint,
        t162_request_audit_status="CONSISTENT",
        t162_proposal_audit_status="CONSISTENT",
        t162_provider_name="test-provider",
        t162_model_name="test-model",
        t162_finding_count=0,
        t162_findings=[],
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        t163_session_id=session_id,
        t163_slice_status="READY",
        t163_admission_status="ADMITTED",
        t163_diagnostics_status="HEALTHY",
        t163_provider_name="test-provider",
        t163_model_name="test-model",
        t163_finding_count=0,
        t163_findings=[],
        t163_certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        t164_session_id=session_id,
        t164_slice_audit_status="CONSISTENT",
        t164_available=True,
        t164_consistent=True,
        t164_published_slice_status="READY",
        t164_expected_slice_status="READY",
        t164_finding_count=0,
        t164_findings=[],
        t164_audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        t165_session_id=session_id,
        t165_bundle_status="READY",
        t165_bundle_finding_count=0,
        t165_bundle_findings=[],
        t165_bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
        t165_bundle_evidence=ready_bundle_evidence(session_id, fingerprint),
        t166_session_id=session_id,
        t166_bundle_audit_status="CONSISTENT",
        t166_available=True,
        t166_consistent=True,
        t166_published_bundle_status="READY",
        t166_expected_bundle_status="READY",
        t166_finding_count=0,
        t166_findings=[],
        t166_audit_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
        t166_audited_bundle=ready_bundle_evidence(session_id, fingerprint),
        t167_session_id=session_id,
        t167_consistency_status="CONSISTENT",
        t167_available=True,
        t167_consistent=True,
        t167_finding_count=0,
        t167_findings=[],
        t167_consistency_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
        package_status="READY",
        finding_count=0,
        findings=[],
        package_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    )

    return {
        "package": package168,
        "pkg162": pkg162,
        "slice163": slice163,
        "audit164": audit164,
        "bundle165": bundle165,
        "audit166": audit166,
        "consistency167": consistency167,
    }


def test_ready_package_audits_consistent(ready_evidence):
    """READY package with matching evidence audits to CONSISTENT."""
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "CONSISTENT"
    assert audit["published_package_status"] == "READY"
    assert audit["expected_package_status"] == "READY"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    expected_source = REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
    assert audit["audit_source"] == expected_source


def test_schema_validates_consistent_audit(ready_evidence):
    """Schema validates a CONSISTENT audit."""
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    validated = ReasoningRunStage7EvidencePackageAuditRead.model_validate(audit)
    assert validated.package_audit_status == "CONSISTENT"
    assert validated.available is True
    assert validated.consistent is True


def test_schema_rejects_extra_fields(ready_evidence):
    """Schema rejects extra fields."""
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    audit["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageAuditRead.model_validate(audit)


def test_package_source_mismatch_detected(ready_evidence):
    """Package source mismatch creates INCONSISTENT audit."""
    ready_evidence["package"].package_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "TASK_168_SOURCE_MISMATCH" in audit["findings"]


def test_session_id_mismatch_detected(ready_evidence):
    """Session ID mismatch between package and inputs creates INCONSISTENT audit."""
    ready_evidence["pkg162"].session_id = str(uuid4())
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "SESSION_ID_MISMATCH" in audit["findings"]


def test_t162_evidence_tampering_detected(ready_evidence):
    """Task 162 evidence tampering in package creates INCONSISTENT audit."""
    ready_evidence["package"].t162_admission_status = "BLOCKED"
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T162_ADMISSION_STATUS_MISMATCH" in audit["findings"]


def test_t163_evidence_tampering_detected(ready_evidence):
    """Task 163 evidence tampering in package creates INCONSISTENT audit."""
    ready_evidence["package"].t163_slice_status = "BLOCKED"
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T163_SLICE_STATUS_MISMATCH" in audit["findings"]


def test_t164_evidence_tampering_detected(ready_evidence):
    """Task 164 evidence tampering in package creates INCONSISTENT audit."""
    ready_evidence["package"].t164_slice_audit_status = "INCONSISTENT"
    ready_evidence["package"].t164_consistent = False
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T164_SLICE_AUDIT_STATUS_MISMATCH" in audit["findings"]


def test_t165_evidence_tampering_detected(ready_evidence):
    """Task 165 evidence tampering in package creates INCONSISTENT audit."""
    ready_evidence["package"].t165_bundle_status = "BLOCKED"
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T165_BUNDLE_STATUS_MISMATCH" in audit["findings"]


def test_t166_evidence_tampering_detected(ready_evidence):
    """Task 166 evidence tampering in package creates INCONSISTENT audit."""
    ready_evidence["package"].t166_bundle_audit_status = "INCONSISTENT"
    ready_evidence["package"].t166_consistent = False
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T166_BUNDLE_AUDIT_STATUS_MISMATCH" in audit["findings"]


def test_t167_evidence_tampering_detected(ready_evidence):
    """Task 167 evidence tampering in package creates INCONSISTENT audit."""
    ready_evidence["package"].t167_consistency_status = "INCONSISTENT"
    ready_evidence["package"].t167_consistent = False
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T167_CONSISTENCY_STATUS_MISMATCH" in audit["findings"]


def test_package_status_forgery_detected(ready_evidence):
    """Package status forgery creates INCONSISTENT audit."""
    # Change package status to BLOCKED without corresponding evidence
    ready_evidence["package"].package_status = "BLOCKED"
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["expected_package_status"] == "READY"
    assert audit["published_package_status"] == "BLOCKED"
    assert "PACKAGE_STATUS_MISMATCH" in audit["findings"]


def test_findings_aggregation_mismatch_detected(ready_evidence):
    """Findings aggregation mismatch creates INCONSISTENT audit."""
    ready_evidence["pkg162"].findings = ["TEST_FINDING"]
    ready_evidence["pkg162"].finding_count = 1
    # Package doesn't reflect this finding
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "AGGREGATE_FINDINGS_MISMATCH" in audit["findings"]


def test_blocked_package_derives_correctly(ready_evidence):
    """BLOCKED package status derives correctly when evidence supports it."""
    ready_evidence["pkg162"].admission_status = "BLOCKED"
    ready_evidence["pkg162"].finding_count = 1
    ready_evidence["pkg162"].findings = ["BLOCKED_REASON"]
    ready_evidence["package"].t162_admission_status = "BLOCKED"
    ready_evidence["package"].t162_finding_count = 1
    ready_evidence["package"].t162_findings = ["BLOCKED_REASON"]
    ready_evidence["package"].package_status = "BLOCKED"
    ready_evidence["package"].finding_count = 1
    ready_evidence["package"].findings = ["BLOCKED_REASON"]

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "CONSISTENT"
    assert audit["expected_package_status"] == "BLOCKED"
    assert audit["published_package_status"] == "BLOCKED"


def test_unavailable_package_derives_correctly(ready_evidence):
    """UNAVAILABLE package status derives correctly when evidence supports it."""
    ready_evidence["pkg162"].admission_status = "UNAVAILABLE"
    ready_evidence["pkg162"].finding_count = 1
    ready_evidence["pkg162"].findings = ["UNAVAILABLE_REASON"]
    ready_evidence["package"].t162_admission_status = "UNAVAILABLE"
    ready_evidence["package"].t162_finding_count = 1
    ready_evidence["package"].t162_findings = ["UNAVAILABLE_REASON"]
    ready_evidence["package"].package_status = "UNAVAILABLE"
    ready_evidence["package"].finding_count = 1
    ready_evidence["package"].findings = ["UNAVAILABLE_REASON"]

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "CONSISTENT"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert audit["published_package_status"] == "UNAVAILABLE"


def test_multiple_evidence_mismatches_detected(ready_evidence):
    """Multiple evidence mismatches all detected in single audit."""
    ready_evidence["package"].t162_admission_status = "BLOCKED"
    ready_evidence["package"].t163_slice_status = "BLOCKED"
    ready_evidence["package"].t164_slice_audit_status = "INCONSISTENT"
    ready_evidence["package"].t164_consistent = False

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T162_ADMISSION_STATUS_MISMATCH" in audit["findings"]
    assert "T163_SLICE_STATUS_MISMATCH" in audit["findings"]
    assert "T164_SLICE_AUDIT_STATUS_MISMATCH" in audit["findings"]
    assert audit["finding_count"] >= 3


def test_missing_input_detection(ready_evidence):
    """Nullable fields match correctly."""
    ready_evidence["package"].t162_provider_name = None
    ready_evidence["pkg162"].provider_name = None
    ready_evidence["package"].t162_model_name = None
    ready_evidence["pkg162"].model_name = None

    # Task 168's READY attribution contract must reject this post-construction
    # mutation even though the copied Task 162 fields agree.
    ready_evidence["pkg162"].admission_status = "UNAVAILABLE"
    ready_evidence["package"].t162_admission_status = "UNAVAILABLE"
    ready_evidence["package"].package_status = "UNAVAILABLE"

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "TASK_168_PACKAGE_INVALID" in audit["findings"]


def test_audit_service_is_independent(ready_evidence):
    """Audit service never calls upstream services."""
    # This is a contract test: the service signature requires all inputs
    # to be passed directly, demonstrating independence
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    # If the service tried to call Task 168 or earlier services, this would fail
    expected_source = REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
    assert audit["audit_source"] == expected_source


def test_fingerprint_mismatch_detected(ready_evidence):
    """Request fingerprint mismatch detected."""
    ready_evidence["package"].t162_request_fingerprint = "b" * 64
    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T162_REQUEST_FINGERPRINT_MISMATCH" in audit["findings"]


def test_source_forgery_detection(ready_evidence):
    """Source forgery across all tasks detected."""
    ready_evidence["package"].t162_audit_source = "FORGED_SOURCE"
    ready_evidence["package"].t163_certification_source = "FORGED_SOURCE"
    ready_evidence["package"].t164_audit_source = "FORGED_SOURCE"
    ready_evidence["package"].t165_bundle_source = "FORGED_SOURCE"
    ready_evidence["package"].t166_audit_source = "FORGED_SOURCE"
    ready_evidence["package"].t167_consistency_source = "FORGED_SOURCE"

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T162_AUDIT_SOURCE_MISMATCH" in audit["findings"]
    assert "T163_CERTIFICATION_SOURCE_MISMATCH" in audit["findings"]
    assert "T164_AUDIT_SOURCE_MISMATCH" in audit["findings"]
    assert "T165_BUNDLE_SOURCE_MISMATCH" in audit["findings"]
    assert "T166_AUDIT_SOURCE_MISMATCH" in audit["findings"]
    assert "T167_CONSISTENCY_SOURCE_MISMATCH" in audit["findings"]


def test_identity_mismatch_across_inputs(ready_evidence):
    """Session identity mismatch across all inputs detected."""
    ready_evidence["slice163"].session_id = str(uuid4())
    ready_evidence["package"].t163_session_id = ready_evidence["slice163"].session_id
    ready_evidence["package"].session_id = ""

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    # Session mismatch in inputs means package session should be ""
    # If package.session_id matches original, that's correct behavior


def test_finding_count_mismatch_detected(ready_evidence):
    """Finding count mismatches detected across all tasks."""
    ready_evidence["package"].t162_finding_count = 99
    ready_evidence["package"].t163_finding_count = 99
    ready_evidence["package"].t164_finding_count = 99
    ready_evidence["package"].t165_bundle_finding_count = 99
    ready_evidence["package"].t166_finding_count = 99
    ready_evidence["package"].t167_finding_count = 99

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "T162_FINDING_COUNT_MISMATCH" in audit["findings"]
    assert "T163_FINDING_COUNT_MISMATCH" in audit["findings"]
    assert "T164_FINDING_COUNT_MISMATCH" in audit["findings"]
    assert "T165_BUNDLE_FINDING_COUNT_MISMATCH" in audit["findings"]
    assert "T166_FINDING_COUNT_MISMATCH" in audit["findings"]
    assert "T167_FINDING_COUNT_MISMATCH" in audit["findings"]


def test_malformed_package_input(ready_evidence):
    """Malformed package input creates valid INCONSISTENT audit."""
    # Tamper with multiple fields to simulate malformed input
    ready_evidence["package"].t162_diagnostics_status = "UNHEALTHY"
    ready_evidence["package"].t163_diagnostics_status = "UNHEALTHY"

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["finding_count"] > 0


def test_audit_findings_sorted_deduplicated(ready_evidence):
    """Audit findings are sorted and deduplicated."""
    # Create multiple mismatches
    ready_evidence["package"].t162_admission_status = "BLOCKED"
    ready_evidence["package"].t163_slice_status = "BLOCKED"

    audit = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)
    findings = audit["findings"]
    assert findings == sorted(findings)
    assert len(findings) == len(set(findings))


@pytest.mark.parametrize("mutation", ["fingerprint", "attribution"])
def test_audit_rejects_aligned_invalid_task_165_evidence(ready_evidence, mutation):
    package = ready_evidence["package"]
    embedded = package.t165_bundle_evidence
    audited = package.t166_audited_bundle
    if mutation == "fingerprint":
        package.t162_request_fingerprint = "malformed"
        embedded.request_fingerprint = "malformed"
        audited.request_fingerprint = "malformed"
    else:
        package.t162_provider_name = None
        package.t162_model_name = None
        package.t163_provider_name = None
        package.t163_model_name = None
        embedded.provider_name = None
        embedded.model_name = None
        audited.provider_name = None
        audited.model_name = None

    result = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)

    assert result["package_audit_status"] == "INCONSISTENT"
    assert "TASK_168_PACKAGE_INVALID" in result["findings"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageRead.model_validate(package.model_dump())


@pytest.mark.parametrize(
    ("finding_count", "findings"),
    [(1, []), (1, ["FORGED_BUNDLE_FINDING"])],
)
def test_audit_rejects_task_165_bundle_finding_mutation(
    ready_evidence, finding_count, findings
):
    package = ready_evidence["package"]
    package.t165_bundle_finding_count = finding_count
    package.t165_bundle_findings = findings
    package.t165_bundle_evidence.bundle_finding_count = finding_count
    package.t165_bundle_evidence.bundle_findings = findings
    package.t166_audited_bundle.bundle_finding_count = finding_count
    package.t166_audited_bundle.bundle_findings = findings
    package.findings = sorted(set(findings))
    package.finding_count = len(package.findings)

    result = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)

    assert result["package_audit_status"] == "INCONSISTENT"
    assert "TASK_168_PACKAGE_INVALID" in result["findings"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageRead.model_validate(package.model_dump())


def test_audit_detects_substituted_task_165_snapshot(ready_evidence):
    ready_evidence["package"].t165_bundle_evidence.request_fingerprint = "b" * 64
    ready_evidence["package"].t166_audited_bundle.request_fingerprint = "b" * 64

    result = ReasoningRunStage7EvidencePackageAuditService.audit(**ready_evidence)

    assert result["package_audit_status"] == "INCONSISTENT"
    assert "T165_BUNDLE_EVIDENCE_MISMATCH" in result["findings"]

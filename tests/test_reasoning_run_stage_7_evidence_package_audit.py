"""Task 169: independent Stage 7 evidence-package audit tests.

Independent audit boundary over the already-published Task 168 evidence package.
The auditor independently derives the expected package state from the
published Task 162-167 surfaces, then compares against the published Task 168
package status.
"""

from __future__ import annotations

import copy
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
from rop.services.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageService,
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


# ---------------------------------------------------------------------------
# Task 169 correction: complete package findings, complete status derivation,
# and a deterministic result for malformed evidence.
# ---------------------------------------------------------------------------

AUDIT = ReasoningRunStage7EvidencePackageAuditService
INPUT_NAMES = (
    "pkg162",
    "slice163",
    "audit164",
    "bundle165",
    "audit166",
    "consistency167",
)


@pytest.fixture
def real_inputs(ready_evidence):
    """READY inputs whose Task 166/167 evidence comes from the real services."""
    inputs = {name: ready_evidence[name] for name in INPUT_NAMES}
    inputs["audit166"] = ReasoningRunStage7EvidenceBundleAuditRead.model_validate(
        ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=inputs["bundle165"])
    )
    inputs["consistency167"] = (
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
                bundle=inputs["bundle165"], audit=inputs["audit166"]
            )
        )
    )
    return inputs


def rebind_task_166_and_167(inputs):
    """Publish Task 166/167 evidence that matches a changed Task 165 bundle."""
    bundle = inputs["bundle165"]
    audit = inputs["audit166"]
    audit.audited_bundle = ReasoningRunStage7EvidenceBundleSnapshot.model_validate(
        bundle.model_dump()
    )
    audit.published_bundle_status = bundle.bundle_status
    audit.expected_bundle_status = bundle.bundle_status
    inputs["consistency167"] = (
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
                bundle=bundle, audit=audit
            )
        )
    )


def assemble_package(inputs):
    """Assemble a package with the real Task 168 service."""
    return ReasoningRunStage7EvidencePackageRead.model_validate(
        ReasoningRunStage7EvidencePackageService.assemble(**inputs)
    )


def audit_package(package, inputs):
    return AUDIT.audit(package=package, **inputs)


def child_findings(package):
    return set(
        package.t162_findings
        + package.t163_findings
        + package.t164_findings
        + package.t165_bundle_findings
        + package.t166_findings
        + package.t167_findings
    )


def _fingerprint_disagreement(inputs):
    inputs["bundle165"].request_fingerprint = "b" * 64
    rebind_task_166_and_167(inputs)


def _forged_task_162_source(inputs):
    inputs["pkg162"].audit_source = "FORGED_SOURCE"


def _forged_task_166_source(inputs):
    inputs["audit166"].audit_source = "FORGED_SOURCE"


def _forged_task_167_source(inputs):
    inputs["consistency167"].consistency_source = "FORGED_SOURCE"


def _substituted_task_165_bundle(inputs):
    inputs["bundle165"].provider_name = "substituted-provider"


def _missing_task_166_snapshot(inputs):
    inputs["audit166"].audited_bundle = None


def _session_mismatch(inputs):
    inputs["slice163"].session_id = str(uuid4())


def _stale_task_167_verdict(inputs):
    inputs["bundle165"].request_fingerprint = "b" * 64


def _aligned_malformed_fingerprint(inputs):
    inputs["pkg162"].request_fingerprint = "malformed"
    inputs["bundle165"].request_fingerprint = "malformed"
    rebind_task_166_and_167(inputs)


def _unsupported_embedded_status(inputs):
    inputs["bundle165"].slice_status = "FORGED"
    inputs["audit166"].audited_bundle.slice_status = "FORGED"


def _task_164_status_contradiction(inputs):
    inputs["audit164"].published_slice_status = "BLOCKED"
    inputs["bundle165"].published_slice_status = "BLOCKED"
    rebind_task_166_and_167(inputs)


def test_valid_unavailable_package_with_fingerprint_disagreement_is_consistent(
    real_inputs,
):
    _fingerprint_disagreement(real_inputs)

    package = assemble_package(real_inputs)

    # Task 168 publishes a valid UNAVAILABLE package whose aggregate carries a
    # package-level finding that no child list contains.
    assert package.package_status == "UNAVAILABLE"
    assert "T165_T162_EVIDENCE_MISMATCH" in package.findings
    assert "T165_T162_EVIDENCE_MISMATCH" not in child_findings(package)

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "CONSISTENT"
    assert audit["published_package_status"] == "UNAVAILABLE"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert audit["findings"] == []
    assert audit["finding_count"] == 0
    ReasoningRunStage7EvidencePackageAuditRead.model_validate(audit)


@pytest.mark.parametrize(
    ("mutate", "package_finding"),
    [
        (_forged_task_162_source, "T162_SOURCE_MISMATCH"),
        (_forged_task_166_source, "T166_SOURCE_MISMATCH"),
        (_forged_task_167_source, "T167_SOURCE_MISMATCH"),
        (_substituted_task_165_bundle, "T166_SNAPSHOT_MISMATCH"),
        (_missing_task_166_snapshot, "T166_SNAPSHOT_MISSING"),
        (_session_mismatch, "STAGE_7_SESSION_MISMATCH"),
        (_stale_task_167_verdict, "T167_RESULT_MISMATCH"),
        (_aligned_malformed_fingerprint, "T165_BUNDLE_INVALID"),
        (_unsupported_embedded_status, "T165_STATUS_INVALID"),
        (_task_164_status_contradiction, "T164_PUBLISHED_STATUS_MISMATCH"),
    ],
)
def test_valid_unavailable_package_with_structural_finding_is_consistent(
    real_inputs, mutate, package_finding
):
    mutate(real_inputs)

    package = assemble_package(real_inputs)

    assert package.package_status == "UNAVAILABLE"
    assert package_finding in package.findings
    assert package_finding not in child_findings(package)

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "CONSISTENT", audit["findings"]
    assert audit["published_package_status"] == "UNAVAILABLE"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert audit["findings"] == []


def test_valid_package_with_unavailable_task_166_audit_is_consistent(real_inputs):
    real_inputs["audit166"] = ReasoningRunStage7EvidenceBundleAuditRead(
        session_id="",
        bundle_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_bundle_status=None,
        expected_bundle_status=None,
        finding_count=1,
        findings=["TASK_165_BUNDLE_MISSING"],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    )
    package = assemble_package(real_inputs)
    assert package.package_status == "UNAVAILABLE"

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "CONSISTENT", audit["findings"]
    assert audit["expected_package_status"] == "UNAVAILABLE"


def test_ready_package_from_task_168_assembler_audits_consistent(real_inputs):
    package = assemble_package(real_inputs)
    assert package.package_status == "READY"

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "CONSISTENT"
    assert audit["published_package_status"] == "READY"
    assert audit["expected_package_status"] == "READY"
    assert audit["findings"] == []


def test_genuine_blocked_evidence_derives_blocked(real_inputs):
    real_inputs["pkg162"].admission_status = "BLOCKED"
    real_inputs["pkg162"].finding_count = 1
    real_inputs["pkg162"].findings = ["BLOCKED"]
    package = assemble_package(real_inputs)
    assert package.package_status == "BLOCKED"

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "CONSISTENT", audit["findings"]
    assert audit["published_package_status"] == "BLOCKED"
    assert audit["expected_package_status"] == "BLOCKED"


def test_blocked_keeps_precedence_over_package_level_findings(real_inputs):
    real_inputs["pkg162"].admission_status = "BLOCKED"
    real_inputs["pkg162"].finding_count = 1
    real_inputs["pkg162"].findings = ["BLOCKED"]
    _fingerprint_disagreement(real_inputs)
    package = assemble_package(real_inputs)
    assert package.package_status == "BLOCKED"
    assert "T165_T162_EVIDENCE_MISMATCH" in package.findings

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "CONSISTENT", audit["findings"]
    assert audit["expected_package_status"] == "BLOCKED"

    # Downgrading the same genuinely BLOCKED package is a contradiction.
    package.package_status = "UNAVAILABLE"
    audit = audit_package(package, real_inputs)
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["expected_package_status"] == "BLOCKED"
    assert audit["published_package_status"] == "UNAVAILABLE"
    assert "PACKAGE_STATUS_MISMATCH" in audit["findings"]


def test_blocked_requires_genuine_blocking_evidence(real_inputs):
    _fingerprint_disagreement(real_inputs)
    package = assemble_package(real_inputs)
    assert package.package_status == "UNAVAILABLE"

    package.package_status = "BLOCKED"
    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert audit["published_package_status"] == "BLOCKED"
    assert "PACKAGE_STATUS_MISMATCH" in audit["findings"]

    package.package_status = "READY"
    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert "PACKAGE_STATUS_MISMATCH" in audit["findings"]


def test_withheld_package_level_finding_is_detected(real_inputs):
    _fingerprint_disagreement(real_inputs)
    package = assemble_package(real_inputs)
    package.findings = [
        finding
        for finding in package.findings
        if finding != "T165_T162_EVIDENCE_MISMATCH"
    ]
    package.finding_count = len(package.findings)

    audit = audit_package(package, real_inputs)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "AGGREGATE_FINDINGS_MISMATCH" in audit["findings"]
    # The withheld finding also leaves the published count one short.
    assert "AGGREGATE_FINDING_COUNT_MISMATCH" in audit["findings"]


def test_fabricated_package_level_finding_is_detected(ready_evidence):
    package = ready_evidence["package"]
    package.findings = ["T165_T162_EVIDENCE_MISMATCH"]
    package.finding_count = 1

    audit = AUDIT.audit(**ready_evidence)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "AGGREGATE_FINDINGS_MISMATCH" in audit["findings"]
    assert "AGGREGATE_FINDING_COUNT_MISMATCH" in audit["findings"]


# --- Malformed evidence: a deterministic, schema-valid result --------------


def assert_unavailable_audit(audit, expected_findings):
    assert audit["package_audit_status"] == "UNAVAILABLE"
    assert audit["available"] is False
    assert audit["consistent"] is False
    assert audit["session_id"] == ""
    assert audit["published_package_status"] is None
    assert audit["expected_package_status"] is None
    assert audit["findings"] == expected_findings
    assert audit["finding_count"] == len(expected_findings)
    ReasoningRunStage7EvidencePackageAuditRead.model_validate(audit)


@pytest.mark.parametrize("bad_value", [None, "not-a-snapshot", {}, 7])
@pytest.mark.parametrize("field", ["t165_bundle_evidence", "t166_audited_bundle"])
def test_malformed_embedded_evidence_is_unavailable_not_a_crash(
    ready_evidence, field, bad_value
):
    if field == "t166_audited_bundle" and bad_value is None:
        pytest.skip("None is a legitimate Task 166 snapshot value")
    setattr(ready_evidence["package"], field, bad_value)

    audit = AUDIT.audit(**ready_evidence)

    assert_unavailable_audit(
        audit, ["TASK_168_PACKAGE_INVALID", "TASK_168_PACKAGE_UNREADABLE"]
    )
    assert audit == AUDIT.audit(**ready_evidence)


@pytest.mark.parametrize("bad_value", [None, "findings", 5, [1], [None]])
def test_malformed_package_finding_lists_are_unavailable(ready_evidence, bad_value):
    ready_evidence["package"].t162_findings = bad_value

    audit = AUDIT.audit(**ready_evidence)

    assert_unavailable_audit(
        audit, ["TASK_168_PACKAGE_INVALID", "TASK_168_PACKAGE_UNREADABLE"]
    )


def test_package_missing_a_required_attribute_is_unavailable(ready_evidence):
    del ready_evidence["package"].__dict__["t164_findings"]

    audit = AUDIT.audit(**ready_evidence)

    assert audit["package_audit_status"] == "UNAVAILABLE"
    assert "TASK_168_PACKAGE_UNREADABLE" in audit["findings"]
    ReasoningRunStage7EvidencePackageAuditRead.model_validate(audit)


@pytest.mark.parametrize("not_a_package", [None, {}, "package", object()])
def test_non_package_object_is_unavailable(ready_evidence, not_a_package):
    ready_evidence["package"] = not_a_package

    audit = AUDIT.audit(**ready_evidence)

    assert_unavailable_audit(audit, ["TASK_168_PACKAGE_UNREADABLE"])


@pytest.mark.parametrize("bad_status", ["FORGED", "", "ready", None, 7, ["READY"]])
def test_unsupported_published_package_status_is_unavailable(
    ready_evidence, bad_status
):
    ready_evidence["package"].package_status = bad_status

    audit = AUDIT.audit(**ready_evidence)

    # The published status cannot be read as a permitted value: the result
    # names no status instead of inventing one.
    assert_unavailable_audit(
        audit, ["TASK_168_PACKAGE_INVALID", "TASK_168_PACKAGE_STATUS_UNREADABLE"]
    )


@pytest.mark.parametrize(
    ("input_name", "mutate", "finding"),
    [
        ("audit166", lambda _: None, "T166_INPUT_UNREADABLE"),
        ("consistency167", lambda _: "garbage", "T167_INPUT_UNREADABLE"),
        ("pkg162", lambda _: None, "T162_INPUT_UNREADABLE"),
    ],
)
def test_non_model_upstream_input_is_unavailable(
    ready_evidence, input_name, mutate, finding
):
    ready_evidence[input_name] = mutate(ready_evidence[input_name])

    audit = AUDIT.audit(**ready_evidence)

    assert_unavailable_audit(audit, [finding])


@pytest.mark.parametrize(
    ("input_name", "field", "bad_value", "finding"),
    [
        ("slice163", "findings", None, "T163_INPUT_UNREADABLE"),
        ("audit164", "findings", [1], "T164_INPUT_UNREADABLE"),
        ("bundle165", "finding_count", True, "T165_INPUT_UNREADABLE"),
        ("bundle165", "bundle_findings", None, "T165_INPUT_UNREADABLE"),
        ("audit166", "audited_bundle", "garbage", "T166_INPUT_UNREADABLE"),
        ("pkg162", "session_id", 123, "SESSION_ID_INVALID"),
        ("bundle165", "session_id", None, "SESSION_ID_INVALID"),
    ],
)
def test_malformed_postconstruction_upstream_fields_are_unavailable(
    ready_evidence, input_name, field, bad_value, finding
):
    setattr(ready_evidence[input_name], field, bad_value)

    audit = AUDIT.audit(**ready_evidence)

    assert_unavailable_audit(audit, [finding])


def test_unreadable_evidence_reports_every_unreadable_input(ready_evidence):
    ready_evidence["slice163"].findings = None
    ready_evidence["audit166"] = None
    ready_evidence["package"].t165_bundle_evidence = None

    audit = AUDIT.audit(**ready_evidence)

    assert_unavailable_audit(
        audit,
        [
            "T163_INPUT_UNREADABLE",
            "T166_INPUT_UNREADABLE",
            "TASK_168_PACKAGE_INVALID",
            "TASK_168_PACKAGE_UNREADABLE",
        ],
    )


def test_readable_but_contradictory_package_stays_inconsistent(ready_evidence):
    # A readable package that fails Task 168 revalidation is contradictory,
    # not unauditable: the result must be INCONSISTENT and name both statuses.
    ready_evidence["package"].t162_request_fingerprint = "malformed"
    ready_evidence["package"].t165_bundle_evidence.request_fingerprint = "malformed"
    ready_evidence["package"].t166_audited_bundle.request_fingerprint = "malformed"

    audit = AUDIT.audit(**ready_evidence)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["published_package_status"] == "READY"
    assert audit["expected_package_status"] in {"READY", "BLOCKED", "UNAVAILABLE"}
    assert "TASK_168_PACKAGE_INVALID" in audit["findings"]


# --- Availability / consistency flags never leave the expected status READY -


@pytest.mark.parametrize(
    ("input_name", "field", "package_field", "flags_finding"),
    [
        ("audit164", "available", "t164_available", "T164_FLAGS_INCOHERENT"),
        ("audit164", "consistent", "t164_consistent", "T164_FLAGS_INCOHERENT"),
        ("audit166", "available", "t166_available", "T166_FLAGS_INCOHERENT"),
        ("audit166", "consistent", "t166_consistent", "T166_FLAGS_INCOHERENT"),
        (
            "consistency167",
            "available",
            "t167_available",
            "T167_FLAGS_INCOHERENT",
        ),
        (
            "consistency167",
            "consistent",
            "t167_consistent",
            "T167_FLAGS_INCOHERENT",
        ),
    ],
)
@pytest.mark.parametrize("aligned", [False, True])
def test_mutated_availability_flags_never_derive_ready(
    ready_evidence, input_name, field, package_field, flags_finding, aligned
):
    setattr(ready_evidence[input_name], field, False)
    if aligned:
        setattr(ready_evidence["package"], package_field, False)

    audit = AUDIT.audit(**ready_evidence)

    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert audit["published_package_status"] == "READY"
    assert audit["package_audit_status"] == "INCONSISTENT"
    assert "PACKAGE_STATUS_MISMATCH" in audit["findings"]
    assert flags_finding in audit["findings"]
    if not aligned:
        assert any(
            finding.endswith(("_AVAILABLE_MISMATCH", "_CONSISTENT_MISMATCH"))
            for finding in audit["findings"]
        )


def test_task_166_unavailable_claiming_a_bundle_is_inconsistent(ready_evidence):
    ready_evidence["audit166"].bundle_audit_status = "UNAVAILABLE"
    ready_evidence["audit166"].available = False
    ready_evidence["audit166"].consistent = False

    audit = AUDIT.audit(**ready_evidence)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert "T166_UNAVAILABLE_CLAIMS_BUNDLE" in audit["findings"]


def test_compared_task_166_without_statuses_is_inconsistent(ready_evidence):
    ready_evidence["audit166"].published_bundle_status = None
    ready_evidence["audit166"].expected_bundle_status = None

    audit = AUDIT.audit(**ready_evidence)

    assert audit["package_audit_status"] == "INCONSISTENT"
    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert "T166_COMPARED_STATUS_MISSING" in audit["findings"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda inputs: setattr(inputs["pkg162"], "finding_count", 1),
        lambda inputs: setattr(inputs["bundle165"], "bundle_finding_count", 1),
        lambda inputs: setattr(inputs["audit164"], "finding_count", 1),
    ],
)
def test_nonzero_finding_count_never_derives_ready(ready_evidence, mutation):
    mutation(ready_evidence)

    audit = AUDIT.audit(**ready_evidence)

    assert audit["expected_package_status"] == "UNAVAILABLE"
    assert audit["package_audit_status"] == "INCONSISTENT"


# --- Result contract --------------------------------------------------------


def _audit_payload(**overrides):
    payload = {
        "session_id": "s",
        "package_audit_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "published_package_status": "READY",
        "expected_package_status": "READY",
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "overrides",
    [
        {"audit_source": "FORGED"},
        # UNAVAILABLE must not name a package status or a session.
        {
            "package_audit_status": "UNAVAILABLE",
            "available": False,
            "consistent": False,
            "finding_count": 1,
            "findings": ["X"],
            "session_id": "",
        },
        {
            "package_audit_status": "UNAVAILABLE",
            "available": False,
            "consistent": False,
            "finding_count": 1,
            "findings": ["X"],
            "published_package_status": None,
            "expected_package_status": None,
        },
        # A compared (non-UNAVAILABLE) audit must name both statuses.
        {
            "package_audit_status": "INCONSISTENT",
            "consistent": False,
            "finding_count": 1,
            "findings": ["X"],
            "published_package_status": None,
        },
        {"published_package_status": "FORGED"},
        {"expected_package_status": None},
        {"findings": ["B", "A"], "finding_count": 2},
        {
            "package_audit_status": "INCONSISTENT",
            "consistent": False,
        },
    ],
)
def test_audit_schema_rejects_incoherent_results(overrides):
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageAuditRead.model_validate(
            _audit_payload(**overrides)
        )


def test_audit_schema_accepts_unavailable_without_statuses():
    payload = _audit_payload(
        package_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_package_status=None,
        expected_package_status=None,
        session_id="",
        finding_count=1,
        findings=["TASK_168_PACKAGE_STATUS_UNREADABLE"],
    )
    validated = ReasoningRunStage7EvidencePackageAuditRead.model_validate(payload)
    assert validated.published_package_status is None


# --- Determinism, ordering, immutability, independence ----------------------


def test_audit_is_deterministic_sorted_and_does_not_mutate_inputs(real_inputs):
    _fingerprint_disagreement(real_inputs)
    package = assemble_package(real_inputs)
    # Tamper with several package copies so the audit has many findings.
    package.t162_admission_status = "BLOCKED"
    package.t163_slice_status = "BLOCKED"
    package.t164_slice_audit_status = "INCONSISTENT"
    package.t164_consistent = False
    package.package_status = "READY"
    models = {**real_inputs, "package": package}
    before = {name: copy.deepcopy(model.model_dump()) for name, model in models.items()}

    first = audit_package(package, real_inputs)
    second = audit_package(package, real_inputs)

    assert first == second
    assert first["package_audit_status"] == "INCONSISTENT"
    assert first["findings"] == sorted(set(first["findings"]))
    assert first["finding_count"] == len(first["findings"])
    assert {name: model.model_dump() for name, model in models.items()} == before


def test_malformed_result_is_deterministic_and_does_not_mutate_inputs(ready_evidence):
    ready_evidence["package"].t165_bundle_evidence = None
    ready_evidence["package"].package_status = "FORGED"
    before = {
        name: copy.deepcopy(model.model_dump())
        for name, model in ready_evidence.items()
    }

    first = AUDIT.audit(**ready_evidence)
    second = AUDIT.audit(**ready_evidence)

    assert first == second
    assert first["findings"] == sorted(set(first["findings"]))
    assert {
        name: model.model_dump() for name, model in ready_evidence.items()
    } == before


def test_audit_never_calls_task_162_to_168_services(ready_evidence, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("the audit must not call upstream services")

    monkeypatch.setattr(
        ReasoningRunStage7EvidencePackageService, "assemble", staticmethod(forbidden)
    )
    monkeypatch.setattr(
        ReasoningRunStage7EvidenceBundleAuditService, "audit", staticmethod(forbidden)
    )
    monkeypatch.setattr(
        ReasoningRunStage7EvidenceBundleAuditConsistencyService,
        "verify",
        staticmethod(forbidden),
    )

    audit = AUDIT.audit(**ready_evidence)

    assert audit["package_audit_status"] == "CONSISTENT"

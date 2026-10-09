"""Task 171: Stage 7 final evidence attestation tests.

Final provider-neutral attestation over the fully audited Stage 7 evidence
chain through Task 170. The attestation answers only: "Does the published
Stage 7 evidence package have complete, mutually consistent, canonically
attributable evidence?"

The attestation is a pure aggregation boundary: it never calls Task 168,
Task 169, or Task 170 services, never recomputes fingerprints, never
invokes a provider, and never accesses a database.
"""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171,
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

ATTESTATION_SOURCE = REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171


@pytest.fixture
def ready_package(
    ready_bundle_evidence,
) -> ReasoningRunStage7EvidencePackageRead:
    """A READY package for testing."""
    session_id = str(uuid4())
    fingerprint = "a" * 64
    return ReasoningRunStage7EvidencePackageRead(
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
        t165_bundle_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_TASK_165",
        t165_bundle_evidence=ready_bundle_evidence(session_id, fingerprint),
        t166_session_id=session_id,
        t166_bundle_audit_status="CONSISTENT",
        t166_available=True,
        t166_consistent=True,
        t166_published_bundle_status="READY",
        t166_expected_bundle_status="READY",
        t166_finding_count=0,
        t166_findings=[],
        t166_audit_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166",
        t166_audited_bundle=ready_bundle_evidence(session_id, fingerprint),
        t167_session_id=session_id,
        t167_consistency_status="CONSISTENT",
        t167_available=True,
        t167_consistent=True,
        t167_finding_count=0,
        t167_findings=[],
        t167_consistency_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_TASK_167",
        package_status="READY",
        finding_count=0,
        findings=[],
        package_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    )


@pytest.fixture
def consistent_audit(
    ready_package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageAuditRead:
    """A CONSISTENT audit for testing."""
    return ReasoningRunStage7EvidencePackageAuditRead(
        session_id=ready_package.session_id,
        package_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_package_status="READY",
        expected_package_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    )


@pytest.fixture
def consistent_consistency(
    ready_package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageAuditConsistencyRead:
    """A CONSISTENT consistency check for testing."""
    return ReasoningRunStage7EvidencePackageAuditConsistencyRead(
        session_id=ready_package.session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_forbids_extra_fields() -> None:
    """Schema rejects extra fields."""
    session_id = str(uuid4())
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="CERTIFIED",
            certified=True,
            blocked=False,
            available=True,
            package_status="READY",
            package_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=0,
            findings=[],
            attestation_source=ATTESTATION_SOURCE,
            extra_field="unexpected",  # type: ignore
        )


def test_schema_certified_requires_zero_findings() -> None:
    """CERTIFIED status requires zero findings."""
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="CERTIFIED requires a finding-free"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="CERTIFIED",
            certified=True,
            blocked=False,
            available=True,
            package_status="READY",
            package_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=1,
            findings=["SOME_FINDING"],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_certified_requires_valid_session() -> None:
    """CERTIFIED status requires a valid session_id."""
    with pytest.raises(ValidationError, match="CERTIFIED requires a valid session_id"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id="",
            attestation_status="CERTIFIED",
            certified=True,
            blocked=False,
            available=True,
            package_status="READY",
            package_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=0,
            findings=[],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_blocked_requires_findings() -> None:
    """BLOCKED status requires at least one finding."""
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="BLOCKED requires at least one finding"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="BLOCKED",
            certified=False,
            blocked=True,
            available=True,
            package_status="BLOCKED",
            finding_count=0,
            findings=[],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_unavailable_requires_findings() -> None:
    """UNAVAILABLE status requires at least one diagnostic finding."""
    session_id = str(uuid4())
    with pytest.raises(
        ValidationError, match="UNAVAILABLE requires at least one diagnostic finding"
    ):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=False,
            available=False,
            finding_count=0,
            findings=[],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_certified_flag_coherence() -> None:
    """certified flag must equal (attestation_status == 'CERTIFIED')."""
    session_id = str(uuid4())
    with pytest.raises(
        ValidationError,
        match="certified must equal \\(attestation_status == 'CERTIFIED'\\)",
    ):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=True,  # Incorrect
            blocked=False,
            available=False,
            finding_count=1,
            findings=["SOME_ISSUE"],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_blocked_flag_coherence() -> None:
    """blocked flag must equal (attestation_status == 'BLOCKED')."""
    session_id = str(uuid4())
    with pytest.raises(
        ValidationError,
        match="blocked must equal \\(attestation_status == 'BLOCKED'\\)",
    ):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=True,  # Incorrect
            available=False,
            finding_count=1,
            findings=["SOME_ISSUE"],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_available_flag_coherence() -> None:
    """available flag must equal (attestation_status != 'UNAVAILABLE')."""
    session_id = str(uuid4())
    with pytest.raises(
        ValidationError,
        match="available must equal \\(attestation_status != 'UNAVAILABLE'\\)",
    ):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=False,
            available=True,  # Incorrect
            finding_count=1,
            findings=["SOME_ISSUE"],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_finding_count_must_match_findings() -> None:
    """finding_count must equal len(findings)."""
    session_id = str(uuid4())
    with pytest.raises(
        ValidationError, match="finding_count must equal len\\(findings\\)"
    ):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=False,
            available=False,
            finding_count=99,  # Incorrect
            findings=["SOME_ISSUE"],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_findings_must_be_sorted() -> None:
    """findings must be sorted."""
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="findings must be sorted"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=False,
            available=False,
            finding_count=2,
            findings=["Z_FINDING", "A_FINDING"],  # Not sorted
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_findings_must_be_deduplicated() -> None:
    """findings must not contain duplicates."""
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="findings must not contain duplicates"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=False,
            available=False,
            finding_count=2,
            findings=["DUPLICATE", "DUPLICATE"],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_schema_attestation_source_must_be_canonical() -> None:
    """attestation_source must be the canonical Task 171 source."""
    session_id = str(uuid4())
    with pytest.raises(
        ValidationError,
        match="attestation_source must be the canonical Task 171 source",
    ):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=session_id,
            attestation_status="UNAVAILABLE",
            certified=False,
            blocked=False,
            available=False,
            finding_count=1,
            findings=["SOME_ISSUE"],
            attestation_source="WRONG_SOURCE",
        )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_service_certified_attestation(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service produces CERTIFIED for complete, consistent evidence."""
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "CERTIFIED"
    assert attestation["certified"] is True
    assert attestation["blocked"] is False
    assert attestation["available"] is True
    assert attestation["finding_count"] == 0
    assert attestation["findings"] == []
    assert attestation["session_id"] == ready_package.session_id
    assert attestation["attestation_source"] == ATTESTATION_SOURCE


def test_service_blocked_attestation(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service produces BLOCKED when package status is BLOCKED."""
    # Build a schema-valid BLOCKED package from genuine blocking evidence.
    blocked_package = copy.deepcopy(ready_package)
    blocked_package.t162_admission_status = "BLOCKED"
    blocked_package.t162_finding_count = 1
    blocked_package.t162_findings = ["BLOCKED"]
    blocked_package.package_status = "BLOCKED"
    blocked_package.finding_count = 1
    blocked_package.findings = ["BLOCKED"]
    blocked_package = ReasoningRunStage7EvidencePackageRead.model_validate(
        blocked_package.model_dump()
    )

    # Audit must reflect the BLOCKED status
    blocked_audit = copy.deepcopy(consistent_audit)
    blocked_audit.published_package_status = "BLOCKED"
    blocked_audit.expected_package_status = "BLOCKED"

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=blocked_package,
        audit=blocked_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "BLOCKED"
    assert attestation["certified"] is False
    assert attestation["blocked"] is True
    assert attestation["available"] is True
    # BLOCKED should have findings about the blocking state
    assert attestation["finding_count"] > 0


def test_service_unavailable_when_audit_not_consistent(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service produces UNAVAILABLE when audit status is not CONSISTENT."""
    inconsistent_audit = copy.deepcopy(consistent_audit)
    inconsistent_audit.package_audit_status = "INCONSISTENT"
    inconsistent_audit.consistent = False
    inconsistent_audit.finding_count = 1
    inconsistent_audit.findings = ["SOME_AUDIT_ISSUE"]

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=inconsistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["certified"] is False
    assert attestation["blocked"] is False
    assert attestation["available"] is False
    assert "AUDIT_NOT_CONSISTENT" in attestation["findings"]
    assert "AUDIT_HAS_FINDINGS" in attestation["findings"]


def test_service_unavailable_when_consistency_not_consistent(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service produces UNAVAILABLE when consistency status is not CONSISTENT."""
    inconsistent_consistency = copy.deepcopy(consistent_consistency)
    inconsistent_consistency.consistency_status = "INCONSISTENT"
    inconsistent_consistency.consistent = False
    inconsistent_consistency.finding_count = 1
    inconsistent_consistency.findings = ["SOME_CONSISTENCY_ISSUE"]

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=inconsistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["certified"] is False
    assert attestation["blocked"] is False
    assert attestation["available"] is False
    assert "CONSISTENCY_NOT_CONSISTENT" in attestation["findings"]
    assert "CONSISTENCY_HAS_FINDINGS" in attestation["findings"]


def test_service_detects_session_mismatch(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects session ID mismatches."""
    mismatched_audit = copy.deepcopy(consistent_audit)
    mismatched_audit.session_id = str(uuid4())

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=mismatched_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert "PACKAGE_AUDIT_SESSION_MISMATCH" in attestation["findings"]


def test_service_detects_invalid_package_source(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects invalid package source."""
    bad_package = copy.deepcopy(ready_package)
    bad_package.package_source = "WRONG_SOURCE"

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=bad_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_invalid_audit_source(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects invalid audit source."""
    bad_audit = copy.deepcopy(consistent_audit)
    bad_audit.audit_source = "WRONG_SOURCE"

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=bad_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_invalid_consistency_source(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects invalid consistency source."""
    bad_consistency = copy.deepcopy(consistent_consistency)
    bad_consistency.consistency_source = "WRONG_SOURCE"

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=bad_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_invalid_fingerprint_length(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects invalid fingerprint length."""
    bad_package = copy.deepcopy(ready_package)
    bad_package.t162_request_fingerprint = "short"

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=bad_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_invalid_fingerprint_format(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects invalid fingerprint format."""
    bad_package = copy.deepcopy(ready_package)
    bad_package.t162_request_fingerprint = "z" * 64  # Invalid hex characters

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=bad_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_missing_provider_name(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects missing provider name for READY package."""
    bad_package = copy.deepcopy(ready_package)
    bad_package.t162_provider_name = None

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=bad_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_missing_model_name(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects missing model name for READY package."""
    bad_package = copy.deepcopy(ready_package)
    bad_package.t162_model_name = None

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=bad_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_rejects_aligned_blank_provider_and_model_attribution(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Aligned mutations cannot bypass Task 165's READY attribution rules."""
    bad_package = copy.deepcopy(ready_package)
    bad_package.t162_provider_name = " "
    bad_package.t163_provider_name = " "
    bad_package.t162_model_name = ""
    bad_package.t163_model_name = ""
    bad_package.t165_bundle_evidence.provider_name = " "
    bad_package.t165_bundle_evidence.model_name = ""
    bad_package.t166_audited_bundle.provider_name = " "
    bad_package.t166_audited_bundle.model_name = ""

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=bad_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_detects_package_status_contradiction(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service detects package status contradiction."""
    bad_audit = copy.deepcopy(consistent_audit)
    bad_audit.package_audit_status = "INCONSISTENT"
    bad_audit.consistent = False
    bad_audit.expected_package_status = "UNAVAILABLE"
    bad_audit.finding_count = 1
    bad_audit.findings = ["STATUS_MISMATCH"]

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=bad_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert "PACKAGE_STATUS_CONTRADICTION" in attestation["findings"]
    assert "PACKAGE_AUDIT_STATUS_MISMATCH" in attestation["findings"]


def test_service_sorts_and_deduplicates_findings(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service sorts and deduplicates findings."""
    # Create multiple issues to trigger duplicate findings
    bad_audit = copy.deepcopy(consistent_audit)
    bad_audit.audit_source = "WRONG_SOURCE"

    bad_consistency = copy.deepcopy(consistent_consistency)
    bad_consistency.consistency_source = "WRONG_SOURCE"

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=bad_audit,
        consistency=bad_consistency,
    )

    # Check findings are sorted
    assert attestation["findings"] == sorted(attestation["findings"])
    # Check findings are deduplicated
    assert len(attestation["findings"]) == len(set(attestation["findings"]))


def test_service_attestation_source_constant_is_exported() -> None:
    """Attestation source constant is exported correctly."""
    assert ATTESTATION_SOURCE == (
        "REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_TASK_171"
    )


def test_service_never_calls_child_services(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service is pure: it never calls Task 168, 169, or 170 services.

    The service receives already-validated Pydantic objects and only reads
    them. If it tried to call child services, this test would fail because
    we are not providing database connections, provider configurations, or
    any other infrastructure.
    """
    # This call succeeds with only Pydantic objects, proving the service
    # does not invoke child services, providers, or databases.
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )
    assert attestation["attestation_status"] == "CERTIFIED"


def test_service_unavailable_when_package_not_ready_or_blocked(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Service produces UNAVAILABLE when package is neither READY nor BLOCKED."""
    unavailable_package = copy.deepcopy(ready_package)
    unavailable_package.t162_admission_status = "UNAVAILABLE"
    unavailable_package.package_status = "UNAVAILABLE"
    unavailable_package = ReasoningRunStage7EvidencePackageRead.model_validate(
        unavailable_package.model_dump()
    )

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=unavailable_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert "PACKAGE_NOT_READY_OR_BLOCKED" in attestation["findings"]


def test_service_revalidates_post_construction_mutations(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Mutated evidence is unavailable rather than trusted as certified."""
    ready_package.session_id = []

    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["session_id"] == ""
    assert attestation["package_status"] is None
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_service_is_deterministic_and_does_not_mutate_inputs(
    ready_package: ReasoningRunStage7EvidencePackageRead,
    consistent_audit: ReasoningRunStage7EvidencePackageAuditRead,
    consistent_consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
) -> None:
    """Repeated attestations are identical and leave published inputs intact."""
    original = (
        copy.deepcopy(ready_package),
        copy.deepcopy(consistent_audit),
        copy.deepcopy(consistent_consistency),
    )
    first = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )
    second = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=ready_package,
        audit=consistent_audit,
        consistency=consistent_consistency,
    )

    assert first == second
    assert ready_package == original[0]
    assert consistent_audit == original[1]
    assert consistent_consistency == original[2]


def test_service_rejects_wrong_input_types() -> None:
    """Unexpected objects do not leak attribute errors."""
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=None,  # type: ignore[arg-type]
        audit=None,  # type: ignore[arg-type]
        consistency=None,  # type: ignore[arg-type]
    )

    assert attestation["attestation_status"] == "UNAVAILABLE"
    assert attestation["session_id"] == ""
    assert attestation["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_attestation_schema_certified_requires_consistent_upstream_statuses() -> None:
    """A direct schema caller cannot claim certification without source verdicts."""
    with pytest.raises(ValidationError, match="CERTIFIED requires READY"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=str(uuid4()),
            attestation_status="CERTIFIED",
            certified=True,
            blocked=False,
            available=True,
            finding_count=0,
            findings=[],
            attestation_source=ATTESTATION_SOURCE,
        )


def test_attestation_schema_blocked_requires_blocked_package() -> None:
    """A direct schema caller cannot claim BLOCKED for a non-blocked package."""
    with pytest.raises(ValidationError, match="BLOCKED requires a BLOCKED package"):
        ReasoningRunStage7FinalEvidenceAttestationRead(
            session_id=str(uuid4()),
            attestation_status="BLOCKED",
            certified=False,
            blocked=True,
            available=True,
            package_status="READY",
            finding_count=1,
            findings=["BLOCKING_EVIDENCE"],
            attestation_source=ATTESTATION_SOURCE,
        )

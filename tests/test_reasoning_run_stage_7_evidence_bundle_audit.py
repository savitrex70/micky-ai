"""Task 166: independent Stage 7 evidence-bundle audit tests.

Deterministic audit boundary over the already-published Task 165 evidence
bundle. The auditor independently derives the expected bundle state from
the published Task 162, Task 163, and Task 164 surfaces already present
inside the bundle, then compares the independently derived state against
the published Task 165 bundle status.

The audit is pure, provider-neutral, and independent: it never calls Task
165, never calls Tasks 162-164 services, never recomputes fingerprints,
never invokes a provider, and never accesses a database.
"""

from __future__ import annotations

import ast
import copy
import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

# ---------------------------------------------------------------------------
# Test fixtures: genuine READY bundle
# ---------------------------------------------------------------------------

AUDIT_SOURCE = REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166


@pytest.fixture
def genuine_ready_bundle() -> ReasoningRunStage7EvidenceBundleRead:
    """A genuine READY bundle with complete canonical evidence."""
    return ReasoningRunStage7EvidenceBundleRead(
        session_id=str(uuid4()),
        # Task 163 surface
        slice_status="READY",
        admission_status="ADMITTED",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        # Task 164 surface
        slice_audit_status="CONSISTENT",
        audit_available=True,
        audit_consistent=True,
        published_slice_status="READY",
        expected_slice_status="READY",
        audit_finding_count=0,
        audit_findings=[],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        # Task 162 attribution
        request_fingerprint="a" * 64,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        # Aggregate
        bundle_status="READY",
        bundle_finding_count=0,
        bundle_findings=[],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )


@pytest.fixture
def genuine_blocked_bundle() -> ReasoningRunStage7EvidenceBundleRead:
    """A genuine BLOCKED bundle with blocking evidence."""
    return ReasoningRunStage7EvidenceBundleRead(
        session_id=str(uuid4()),
        # Task 163 surface
        slice_status="BLOCKED",
        admission_status="BLOCKED",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=1,
        findings=["BLOCKED_BY_ADMISSION"],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        # Task 164 surface
        slice_audit_status="CONSISTENT",
        audit_available=True,
        audit_consistent=True,
        published_slice_status="BLOCKED",
        expected_slice_status="BLOCKED",
        audit_finding_count=0,
        audit_findings=[],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        # Task 162 attribution
        request_fingerprint="a" * 64,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        # Aggregate
        bundle_status="BLOCKED",
        bundle_finding_count=0,
        bundle_findings=[],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )


@pytest.fixture
def genuine_unavailable_bundle() -> ReasoningRunStage7EvidenceBundleRead:
    """A genuine UNAVAILABLE bundle with incomplete evidence."""
    return ReasoningRunStage7EvidenceBundleRead(
        session_id="",
        # Task 163 surface
        slice_status="UNAVAILABLE",
        admission_status=None,
        diagnostics_status=None,
        provider_name=None,
        model_name=None,
        finding_count=1,
        findings=["MISSING_ADMISSION"],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        # Task 164 surface
        slice_audit_status="UNAVAILABLE",
        audit_available=False,
        audit_consistent=False,
        published_slice_status=None,
        expected_slice_status=None,
        audit_finding_count=1,
        audit_findings=["MISSING_ADMISSION"],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        # Task 162 attribution
        request_fingerprint=None,
        request_audit_status=None,
        proposal_audit_status=None,
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        # Aggregate
        bundle_status="UNAVAILABLE",
        bundle_finding_count=3,
        bundle_findings=[
            "PROVIDER_ATTRIBUTION_MISSING",
            "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
            "STAGE_7_SESSION_MISMATCH",
        ],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )


# ---------------------------------------------------------------------------
# Genuine bundles audit correctly
# ---------------------------------------------------------------------------


def test_genuine_ready_bundle_audits_consistent(genuine_ready_bundle):
    """A genuine READY bundle audits as CONSISTENT."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["published_bundle_status"] == "READY"
    assert audit["expected_bundle_status"] == "READY"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["audit_source"] == AUDIT_SOURCE


def test_genuine_blocked_bundle_audits_consistent(genuine_blocked_bundle):
    """A genuine BLOCKED bundle audits as CONSISTENT."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_blocked_bundle
    )
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["published_bundle_status"] == "BLOCKED"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["audit_source"] == AUDIT_SOURCE


def test_genuine_unavailable_bundle_audits_consistent(genuine_unavailable_bundle):
    """A genuine UNAVAILABLE bundle audits as CONSISTENT."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_unavailable_bundle
    )
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["audit_source"] == AUDIT_SOURCE


# ---------------------------------------------------------------------------
# Source forgery detection
# ---------------------------------------------------------------------------


def test_task_165_source_forge_detected(genuine_ready_bundle):
    """Forging the Task 165 bundle source is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.bundle_source = "FORGED_SOURCE"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "TASK_165_SOURCE_MISMATCH" in audit["findings"]


def test_task_162_source_forge_detected(genuine_ready_bundle):
    """Forging the Task 162 audit source is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.t162_audit_source = "FORGED_SOURCE"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "T162_SOURCE_MISMATCH" in audit["findings"]


def test_task_163_source_forge_detected(genuine_ready_bundle):
    """Forging the Task 163 certification source is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.certification_source = "FORGED_SOURCE"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "T163_SOURCE_MISMATCH" in audit["findings"]


def test_task_164_source_forge_detected(genuine_ready_bundle):
    """Forging the Task 164 audit source is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.audit_source = "FORGED_SOURCE"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "T164_SOURCE_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# Session tampering detection
# ---------------------------------------------------------------------------


def test_empty_session_detected(genuine_ready_bundle):
    """Empty session identity is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.session_id = ""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "SESSION_ID_MISMATCH" in audit["findings"]


def test_whitespace_session_detected(genuine_ready_bundle):
    """Whitespace-only session identity is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.session_id = "   "
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "SESSION_ID_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# Fingerprint tampering detection
# ---------------------------------------------------------------------------


def test_missing_fingerprint_detected(genuine_ready_bundle):
    """Missing fingerprint is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.request_fingerprint = None
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "FINGERPRINT_MISMATCH" in audit["findings"]


def test_malformed_fingerprint_detected(genuine_ready_bundle):
    """Malformed fingerprint is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.request_fingerprint = "invalid"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "FINGERPRINT_MISMATCH" in audit["findings"]


def test_uppercase_fingerprint_detected(genuine_ready_bundle):
    """Uppercase fingerprint is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.request_fingerprint = "A" * 64
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "FINGERPRINT_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# Provider/model tampering detection
# ---------------------------------------------------------------------------


def test_missing_provider_detected(genuine_ready_bundle):
    """Missing provider name is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.provider_name = None
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "PROVIDER_NAME_MISMATCH" in audit["findings"]


def test_missing_model_detected(genuine_ready_bundle):
    """Missing model name is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.model_name = None
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "MODEL_NAME_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# Status tampering detection
# ---------------------------------------------------------------------------


def test_forge_ready_under_blocking_evidence(genuine_blocked_bundle):
    """Forging READY when blocking evidence exists is detected."""
    tampered = copy.deepcopy(genuine_blocked_bundle)
    tampered.bundle_status = "READY"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_bundle_status"] == "BLOCKED"


def test_forge_blocked_under_ready_evidence(genuine_ready_bundle):
    """Forging BLOCKED when evidence supports READY is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.bundle_status = "BLOCKED"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_bundle_status"] == "READY"


def test_forge_unavailable_under_ready_evidence(genuine_ready_bundle):
    """Forging UNAVAILABLE when evidence supports READY is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.bundle_status = "UNAVAILABLE"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_bundle_status"] == "READY"


# ---------------------------------------------------------------------------
# Finding tampering detection
# ---------------------------------------------------------------------------


def test_findings_count_mismatch_detected(genuine_ready_bundle):
    """Finding count mismatch is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.finding_count = 1
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "FINDINGS_MISMATCH" in audit["findings"]


def test_findings_duplicate_detected(genuine_ready_bundle):
    """Duplicate findings are detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.findings = ["DUPLICATE", "DUPLICATE"]
    tampered.finding_count = 2
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "FINDINGS_MISMATCH" in audit["findings"]


def test_findings_unsorted_detected(genuine_ready_bundle):
    """Unsorted findings are detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.findings = ["ZEBRA", "ALPHA"]
    tampered.finding_count = 2
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "FINDINGS_MISMATCH" in audit["findings"]


def test_audit_findings_count_mismatch_detected(genuine_ready_bundle):
    """Audit finding count mismatch is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.audit_finding_count = 1
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "AUDIT_FINDINGS_MISMATCH" in audit["findings"]


def test_bundle_findings_count_mismatch_detected(genuine_ready_bundle):
    """Bundle finding count mismatch is detected."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.bundle_finding_count = 1
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# BLOCKED precedence
# ---------------------------------------------------------------------------


def test_blocked_precedence_over_ready(genuine_ready_bundle):
    """BLOCKED takes precedence over READY."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.slice_status = "BLOCKED"
    tampered.admission_status = "BLOCKED"
    tampered.finding_count = 1
    tampered.findings = ["BLOCKED_BY_ADMISSION"]
    tampered.bundle_status = "READY"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


def test_blocked_precedence_over_unavailable(genuine_unavailable_bundle):
    """BLOCKED takes precedence over UNAVAILABLE."""
    tampered = copy.deepcopy(genuine_unavailable_bundle)
    tampered.slice_status = "BLOCKED"
    tampered.admission_status = "BLOCKED"
    tampered.finding_count = 1
    tampered.findings = ["BLOCKED_BY_ADMISSION"]
    tampered.bundle_status = "UNAVAILABLE"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# READY completeness
# ---------------------------------------------------------------------------


def test_ready_requires_complete_evidence(genuine_ready_bundle):
    """READY requires all READY conditions to hold."""
    tampered = copy.deepcopy(genuine_ready_bundle)
    tampered.slice_status = "READY"
    tampered.admission_status = "UNAVAILABLE"
    tampered.bundle_status = "READY"
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# UNAVAILABLE validity
# ---------------------------------------------------------------------------


def test_unavailable_with_no_blockings_is_valid(genuine_unavailable_bundle):
    """UNAVAILABLE is valid when no blocking evidence exists."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_unavailable_bundle
    )
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_audit_schema_rejects_extra_fields(genuine_ready_bundle):
    """Audit schema rejects extra fields."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_audit_schema_rejects_missing_fields(genuine_ready_bundle):
    """Audit schema rejects missing fields."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    del audit["session_id"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_audit_available_consistent_enforced(genuine_ready_bundle):
    """available must equal (bundle_audit_status != 'UNAVAILABLE')."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["available"] = False
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_audit_consistent_enforced(genuine_ready_bundle):
    """consistent must equal (bundle_audit_status == 'CONSISTENT')."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["consistent"] = False
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_consistent_requires_status_match(genuine_ready_bundle):
    """CONSISTENT requires published and expected status to match."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["expected_bundle_status"] = "BLOCKED"
    with pytest.raises(ValidationError, match="CONSISTENT requires"):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_consistent_requires_no_findings(genuine_ready_bundle):
    """CONSISTENT requires a finding-free audit."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["findings"] = ["FORGED"]
    audit["finding_count"] = 1
    with pytest.raises(ValidationError, match="CONSISTENT requires"):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_inconsistent_requires_findings(genuine_ready_bundle):
    """INCONSISTENT requires at least one finding."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["bundle_audit_status"] = "INCONSISTENT"
    audit["available"] = True
    audit["consistent"] = False
    with pytest.raises(ValidationError, match="INCONSISTENT requires"):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_unavailable_requires_findings(genuine_ready_bundle):
    """UNAVAILABLE requires at least one diagnostic finding."""
    audit = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit["bundle_audit_status"] = "UNAVAILABLE"
    audit["available"] = False
    audit["consistent"] = False
    audit["session_id"] = ""
    audit["published_bundle_status"] = None
    audit["expected_bundle_status"] = None
    with pytest.raises(ValidationError, match="UNAVAILABLE requires"):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_audit_does_not_mutate_input(genuine_ready_bundle):
    """Audit does not mutate the input bundle."""
    original_dict = genuine_ready_bundle.model_dump()
    ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=genuine_ready_bundle)
    assert genuine_ready_bundle.model_dump() == original_dict


# ---------------------------------------------------------------------------
# Independence protections
# ---------------------------------------------------------------------------


def test_audit_is_pure_function(genuine_ready_bundle):
    """Audit is a pure function: same input produces same output."""
    audit1 = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    audit2 = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle=genuine_ready_bundle
    )
    assert audit1 == audit2


def test_audit_source_constant_is_correct():
    """Audit source constant is exported correctly."""
    assert (
        REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
        == "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166"
    )


# ---------------------------------------------------------------------------
# Helpers for the correction tests
# ---------------------------------------------------------------------------


def _audit(bundle):
    return ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=bundle)


def _tamper(bundle, **changes):
    """Copy a bundle and set fields directly, bypassing schema validation."""
    tampered = copy.deepcopy(bundle)
    for name, value in changes.items():
        setattr(tampered, name, value)
    return tampered


# ---------------------------------------------------------------------------
# 1. Findings are derived from evidence, never trusted
# ---------------------------------------------------------------------------


def test_fabricated_finding_cannot_hide_ready_evidence(genuine_ready_bundle):
    """A forged finding must not downgrade complete READY evidence."""
    tampered = _tamper(
        genuine_ready_bundle,
        bundle_status="UNAVAILABLE",
        bundle_findings=["FORGED_FINDING"],
        bundle_finding_count=1,
    )
    audit = _audit(tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "READY"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


def test_fabricated_finding_on_ready_bundle_is_detected(genuine_ready_bundle):
    """A forged finding on a published READY bundle is unsupported."""
    tampered = _tamper(
        genuine_ready_bundle,
        bundle_findings=["FORGED_FINDING"],
        bundle_finding_count=1,
    )
    audit = _audit(tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


def test_fabricated_finding_on_blocked_bundle_is_detected(genuine_blocked_bundle):
    """An unsupported finding is caught even when the bundle is BLOCKED."""
    tampered = _tamper(
        genuine_blocked_bundle,
        bundle_findings=["FORGED_FINDING"],
        bundle_finding_count=1,
    )
    audit = _audit(tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


def test_missing_warranted_finding_is_detected(genuine_unavailable_bundle):
    """A finding the evidence warrants cannot be withheld."""
    tampered = _tamper(
        genuine_unavailable_bundle,
        bundle_findings=["PROVIDER_ATTRIBUTION_MISSING"],
        bundle_finding_count=1,
    )
    audit = _audit(tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


def test_duplicate_bundle_findings_detected(genuine_unavailable_bundle):
    """Duplicate bundle findings are contradictory."""
    tampered = _tamper(
        genuine_unavailable_bundle,
        bundle_findings=[
            "PROVIDER_ATTRIBUTION_MISSING",
            "PROVIDER_ATTRIBUTION_MISSING",
            "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
        ],
        bundle_finding_count=3,
    )
    audit = _audit(tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


def test_unsorted_bundle_findings_detected(genuine_unavailable_bundle):
    """Unsorted bundle findings are contradictory."""
    tampered = _tamper(
        genuine_unavailable_bundle,
        bundle_findings=[
            "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
            "PROVIDER_ATTRIBUTION_MISSING",
        ],
    )
    audit = _audit(tampered)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


def test_genuine_session_mismatch_finding_is_accepted(genuine_ready_bundle):
    """An empty session explained by Task 165's finding is consistent."""
    bundle = _tamper(
        genuine_ready_bundle,
        session_id="",
        bundle_status="UNAVAILABLE",
        bundle_findings=["STAGE_7_SESSION_MISMATCH"],
        bundle_finding_count=1,
    )
    ReasoningRunStage7EvidenceBundleRead.model_validate(bundle.model_dump())
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["session_id"] == ""


def test_empty_session_without_finding_is_detected(genuine_ready_bundle):
    """An empty session Task 165 would have explained must be explained."""
    bundle = _tamper(genuine_ready_bundle, session_id="", bundle_status="UNAVAILABLE")
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


@pytest.mark.parametrize(
    ("field", "code", "finding"),
    [
        (
            "t162_audit_source",
            "T162_AUDIT_SOURCE_NOT_CANONICAL",
            "T162_SOURCE_MISMATCH",
        ),
        (
            "certification_source",
            "T163_CERTIFICATION_SOURCE_NOT_CANONICAL",
            "T163_SOURCE_MISMATCH",
        ),
        (
            "audit_source",
            "T164_AUDIT_SOURCE_NOT_CANONICAL",
            "T164_SOURCE_MISMATCH",
        ),
    ],
)
def test_explained_noncanonical_source_is_consistent(
    genuine_ready_bundle, field, code, finding
):
    """A non-canonical child source the bundle explains is a faithful bundle."""
    explained = _tamper(
        genuine_ready_bundle,
        bundle_status="UNAVAILABLE",
        bundle_findings=[code],
        bundle_finding_count=1,
        **{field: "FORGED_SOURCE"},
    )
    audit = _audit(explained)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    # The same source without the explaining finding is a forgery.
    unexplained = _tamper(
        genuine_ready_bundle, bundle_status="UNAVAILABLE", **{field: "FORGED_SOURCE"}
    )
    audit = _audit(unexplained)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert finding in audit["findings"]
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


def test_genuine_malformed_fingerprint_finding_is_accepted(genuine_ready_bundle):
    """A withheld fingerprint explained by Task 165's finding is consistent."""
    bundle = _tamper(
        genuine_ready_bundle,
        request_fingerprint=None,
        bundle_status="UNAVAILABLE",
        bundle_findings=["REQUEST_FINGERPRINT_MISSING_OR_MALFORMED"],
        bundle_finding_count=1,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"


def test_missing_attribution_on_attributed_slice_requires_finding(
    genuine_blocked_bundle,
):
    """READY/BLOCKED slices publish package attribution, so absence is warranted."""
    bundle = _tamper(genuine_blocked_bundle, provider_name=None, model_name=None)
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]
    explained = _tamper(
        bundle,
        bundle_findings=["PROVIDER_ATTRIBUTION_MISSING"],
        bundle_finding_count=1,
    )
    audit = _audit(explained)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["expected_bundle_status"] == "BLOCKED"


def test_attribution_finding_is_optional_for_unavailable_slice(
    genuine_unavailable_bundle,
):
    """An UNAVAILABLE slice hides package attribution, so either way is faithful."""
    without = _tamper(
        genuine_unavailable_bundle,
        bundle_findings=[
            "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
            "STAGE_7_SESSION_MISMATCH",
        ],
        bundle_finding_count=2,
    )
    assert _audit(without)["bundle_audit_status"] == "CONSISTENT"
    assert _audit(genuine_unavailable_bundle)["bundle_audit_status"] == "CONSISTENT"


def test_attribution_finding_unsupported_when_attribution_present(
    genuine_blocked_bundle,
):
    """The attribution finding cannot be claimed while attribution is published."""
    bundle = _tamper(
        genuine_blocked_bundle,
        bundle_findings=["PROVIDER_ATTRIBUTION_MISSING"],
        bundle_finding_count=1,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# 2. Task 164 semantic coherence, in every outer bundle state
# ---------------------------------------------------------------------------


def test_slice_audit_consistent_with_contradictory_statuses_ready(
    genuine_ready_bundle,
):
    """CONSISTENT Task 164 audit cannot publish different slice statuses."""
    bundle = _tamper(genuine_ready_bundle, published_slice_status="BLOCKED")
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "PUBLISHED_SLICE_STATUS_MISMATCH" in audit["findings"]
    assert "EXPECTED_SLICE_STATUS_MISMATCH" in audit["findings"]


def test_slice_audit_consistent_with_contradictory_statuses_blocked(
    genuine_blocked_bundle,
):
    """The reviewer's contradiction passes the outer status but not the audit."""
    bundle = _tamper(genuine_blocked_bundle, expected_slice_status="READY")
    audit = _audit(bundle)
    assert audit["published_bundle_status"] == "BLOCKED"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["EXPECTED_SLICE_STATUS_MISMATCH"]


def test_slice_audit_consistent_with_contradictory_statuses_unavailable(
    genuine_unavailable_bundle,
):
    """A CONSISTENT Task 164 audit with contradictory statuses is caught."""
    bundle = _tamper(
        genuine_unavailable_bundle,
        slice_audit_status="CONSISTENT",
        audit_available=True,
        audit_consistent=True,
        published_slice_status="BLOCKED",
        expected_slice_status="READY",
        audit_finding_count=0,
        audit_findings=[],
    )
    audit = _audit(bundle)
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "EXPECTED_SLICE_STATUS_MISMATCH" in audit["findings"]
    assert "PUBLISHED_SLICE_STATUS_MISMATCH" in audit["findings"]


def test_published_slice_status_must_match_task_163_status(genuine_blocked_bundle):
    """The Task 164 published status must agree with Task 163's slice status."""
    bundle = _tamper(
        genuine_blocked_bundle,
        published_slice_status="READY",
        expected_slice_status="READY",
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["PUBLISHED_SLICE_STATUS_MISMATCH"]


@pytest.mark.parametrize(
    "fixture_name", ["genuine_blocked_bundle", "genuine_ready_bundle"]
)
def test_slice_audit_consistent_with_findings_detected(fixture_name, request):
    """A CONSISTENT Task 164 audit must be finding-free."""
    bundle = _tamper(
        request.getfixturevalue(fixture_name),
        audit_findings=["SLICE_STATUS_MISMATCH"],
        audit_finding_count=1,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in audit["findings"]


def test_slice_audit_inconsistent_requires_findings(genuine_blocked_bundle):
    """An INCONSISTENT Task 164 audit needs finding evidence."""
    bundle = _tamper(
        genuine_blocked_bundle,
        slice_audit_status="INCONSISTENT",
        audit_consistent=False,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["AUDIT_STATUS_MISMATCH"]


def test_genuine_slice_audit_inconsistent_is_accepted(genuine_blocked_bundle):
    """A coherent INCONSISTENT Task 164 audit is not a false positive."""
    bundle = _tamper(
        genuine_blocked_bundle,
        slice_audit_status="INCONSISTENT",
        audit_consistent=False,
        expected_slice_status="READY",
        audit_findings=["SLICE_STATUS_MISMATCH"],
        audit_finding_count=1,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["expected_bundle_status"] == "BLOCKED"


def test_slice_audit_unavailable_must_not_name_statuses(genuine_unavailable_bundle):
    """An UNAVAILABLE Task 164 audit compared nothing and names no status."""
    for field in ("published_slice_status", "expected_slice_status"):
        bundle = _tamper(genuine_unavailable_bundle, **{field: "UNAVAILABLE"})
        audit = _audit(bundle)
        assert audit["bundle_audit_status"] == "INCONSISTENT"
        assert any(f.endswith("_SLICE_STATUS_MISMATCH") for f in audit["findings"])


def test_slice_audit_unavailable_requires_diagnostic_findings(
    genuine_unavailable_bundle,
):
    """An UNAVAILABLE Task 164 audit must carry its diagnostic findings."""
    bundle = _tamper(
        genuine_unavailable_bundle, audit_findings=[], audit_finding_count=0
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["AUDIT_STATUS_MISMATCH"]


def test_slice_audit_flags_must_follow_status_when_not_ready(genuine_blocked_bundle):
    """available/consistent contradictions are caught outside READY bundles."""
    audit = _audit(_tamper(genuine_blocked_bundle, audit_available=False))
    assert "AUDIT_AVAILABLE_MISMATCH" in audit["findings"]
    audit = _audit(_tamper(genuine_blocked_bundle, audit_consistent=False))
    assert "AUDIT_CONSISTENT_MISMATCH" in audit["findings"]


def test_unknown_slice_audit_status_detected(genuine_blocked_bundle):
    """An unknown Task 164 status is a deterministic contradiction."""
    audit = _audit(_tamper(genuine_blocked_bundle, slice_audit_status="FORGED"))
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# 3. Direct schema enforcement of the canonical audit source
# ---------------------------------------------------------------------------


def _audit_payloads(genuine_ready_bundle):
    consistent = _audit(genuine_ready_bundle)
    inconsistent = _audit(_tamper(genuine_ready_bundle, bundle_status="BLOCKED"))
    unavailable = _audit(None)
    assert consistent["bundle_audit_status"] == "CONSISTENT"
    assert inconsistent["bundle_audit_status"] == "INCONSISTENT"
    assert unavailable["bundle_audit_status"] == "UNAVAILABLE"
    return [consistent, inconsistent, unavailable]


@pytest.mark.parametrize(
    "forged",
    [
        "FORGED_AUDIT_SOURCE",
        "",
        "   ",
        AUDIT_SOURCE + "\n",
    ],
    ids=["forged", "empty", "whitespace", "trailing-newline"],
)
def test_schema_rejects_forged_audit_source(genuine_ready_bundle, forged):
    """Every audit status must carry exactly the canonical Task 166 source."""
    for payload in _audit_payloads(genuine_ready_bundle):
        tampered = {**payload, "audit_source": forged}
        with pytest.raises(ValidationError, match="audit_source must be"):
            ReasoningRunStage7EvidenceBundleAuditRead.model_validate(tampered)


def test_schema_accepts_canonical_audit_source_for_every_status(
    genuine_ready_bundle,
):
    """The canonical source is accepted for CONSISTENT, INCONSISTENT, UNAVAILABLE."""
    for payload in _audit_payloads(genuine_ready_bundle):
        assert payload["audit_source"] == AUDIT_SOURCE
        validated = ReasoningRunStage7EvidenceBundleAuditRead.model_validate(payload)
        assert validated.audit_source == AUDIT_SOURCE


def test_schema_still_forbids_extra_fields_and_requires_source(genuine_ready_bundle):
    """audit_source stays required and extra fields stay forbidden."""
    payload = _audit(genuine_ready_bundle)
    del payload["audit_source"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditRead.model_validate(payload)


def test_schema_unavailable_must_not_name_statuses_or_session(genuine_ready_bundle):
    """UNAVAILABLE results claim no verified status and no session identity."""
    payload = _audit(None)
    for field, value in (
        ("published_bundle_status", "READY"),
        ("expected_bundle_status", "READY"),
        ("session_id", "some-session"),
    ):
        with pytest.raises(ValidationError, match="UNAVAILABLE must not"):
            ReasoningRunStage7EvidenceBundleAuditRead.model_validate(
                {**payload, field: value}
            )


@pytest.mark.parametrize("field", ["published_bundle_status", "expected_bundle_status"])
def test_schema_compared_audit_requires_both_statuses(genuine_ready_bundle, field):
    """CONSISTENT and INCONSISTENT audits must name both concrete statuses."""
    for payload in _audit_payloads(genuine_ready_bundle)[:2]:
        with pytest.raises(ValidationError, match="requires both bundle statuses"):
            ReasoningRunStage7EvidenceBundleAuditRead.model_validate(
                {**payload, field: None}
            )


# ---------------------------------------------------------------------------
# 4. Missing and malformed input is UNAVAILABLE
# ---------------------------------------------------------------------------


def _assert_unavailable(audit, marker):
    assert audit["bundle_audit_status"] == "UNAVAILABLE"
    assert audit["available"] is False
    assert audit["consistent"] is False
    assert audit["session_id"] == ""
    assert audit["published_bundle_status"] is None
    assert audit["expected_bundle_status"] is None
    assert audit["finding_count"] == 1
    assert len(audit["findings"]) == 1
    assert audit["findings"][0].startswith(marker)
    assert audit["audit_source"] == AUDIT_SOURCE
    ReasoningRunStage7EvidenceBundleAuditRead.model_validate(audit)


def test_missing_bundle_is_unavailable():
    """No bundle at all is unavailable material."""
    _assert_unavailable(_audit(None), "TASK_165_BUNDLE_MISSING")
    _assert_unavailable(
        ReasoningRunStage7EvidenceBundleAuditService.audit(),
        "TASK_165_BUNDLE_MISSING",
    )


@pytest.mark.parametrize(
    "malformed",
    ["not a bundle", 42, [], {}, {"session_id": "x"}, SimpleNamespace(session_id="x")],
    ids=["str", "int", "list", "empty-mapping", "partial-mapping", "namespace"],
)
def test_malformed_bundle_is_unavailable(malformed):
    """Wrong-typed or incomplete input never raises; it is unavailable."""
    _assert_unavailable(_audit(malformed), "TASK_165_BUNDLE_INVALID")


def test_mapping_with_extra_field_is_unavailable(genuine_ready_bundle):
    """A mapping must satisfy the Task 165 contract, which forbids extras."""
    payload = {**genuine_ready_bundle.model_dump(), "unexpected": "value"}
    _assert_unavailable(_audit(payload), "TASK_165_BUNDLE_INVALID")


def test_bundle_missing_fields_is_unavailable():
    """A bundle object that lacks published fields is unreadable."""
    constructed = ReasoningRunStage7EvidenceBundleRead.model_construct(session_id="x")
    _assert_unavailable(_audit(constructed), "TASK_165_BUNDLE_INVALID")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("findings", None),
        ("bundle_findings", "not-a-list"),
        ("audit_findings", [1, 2]),
        ("finding_count", "0"),
        ("bundle_finding_count", True),
        ("audit_available", "yes"),
        ("session_id", None),
        ("bundle_status", "FORGED"),
        ("bundle_status", None),
        ("request_fingerprint", 123),
    ],
)
def test_bundle_with_malformed_field_types_is_unavailable(
    genuine_ready_bundle, field, value
):
    """Unreadable field types are unavailable material, never an AttributeError."""
    audit = _audit(_tamper(genuine_ready_bundle, **{field: value}))
    _assert_unavailable(audit, "TASK_165_BUNDLE_INVALID")
    assert audit["findings"][0].startswith(f"TASK_165_BUNDLE_INVALID:{field}")


def test_unavailable_diagnostic_never_echoes_published_values(genuine_ready_bundle):
    """Diagnostics name fields and reasons only, never published content."""
    payload = {**genuine_ready_bundle.model_dump(), "session_id": "SECRET-RAW-TEXT"}
    payload["bundle_status"] = "SECRET-STATUS"
    audit = _audit(payload)
    assert "SECRET" not in repr(audit)


def test_valid_mapping_audits_like_the_typed_bundle(genuine_ready_bundle):
    """A contract-valid mapping is read exactly as the typed bundle."""
    assert _audit(genuine_ready_bundle.model_dump()) == _audit(genuine_ready_bundle)


def test_consistent_published_evidence_is_consistent(
    genuine_ready_bundle, genuine_blocked_bundle, genuine_unavailable_bundle
):
    """Published evidence that matches its derivation is CONSISTENT."""
    for bundle in (
        genuine_ready_bundle,
        genuine_blocked_bundle,
        genuine_unavailable_bundle,
    ):
        audit = _audit(bundle)
        assert audit["bundle_audit_status"] == "CONSISTENT"
        assert audit["published_bundle_status"] == audit["expected_bundle_status"]
        assert audit["findings"] == []


def test_contract_valid_bundle_with_forged_finding_is_inconsistent(
    genuine_ready_bundle,
):
    """Valid published evidence contradicting its claimed status is INCONSISTENT."""
    payload = {
        **genuine_ready_bundle.model_dump(),
        "bundle_status": "UNAVAILABLE",
        "bundle_findings": ["FORGED_FINDING"],
        "bundle_finding_count": 1,
    }
    # The Task 165 contract itself accepts this bundle ...
    ReasoningRunStage7EvidenceBundleRead.model_validate(payload)
    # ... which is exactly why the audit must not trust it.
    audit = _audit(payload)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is False
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "READY"
    assert "BUNDLE_FINDING_MISMATCH" in audit["findings"]
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


def test_unavailable_input_is_distinct_from_contradictory_evidence(
    genuine_ready_bundle,
):
    """Malformed input and contradictory evidence yield different verdicts."""
    contradictory = _audit(_tamper(genuine_ready_bundle, bundle_status="BLOCKED"))
    unreadable = _audit(_tamper(genuine_ready_bundle, bundle_status="FORGED"))
    assert contradictory["bundle_audit_status"] == "INCONSISTENT"
    assert unreadable["bundle_audit_status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# 5. Independence and architectural boundaries
# ---------------------------------------------------------------------------


def test_audit_calls_no_child_service(genuine_ready_bundle, monkeypatch):
    """The audit never calls Task 165 or any Task 162-164 service."""
    from rop.services.reasoning_run_stage_7_audit_package import (
        ReasoningRunStage7AuditPackageService,
    )
    from rop.services.reasoning_run_stage_7_evidence_bundle import (
        ReasoningRunStage7EvidenceBundleService,
    )
    from rop.services.reasoning_run_stage_7_vertical_slice import (
        ReasoningRunStage7VerticalSliceService,
    )
    from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditService,
    )

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("child service must not be called")

    for service, method in (
        (ReasoningRunStage7EvidenceBundleService, "assemble"),
        (ReasoningRunStage7VerticalSliceAuditService, "audit"),
        (ReasoningRunStage7VerticalSliceService, "certify"),
        (ReasoningRunStage7AuditPackageService, "assemble"),
    ):
        if hasattr(service, method):
            monkeypatch.setattr(service, method, staticmethod(_forbidden))
    assert _audit(genuine_ready_bundle)["bundle_audit_status"] == "CONSISTENT"
    assert _audit(None)["bundle_audit_status"] == "UNAVAILABLE"


def test_audit_modules_have_no_provider_database_network_or_hashing_imports():
    """The audit stays provider-neutral, offline, and never recomputes hashes."""
    from rop.schemas import reasoning_run_stage_7_evidence_bundle_audit as schema
    from rop.services import reasoning_run_stage_7_evidence_bundle_audit as service

    forbidden_roots = {
        "hashlib",
        "hmac",
        "os",
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "sqlalchemy",
        "openai",
        "anthropic",
    }
    for module in (schema, service):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                # No child service class may be imported by the service module.
                if module is service:
                    for alias in node.names:
                        assert not alias.name.endswith("Service"), alias.name
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in forbidden_roots, name
        # Environment-based provider selection is out of scope.
        assert "environ" not in inspect.getsource(module)
        assert "getenv" not in inspect.getsource(module)


def test_audit_does_not_mutate_input_for_unavailable_and_inconsistent(
    genuine_ready_bundle,
):
    """No audit path mutates the bundle it reads."""
    tampered = _tamper(genuine_ready_bundle, bundle_status="BLOCKED")
    snapshot = tampered.model_dump()
    _audit(tampered)
    assert tampered.model_dump() == snapshot
    payload = genuine_ready_bundle.model_dump()
    payload_snapshot = copy.deepcopy(payload)
    _audit(payload)
    assert payload == payload_snapshot


def test_audit_results_expose_no_raw_provider_material(genuine_ready_bundle):
    """The audit result has a fixed, finding-code-only surface."""
    expected_keys = {
        "session_id",
        "bundle_audit_status",
        "available",
        "consistent",
        "published_bundle_status",
        "expected_bundle_status",
        "finding_count",
        "findings",
        "audit_source",
    }
    for payload in _audit_payloads(genuine_ready_bundle):
        assert set(payload) == expected_keys


# ---------------------------------------------------------------------------
# Session-identity coherence in every aggregate status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [" ", "   ", "\t", "\n"])
def test_blocked_bundle_with_blank_session_and_no_finding_is_inconsistent(
    genuine_blocked_bundle, blank
):
    """A blank session cannot pass as CONSISTENT just because the bundle is BLOCKED."""
    audit = _audit(_tamper(genuine_blocked_bundle, session_id=blank))
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert audit["published_bundle_status"] == "BLOCKED"
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["BUNDLE_FINDING_MISMATCH", "SESSION_ID_MISMATCH"]


@pytest.mark.parametrize("blank", ["", " ", "   "])
def test_unavailable_bundle_with_blank_session_and_no_finding_is_inconsistent(
    genuine_ready_bundle, blank
):
    """A blank session is not excused by an UNAVAILABLE bundle status."""
    bundle = _tamper(
        genuine_ready_bundle, session_id=blank, bundle_status="UNAVAILABLE"
    )
    audit = _audit(bundle)
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["BUNDLE_FINDING_MISMATCH", "SESSION_ID_MISMATCH"]


@pytest.mark.parametrize("blank", ["", " ", "   "])
def test_blank_session_with_required_finding_is_faithfully_audited(
    genuine_blocked_bundle, blank
):
    """A blank session explained by the canonical finding stays consistent."""
    bundle = _tamper(
        genuine_blocked_bundle,
        session_id=blank,
        bundle_findings=["STAGE_7_SESSION_MISMATCH"],
        bundle_finding_count=1,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["published_bundle_status"] == "BLOCKED"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert audit["findings"] == []


def test_blank_session_never_audits_as_ready(genuine_ready_bundle):
    """A READY claim over a blank session is a contradiction even if explained."""
    bundle = _tamper(
        genuine_ready_bundle,
        session_id=" ",
        bundle_findings=["STAGE_7_SESSION_MISMATCH"],
        bundle_finding_count=1,
    )
    audit = _audit(bundle)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert "SESSION_ID_MISMATCH" in audit["findings"]
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


def test_unavailable_slice_audit_with_nonblank_session_is_inconsistent(
    genuine_unavailable_bundle,
):
    """Task 164 UNAVAILABLE cannot bind a nonblank common session."""
    bundle = _tamper(
        genuine_unavailable_bundle,
        session_id=str(uuid4()),
        bundle_findings=[
            "PROVIDER_ATTRIBUTION_MISSING",
            "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
        ],
        bundle_finding_count=2,
    )
    audit = _audit(bundle)
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["findings"] == ["SESSION_ID_MISMATCH"]


def test_unavailable_slice_audit_with_nonblank_session_is_inconsistent_when_blocked(
    genuine_unavailable_bundle,
):
    """The Task 164 session binding is checked under a BLOCKED outer status too."""
    bundle = _tamper(
        genuine_unavailable_bundle,
        session_id=str(uuid4()),
        slice_status="BLOCKED",
        admission_status="BLOCKED",
        bundle_status="BLOCKED",
        bundle_findings=[],
        bundle_finding_count=0,
        provider_name="test-provider",
        model_name="test-model",
        request_fingerprint="a" * 64,
    )
    audit = _audit(bundle)
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "SESSION_ID_MISMATCH" in audit["findings"]


def test_genuine_unavailable_slice_audit_with_blank_session_is_accepted(
    genuine_unavailable_bundle,
):
    """Task 164 UNAVAILABLE with a blank session and its finding is faithful."""
    assert genuine_unavailable_bundle.session_id == ""
    assert genuine_unavailable_bundle.slice_audit_status == "UNAVAILABLE"
    assert "STAGE_7_SESSION_MISMATCH" in genuine_unavailable_bundle.bundle_findings
    audit = _audit(genuine_unavailable_bundle)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["session_id"] == ""
    assert audit["findings"] == []


def test_session_findings_are_sorted_and_deduplicated(genuine_blocked_bundle):
    """Session findings join the sorted, deduplicated finding list."""
    bundle = _tamper(genuine_blocked_bundle, session_id=" ", bundle_findings=[])
    audit = _audit(bundle)
    assert audit["findings"] == sorted(set(audit["findings"]))
    assert audit["finding_count"] == len(audit["findings"])

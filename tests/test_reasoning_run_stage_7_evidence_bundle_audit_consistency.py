"""Task 167: Stage 7 evidence-bundle audit consistency tests.

Independent consistency boundary between Task 165 Evidence Bundle and
Task 166 Evidence-Bundle Audit. The service verifies exact binding of
session identity, bundle status, bundle evidence, published versus expected
status, audit status, and audit source.

The consistency check is pure and independent: it never calls Task 165
or Task 166 services, never recomputes fingerprints, never invokes a
provider, and never accesses a database.
"""

from __future__ import annotations

import copy
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
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyService,
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

CONSISTENCY_SOURCE = (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
)


@pytest.fixture
def ready_bundle() -> ReasoningRunStage7EvidenceBundleRead:
    """A READY bundle for testing."""
    session_id = str(uuid4())
    return ReasoningRunStage7EvidenceBundleRead(
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
        request_fingerprint="a" * 64,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        bundle_status="READY",
        bundle_finding_count=0,
        bundle_findings=[],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )


@pytest.fixture
def ready_audit(
    ready_bundle: ReasoningRunStage7EvidenceBundleRead,
) -> ReasoningRunStage7EvidenceBundleAuditRead:
    """A CONSISTENT audit for the READY bundle."""
    return ReasoningRunStage7EvidenceBundleAuditRead(
        session_id=ready_bundle.session_id,
        bundle_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_bundle_status="READY",
        expected_bundle_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    )


# ---------------------------------------------------------------------------
# Genuine consistency
# ---------------------------------------------------------------------------


def test_genuine_ready_bundle_with_consistent_audit_is_consistent(
    ready_bundle, ready_audit
):
    """A genuine READY bundle with a CONSISTENT audit is CONSISTENT."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    assert consistency["consistency_status"] == "CONSISTENT"
    assert consistency["available"] is True
    assert consistency["consistent"] is True
    assert consistency["finding_count"] == 0
    assert consistency["findings"] == []
    assert consistency["consistency_source"] == CONSISTENCY_SOURCE


# ---------------------------------------------------------------------------
# Session mismatch detection
# ---------------------------------------------------------------------------


def test_session_mismatch_detected(ready_bundle, ready_audit):
    """Session mismatch between bundle and audit is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = str(uuid4())
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Published status mismatch detection
# ---------------------------------------------------------------------------


def test_published_status_mismatch_detected(ready_bundle, ready_audit):
    """Published status mismatch is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.published_bundle_status = "BLOCKED"
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Expected status contradiction detection
# ---------------------------------------------------------------------------


def test_expected_status_contradiction_detected(ready_bundle, ready_audit):
    """Expected status contradiction is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.expected_bundle_status = "BLOCKED"
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]


# ---------------------------------------------------------------------------
# Audit status mismatch detection
# ---------------------------------------------------------------------------


def test_audit_status_mismatch_for_ready(ready_bundle, ready_audit):
    """Audit status mismatch for READY bundle is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.bundle_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["FORGED"]
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Audit source mismatch detection
# ---------------------------------------------------------------------------


def test_audit_source_mismatch_detected(ready_bundle, ready_audit):
    """Audit source mismatch is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.audit_source = "FORGED_SOURCE"
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Finding count mismatch detection
# ---------------------------------------------------------------------------


def test_finding_count_mismatch_bundle_has_findings(ready_bundle, ready_audit):
    """Finding count mismatch when bundle has findings is detected."""
    tampered_bundle = copy.deepcopy(ready_bundle)
    tampered_bundle.bundle_finding_count = 1
    tampered_bundle.bundle_findings = ["SOME_FINDING"]
    tampered_bundle.bundle_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=tampered_bundle, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in consistency["findings"]


def test_finding_count_mismatch_audit_has_findings(ready_bundle, ready_audit):
    """Finding count mismatch when audit has findings is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_FINDING"]
    tampered_audit.bundle_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_consistency_schema_rejects_extra_fields(ready_bundle, ready_audit):
    """Consistency schema rejects extra fields."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


def test_consistency_schema_rejects_missing_fields(ready_bundle, ready_audit):
    """Consistency schema rejects missing fields."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    del consistency["session_id"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


def test_consistency_available_consistent_enforced(ready_bundle, ready_audit):
    """available must equal (consistency_status != 'UNAVAILABLE')."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency["available"] = False
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


def test_consistency_consistent_enforced(ready_bundle, ready_audit):
    """consistent must equal (consistency_status == 'CONSISTENT')."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


def test_consistent_requires_no_findings(ready_bundle, ready_audit):
    """CONSISTENT requires a finding-free consistency check."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency["findings"] = ["FORGED"]
    consistency["finding_count"] = 1
    with pytest.raises(ValidationError, match="CONSISTENT requires"):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


def test_inconsistent_requires_findings(ready_bundle, ready_audit):
    """INCONSISTENT requires at least one finding."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency["consistency_status"] = "INCONSISTENT"
    consistency["available"] = True
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="INCONSISTENT requires"):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


def test_unavailable_requires_findings(ready_bundle, ready_audit):
    """UNAVAILABLE requires at least one diagnostic finding."""
    consistency = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency["consistency_status"] = "UNAVAILABLE"
    consistency["available"] = False
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="UNAVAILABLE requires"):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(consistency)


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_consistency_does_not_mutate_inputs(ready_bundle, ready_audit):
    """Consistency check does not mutate inputs."""
    original_bundle = ready_bundle.model_dump()
    original_audit = ready_audit.model_dump()
    ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    assert ready_bundle.model_dump() == original_bundle
    assert ready_audit.model_dump() == original_audit


# ---------------------------------------------------------------------------
# Independence protections
# ---------------------------------------------------------------------------


def test_consistency_is_pure_function(ready_bundle, ready_audit):
    """Consistency check is a pure function."""
    consistency1 = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    consistency2 = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=ready_bundle, audit=ready_audit
    )
    assert consistency1 == consistency2


def test_consistency_source_constant_is_correct():
    """Consistency source constant is exported correctly."""
    assert CONSISTENCY_SOURCE == (
        "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_TASK_167"
    )

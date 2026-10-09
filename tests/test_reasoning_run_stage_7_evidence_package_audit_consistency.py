"""Task 170: Stage 7 evidence-package audit consistency tests.

Independent consistency boundary between Task 168 Evidence Package and
Task 169 Evidence-Package Audit. The service verifies exact binding of
session identity, package status, package source, evidence presence,
findings, finding counts, published versus expected status, audit source,
and audit status.

The consistency check is pure and independent: it never calls Task 168
or Task 169 services, never recomputes fingerprints, never invokes a
provider, and never accesses a database.
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
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit_consistency import (
    ReasoningRunStage7EvidencePackageAuditConsistencyService,
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
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
)


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
def ready_audit(
    ready_package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageAuditRead:
    """A CONSISTENT audit for the READY package."""
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


# ---------------------------------------------------------------------------
# Genuine consistency
# ---------------------------------------------------------------------------


def test_genuine_ready_package_with_consistent_audit_is_consistent(
    ready_package, ready_audit
):
    """A genuine READY package with a CONSISTENT audit is CONSISTENT."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
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


def test_session_mismatch_detected(ready_package, ready_audit):
    """Session mismatch between package and audit is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = str(uuid4())
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]


def test_cross_session_audit_detected(ready_package, ready_audit):
    """Audit from different session is detected as inconsistent."""
    different_session = str(uuid4())
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = different_session
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Source forgery detection
# ---------------------------------------------------------------------------


def test_package_source_mismatch_detected(ready_package, ready_audit):
    """Package source forgery is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.package_source = "FORGED_PACKAGE_SOURCE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PACKAGE_SOURCE_MISMATCH" in consistency["findings"]


def test_audit_source_mismatch_detected(ready_package, ready_audit):
    """Audit source forgery is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.audit_source = "FORGED_AUDIT_SOURCE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Status mismatch detection
# ---------------------------------------------------------------------------


def test_published_status_mismatch_detected(ready_package, ready_audit):
    """Published status mismatch is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.published_package_status = "BLOCKED"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]


def test_expected_status_contradiction_detected(ready_package, ready_audit):
    """Expected status contradiction is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.expected_package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]


def test_forged_package_status_detected(ready_package, ready_audit):
    """Forged package status (not matching expected) is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.package_status = "BLOCKED"
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.published_package_status = "BLOCKED"
    tampered_audit.expected_package_status = "READY"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]


# ---------------------------------------------------------------------------
# Audit status detection
# ---------------------------------------------------------------------------


def test_audit_not_consistent_detected(ready_package, ready_audit):
    """Audit that is not CONSISTENT is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_ISSUE"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]


def test_unavailable_audit_detected(ready_package, ready_audit):
    """UNAVAILABLE audit is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.package_audit_status = "UNAVAILABLE"
    tampered_audit.available = False
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["UNAVAILABLE_REASON"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]


# ---------------------------------------------------------------------------
# Finding count mismatch detection
# ---------------------------------------------------------------------------


def test_finding_count_mismatch_package_has_findings(ready_package, ready_audit):
    """Finding count mismatch when package has findings is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.finding_count = 1
    tampered_package.findings = ["SOME_FINDING"]
    tampered_package.package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in consistency["findings"]


def test_finding_count_mismatch_audit_has_findings(ready_package, ready_audit):
    """Finding count mismatch when audit has findings is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_FINDING"]
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in consistency["findings"]


def test_same_session_different_content_detected(ready_package, ready_audit):
    """Same session but different content is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.t162_admission_status = "BLOCKED"
    tampered_package.package_status = "BLOCKED"
    # Audit still says READY
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Evidence presence detection
# ---------------------------------------------------------------------------


def test_audit_unavailable_flag_detected(ready_package, ready_audit):
    """Audit with unavailable=False is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.available = False
    tampered_audit.package_audit_status = "UNAVAILABLE"
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["UNAVAILABLE"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_UNAVAILABLE" in consistency["findings"]


def test_audit_inconsistent_flag_detected(ready_package, ready_audit):
    """Audit with consistent=False is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.consistent = False
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_ISSUE"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_INCONSISTENT" in consistency["findings"]


def test_package_empty_session_detected(ready_package, ready_audit):
    """Package with empty session_id is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.session_id = ""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = ""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PACKAGE_SESSION_EMPTY" in consistency["findings"]


# ---------------------------------------------------------------------------
# Adversarial tests
# ---------------------------------------------------------------------------


def test_detached_audit_from_different_package(ready_package, ready_audit):
    """Detached audit from a completely different package is detected."""
    different_session = str(uuid4())
    detached_audit = copy.deepcopy(ready_audit)
    detached_audit.session_id = different_session
    detached_audit.published_package_status = "BLOCKED"
    detached_audit.expected_package_status = "BLOCKED"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=detached_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]


def test_finding_tampering_detected(ready_package, ready_audit):
    """Finding tampering across package and audit is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.finding_count = 2
    tampered_package.findings = ["FINDING_A", "FINDING_B"]
    tampered_package.package_status = "UNAVAILABLE"
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["FINDING_C"]
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    tampered_audit.published_package_status = "UNAVAILABLE"
    tampered_audit.expected_package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    # Both have findings, so this is acceptable, but the audit status is not CONSISTENT
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]


def test_multiple_forgeries_detected(ready_package, ready_audit):
    """Multiple forgeries are all detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.package_source = "FORGED"
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.audit_source = "FORGED"
    tampered_audit.published_package_status = "BLOCKED"
    tampered_audit.expected_package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PACKAGE_SOURCE_MISMATCH" in consistency["findings"]
    assert "AUDIT_SOURCE_MISMATCH" in consistency["findings"]
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_consistency_schema_rejects_extra_fields(ready_package, ready_audit):
    """Consistency schema rejects extra fields."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_schema_rejects_missing_fields(ready_package, ready_audit):
    """Consistency schema rejects missing fields."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    del consistency["session_id"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_available_consistent_enforced(ready_package, ready_audit):
    """available must equal (consistency_status != 'UNAVAILABLE')."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["available"] = False
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_consistent_enforced(ready_package, ready_audit):
    """consistent must equal (consistency_status == 'CONSISTENT')."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistent_requires_no_findings(ready_package, ready_audit):
    """CONSISTENT requires a finding-free consistency check."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["findings"] = ["FORGED"]
    consistency["finding_count"] = 1
    with pytest.raises(ValidationError, match="CONSISTENT requires"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_inconsistent_requires_findings(ready_package, ready_audit):
    """INCONSISTENT requires at least one finding."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistency_status"] = "INCONSISTENT"
    consistency["available"] = True
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="INCONSISTENT requires"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_unavailable_requires_findings(ready_package, ready_audit):
    """UNAVAILABLE requires at least one diagnostic finding."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistency_status"] = "UNAVAILABLE"
    consistency["available"] = False
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="UNAVAILABLE requires"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_consistency_does_not_mutate_inputs(ready_package, ready_audit):
    """Consistency check does not mutate inputs."""
    original_package = ready_package.model_dump()
    original_audit = ready_audit.model_dump()
    ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    assert ready_package.model_dump() == original_package
    assert ready_audit.model_dump() == original_audit


# ---------------------------------------------------------------------------
# Independence protections
# ---------------------------------------------------------------------------


def test_consistency_is_pure_function(ready_package, ready_audit):
    """Consistency check is a pure function."""
    consistency1 = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency2 = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    assert consistency1 == consistency2


def test_consistency_source_constant_is_correct():
    """Consistency source constant is exported correctly."""
    assert CONSISTENCY_SOURCE == (
        "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_170"
    )


def test_no_provider_invocation():
    """Service never invokes provider or network."""
    # This is a structural test - the service signature accepts only
    # validated Pydantic objects and has no DB session or provider parameter
    import inspect

    sig = inspect.signature(
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify
    )
    param_names = list(sig.parameters.keys())
    assert "db" not in param_names
    assert "session" not in param_names
    assert "provider" not in param_names
    assert "client" not in param_names


def test_no_mutation():
    """Service never performs mutation."""
    # This is a structural test - the service returns a dict,
    # not a database object or mutated input
    import inspect

    sig = inspect.signature(
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify
    )
    return_annotation = sig.return_annotation
    assert "dict" in str(return_annotation).lower()

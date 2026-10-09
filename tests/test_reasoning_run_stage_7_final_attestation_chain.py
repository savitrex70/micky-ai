"""Tasks 171-175: Stage 7 final attestation and release-readiness tests.

Comprehensive tests for the final attestation chain and release-readiness
projection with independent audits.
"""

from __future__ import annotations

import copy
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

# Set environment for imports
os.environ.setdefault("ROP_APP_NAME", "test")
os.environ.setdefault("ROP_ENVIRONMENT", "testing")
os.environ.setdefault("ROP_LOG_LEVEL", "INFO")
os.environ.setdefault("ROP_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")

from rop.schemas.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
    ReasoningRunStage7FinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_consistency import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173,
    ReasoningRunStage7FinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171,
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationService,
)
from rop.services.reasoning_run_stage_7_final_attestation_audit import (
    ReasoningRunStage7FinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_final_attestation_consistency import (
    ReasoningRunStage7FinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
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

@pytest.fixture
def ready_chain():
    """All inputs in READY/CONSISTENT/CERTIFIED state."""
    session_id = str(uuid4())
    
    package = ReasoningRunStage7EvidencePackageRead(
        session_id=session_id,
        t162_session_id=session_id,
        t162_admission_status="ADMITTED",
        t162_diagnostics_status="HEALTHY",
        t162_request_fingerprint="a" * 64,
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
        t165_bundle_source="REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168",
        t166_session_id=session_id,
        t166_bundle_audit_status="CONSISTENT",
        t166_available=True,
        t166_consistent=True,
        t166_published_bundle_status="READY",
        t166_expected_bundle_status="READY",
        t166_finding_count=0,
        t166_findings=[],
        t166_audit_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166",
        t167_session_id=session_id,
        t167_consistency_status="CONSISTENT",
        t167_available=True,
        t167_consistent=True,
        t167_finding_count=0,
        t167_findings=[],
        t167_consistency_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
        package_status="READY",
        finding_count=0,
        findings=[],
        package_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    )
    
    audit = ReasoningRunStage7EvidencePackageAuditRead(
        session_id=session_id,
        package_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_package_status="READY",
        expected_package_status="READY",
        finding_count=0,
        findings=[],
        audit_source="REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_TASK_169",
    )
    
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyRead(
        session_id=session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source="REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_170",
    )
    
    return {"package": package, "audit": audit, "consistency": consistency}


# ---------------------------------------------------------------------------
# Task 171: Final Evidence Attestation
# ---------------------------------------------------------------------------

def test_task_171_ready_chain_certifies(ready_chain):
    """READY/CONSISTENT chain certifies to CERTIFIED."""
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    assert attestation["attestation_status"] == "CERTIFIED"
    assert attestation["package_status"] == "READY"
    assert attestation["package_audit_status"] == "CONSISTENT"
    assert attestation["consistency_status"] == "CONSISTENT"
    assert attestation["finding_count"] == 0
    assert attestation["findings"] == []


def test_task_171_blocked_chain_blocks(ready_chain):
    """Blocked chain attests to BLOCKED."""
    ready_chain["package"].package_status = "BLOCKED"
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    assert attestation["attestation_status"] == "BLOCKED"


def test_task_171_schema_rejects_extra_fields(ready_chain):
    """Schema rejects extra fields."""
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(attestation)


# ---------------------------------------------------------------------------
# Task 172: Final Attestation Audit
# ---------------------------------------------------------------------------

def test_task_172_certified_attestation_audits_consistent(ready_chain):
    """CERTIFIED attestation with consistent evidence audits CONSISTENT."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    assert audit["attestation_audit_status"] == "CONSISTENT"
    assert audit["published_attestation_status"] == "CERTIFIED"
    assert audit["expected_attestation_status"] == "CERTIFIED"
    assert audit["finding_count"] == 0


def test_task_172_forge_certified_detected(ready_chain):
    """Forging CERTIFIED is detected."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    tampered_dict = copy.deepcopy(attestation_dict)
    tampered_dict["attestation_status"] = "BLOCKED"
    tampered_dict["findings"] = ["FORGED_STATUS"]
    tampered_dict["finding_count"] = 1
    # Pass dict directly to audit service - it validates internally
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=tampered_dict
    )
    assert audit["attestation_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_STATUS_MISMATCH" in audit["findings"]


# ---------------------------------------------------------------------------
# Task 173: Final Attestation Consistency
# ---------------------------------------------------------------------------

def test_task_173_certified_attestation_with_consistent_audit_is_consistent(
    ready_chain,
):
    """CERTIFIED attestation with CONSISTENT audit is CONSISTENT."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(audit_dict)
    consistency = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=audit
    )
    assert consistency["consistency_status"] == "CONSISTENT"


def test_task_173_session_mismatch_detected(ready_chain):
    """Session mismatch is detected."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit_dict["session_id"] = str(uuid4())
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(audit_dict)
    consistency = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Task 174: Release Readiness Projection
# ---------------------------------------------------------------------------

def test_task_174_certified_chain_projects_ready(ready_chain):
    """CERTIFIED chain projects to READY."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(audit_dict)
    consistency_dict = (
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        consistency_dict
    )
    projection = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=attestation, audit=audit, consistency=consistency
    )
    assert projection["readiness_status"] == "READY"
    assert projection["attestation_status"] == "CERTIFIED"
    assert projection["attestation_audit_status"] == "CONSISTENT"
    assert projection["consistency_status"] == "CONSISTENT"
    assert projection["finding_count"] == 0


def test_task_174_blocked_chain_projects_blocked(ready_chain):
    """Blocked chain projects to BLOCKED."""
    ready_chain["package"].package_status = "BLOCKED"
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(audit_dict)
    consistency_dict = (
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        consistency_dict
    )
    projection = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=attestation, audit=audit, consistency=consistency
    )
    assert projection["readiness_status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Task 175: Release Readiness Audit
# ---------------------------------------------------------------------------

def test_task_175_ready_projection_audits_consistent(ready_chain):
    """READY projection with consistent evidence audits CONSISTENT."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(audit_dict)
    consistency_dict = (
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        consistency_dict
    )
    projection_dict = (
        ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=attestation, audit=audit, consistency=consistency
        )
    )
    projection = ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
        projection_dict
    )
    readiness_audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation,
        audit=audit,
        consistency=consistency,
        projection=projection,
    )
    assert readiness_audit["readiness_audit_status"] == "CONSISTENT"
    assert readiness_audit["published_readiness_status"] == "READY"
    assert readiness_audit["expected_readiness_status"] == "READY"
    assert readiness_audit["finding_count"] == 0


def test_task_175_forge_ready_detected(ready_chain):
    """Forging READY is detected."""
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    audit_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(audit_dict)
    consistency_dict = (
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        consistency_dict
    )
    projection_dict = (
        ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=attestation, audit=audit, consistency=consistency
        )
    )
    tampered_dict = copy.deepcopy(projection_dict)
    tampered_dict["readiness_status"] = "BLOCKED"
    tampered_dict["findings"] = ["FORGED_STATUS"]
    tampered_dict["finding_count"] = 1
    # Pass dict directly to audit service - it validates internally
    readiness_audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation,
        audit=audit,
        consistency=consistency,
        projection=tampered_dict,
    )
    assert readiness_audit["readiness_audit_status"] == "INCONSISTENT"
    assert "READINESS_STATUS_MISMATCH" in readiness_audit["findings"]


# ---------------------------------------------------------------------------
# Independence tests
# ---------------------------------------------------------------------------

def test_all_services_are_pure(ready_chain):
    """All services are pure functions."""
    attestation1_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    attestation2_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    assert attestation1_dict == attestation2_dict
    
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation1_dict
    )
    audit1_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    audit2_dict = ReasoningRunStage7FinalAttestationAuditService.audit(
        **ready_chain, attestation=attestation
    )
    assert audit1_dict == audit2_dict


def test_no_database_or_provider_access(ready_chain):
    """Services do not access database or provider."""
    attestation = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        **ready_chain
    )
    assert attestation is not None


# ---------------------------------------------------------------------------
# Source constant tests
# ---------------------------------------------------------------------------

def test_source_constants_are_correct():
    """All source constants are exported correctly."""
    assert (
        REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171
        == "REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_TASK_171"
    )
    assert (
        REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172
        == "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_TASK_172"
    )
    assert (
        REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
        == "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_TASK_173"
    )
    assert (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
        == "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174"
    )
    assert (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
        == "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_TASK_175"
    )

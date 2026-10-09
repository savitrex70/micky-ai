"""Task 174: Stage 7 release-readiness projection tests.

Deterministic projection answering whether the fully audited Stage 7
evidence is eligible to be considered release-ready. The projection
never releases, persists, executes, or invokes anything, and never
calls child services, recomputes fingerprints, invokes a provider, or
accesses a database.
"""

from __future__ import annotations

import copy
import inspect
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
from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (
    ReasoningRunStage7FinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_consistency import (
    ReasoningRunStage7FinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_final_attestation_audit import (
    ReasoningRunStage7FinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_final_attestation_consistency import (
    ReasoningRunStage7FinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationService,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

PROJECTION_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174


def _ready_package() -> ReasoningRunStage7EvidencePackageRead:
    session_id = str(uuid4())
    return ReasoningRunStage7EvidencePackageRead(
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
        t165_bundle_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_TASK_165",
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
        t167_consistency_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_TASK_167",
        package_status="READY",
        finding_count=0,
        findings=[],
        package_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    )


@pytest.fixture
def ready_chain():
    package = _ready_package()
    audit_inputs = ReasoningRunStage7EvidencePackageAuditRead(
        session_id=package.session_id,
        package_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_package_status="READY",
        expected_package_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    )
    consistency_inputs = ReasoningRunStage7EvidencePackageAuditConsistencyRead(
        session_id=package.session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        ReasoningRunStage7FinalEvidenceAttestationService.attest(
            package=package, audit=audit_inputs, consistency=consistency_inputs
        )
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
        ReasoningRunStage7FinalAttestationAuditService.audit(
            package=package,
            audit=audit_inputs,
            consistency=consistency_inputs,
            attestation=attestation,
        )
    )
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    return {"attestation": attestation, "audit": audit, "consistency": consistency}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_forbids_extra_fields() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessProjectionRead(
            session_id=session_id,
            readiness_status="READY",
            attestation_status="CERTIFIED",
            attestation_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=0,
            findings=[],
            projection_source=PROJECTION_SOURCE,
            extra_field="unexpected",  # type: ignore
        )


def test_schema_ready_requires_certified_inputs() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="READY requires CERTIFIED attestation"):
        ReasoningRunStage7ReleaseReadinessProjectionRead(
            session_id=session_id,
            readiness_status="READY",
            attestation_status="BLOCKED",
            attestation_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=0,
            findings=[],
            projection_source=PROJECTION_SOURCE,
        )


def test_schema_ready_requires_finding_free() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="READY requires a finding-free"):
        ReasoningRunStage7ReleaseReadinessProjectionRead(
            session_id=session_id,
            readiness_status="READY",
            attestation_status="CERTIFIED",
            attestation_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=1,
            findings=["SOME_FINDING"],
            projection_source=PROJECTION_SOURCE,
        )


def test_schema_blocked_requires_blocking_evidence() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="BLOCKED requires published blocking"):
        ReasoningRunStage7ReleaseReadinessProjectionRead(
            session_id=session_id,
            readiness_status="BLOCKED",
            attestation_status="CERTIFIED",
            attestation_audit_status="CONSISTENT",
            consistency_status="CONSISTENT",
            finding_count=0,
            findings=[],
            projection_source=PROJECTION_SOURCE,
        )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_project_certified_chain_is_ready(ready_chain) -> None:
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    assert result["readiness_status"] == "READY"
    assert result["attestation_status"] == "CERTIFIED"
    assert result["attestation_audit_status"] == "CONSISTENT"
    assert result["consistency_status"] == "CONSISTENT"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["session_id"] == ready_chain["attestation"].session_id
    assert result["projection_source"] == PROJECTION_SOURCE


def test_project_detects_session_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.session_id = str(uuid4())
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=ready_chain["consistency"],
    )
    assert result["readiness_status"] == "UNAVAILABLE"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]


def test_project_blocked_attestation_projects_blocked(ready_chain) -> None:
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_status = "BLOCKED"
    attestation.certified = False
    attestation.blocked = True
    attestation.finding_count = 1
    attestation.findings = ["PACKAGE_BLOCKED"]
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=attestation,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    assert result["readiness_status"] == "BLOCKED"


def test_project_inconsistent_audit_projects_blocked(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.attestation_audit_status = "INCONSISTENT"
    audit.consistent = False
    audit.finding_count = 1
    audit.findings = ["SOME_AUDIT_ISSUE"]
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=ready_chain["consistency"],
    )
    assert result["readiness_status"] == "BLOCKED"
    assert "ATTESTATION_AUDIT_INCONSISTENT" in result["findings"]


def test_project_inconsistent_consistency_projects_blocked(ready_chain) -> None:
    consistency = copy.deepcopy(ready_chain["consistency"])
    consistency.consistency_status = "INCONSISTENT"
    consistency.consistent = False
    consistency.finding_count = 1
    consistency.findings = ["SOME_CONSISTENCY_ISSUE"]
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=consistency,
    )
    assert result["readiness_status"] == "BLOCKED"
    assert "CONSISTENCY_INCONSISTENT" in result["findings"]


def test_project_detects_wrong_attestation_source(ready_chain) -> None:
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_source = "WRONG_SOURCE"
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=attestation,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    assert result["readiness_status"] == "UNAVAILABLE"
    assert "ATTESTATION_SOURCE_INVALID" in result["findings"]


def test_project_detects_wrong_audit_source(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.audit_source = "WRONG_SOURCE"
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=ready_chain["consistency"],
    )
    assert result["readiness_status"] == "UNAVAILABLE"
    assert "AUDIT_SOURCE_INVALID" in result["findings"]


def test_project_detects_wrong_consistency_source(ready_chain) -> None:
    consistency = copy.deepcopy(ready_chain["consistency"])
    consistency.consistency_source = "WRONG_SOURCE"
    result = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=consistency,
    )
    assert result["readiness_status"] == "UNAVAILABLE"
    assert "CONSISTENCY_SOURCE_INVALID" in result["findings"]


def test_project_does_not_mutate_inputs(ready_chain) -> None:
    before = {key: value.model_dump() for key, value in ready_chain.items()}
    ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    for key, value in ready_chain.items():
        assert value.model_dump() == before[key]


def test_project_deterministic(ready_chain) -> None:
    first = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    second = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    assert first == second


def test_project_has_no_provider_or_runtime_access() -> None:
    """Architecture: projection source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_release_readiness_projection as module

    source = inspect.getsource(module)
    for token in (
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "api_key",
        "httpx",
        "sqlite",
        "postgres",
        "socket",
        "requests",
        "import os",
        "subprocess",
    ):
        assert token not in source.lower(), token

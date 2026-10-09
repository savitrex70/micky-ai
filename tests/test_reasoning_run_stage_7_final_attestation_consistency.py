"""Task 173: Stage 7 final attestation consistency tests.

Independent consistency boundary between the Task 171 final evidence
attestation and the Task 172 final attestation audit. Requires exact
evidence binding with no child service invocation, provider, network,
database, or fingerprint recomputation.
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
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173,
    ReasoningRunStage7FinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationRead,
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
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

CONSISTENCY_SOURCE = REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173


def _ready_package(ready_bundle_evidence) -> ReasoningRunStage7EvidencePackageRead:
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
        t165_bundle_evidence=ready_bundle_evidence(session_id),
        t166_session_id=session_id,
        t166_bundle_audit_status="CONSISTENT",
        t166_available=True,
        t166_consistent=True,
        t166_published_bundle_status="READY",
        t166_expected_bundle_status="READY",
        t166_finding_count=0,
        t166_findings=[],
        t166_audit_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166",
        t166_audited_bundle=ready_bundle_evidence(session_id),
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
def ready_chain(ready_bundle_evidence):
    package = _ready_package(ready_bundle_evidence)
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
    return {"attestation": attestation, "audit": audit}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_forbids_extra_fields() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=session_id,
            consistency_status="CONSISTENT",
            available=True,
            consistent=True,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
            extra_field="unexpected",  # type: ignore
        )


def test_schema_flag_coherence() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=session_id,
            consistency_status="CONSISTENT",
            available=False,
            consistent=True,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
        )
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=session_id,
            consistency_status="CONSISTENT",
            available=True,
            consistent=False,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_consistent_requires_no_findings() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="CONSISTENT requires a finding-free"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=session_id,
            consistency_status="CONSISTENT",
            available=True,
            consistent=True,
            finding_count=1,
            findings=["SOME_FINDING"],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_inconsistent_requires_findings() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="INCONSISTENT requires at least one"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=session_id,
            consistency_status="INCONSISTENT",
            available=True,
            consistent=False,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
        )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_verify_bound_chain_is_consistent(ready_chain) -> None:
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=ready_chain["audit"]
    )
    assert result["consistency_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["session_id"] == ready_chain["attestation"].session_id
    assert result["consistency_source"] == CONSISTENCY_SOURCE


def test_verify_detects_session_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.session_id = str(uuid4())
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in result["findings"]


def test_verify_detects_published_status_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.published_attestation_status = "BLOCKED"
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]


def test_verify_detects_expected_status_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.expected_attestation_status = "BLOCKED"
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]


def test_verify_detects_inconsistent_audit_of_certified(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.attestation_audit_status = "INCONSISTENT"
    audit.consistent = False
    audit.finding_count = 1
    audit.findings = ["SOME_AUDIT_ISSUE"]
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in result["findings"]


def test_verify_detects_wrong_attestation_source(ready_chain) -> None:
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_source = "WRONG_SOURCE"
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=ready_chain["audit"]
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "ATTESTATION_SOURCE_INVALID" in result["findings"]


def test_verify_detects_wrong_audit_source(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.audit_source = "WRONG_SOURCE"
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_INVALID" in result["findings"]


def test_verify_detects_finding_count_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.finding_count = 2
    audit.findings = ["ISSUE_ONE", "ISSUE_TWO"]
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in result["findings"]


def test_verify_does_not_mutate_inputs(ready_chain) -> None:
    before_attestation = ready_chain["attestation"].model_dump()
    before_audit = ready_chain["audit"].model_dump()
    ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=ready_chain["audit"]
    )
    assert ready_chain["attestation"].model_dump() == before_attestation
    assert ready_chain["audit"].model_dump() == before_audit


def test_verify_deterministic(ready_chain) -> None:
    first = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=ready_chain["audit"]
    )
    second = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=ready_chain["audit"]
    )
    assert first == second


def test_verify_has_no_provider_or_runtime_access() -> None:
    """Architecture: consistency source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_final_attestation_consistency as module

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

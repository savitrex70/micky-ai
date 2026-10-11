"""Externally compose the real Task 174–188 release-readiness chain."""

from __future__ import annotations

import copy

from pydantic import BaseModel

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
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit import (
    ReasoningRunStage7FinalReleaseGateAuditService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    ReasoningRunStage7FinalReleaseGateAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_projection import (
    ReasoningRunStage7FinalReleaseGateProjectionService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit_consistency import (
    ReasoningRunStage7ReleaseReadinessAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionService,
)

SESSION = "release-readiness-chain-session"
_HANDOFF_CONSISTENCY = (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService
)


def _validate(model: type[BaseModel], value: dict) -> BaseModel:
    return model.model_validate(value)


def _seed(status: str):
    finding = [] if status == "READY" else [f"SEED_{status}"]
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead(
        session_id=SESSION,
        attestation_status={
            "READY": "CERTIFIED",
            "BLOCKED": "BLOCKED",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        certified=status == "READY",
        blocked=status == "BLOCKED",
        available=status != "UNAVAILABLE",
        package_status=status,
        package_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=len(finding),
        findings=finding,
        attestation_source=(
            REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171
        ),
    )
    audit = ReasoningRunStage7FinalAttestationAuditRead(
        session_id=SESSION,
        attestation_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_attestation_status=attestation.attestation_status,
        expected_attestation_status=attestation.attestation_status,
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
    )
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead(
        session_id=SESSION,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=(
            REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
        ),
    )
    return attestation, audit, consistency


def _compose(status: str = "READY") -> dict[str, BaseModel]:
    attestation171, audit172, consistency173 = _seed(status)
    projection174 = _validate(
        ReasoningRunStage7ReleaseReadinessProjectionRead,
        ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=attestation171, audit=audit172, consistency=consistency173
        ),
    )
    audit175 = _validate(
        ReasoningRunStage7ReleaseReadinessAuditRead,
        ReasoningRunStage7ReleaseReadinessAuditService.audit(
            attestation=attestation171,
            audit=audit172,
            consistency=consistency173,
            projection=projection174,
        ),
    )
    consistency176 = _validate(
        ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
        ReasoningRunStage7ReleaseReadinessAuditConsistencyService.verify(
            projection=projection174, audit=audit175
        ),
    )
    bundle177 = _validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
        ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
            projection174=projection174,
            audit175=audit175,
            consistency176=consistency176,
        ),
    )
    audit178 = _validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
            projection174=projection174,
            audit175=audit175,
            consistency176=consistency176,
            bundle=bundle177,
        ),
    )
    consistency179 = _validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService.verify(
            bundle=bundle177, audit=audit178
        ),
    )
    attestation180 = _validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
        ReasoningRunStage7ReleaseReadinessFinalAttestationService.attest(
            bundle=bundle177, audit=audit178, consistency=consistency179
        ),
    )
    audit181 = _validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
            bundle=bundle177,
            audit=audit178,
            consistency=consistency179,
            attestation=attestation180,
        ),
    )
    consistency182 = _validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService.verify(
            attestation=attestation180, audit=audit181
        ),
    )
    projection183 = _validate(
        ReasoningRunStage7FinalReleaseGateProjectionRead,
        ReasoningRunStage7FinalReleaseGateProjectionService.project(
            attestation=attestation180,
            audit=audit181,
            consistency=consistency182,
        ),
    )
    audit184 = _validate(
        ReasoningRunStage7FinalReleaseGateAuditRead,
        ReasoningRunStage7FinalReleaseGateAuditService.audit(
            attestation=attestation180,
            audit=audit181,
            consistency=consistency182,
            projection=projection183,
        ),
    )
    consistency185 = _validate(
        ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
        ReasoningRunStage7FinalReleaseGateAuditConsistencyService.verify(
            projection=projection183, audit=audit184
        ),
    )
    package186 = _validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection183, audit=audit184, consistency=consistency185
        ),
    )
    audit187 = _validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection183,
            audit=audit184,
            consistency=consistency185,
            package=package186,
        ),
    )
    consistency188 = _validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead,
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package186, audit=audit187
        ),
    )
    return {
        "174": projection174,
        "175": audit175,
        "176": consistency176,
        "177": bundle177,
        "178": audit178,
        "179": consistency179,
        "180": attestation180,
        "181": audit181,
        "182": consistency182,
        "183": projection183,
        "184": audit184,
        "185": consistency185,
        "186": package186,
        "187": audit187,
        "188": consistency188,
    }


def test_ready_chain_reaches_consistent_handoff_and_is_deterministic():
    chain = _compose()
    assert chain["174"].readiness_status == "READY"
    assert chain["177"].bundle_status == "READY"
    assert chain["180"].attestation_status == "CERTIFIED"
    assert chain["183"].gate_status == "READY"
    assert chain["186"].package_status == "READY"
    assert chain["187"].package_audit_status == "CONSISTENT"
    assert chain["188"].consistency_status == "CONSISTENT"
    snapshot = {key: value.model_dump() for key, value in chain.items()}
    assert {key: value.model_dump() for key, value in _compose().items()} == snapshot
    assert {key: value.model_dump() for key, value in chain.items()} == snapshot


def test_blocked_chain_remains_blocked_through_handoff():
    chain = _compose("BLOCKED")
    assert chain["174"].readiness_status == "BLOCKED"
    assert chain["175"].readiness_audit_status == "CONSISTENT"
    assert chain["176"].consistency_status == "CONSISTENT"
    assert chain["177"].bundle_status == "BLOCKED"
    assert chain["178"].bundle_audit_status == "CONSISTENT"
    assert chain["179"].consistency_status == "CONSISTENT"
    assert chain["180"].attestation_status == "BLOCKED"
    assert chain["181"].attestation_audit_status == "CONSISTENT"
    assert chain["182"].attestation_consistency_status == "CONSISTENT"
    assert chain["183"].gate_status == "BLOCKED"
    assert chain["184"].gate_audit_status == "CONSISTENT"
    assert chain["185"].gate_consistency_status == "CONSISTENT"
    assert chain["186"].package_status == "BLOCKED"
    assert chain["187"].package_audit_status == "CONSISTENT"
    assert chain["188"].consistency_status == "CONSISTENT"


def test_valid_unavailable_business_state_is_never_promoted():
    chain = _compose("UNAVAILABLE")
    assert chain["174"].readiness_status == "UNAVAILABLE"
    assert chain["175"].readiness_audit_status == "CONSISTENT"
    assert chain["176"].consistency_status == "CONSISTENT"
    assert chain["177"].bundle_status == "UNAVAILABLE"
    assert chain["178"].bundle_audit_status == "CONSISTENT"
    assert chain["179"].consistency_status == "CONSISTENT"
    assert chain["180"].attestation_status == "UNAVAILABLE"
    assert chain["181"].attestation_audit_status == "CONSISTENT"
    assert chain["182"].attestation_consistency_status == "CONSISTENT"
    assert chain["183"].gate_status == "UNAVAILABLE"
    assert chain["184"].gate_audit_status == "CONSISTENT"
    assert chain["185"].gate_consistency_status == "CONSISTENT"
    assert chain["186"].package_status == "UNAVAILABLE"
    assert chain["187"].package_audit_status == "CONSISTENT"
    assert chain["186"].package_status not in {"READY", "BLOCKED"}
    assert chain["188"].consistency_status == "CONSISTENT"


def test_mutated_upstream_record_cannot_be_promoted_to_ready():
    attestation, audit, consistency = _seed("READY")
    attestation.attestation_source = "FORGED_SOURCE"
    projection = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=attestation, audit=audit, consistency=consistency
    )
    assert projection["readiness_status"] == "UNAVAILABLE"
    assert projection["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_unknown_published_status_is_unavailable_not_a_fabricated_claim():
    attestation, audit, consistency = _seed("READY")
    attestation.attestation_status = "UNKNOWN"
    projection = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=attestation, audit=audit, consistency=consistency
    )
    assert projection["readiness_status"] == "UNAVAILABLE"
    assert projection["attestation_status"] == "UNAVAILABLE"
    assert projection["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_unknown_package_status_and_wrong_input_types_are_unavailable():
    chain = _compose()
    package = copy.deepcopy(chain["186"])
    package.package_status = "UNKNOWN"
    audit = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
        projection=chain["183"],
        audit=chain["184"],
        consistency=chain["185"],
        package=package,
    )
    assert audit["package_audit_status"] == "UNAVAILABLE"
    unavailable = _HANDOFF_CONSISTENCY.verify(
        package=package,
        audit=ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead.model_construct(
            **audit
        ),
    )
    assert unavailable["consistency_status"] == "UNAVAILABLE"
    wrong_type = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
        projection=object(),
        audit=chain["184"],
        consistency=chain["185"],
        package=chain["186"],
    )
    assert wrong_type["package_audit_status"] == "UNAVAILABLE"


def test_forged_ready_or_blocked_handoff_status_is_detected():
    chain = _compose()
    for forged_status in ("BLOCKED", "UNAVAILABLE"):
        package = copy.deepcopy(chain["186"])
        package.package_status = forged_status
        audit = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=chain["183"],
            audit=chain["184"],
            consistency=chain["185"],
            package=package,
        )
        assert audit["package_audit_status"] == "INCONSISTENT"
        assert audit["published_package_status"] == forged_status
        assert audit["expected_package_status"] == "READY"
        assert "PACKAGE_STATUS_MISMATCH" in audit["findings"]


def test_package_findings_and_count_tampering_are_audited():
    chain = _compose("BLOCKED")
    package = copy.deepcopy(chain["186"])
    package.findings = []
    package.finding_count = 0
    result = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
        projection=chain["183"],
        audit=chain["184"],
        consistency=chain["185"],
        package=package,
    )
    assert result["package_audit_status"] == "INCONSISTENT"
    assert any(
        "FINDINGS" in finding or "EVIDENCE_MISMATCH" in finding
        for finding in result["findings"]
    )


def test_unavailable_business_result_does_not_hide_valid_status_contradiction():
    chain = _compose("UNAVAILABLE")
    audit_payload = chain["187"].model_dump()
    audit_payload.update(
        package_audit_status="INCONSISTENT",
        consistent=False,
        expected_package_status="BLOCKED",
        finding_count=1,
        findings=["PACKAGE_STATUS_MISMATCH"],
    )
    contradictory_audit = (
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead.model_validate(
            audit_payload
        )
    )
    result = _HANDOFF_CONSISTENCY.verify(
        package=chain["186"],
        audit=contradictory_audit,
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in result["findings"]


def test_forged_claim_source_and_detached_session_are_detected():
    chain = _compose()
    package = chain["186"]
    package.package_source = "FORGED_SOURCE"
    package_audit = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
        projection=chain["183"],
        audit=chain["184"],
        consistency=chain["185"],
        package=package,
    )
    assert package_audit["package_audit_status"] == "INCONSISTENT"
    detached_audit = chain["187"]
    detached_audit.session_id = "different-session"
    result = _HANDOFF_CONSISTENCY.verify(package=package, audit=detached_audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in result["findings"]

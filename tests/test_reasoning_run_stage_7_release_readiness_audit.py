"""Task 175: independent Stage 7 release-readiness audit tests.

Independent audit boundary over the already-published Task 174
release-readiness projection. The audit derives the expected readiness
from the published Task 171-173 evidence rather than trusting Task 174,
and never calls Task 174, Tasks 171-173 services, recomputes
fingerprints, invokes a provider, or accesses a database.
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
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
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
from rop.services.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditService,
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

AUDIT_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175


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
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    projection = ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
        ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=attestation, audit=audit, consistency=consistency
        )
    )
    return {
        "attestation": attestation,
        "audit": audit,
        "consistency": consistency,
        "projection": projection,
        "package": package,
        "audit_inputs": audit_inputs,
        "consistency_inputs": consistency_inputs,
    }


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_forbids_extra_fields() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=session_id,
            readiness_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_readiness_status="READY",
            expected_readiness_status="READY",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
            extra_field="unexpected",  # type: ignore
        )


def test_schema_consistent_requires_status_agreement() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="CONSISTENT requires published"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=session_id,
            readiness_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_readiness_status="BLOCKED",
            expected_readiness_status="READY",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_consistent_requires_no_findings() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="CONSISTENT requires a finding-free"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=session_id,
            readiness_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_readiness_status="READY",
            expected_readiness_status="READY",
            finding_count=1,
            findings=["SOME_FINDING"],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_requires_canonical_source() -> None:
    with pytest.raises(ValidationError, match="canonical Task 175 source"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=str(uuid4()),
            readiness_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_readiness_status="READY",
            expected_readiness_status="READY",
            finding_count=0,
            findings=[],
            audit_source="FORGED",
        )


def test_schema_unavailable_must_not_claim_session() -> None:
    with pytest.raises(ValidationError, match="must not claim a session"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=str(uuid4()),
            readiness_audit_status="UNAVAILABLE",
            available=False,
            consistent=False,
            published_readiness_status="UNAVAILABLE",
            expected_readiness_status="UNAVAILABLE",
            finding_count=1,
            findings=["EVIDENCE_INPUT_INVALID"],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_inconsistent_requires_findings() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="INCONSISTENT requires at least one"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=session_id,
            readiness_audit_status="INCONSISTENT",
            available=True,
            consistent=False,
            published_readiness_status="BLOCKED",
            expected_readiness_status="READY",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_flag_coherence() -> None:
    session_id = str(uuid4())
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=session_id,
            readiness_audit_status="CONSISTENT",
            available=False,
            consistent=True,
            published_readiness_status="READY",
            expected_readiness_status="READY",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=session_id,
            readiness_audit_status="CONSISTENT",
            available=True,
            consistent=False,
            published_readiness_status="READY",
            expected_readiness_status="READY",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_audit_ready_chain_is_consistent(ready_chain) -> None:
    """Genuine READY projection audits CONSISTENT."""
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    assert audit["readiness_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["published_readiness_status"] == "READY"
    assert audit["expected_readiness_status"] == "READY"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["session_id"] == ready_chain["attestation"].session_id
    assert audit["audit_source"] == AUDIT_SOURCE


def test_audit_detects_forged_ready_status(ready_chain) -> None:
    """Forged READY over BLOCKED evidence is INCONSISTENT."""
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_status = "BLOCKED"
    attestation.certified = False
    attestation.blocked = True
    attestation.package_status = "BLOCKED"
    attestation.finding_count = 1
    attestation.findings = ["PACKAGE_BLOCKED"]
    forged_projection = {
        "session_id": attestation.session_id,
        "readiness_status": "READY",
        "attestation_status": "CERTIFIED",
        "attestation_audit_status": "CONSISTENT",
        "consistency_status": "CONSISTENT",
        "finding_count": 0,
        "findings": [],
        "projection_source": (
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174"
        ),
    }
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=forged_projection,
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "READINESS_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_readiness_status"] == "BLOCKED"


def test_audit_detects_forged_blocked_status(ready_chain) -> None:
    """Forged BLOCKED over READY evidence is INCONSISTENT."""
    projection = copy.deepcopy(ready_chain["projection"])
    projection.readiness_status = "BLOCKED"
    projection.finding_count = 1
    projection.findings = ["FORGED_BLOCKED"]
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=projection,
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "READINESS_STATUS_MISMATCH" in audit["findings"]


def test_audit_detects_blocking_evidence_hidden_under_unavailable(
    ready_chain,
) -> None:
    """BLOCKED evidence surfaced as UNAVAILABLE projection is INCONSISTENT."""
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_status = "BLOCKED"
    attestation.certified = False
    attestation.blocked = True
    attestation.package_status = "BLOCKED"
    attestation.finding_count = 1
    attestation.findings = ["PACKAGE_BLOCKED"]
    projection = copy.deepcopy(ready_chain["projection"])
    projection.readiness_status = "UNAVAILABLE"
    projection.finding_count = 1
    projection.findings = ["HIDDEN_BLOCKING_EVIDENCE"]
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=projection,
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "READINESS_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_readiness_status"] == "BLOCKED"


def test_audit_detects_contradictory_evidence_presented_as_ready(
    ready_chain,
) -> None:
    """INCONSISTENT audit evidence presented as READY is INCONSISTENT."""
    audit_inputs = copy.deepcopy(ready_chain["audit"])
    audit_inputs.attestation_audit_status = "INCONSISTENT"
    audit_inputs.consistent = False
    audit_inputs.finding_count = 1
    audit_inputs.findings = ["SOME_AUDIT_ISSUE"]
    projection = copy.deepcopy(ready_chain["projection"])
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=audit_inputs,
        consistency=ready_chain["consistency"],
        projection=projection,
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "READINESS_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_readiness_status"] == "BLOCKED"


def test_audit_detects_session_mismatch(ready_chain) -> None:
    """Detached projection from another session is INCONSISTENT."""
    projection = copy.deepcopy(ready_chain["projection"])
    projection.session_id = str(uuid4())
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=projection,
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit["findings"]


def test_audit_detects_wrong_attestation_source(ready_chain) -> None:
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_SOURCE_INVALID" in audit["findings"]


def test_audit_detects_wrong_audit_source(ready_chain) -> None:
    audit_inputs = copy.deepcopy(ready_chain["audit"])
    audit_inputs.audit_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=audit_inputs,
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_INVALID" in audit["findings"]


def test_audit_detects_wrong_consistency_source(ready_chain) -> None:
    consistency = copy.deepcopy(ready_chain["consistency"])
    consistency.consistency_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=consistency,
        projection=ready_chain["projection"],
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "CONSISTENCY_SOURCE_INVALID" in audit["findings"]


@pytest.mark.parametrize("bad_session_id", [None, 7, []])
def test_audit_rejects_mutated_upstream_identity(ready_chain, bad_session_id) -> None:
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.session_id = bad_session_id
    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    assert result["readiness_audit_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_audit_detects_projection_upstream_status_echo_mismatch(ready_chain) -> None:
    projection = ready_chain["projection"].model_dump()
    projection["attestation_audit_status"] = "UNAVAILABLE"
    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=projection,
    )
    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "UPSTREAM_STATUS_MISMATCH" in result["findings"]


def test_audit_malformed_projection_dict_is_unavailable(ready_chain) -> None:
    """Garbage projection input yields UNAVAILABLE, not an exception."""
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection={"readiness_status": "GARBAGE"},
    )
    assert audit["readiness_audit_status"] == "UNAVAILABLE"
    assert "PROJECTION_INVALID" in audit["findings"]


def test_audit_finding_count_tampering_detected(ready_chain) -> None:
    """Finding-count tampering on a valid projection is INCONSISTENT."""
    tampered = {
        "session_id": ready_chain["projection"].session_id,
        "readiness_status": "READY",
        "attestation_status": "CERTIFIED",
        "attestation_audit_status": "CONSISTENT",
        "consistency_status": "CONSISTENT",
        "finding_count": 5,
        "findings": [],
        "projection_source": (
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174"
        ),
    }
    audit = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=tampered,
    )
    assert audit["readiness_audit_status"] == "INCONSISTENT"
    assert "PROJECTION_INVALID" in audit["findings"]


def test_audit_does_not_mutate_inputs(ready_chain) -> None:
    """Audit inputs are immutable."""
    before = {
        "attestation": ready_chain["attestation"].model_dump(),
        "audit": ready_chain["audit"].model_dump(),
        "consistency": ready_chain["consistency"].model_dump(),
        "projection": ready_chain["projection"].model_dump(),
    }
    ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    assert ready_chain["attestation"].model_dump() == before["attestation"]
    assert ready_chain["audit"].model_dump() == before["audit"]
    assert ready_chain["consistency"].model_dump() == before["consistency"]
    assert ready_chain["projection"].model_dump() == before["projection"]


def test_audit_deterministic(ready_chain) -> None:
    first = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    second = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )
    assert first == second


def test_audit_has_no_provider_or_runtime_access() -> None:
    """Architecture: audit source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_release_readiness_audit as module

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


# ---------------------------------------------------------------------------
# Unavailable evidence is preserved; Task 172 nullable-status invariant
# ---------------------------------------------------------------------------

PROJECTION_SOURCE = "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174"
UNAVAILABLE_FINDINGS = [
    "AUDIT_UNAVAILABLE",
    "CONSISTENCY_UNAVAILABLE",
    "SESSION_BINDING_UNPROVABLE",
]


def _real_task_172_audit(ready_chain, *, attestation=None, package=None):
    """Run the real Task 172 service over the chain's upstream evidence."""
    return ReasoningRunStage7FinalAttestationAuditRead.model_validate(
        ReasoningRunStage7FinalAttestationAuditService.audit(
            package=package or ready_chain["package"],
            audit=ready_chain["audit_inputs"],
            consistency=ready_chain["consistency_inputs"],
            attestation=attestation or ready_chain["attestation"],
        )
    )


def _real_task_173_and_174(attestation, audit):
    """Run the real Task 173 and 174 services externally (never from Task 175)."""
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation, audit=audit
        )
    )
    projection = ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
        ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=attestation, audit=audit, consistency=consistency
        )
    )
    return consistency, projection


def _unknown_status_chain(ready_chain):
    """Unreadable published status: real Tasks 172 -> 173 -> 174."""
    broken = ready_chain["attestation"].model_dump()
    broken["attestation_status"] = "GARBAGE"
    audit = _real_task_172_audit(ready_chain, attestation=broken)
    consistency, projection = _real_task_173_and_174(ready_chain["attestation"], audit)
    return audit, consistency, projection


def _malformed_evidence_chain(ready_chain):
    """Readable CERTIFIED but unverifiable evidence: real Tasks 172 -> 173 -> 174."""
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    audit = _real_task_172_audit(ready_chain, package=package)
    consistency, projection = _real_task_173_and_174(ready_chain["attestation"], audit)
    return audit, consistency, projection


def _audit175(ready_chain, *, attestation=None, audit, consistency, projection):
    return ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=attestation or ready_chain["attestation"],
        audit=audit,
        consistency=consistency,
        projection=projection,
    )


def _assert_well_formed(result: dict) -> None:
    assert result["findings"] == sorted(set(result["findings"]))
    assert result["finding_count"] == len(result["findings"])
    assert result["audit_source"] == AUDIT_SOURCE
    ReasoningRunStage7ReleaseReadinessAuditRead.model_validate(result)


def _assert_unavailable(result: dict, findings: list[str]) -> None:
    assert result["readiness_audit_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["findings"] == findings
    _assert_well_formed(result)


def test_unreadable_status_chain_stays_unavailable_end_to_end(ready_chain) -> None:
    audit, consistency, projection = _unknown_status_chain(ready_chain)

    # Task 172 -> 173 -> 174 each preserve UNAVAILABLE, never BLOCKED.
    assert audit.attestation_audit_status == "UNAVAILABLE"
    assert audit.published_attestation_status is None
    assert consistency.consistency_status == "UNAVAILABLE"
    assert consistency.session_id == ""
    assert projection.readiness_status == "UNAVAILABLE"
    assert projection.session_id == ready_chain["attestation"].session_id

    result = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )

    _assert_unavailable(result, UNAVAILABLE_FINDINGS)
    assert result["published_readiness_status"] == "UNAVAILABLE"
    assert result["expected_readiness_status"] == "UNAVAILABLE"
    assert "SESSION_BINDING_MISMATCH" not in result["findings"]


def test_malformed_evidence_audit_with_readable_status_is_not_blocking(
    ready_chain,
) -> None:
    audit, consistency, projection = _malformed_evidence_chain(ready_chain)

    assert audit.attestation_audit_status == "UNAVAILABLE"
    assert audit.published_attestation_status == "CERTIFIED"
    assert consistency.consistency_status == "UNAVAILABLE"
    assert projection.readiness_status == "UNAVAILABLE"

    result = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )

    _assert_unavailable(result, UNAVAILABLE_FINDINGS)
    assert result["expected_readiness_status"] == "UNAVAILABLE"
    assert result["expected_readiness_status"] != "BLOCKED"
    assert result["published_readiness_status"] == "UNAVAILABLE"


def test_unavailable_audit_alone_leaves_binding_unprovable(ready_chain) -> None:
    """Only the audit is unavailable; the consistency result is available."""
    audit, _, _ = _unknown_status_chain(ready_chain)
    projection = ready_chain["projection"].model_copy(
        update={
            "readiness_status": "UNAVAILABLE",
            "attestation_audit_status": "UNAVAILABLE",
            "finding_count": 1,
            "findings": ["ATTESTATION_AUDIT_INCONSISTENT"],
        }
    )

    result = _audit175(
        ready_chain,
        audit=audit,
        consistency=ready_chain["consistency"],
        projection=projection,
    )

    _assert_unavailable(result, ["AUDIT_UNAVAILABLE", "SESSION_BINDING_UNPROVABLE"])


def _mutate_unknown_status(audit, variant: str):
    """Impossible Task 172 states reachable only by post-construction mutation."""
    audit = copy.deepcopy(audit)
    audit.published_attestation_status = None
    if variant == "inconsistent_with_findings":
        audit.attestation_audit_status = "INCONSISTENT"
        audit.consistent = False
        audit.finding_count = 1
        audit.findings = ["ATTESTATION_STATUS_MISMATCH"]
    elif variant == "unavailable_missing_attestation_invalid":
        audit.attestation_audit_status = "UNAVAILABLE"
        audit.available = False
        audit.consistent = False
        audit.finding_count = 1
        audit.findings = ["EVIDENCE_INPUT_INVALID"]
    elif variant == "consistent_with_no_findings":
        pass  # still CONSISTENT, finding-free: no ATTESTATION_INVALID
    elif variant == "unavailable_with_incoherent_flags":
        audit.attestation_audit_status = "UNAVAILABLE"
        audit.finding_count = 1
        audit.findings = ["ATTESTATION_INVALID"]  # available/consistent stay True
    else:  # pragma: no cover
        raise AssertionError(variant)
    return audit


UNKNOWN_STATUS_VARIANTS = [
    "inconsistent_with_findings",
    "unavailable_missing_attestation_invalid",
    "consistent_with_no_findings",
    "unavailable_with_incoherent_flags",
]


@pytest.mark.parametrize("variant", UNKNOWN_STATUS_VARIANTS)
def test_unknown_status_audit_violating_task_172_is_rejected(
    ready_chain, variant
) -> None:
    audit = _mutate_unknown_status(ready_chain["audit"], variant)

    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )

    _assert_unavailable(result, ["EVIDENCE_INPUT_INVALID"])
    assert result["expected_readiness_status"] == "UNAVAILABLE"
    assert result["published_readiness_status"] == "UNAVAILABLE"


@pytest.mark.parametrize("variant", UNKNOWN_STATUS_VARIANTS)
def test_invalid_unknown_status_audit_never_becomes_blocking_evidence(
    ready_chain, variant
) -> None:
    """A projection claiming BLOCKED must not be validated by invalid evidence."""
    audit = _mutate_unknown_status(ready_chain["audit"], variant)
    blocked_projection = {
        "session_id": ready_chain["attestation"].session_id,
        "readiness_status": "BLOCKED",
        "attestation_status": "CERTIFIED",
        "attestation_audit_status": audit.attestation_audit_status,
        "consistency_status": "CONSISTENT",
        "finding_count": 1,
        "findings": ["ATTESTATION_AUDIT_INCONSISTENT"],
        "projection_source": PROJECTION_SOURCE,
    }

    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=ready_chain["consistency"],
        projection=blocked_projection,
    )

    assert result["readiness_audit_status"] == "UNAVAILABLE"
    assert result["expected_readiness_status"] != "BLOCKED"
    assert result["consistent"] is False
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]
    _assert_well_formed(result)


def test_unknown_status_audit_with_wrong_source_is_rejected(ready_chain) -> None:
    """No semantic-conflict recovery for an audit that asserts no status."""
    audit, consistency, projection = _unknown_status_chain(ready_chain)
    audit = copy.deepcopy(audit)
    audit.audit_source = "WRONG_SOURCE"

    result = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )

    _assert_unavailable(result, ["EVIDENCE_INPUT_INVALID"])


def test_readable_status_contradiction_is_still_recovered(ready_chain) -> None:
    """Genuine readable contradictions keep their semantic-conflict handling."""
    audit = copy.deepcopy(ready_chain["audit"])
    audit.audit_source = "WRONG_SOURCE"

    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=ready_chain["consistency"],
        projection=ready_chain["projection"],
    )

    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_INVALID" in result["findings"]
    _assert_well_formed(result)


@pytest.mark.parametrize("who", ["audit", "consistency"])
def test_session_mismatch_between_available_records_stays_inconsistent(
    ready_chain, who
) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    consistency = copy.deepcopy(ready_chain["consistency"])
    if who == "audit":
        audit.session_id = str(uuid4())
    else:
        consistency.session_id = str(uuid4())

    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=ready_chain["attestation"],
        audit=audit,
        consistency=consistency,
        projection=ready_chain["projection"],
    )

    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]
    _assert_well_formed(result)


def test_available_audit_mismatch_is_inconsistent_beside_unavailable_consistency(
    ready_chain,
) -> None:
    """One unavailable record does not hide a mismatch in an available one."""
    audit = copy.deepcopy(ready_chain["audit"])
    audit.session_id = str(uuid4())
    _, consistency, _ = _unknown_status_chain(ready_chain)
    projection = ready_chain["projection"].model_copy(
        update={
            "readiness_status": "UNAVAILABLE",
            "consistency_status": "UNAVAILABLE",
            "finding_count": 1,
            "findings": ["CONSISTENCY_INCONSISTENT"],
        }
    )

    result = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )

    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]
    assert result["session_id"] == projection.session_id


def test_projection_session_mismatch_stays_inconsistent_with_unavailable_evidence(
    ready_chain,
) -> None:
    audit, consistency, projection = _unknown_status_chain(ready_chain)
    projection = projection.model_copy(update={"session_id": str(uuid4())})

    result = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )

    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]
    _assert_well_formed(result)


@pytest.mark.parametrize("forged", ["READY", "BLOCKED"])
def test_forged_projection_detected_despite_unavailable_evidence(
    ready_chain, forged
) -> None:
    audit, consistency, projection = _unknown_status_chain(ready_chain)
    findings = [] if forged == "READY" else ["FORGED_BLOCKED"]
    forged_projection = projection.model_dump()
    forged_projection.update(
        {
            "readiness_status": forged,
            "finding_count": len(findings),
            "findings": findings,
        }
    )

    result = _audit175(
        ready_chain,
        audit=audit,
        consistency=consistency,
        projection=forged_projection,
    )

    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "READINESS_STATUS_MISMATCH" in result["findings"]
    assert result["published_readiness_status"] == forged
    assert result["expected_readiness_status"] == "UNAVAILABLE"
    _assert_well_formed(result)


def test_unavailable_upstream_does_not_hide_other_contradictions(ready_chain) -> None:
    """A contradiction wins over unavailability, so the audit stays INCONSISTENT."""
    audit, consistency, projection = _unknown_status_chain(ready_chain)
    echo_mismatch = projection.model_dump()
    echo_mismatch["attestation_audit_status"] = "CONSISTENT"

    result = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=echo_mismatch
    )

    assert result["readiness_audit_status"] == "INCONSISTENT"
    assert "UPSTREAM_STATUS_MISMATCH" in result["findings"]
    assert not set(UNAVAILABLE_FINDINGS) & set(result["findings"])


def test_genuine_blocked_attestation_with_unavailable_audit_detects_forgery(
    ready_chain,
) -> None:
    """Blocking evidence stays authoritative; READY/UNAVAILABLE cannot hide it."""
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_status = "BLOCKED"
    attestation.certified = False
    attestation.blocked = True
    attestation.package_status = "BLOCKED"
    attestation.finding_count = 1
    attestation.findings = ["PACKAGE_BLOCKED"]
    audit, consistency, projection = _unknown_status_chain(ready_chain)

    for claimed in ("READY", "UNAVAILABLE"):
        forged = projection.model_dump()
        forged.update(
            {
                "readiness_status": claimed,
                "attestation_status": "BLOCKED",
                "finding_count": 0 if claimed == "READY" else 1,
                "findings": [] if claimed == "READY" else ["HIDDEN"],
            }
        )
        result = _audit175(
            ready_chain,
            attestation=attestation,
            audit=audit,
            consistency=consistency,
            projection=forged,
        )
        assert result["readiness_audit_status"] == "INCONSISTENT", claimed
        assert result["expected_readiness_status"] == "BLOCKED", claimed
        assert "READINESS_STATUS_MISMATCH" in result["findings"], claimed


def test_unavailable_path_is_deterministic_and_does_not_mutate(ready_chain) -> None:
    audit, consistency, projection = _unknown_status_chain(ready_chain)
    before = {
        "attestation": ready_chain["attestation"].model_dump(),
        "audit": audit.model_dump(),
        "consistency": consistency.model_dump(),
        "projection": projection.model_dump(),
    }

    first = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )
    second = _audit175(
        ready_chain, audit=audit, consistency=consistency, projection=projection
    )

    assert first == second
    assert ready_chain["attestation"].model_dump() == before["attestation"]
    assert audit.model_dump() == before["audit"]
    assert consistency.model_dump() == before["consistency"]
    assert projection.model_dump() == before["projection"]


def test_post_construction_mutation_of_unavailable_inputs_is_revalidated(
    ready_chain,
) -> None:
    audit, consistency, projection = _unknown_status_chain(ready_chain)

    bad_audit = copy.deepcopy(audit)
    bad_audit.published_attestation_status = "BOGUS"  # type: ignore[assignment]
    bad_consistency = copy.deepcopy(consistency)
    bad_consistency.session_id = []  # type: ignore[assignment]

    for kwargs in (
        {"audit": bad_audit, "consistency": consistency},
        {"audit": audit, "consistency": bad_consistency},
    ):
        result = _audit175(ready_chain, projection=projection, **kwargs)
        _assert_unavailable(result, ["EVIDENCE_INPUT_INVALID"])


@pytest.mark.parametrize("bad", [None, "UNAVAILABLE", 7, {"a": 1}])
def test_wrong_input_types_are_invalid_input_with_unavailable_evidence(
    ready_chain, bad
) -> None:
    audit, consistency, projection = _unknown_status_chain(ready_chain)

    for kwargs in (
        {"audit": bad, "consistency": consistency},
        {"audit": audit, "consistency": bad},
    ):
        result = _audit175(ready_chain, projection=projection, **kwargs)
        _assert_unavailable(result, ["EVIDENCE_INPUT_INVALID"])

    result = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=bad,  # type: ignore[arg-type]
        audit=audit,
        consistency=consistency,
        projection=projection,
    )
    _assert_unavailable(result, ["EVIDENCE_INPUT_INVALID"])


def test_schema_accepts_unavailable_result_with_unprovable_binding_findings() -> None:
    result = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id="",
        readiness_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_readiness_status="UNAVAILABLE",
        expected_readiness_status="UNAVAILABLE",
        finding_count=3,
        findings=UNAVAILABLE_FINDINGS,
        audit_source=AUDIT_SOURCE,
    )
    assert result.findings == UNAVAILABLE_FINDINGS

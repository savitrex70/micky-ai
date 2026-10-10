"""Task 172: independent Stage 7 final-attestation audit tests.

Independent audit boundary over the already-published Task 171 final
evidence attestation. The audit derives the expected certification
state from the published Task 168-170 evidence rather than trusting
Task 171, and never calls Task 171, Tasks 168-170 services,
recomputes fingerprints, invokes a provider, or accesses a database.
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
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
    ReasoningRunStage7FinalAttestationAuditRead,
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
from rop.services.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

AUDIT_SOURCE = REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172


def _session_id() -> str:
    return str(uuid4())


def _ready_package(ready_bundle_evidence) -> ReasoningRunStage7EvidencePackageRead:
    session_id = _session_id()
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


def _consistent_audit(
    package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageAuditRead:
    return ReasoningRunStage7EvidencePackageAuditRead(
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


def _consistent_consistency(
    package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageAuditConsistencyRead:
    return ReasoningRunStage7EvidencePackageAuditConsistencyRead(
        session_id=package.session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    )


def _certified_attestation(package, audit, consistency):
    attested = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=package, audit=audit, consistency=consistency
    )
    return ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(attested)


@pytest.fixture
def ready_chain(ready_bundle_evidence):
    package = _ready_package(ready_bundle_evidence)
    audit = _consistent_audit(package)
    consistency = _consistent_consistency(package)
    attestation = _certified_attestation(package, audit, consistency)
    return {
        "package": package,
        "audit": audit,
        "consistency": consistency,
        "attestation": attestation,
    }


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_forbids_extra_fields() -> None:
    session_id = _session_id()
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=session_id,
            attestation_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_attestation_status="CERTIFIED",
            expected_attestation_status="CERTIFIED",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
            extra_field="unexpected",  # type: ignore
        )


def test_schema_requires_canonical_source() -> None:
    with pytest.raises(ValidationError, match="canonical Task 172 source"):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=_session_id(),
            attestation_audit_status="UNAVAILABLE",
            available=False,
            consistent=False,
            published_attestation_status="UNAVAILABLE",
            expected_attestation_status="UNAVAILABLE",
            finding_count=1,
            findings=["INPUT_MISSING"],
            audit_source="FORGED_SOURCE",
        )


def test_schema_consistent_requires_status_agreement() -> None:
    session_id = _session_id()
    with pytest.raises(ValidationError, match="CONSISTENT requires published"):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=session_id,
            attestation_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_attestation_status="BLOCKED",
            expected_attestation_status="CERTIFIED",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_consistent_requires_no_findings() -> None:
    session_id = _session_id()
    with pytest.raises(ValidationError, match="CONSISTENT requires a finding-free"):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=session_id,
            attestation_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_attestation_status="CERTIFIED",
            expected_attestation_status="CERTIFIED",
            finding_count=1,
            findings=["SOME_FINDING"],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_inconsistent_requires_findings() -> None:
    session_id = _session_id()
    with pytest.raises(ValidationError, match="INCONSISTENT requires at least one"):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=session_id,
            attestation_audit_status="INCONSISTENT",
            available=True,
            consistent=False,
            published_attestation_status="BLOCKED",
            expected_attestation_status="CERTIFIED",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_flag_coherence() -> None:
    session_id = _session_id()
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=session_id,
            attestation_audit_status="CONSISTENT",
            available=False,
            consistent=True,
            published_attestation_status="CERTIFIED",
            expected_attestation_status="CERTIFIED",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7FinalAttestationAuditRead(
            session_id=session_id,
            attestation_audit_status="CONSISTENT",
            available=True,
            consistent=False,
            published_attestation_status="CERTIFIED",
            expected_attestation_status="CERTIFIED",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_audit_certified_chain_is_consistent(ready_chain) -> None:
    """Genuine CERTIFIED attestation audits CONSISTENT."""
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    assert audit["attestation_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["published_attestation_status"] == "CERTIFIED"
    assert audit["expected_attestation_status"] == "CERTIFIED"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["session_id"] == ready_chain["package"].session_id
    assert audit["audit_source"] == AUDIT_SOURCE


def _blocked_package(
    package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageRead:
    package.t162_admission_status = "BLOCKED"
    package.t162_finding_count = 1
    package.t162_findings = ["BLOCKED"]
    package.package_status = "BLOCKED"
    package.finding_count = 1
    package.findings = ["BLOCKED"]
    return ReasoningRunStage7EvidencePackageRead.model_validate(package.model_dump())


def test_audit_blocked_chain_is_consistent(ready_chain) -> None:
    """Genuine BLOCKED attestation with matching evidence audits CONSISTENT."""
    package = _blocked_package(copy.deepcopy(ready_chain["package"]))
    audit_inputs = copy.deepcopy(ready_chain["audit"])
    audit_inputs.published_package_status = "BLOCKED"
    audit_inputs.expected_package_status = "BLOCKED"
    consistency = copy.deepcopy(ready_chain["consistency"])
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=package, audit=audit_inputs, consistency=consistency
    )
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        attestation_dict
    )
    assert attestation.attestation_status == "BLOCKED"

    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=audit_inputs,
        consistency=consistency,
        attestation=attestation,
    )
    assert audit["attestation_audit_status"] == "CONSISTENT"
    assert audit["published_attestation_status"] == "BLOCKED"
    assert audit["expected_attestation_status"] == "BLOCKED"


def test_audit_detects_forged_certified_status(ready_chain) -> None:
    """Forged CERTIFIED status over BLOCKED evidence is INCONSISTENT."""
    package = _blocked_package(copy.deepcopy(ready_chain["package"]))
    attestation_dict = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
    )
    forged = copy.deepcopy(attestation_dict)
    forged["attestation_status"] = "CERTIFIED"
    forged["certified"] = True
    forged["blocked"] = False
    forged["available"] = True
    forged["findings"] = []
    forged["finding_count"] = 0

    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=forged,
    )
    assert audit["attestation_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_attestation_status"] == "BLOCKED"


def test_audit_detects_session_mismatch(ready_chain) -> None:
    """Detached attestation from another session is INCONSISTENT."""
    other = copy.deepcopy(ready_chain["attestation"])
    other_dict = other.model_dump()
    other_dict["session_id"] = str(uuid4())
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=other_dict,
    )
    assert audit["attestation_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit["findings"]


def _assert_unverifiable_but_published(result: dict, *, published: str) -> None:
    """Malformed upstream evidence: unverifiable, yet the published claim holds."""
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["published_attestation_status"] == published
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]
    assert result["finding_count"] == 1
    assert result["session_id"] == ""
    assert result["audit_source"] == AUDIT_SOURCE
    # Result must remain a schema-valid Task 172 audit.
    ReasoningRunStage7FinalAttestationAuditRead.model_validate(result)


def test_audit_detects_wrong_package_source(ready_chain) -> None:
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    _assert_unverifiable_but_published(audit, published="CERTIFIED")


def test_audit_detects_wrong_audit_source(ready_chain) -> None:
    audit_inputs = copy.deepcopy(ready_chain["audit"])
    audit_inputs.audit_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=audit_inputs,
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    _assert_unverifiable_but_published(audit, published="CERTIFIED")


def test_audit_detects_wrong_consistency_source(ready_chain) -> None:
    consistency = copy.deepcopy(ready_chain["consistency"])
    consistency.consistency_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=consistency,
        attestation=ready_chain["attestation"],
    )
    _assert_unverifiable_but_published(audit, published="CERTIFIED")


def _blocked_chain(ready_chain):
    """Genuine BLOCKED attestation together with its matching evidence."""
    package = _blocked_package(copy.deepcopy(ready_chain["package"]))
    audit_inputs = copy.deepcopy(ready_chain["audit"])
    audit_inputs.published_package_status = "BLOCKED"
    audit_inputs.expected_package_status = "BLOCKED"
    consistency = copy.deepcopy(ready_chain["consistency"])
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        ReasoningRunStage7FinalEvidenceAttestationService.attest(
            package=package, audit=audit_inputs, consistency=consistency
        )
    )
    assert attestation.attestation_status == "BLOCKED"
    return package, audit_inputs, consistency, attestation


@pytest.mark.parametrize("malformed", ["audit", "consistency"])
def test_malformed_audit_or_consistency_preserves_blocked_status(
    ready_chain, malformed
) -> None:
    package, audit_inputs, consistency, attestation = _blocked_chain(ready_chain)
    if malformed == "audit":
        audit_inputs.audit_source = "WRONG_SOURCE"
    else:
        consistency.consistency_source = "WRONG_SOURCE"

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=audit_inputs,
        consistency=consistency,
        attestation=attestation,
    )

    _assert_unverifiable_but_published(result, published="BLOCKED")


@pytest.mark.parametrize("malformed", ["package", "audit", "consistency"])
def test_malformed_evidence_with_valid_certified_attestation(
    ready_chain, malformed
) -> None:
    inputs = {
        "package": copy.deepcopy(ready_chain["package"]),
        "audit": copy.deepcopy(ready_chain["audit"]),
        "consistency": copy.deepcopy(ready_chain["consistency"]),
    }
    if malformed == "package":
        inputs["package"].session_id = []
    elif malformed == "audit":
        inputs["audit"].session_id = []
    else:
        inputs["consistency"].session_id = []

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        **inputs, attestation=ready_chain["attestation"]
    )

    _assert_unverifiable_but_published(result, published="CERTIFIED")


def test_malformed_evidence_with_attestation_dict_preserves_status(
    ready_chain,
) -> None:
    """A published attestation supplied as a plain dict is read the same way."""
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"].model_dump(),
    )
    _assert_unverifiable_but_published(result, published="CERTIFIED")


def test_malformed_evidence_with_unreadable_attestation_invents_no_claim(
    ready_chain,
) -> None:
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation={"attestation_status": "GARBAGE"},
    )

    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["published_attestation_status"] is None
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["ATTESTATION_INVALID", "EVIDENCE_INPUT_INVALID"]
    assert result["finding_count"] == 2


@pytest.mark.parametrize("attestation", [None, "CERTIFIED", 7, []])
def test_malformed_evidence_with_wrong_attestation_type_is_unavailable(
    ready_chain, attestation
) -> None:
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=attestation,  # type: ignore[arg-type]
    )

    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["ATTESTATION_INVALID", "EVIDENCE_INPUT_INVALID"]


def test_malformed_evidence_revalidates_mutated_attestation(ready_chain) -> None:
    """A mutated attestation is revalidated, not trusted, beside bad evidence."""
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    mutated = copy.deepcopy(ready_chain["attestation"])
    mutated.attestation_status = "NOT_A_STATUS"  # type: ignore[assignment]

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=mutated,
    )

    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None
    assert result["findings"] == ["ATTESTATION_INVALID", "EVIDENCE_INPUT_INVALID"]


def test_malformed_evidence_with_readable_status_but_invalid_attestation(
    ready_chain,
) -> None:
    """A readable status survives an otherwise invalid attestation and bad evidence."""
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    broken = ready_chain["attestation"].model_dump()
    broken["finding_count"] = "not-an-int"

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )

    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["ATTESTATION_INVALID", "EVIDENCE_INPUT_INVALID"]


def test_malformed_evidence_path_is_deterministic_and_does_not_mutate(
    ready_chain,
) -> None:
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    before = {
        "package": package.model_dump(),
        "audit": ready_chain["audit"].model_dump(),
        "consistency": ready_chain["consistency"].model_dump(),
        "attestation": ready_chain["attestation"].model_dump(),
    }

    first = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    second = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )

    assert first == second
    assert package.model_dump() == before["package"]
    assert ready_chain["audit"].model_dump() == before["audit"]
    assert ready_chain["consistency"].model_dump() == before["consistency"]
    assert ready_chain["attestation"].model_dump() == before["attestation"]


def test_malformed_evidence_never_claims_verified_consistency(ready_chain) -> None:
    """Even when the published and expected statuses could coincide."""
    package, audit_inputs, consistency, attestation = _blocked_chain(ready_chain)
    audit_inputs.audit_source = "WRONG_SOURCE"
    unavailable_attestation = attestation.model_dump()
    unavailable_attestation.update(
        {
            "attestation_status": "UNAVAILABLE",
            "certified": False,
            "blocked": False,
            "available": False,
        }
    )

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=audit_inputs,
        consistency=consistency,
        attestation=unavailable_attestation,
    )

    assert result["published_attestation_status"] == "UNAVAILABLE"
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["consistent"] is False
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]


def test_audit_malformed_attestation_dict_is_unavailable(ready_chain) -> None:
    """Garbage attestation input yields UNAVAILABLE, not an exception."""
    audit = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation={"attestation_status": "GARBAGE"},
    )
    assert audit["attestation_audit_status"] == "UNAVAILABLE"
    assert audit["published_attestation_status"] is None
    assert "ATTESTATION_INVALID" in audit["findings"]


def test_audit_revalidates_post_construction_evidence_mutation(ready_chain) -> None:
    ready_chain["package"].session_id = []

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )

    # The mutated evidence is unreadable, so nothing is independently
    # verified, but the published CERTIFIED claim is preserved, not replaced.
    _assert_unverifiable_but_published(result, published="CERTIFIED")


def test_audit_rejects_wrong_evidence_types(ready_chain) -> None:
    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=None,  # type: ignore[arg-type]
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )

    _assert_unverifiable_but_published(result, published="CERTIFIED")


def test_inconsistent_upstream_audit_does_not_claim_blocked(ready_chain) -> None:
    bad_audit = copy.deepcopy(ready_chain["audit"])
    bad_audit.package_audit_status = "INCONSISTENT"
    bad_audit.consistent = False
    bad_audit.finding_count = 1
    bad_audit.findings = ["AUDIT_DISAGREES"]

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=bad_audit,
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )

    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_STATUS_MISMATCH" in result["findings"]


def test_session_mismatch_makes_expected_attestation_unavailable(ready_chain) -> None:
    detached_audit = copy.deepcopy(ready_chain["audit"])
    detached_audit.session_id = _session_id()

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=detached_audit,
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )

    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]
    assert "ATTESTATION_STATUS_MISMATCH" in result["findings"]


def test_audit_does_not_mutate_inputs(ready_chain) -> None:
    """Audit inputs are immutable."""
    before = {
        "package": ready_chain["package"].model_dump(),
        "audit": ready_chain["audit"].model_dump(),
        "consistency": ready_chain["consistency"].model_dump(),
        "attestation": ready_chain["attestation"].model_dump(),
    }
    ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    assert ready_chain["package"].model_dump() == before["package"]
    assert ready_chain["audit"].model_dump() == before["audit"]
    assert ready_chain["consistency"].model_dump() == before["consistency"]
    assert ready_chain["attestation"].model_dump() == before["attestation"]


def test_audit_deterministic(ready_chain) -> None:
    first = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    second = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=ready_chain["attestation"],
    )
    assert first == second


def test_audit_has_no_provider_or_runtime_access() -> None:
    """Architecture: audit source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_final_attestation_audit as module

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
# Unknown published status (None) vs. genuinely published UNAVAILABLE
# ---------------------------------------------------------------------------


def _unavailable_attestation_chain(ready_chain):
    """Genuinely published UNAVAILABLE attestation with matching evidence."""
    bad_audit = copy.deepcopy(ready_chain["audit"])
    bad_audit.package_audit_status = "INCONSISTENT"
    bad_audit.consistent = False
    bad_audit.finding_count = 1
    bad_audit.findings = ["AUDIT_DISAGREES"]
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        ReasoningRunStage7FinalEvidenceAttestationService.attest(
            package=ready_chain["package"],
            audit=bad_audit,
            consistency=ready_chain["consistency"],
        )
    )
    assert attestation.attestation_status == "UNAVAILABLE"
    return bad_audit, attestation


def _unknown_status_result(**overrides):
    fields = {
        "session_id": "",
        "attestation_audit_status": "UNAVAILABLE",
        "available": False,
        "consistent": False,
        "published_attestation_status": None,
        "expected_attestation_status": "UNAVAILABLE",
        "finding_count": 1,
        "findings": ["ATTESTATION_INVALID"],
        "audit_source": AUDIT_SOURCE,
    }
    fields.update(overrides)
    return fields


def test_schema_accepts_unknown_published_status() -> None:
    result = ReasoningRunStage7FinalAttestationAuditRead(**_unknown_status_result())
    assert result.published_attestation_status is None


def test_schema_requires_published_status_field() -> None:
    """None is explicit: omitting the field is still a contract error."""
    fields = _unknown_status_result()
    del fields["published_attestation_status"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalAttestationAuditRead(**fields)


def test_schema_unknown_published_status_requires_unavailable_audit() -> None:
    with pytest.raises(ValidationError, match="requires an UNAVAILABLE audit"):
        ReasoningRunStage7FinalAttestationAuditRead(
            **_unknown_status_result(
                attestation_audit_status="INCONSISTENT",
                available=True,
                findings=["ATTESTATION_INVALID", "ATTESTATION_STATUS_MISMATCH"],
                finding_count=2,
            )
        )
    with pytest.raises(ValidationError, match="requires an UNAVAILABLE audit"):
        ReasoningRunStage7FinalAttestationAuditRead(
            **_unknown_status_result(
                attestation_audit_status="CONSISTENT",
                available=True,
                consistent=True,
                findings=[],
                finding_count=0,
            )
        )


def test_schema_unknown_published_status_requires_attestation_invalid() -> None:
    with pytest.raises(ValidationError, match="ATTESTATION_INVALID"):
        ReasoningRunStage7FinalAttestationAuditRead(
            **_unknown_status_result(
                findings=["EVIDENCE_INPUT_INVALID"], finding_count=1
            )
        )


def test_schema_unknown_published_status_keeps_other_contracts() -> None:
    with pytest.raises(ValidationError, match="canonical Task 172 source"):
        ReasoningRunStage7FinalAttestationAuditRead(
            **_unknown_status_result(audit_source="FORGED_SOURCE")
        )
    with pytest.raises(ValidationError, match="finding_count must equal"):
        ReasoningRunStage7FinalAttestationAuditRead(
            **_unknown_status_result(finding_count=2)
        )


def test_schema_published_unavailable_is_distinct_from_unknown() -> None:
    """A genuine published UNAVAILABLE is a different value from None."""
    published = ReasoningRunStage7FinalAttestationAuditRead(
        session_id=_session_id(),
        attestation_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_attestation_status="UNAVAILABLE",
        expected_attestation_status="UNAVAILABLE",
        finding_count=0,
        findings=[],
        audit_source=AUDIT_SOURCE,
    )
    unknown = ReasoningRunStage7FinalAttestationAuditRead(**_unknown_status_result())
    assert published.published_attestation_status == "UNAVAILABLE"
    assert unknown.published_attestation_status is None
    assert published.published_attestation_status is not None


def test_genuine_published_unavailable_attestation_is_not_unknown(
    ready_chain,
) -> None:
    bad_audit, attestation = _unavailable_attestation_chain(ready_chain)

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=bad_audit,
        consistency=ready_chain["consistency"],
        attestation=attestation,
    )

    assert result["published_attestation_status"] == "UNAVAILABLE"
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["attestation_audit_status"] == "CONSISTENT"
    assert result["findings"] == []


def test_genuine_published_unavailable_with_malformed_evidence_is_not_unknown(
    ready_chain,
) -> None:
    """Published UNAVAILABLE stays UNAVAILABLE (not None) beside bad evidence."""
    _, attestation = _unavailable_attestation_chain(ready_chain)
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=attestation,
    )

    _assert_unverifiable_but_published(result, published="UNAVAILABLE")


def _without_status(attestation: dict) -> dict:
    attestation = dict(attestation)
    del attestation["attestation_status"]
    return attestation


@pytest.mark.parametrize(
    "bad_status",
    ["MISSING", None, "GARBAGE", "certified", "", 7, ["CERTIFIED"], {"s": 1}],
)
def test_missing_or_invalid_status_is_unknown_not_unavailable(
    ready_chain, bad_status
) -> None:
    broken = ready_chain["attestation"].model_dump()
    if bad_status == "MISSING":
        broken = _without_status(broken)
    else:
        broken["attestation_status"] = bad_status

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )

    assert result["published_attestation_status"] is None
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert "ATTESTATION_INVALID" in result["findings"]
    assert "ATTESTATION_STATUS_MISMATCH" not in result["findings"]
    ReasoningRunStage7FinalAttestationAuditRead.model_validate(result)


@pytest.mark.parametrize("bad_status", ["MISSING", "GARBAGE", None])
def test_missing_or_invalid_status_with_malformed_evidence_is_unknown(
    ready_chain, bad_status
) -> None:
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    broken = ready_chain["attestation"].model_dump()
    if bad_status == "MISSING":
        broken = _without_status(broken)
    else:
        broken["attestation_status"] = bad_status

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )

    assert result["published_attestation_status"] is None
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["findings"] == ["ATTESTATION_INVALID", "EVIDENCE_INPUT_INVALID"]


def test_invalid_attestation_with_readable_status_keeps_that_status(
    ready_chain,
) -> None:
    """An otherwise-invalid attestation with a readable status is not unknown."""
    broken = ready_chain["attestation"].model_dump()
    broken["finding_count"] = "not-an-int"

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )

    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert result["findings"] == ["ATTESTATION_INVALID"]
    ReasoningRunStage7FinalAttestationAuditRead.model_validate(result)


def test_invalid_attestation_with_readable_contradicting_status_is_inconsistent(
    ready_chain,
) -> None:
    package = _blocked_package(copy.deepcopy(ready_chain["package"]))
    broken = ready_chain["attestation"].model_dump()
    broken["finding_count"] = "not-an-int"  # status CERTIFIED stays readable

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )

    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["expected_attestation_status"] == "BLOCKED"
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert result["findings"] == ["ATTESTATION_INVALID", "ATTESTATION_STATUS_MISMATCH"]


@pytest.mark.parametrize("malformed", ["package", "audit", "consistency"])
def test_malformed_evidence_with_valid_blocked_attestation_all_inputs(
    ready_chain, malformed
) -> None:
    package, audit_inputs, consistency, attestation = _blocked_chain(ready_chain)
    if malformed == "package":
        package.package_source = "WRONG_SOURCE"
    elif malformed == "audit":
        audit_inputs.audit_source = "WRONG_SOURCE"
    else:
        consistency.consistency_source = "WRONG_SOURCE"

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=package,
        audit=audit_inputs,
        consistency=consistency,
        attestation=attestation,
    )

    _assert_unverifiable_but_published(result, published="BLOCKED")


def test_unknown_status_path_is_deterministic_and_does_not_mutate(
    ready_chain,
) -> None:
    broken = ready_chain["attestation"].model_dump()
    broken["attestation_status"] = "GARBAGE"
    snapshot = copy.deepcopy(broken)
    before = {
        "package": ready_chain["package"].model_dump(),
        "audit": ready_chain["audit"].model_dump(),
        "consistency": ready_chain["consistency"].model_dump(),
    }

    first = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )
    second = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=broken,
    )

    assert first == second
    assert first["published_attestation_status"] is None
    assert broken == snapshot
    assert ready_chain["package"].model_dump() == before["package"]
    assert ready_chain["audit"].model_dump() == before["audit"]
    assert ready_chain["consistency"].model_dump() == before["consistency"]


def test_post_construction_mutation_to_invalid_status_is_unknown(
    ready_chain,
) -> None:
    """A model mutated after construction is revalidated, not trusted."""
    mutated = copy.deepcopy(ready_chain["attestation"])
    mutated.attestation_status = "NOT_A_STATUS"  # type: ignore[assignment]

    result = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=ready_chain["package"],
        audit=ready_chain["audit"],
        consistency=ready_chain["consistency"],
        attestation=mutated,
    )

    assert result["published_attestation_status"] is None
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert "ATTESTATION_INVALID" in result["findings"]
    assert result["audit_source"] == AUDIT_SOURCE

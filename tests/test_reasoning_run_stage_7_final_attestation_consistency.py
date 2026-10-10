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
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
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
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

CONSISTENCY_SOURCE = REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
AUDIT_SOURCE = REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172


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
    return {
        "attestation": attestation,
        "audit": audit,
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


def test_schema_requires_canonical_source() -> None:
    with pytest.raises(ValidationError, match="canonical Task 173 source"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id="",
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=1,
            findings=["EVIDENCE_INPUT_INVALID"],
            consistency_source="FORGED_SOURCE",
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


def test_schema_unavailable_requires_blank_session() -> None:
    with pytest.raises(ValidationError, match="must not claim a session"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=str(uuid4()),
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=1,
            findings=["EVIDENCE_INPUT_INVALID"],
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
    audit.attestation_audit_status = "INCONSISTENT"
    audit.consistent = False
    audit.published_attestation_status = "BLOCKED"
    audit.finding_count = 1
    audit.findings = ["PUBLISHED_STATUS_MISMATCH"]
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]


def test_verify_detects_expected_status_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.attestation_audit_status = "INCONSISTENT"
    audit.consistent = False
    audit.expected_attestation_status = "BLOCKED"
    audit.finding_count = 1
    audit.findings = ["EXPECTED_STATUS_MISMATCH"]
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
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_verify_detects_wrong_audit_source(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.audit_source = "WRONG_SOURCE"
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_verify_detects_finding_count_mismatch(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.attestation_audit_status = "INCONSISTENT"
    audit.consistent = False
    audit.finding_count = 2
    audit.findings = ["ISSUE_ONE", "ISSUE_TWO"]
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in result["findings"]
    assert "AUDIT_HAS_FINDINGS" in result["findings"]


def test_verify_accepts_valid_blocked_attestation_findings(ready_chain) -> None:
    attestation = copy.deepcopy(ready_chain["attestation"])
    attestation.attestation_status = "BLOCKED"
    attestation.certified = False
    attestation.blocked = True
    attestation.package_status = "BLOCKED"
    attestation.finding_count = 1
    attestation.findings = ["PACKAGE_BLOCKED"]
    audit = copy.deepcopy(ready_chain["audit"])
    audit.published_attestation_status = "BLOCKED"
    audit.expected_attestation_status = "BLOCKED"

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=audit
    )

    assert result["consistency_status"] == "CONSISTENT"
    assert result["findings"] == []


def test_verify_revalidates_mutated_inputs(ready_chain) -> None:
    ready_chain["attestation"].session_id = []

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=ready_chain["audit"]
    )

    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_verify_handles_wrong_input_types(ready_chain) -> None:
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=None,  # type: ignore[arg-type]
        audit=ready_chain["audit"],
    )

    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


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


# ---------------------------------------------------------------------------
# UNAVAILABLE evidence is preserved, not escalated to INCONSISTENT
# ---------------------------------------------------------------------------


def _unavailable_audit(
    published: str | None, *, findings: list[str] | None = None
) -> ReasoningRunStage7FinalAttestationAuditRead:
    """A contract-valid Task 172 audit that could not verify anything."""
    if findings is None:
        findings = (
            ["ATTESTATION_INVALID"] if published is None else ["EVIDENCE_INPUT_INVALID"]
        )
    return ReasoningRunStage7FinalAttestationAuditRead(
        session_id="",
        attestation_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_attestation_status=published,
        expected_attestation_status="UNAVAILABLE",
        finding_count=len(findings),
        findings=findings,
        audit_source=AUDIT_SOURCE,
    )


def _assert_unavailable(result: dict, *, findings: list[str]) -> None:
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["findings"] == findings
    assert result["finding_count"] == len(findings)
    assert result["consistency_source"] == CONSISTENCY_SOURCE
    ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(result)


def test_unknown_published_status_audit_is_unavailable_not_inconsistent(
    ready_chain,
) -> None:
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=_unavailable_audit(None)
    )

    _assert_unavailable(
        result, findings=["AUDIT_UNAVAILABLE", "PUBLISHED_STATUS_UNKNOWN"]
    )
    assert "PUBLISHED_STATUS_MISMATCH" not in result["findings"]
    assert "SESSION_MISMATCH" not in result["findings"]


@pytest.mark.parametrize("published", ["CERTIFIED", "BLOCKED", "UNAVAILABLE"])
def test_readable_published_status_with_unavailable_audit_is_unavailable(
    ready_chain, published
) -> None:
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=_unavailable_audit(published)
    )

    _assert_unavailable(result, findings=["AUDIT_UNAVAILABLE"])


def test_unavailable_audit_findings_are_not_escalated(ready_chain) -> None:
    """Audit findings never become AUDIT_HAS_FINDINGS / AUDIT_STATUS_MISMATCH."""
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"],
        audit=_unavailable_audit(
            "CERTIFIED", findings=["EVIDENCE_INPUT_INVALID", "OTHER_DIAGNOSTIC"]
        ),
    )

    _assert_unavailable(result, findings=["AUDIT_UNAVAILABLE"])


def test_real_task_172_unknown_status_audit_flows_to_unavailable(
    ready_chain,
) -> None:
    """End to end: a real Task 172 audit of an unreadable status."""
    broken = ready_chain["attestation"].model_dump()
    broken["attestation_status"] = "GARBAGE"
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
        ReasoningRunStage7FinalAttestationAuditService.audit(
            package=ready_chain["package"],
            audit=ready_chain["audit_inputs"],
            consistency=ready_chain["consistency_inputs"],
            attestation=broken,
        )
    )
    assert audit.published_attestation_status is None
    assert audit.attestation_audit_status == "UNAVAILABLE"

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    _assert_unavailable(
        result, findings=["AUDIT_UNAVAILABLE", "PUBLISHED_STATUS_UNKNOWN"]
    )


def test_real_task_172_malformed_evidence_audit_flows_to_unavailable(
    ready_chain,
) -> None:
    """End to end: Task 172 preserved CERTIFIED but could not verify evidence."""
    package = copy.deepcopy(ready_chain["package"])
    package.package_source = "WRONG_SOURCE"
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
        ReasoningRunStage7FinalAttestationAuditService.audit(
            package=package,
            audit=ready_chain["audit_inputs"],
            consistency=ready_chain["consistency_inputs"],
            attestation=ready_chain["attestation"],
        )
    )
    assert audit.published_attestation_status == "CERTIFIED"
    assert audit.attestation_audit_status == "UNAVAILABLE"

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    _assert_unavailable(result, findings=["AUDIT_UNAVAILABLE"])


def _published_unavailable_chain(ready_chain):
    """Genuinely published UNAVAILABLE attestation with a successful audit."""
    bad_audit = copy.deepcopy(ready_chain["audit_inputs"])
    bad_audit.package_audit_status = "INCONSISTENT"
    bad_audit.consistent = False
    bad_audit.finding_count = 1
    bad_audit.findings = ["AUDIT_DISAGREES"]
    attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
        ReasoningRunStage7FinalEvidenceAttestationService.attest(
            package=ready_chain["package"],
            audit=bad_audit,
            consistency=ready_chain["consistency_inputs"],
        )
    )
    assert attestation.attestation_status == "UNAVAILABLE"
    audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
        ReasoningRunStage7FinalAttestationAuditService.audit(
            package=ready_chain["package"],
            audit=bad_audit,
            consistency=ready_chain["consistency_inputs"],
            attestation=attestation,
        )
    )
    return attestation, audit


def test_genuine_published_unavailable_attestation_stays_consistent(
    ready_chain,
) -> None:
    attestation, audit = _published_unavailable_chain(ready_chain)
    assert audit.attestation_audit_status == "CONSISTENT"
    assert audit.published_attestation_status == "UNAVAILABLE"

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=audit
    )

    assert result["consistency_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["findings"] == []
    assert result["session_id"] == attestation.session_id


def test_published_unavailable_attestation_differs_from_unavailable_audit(
    ready_chain,
) -> None:
    """Same attestation: a successful audit binds; an unavailable audit does not."""
    attestation, audit = _published_unavailable_chain(ready_chain)

    bound = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=audit
    )
    unverified = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=attestation, audit=_unavailable_audit("UNAVAILABLE")
    )

    assert bound["consistency_status"] == "CONSISTENT"
    _assert_unavailable(unverified, findings=["AUDIT_UNAVAILABLE"])


def test_conflicting_known_statuses_remain_inconsistent(ready_chain) -> None:
    """A successful audit of a different known status is a real contradiction."""
    audit = copy.deepcopy(ready_chain["audit"])
    audit.published_attestation_status = "BLOCKED"
    audit.expected_attestation_status = "BLOCKED"

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    assert result["consistency_status"] == "INCONSISTENT"
    assert result["available"] is True
    assert result["findings"] == [
        "EXPECTED_STATUS_MISMATCH",
        "PUBLISHED_STATUS_MISMATCH",
    ]


def test_detached_session_remains_inconsistent_with_readable_audit(
    ready_chain,
) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.session_id = str(uuid4())

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    assert result["consistency_status"] == "INCONSISTENT"
    assert result["findings"] == ["SESSION_MISMATCH"]


def test_inconsistent_readable_audit_remains_inconsistent(ready_chain) -> None:
    audit = copy.deepcopy(ready_chain["audit"])
    audit.attestation_audit_status = "INCONSISTENT"
    audit.consistent = False
    audit.finding_count = 1
    audit.findings = ["ATTESTATION_STATUS_MISMATCH"]

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in result["findings"]
    assert "AUDIT_HAS_FINDINGS" in result["findings"]


def test_task_174_does_not_block_on_unavailable_consistency(ready_chain) -> None:
    """Insufficient evidence stays UNAVAILABLE downstream, never BLOCKED."""
    for published in (None, "CERTIFIED"):
        audit = _unavailable_audit(published)
        consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
            ReasoningRunStage7FinalAttestationConsistencyService.verify(
                attestation=ready_chain["attestation"], audit=audit
            )
        )
        assert consistency.consistency_status == "UNAVAILABLE"

        projection = ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=ready_chain["attestation"],
            audit=audit,
            consistency=consistency,
        )

        assert projection["readiness_status"] == "UNAVAILABLE", published
        assert projection["consistency_status"] == "UNAVAILABLE"
        assert projection["attestation_audit_status"] == "UNAVAILABLE"


def test_task_174_still_blocks_on_demonstrated_contradiction(ready_chain) -> None:
    """Contrast: a proven contradiction is still blocking evidence downstream."""
    audit = copy.deepcopy(ready_chain["audit"])
    audit.published_attestation_status = "BLOCKED"
    audit.expected_attestation_status = "BLOCKED"
    consistency = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=ready_chain["attestation"], audit=audit
        )
    )
    assert consistency.consistency_status == "INCONSISTENT"

    projection = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=ready_chain["attestation"], audit=audit, consistency=consistency
    )

    assert projection["readiness_status"] == "BLOCKED"


def test_unavailable_audit_path_is_deterministic_and_does_not_mutate(
    ready_chain,
) -> None:
    audit = _unavailable_audit(None)
    before_attestation = ready_chain["attestation"].model_dump()
    before_audit = audit.model_dump()

    first = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )
    second = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    assert first == second
    assert ready_chain["attestation"].model_dump() == before_attestation
    assert audit.model_dump() == before_audit


def test_post_construction_mutation_of_unavailable_audit_is_revalidated(
    ready_chain,
) -> None:
    """Mutating a valid audit into an incoherent one yields invalid input."""
    audit = _unavailable_audit(None)
    audit.published_attestation_status = "BOGUS"  # type: ignore[assignment]

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    _assert_unavailable(result, findings=["EVIDENCE_INPUT_INVALID"])


def test_mutating_ready_audit_to_unavailable_is_revalidated(ready_chain) -> None:
    """A half-applied UNAVAILABLE mutation breaks its own flags and is rejected."""
    audit = copy.deepcopy(ready_chain["audit"])
    audit.attestation_audit_status = "UNAVAILABLE"

    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"], audit=audit
    )

    _assert_unavailable(result, findings=["EVIDENCE_INPUT_INVALID"])


@pytest.mark.parametrize("bad_audit", [None, "UNAVAILABLE", 7, {"a": 1}])
def test_wrong_audit_types_are_invalid_input_not_unavailable_audit(
    ready_chain, bad_audit
) -> None:
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"],
        audit=bad_audit,  # type: ignore[arg-type]
    )

    _assert_unavailable(result, findings=["EVIDENCE_INPUT_INVALID"])


def test_unavailable_audit_with_wrong_attestation_type_is_invalid_input(
    ready_chain,
) -> None:
    result = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=ready_chain["attestation"].model_dump(),  # type: ignore[arg-type]
        audit=_unavailable_audit(None),
    )

    _assert_unavailable(result, findings=["EVIDENCE_INPUT_INVALID"])


def test_unavailable_result_enforces_canonical_source_and_blank_session() -> None:
    with pytest.raises(ValidationError, match="canonical Task 173 source"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id="",
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=1,
            findings=["AUDIT_UNAVAILABLE"],
            consistency_source="FORGED_SOURCE",
        )
    with pytest.raises(ValidationError, match="must not claim a session"):
        ReasoningRunStage7FinalAttestationConsistencyRead(
            session_id=str(uuid4()),
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=1,
            findings=["AUDIT_UNAVAILABLE"],
            consistency_source=CONSISTENCY_SOURCE,
        )

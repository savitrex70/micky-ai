"""Task 177: Stage 7 release-readiness evidence bundle tests.

Comprehensive tests for the aggregation of Tasks 174, 175, and 176 into
one deterministic evidence bundle.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176,
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleService,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ready_chain():
    """READY projection, CONSISTENT audit, CONSISTENT consistency verdict."""
    session_id = str(uuid4())

    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=session_id,
        readiness_status="READY",
        attestation_status="CERTIFIED",
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=0,
        findings=[],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )

    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id=session_id,
        readiness_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_readiness_status="READY",
        expected_readiness_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )

    consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id=session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    )

    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "session_id": session_id,
    }


def _unavailable_chain():
    """UNAVAILABLE projection with CONSISTENT audit over UNAVAILABLE."""
    session_id = str(uuid4())

    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=session_id,
        readiness_status="UNAVAILABLE",
        attestation_status="UNAVAILABLE",
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=1,
        findings=["INSUFFICIENT_EVIDENCE"],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )

    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id=session_id,
        readiness_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_readiness_status="UNAVAILABLE",
        expected_readiness_status="UNAVAILABLE",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )

    consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id=session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    )

    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "session_id": session_id,
    }


def _blocked_chain():
    """BLOCKED projection with CONSISTENT audit over BLOCKED."""
    session_id = str(uuid4())

    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=session_id,
        readiness_status="BLOCKED",
        attestation_status="BLOCKED",
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=1,
        findings=["BLOCKING_EVIDENCE"],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )

    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id=session_id,
        readiness_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_readiness_status="BLOCKED",
        expected_readiness_status="BLOCKED",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )

    consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id=session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    )

    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "session_id": session_id,
    }


def _bundle(chain):
    return (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
            projection174=chain["projection"],
            audit175=chain["audit"],
            consistency176=chain["consistency"],
        ),
        chain,
    )


def _inconsistent_chain(ready):
    """A schema-valid INCONSISTENT audit directly against the projection."""
    session_id = ready["projection"].session_id

    projection = ready["projection"]
    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id=session_id,
        readiness_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_readiness_status="READY",
        expected_readiness_status="BLOCKED",
        finding_count=1,
        findings=["EXPECTED_STATUS_MISMATCH"],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )
    consistency = ready["consistency"]
    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "session_id": session_id,
    }


# ---------------------------------------------------------------------------
# Aggregate tests
# ---------------------------------------------------------------------------


def test_ready_chain_bundles_ready() -> None:
    bundle, chain = _bundle(_ready_chain())
    assert bundle["bundle_status"] == "READY"
    assert bundle["session_id"] == chain["session_id"]
    assert bundle["finding_count"] == 0
    assert bundle["findings"] == []
    assert bundle["audit_finding_count"] == 0
    assert bundle["consistency_finding_count"] == 0
    assert bundle["bundle_finding_count"] == 0
    assert bundle["bundle_findings"] == []


def test_blocked_chain_bundles_blocked() -> None:
    bundle, chain = _bundle(_blocked_chain())
    assert bundle["bundle_status"] == "BLOCKED"
    assert bundle["session_id"] == chain["session_id"]
    assert bundle["readiness_status"] == "BLOCKED"
    assert bundle["bundle_finding_count"] == 0


def test_unavailable_chain_stays_unavailable() -> None:
    bundle, chain = _bundle(_unavailable_chain())
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["session_id"] == chain["session_id"]
    assert bundle["readiness_status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------


def test_session_mismatch_bundles_unavailable_with_finding() -> None:
    """A schema-valid consistency verdict over a different session mismatches."""
    chain = _ready_chain()
    other = str(uuid4())
    consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id=other,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    )
    bundle, _ = _bundle(
        {
            "projection": chain["projection"],
            "audit": chain["audit"],
            "consistency": consistency,
        }
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["session_id"] == ""
    assert "STAGE_7_SESSION_MISMATCH" in bundle["bundle_findings"]


def test_blank_session_from_forge_is_unavailable_with_finding() -> None:
    """A forged blank-session READY projection is rejected as invalid input."""
    chain = _ready_chain()
    raw = chain["projection"].model_dump()
    raw["session_id"] = ""
    forged = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=raw,
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    assert forged["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in forged["bundle_findings"]


# ---------------------------------------------------------------------------
# Immutability and determinism test
# ---------------------------------------------------------------------------


def test_assembly_does_not_mutate_inputs() -> None:
    chain = _ready_chain()
    before = (
        chain["projection"].model_dump(),
        chain["audit"].model_dump(),
        chain["consistency"].model_dump(),
    )
    ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    after = (
        chain["projection"].model_dump(),
        chain["audit"].model_dump(),
        chain["consistency"].model_dump(),
    )
    assert before == after


def test_assembly_is_deterministic() -> None:
    chain = _ready_chain()
    one = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    two = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    assert one == two


# ---------------------------------------------------------------------------
# Malformed input and mutation detection tests
# ---------------------------------------------------------------------------


def test_wrong_type_projection_bundles_unavailable() -> None:
    chain = _ready_chain()
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174="not a model",
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert "EVIDENCE_INPUT_INVALID" in bundle["consistency_findings"]


def test_wrong_type_audit_bundles_unavailable() -> None:
    chain = _ready_chain()
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175="not a model",
        consistency176=chain["consistency"],
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]


def test_wrong_type_consistency_bundles_unavailable() -> None:
    chain = _ready_chain()
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176="not a model",
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]


def test_mutated_projection_detected() -> None:
    """Post-construction mutation of a projection input is detected."""
    chain = _ready_chain()
    projection = chain["projection"]
    projection.readiness_status = "BLOCKED"
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=projection,
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]


def test_mutated_audit_detected() -> None:
    chain = _ready_chain()
    audit = chain["audit"]
    audit.readiness_audit_status = "INCONSISTENT"
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=audit,
        consistency176=chain["consistency"],
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]


def test_mutated_consistency_detected() -> None:
    chain = _ready_chain()
    consistency = chain["consistency"]
    consistency.consistency_status = "INCONSISTENT"
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=consistency,
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]


def test_task_inputs_with_findings_still_aggregate() -> None:
    """Bundle copies child findings verbatim but never reports them as its own."""
    chain = _blocked_chain()
    bundle, _ = _bundle(chain)
    assert bundle["findings"] == ["BLOCKING_EVIDENCE"]
    assert "BLOCKING_EVIDENCE" not in bundle["bundle_findings"]


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_schema_rejects_mismatched_available() -> None:
    chain = _ready_chain()
    bundle, _ = _bundle(chain)
    bundle["audit_available"] = False
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)


import pytest  # noqa: E402  (isort: skip)


def test_schema_rejects_forged_ready() -> None:
    chain = _blocked_chain()
    bundle, _ = _bundle(chain)
    bundle["bundle_status"] = "READY"
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)


def test_schema_rejects_forged_source() -> None:
    chain = _ready_chain()
    bundle, _ = _bundle(chain)
    bundle["bundle_source"] = "FORGED"
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)


def test_schema_rejects_extra_fields() -> None:
    chain = _ready_chain()
    bundle, _ = _bundle(chain)
    bundle["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)


# ---------------------------------------------------------------------------
# Source-constant test
# ---------------------------------------------------------------------------


def test_source_constant_is_correct() -> None:
    assert (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
        == "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_TASK_177"
    )

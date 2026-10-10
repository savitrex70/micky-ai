"""Task 178: Stage 7 release-readiness evidence bundle audit tests."""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest
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
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService,
)

AUDIT_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
)


# ---------------------------------------------------------------------------
# Fixtures: externally composed Task 174-177 chains
# ---------------------------------------------------------------------------


def _chain(status: str):
    """Build a schema-valid Task 174-176 triple for the requested status."""
    session_id = str(uuid4())

    attestation_status = {
        "READY": "CERTIFIED",
        "BLOCKED": "BLOCKED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[status]
    finding = {
        "READY": None,
        "BLOCKED": "BLOCKING_EVIDENCE",
        "UNAVAILABLE": "INSUFFICIENT_EVIDENCE",
    }[status]

    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=session_id,
        readiness_status=status,
        attestation_status=attestation_status,
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=1 if finding else 0,
        findings=[finding] if finding else [],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )

    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id=session_id,
        readiness_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_readiness_status=status,
        expected_readiness_status=status,
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

    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=projection,
        audit175=audit,
        consistency176=consistency,
    )
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)
    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "bundle": bundle,
        "session_id": session_id,
    }


@pytest.fixture
def ready_chain() -> dict:
    return _chain("READY")


@pytest.fixture
def blocked_chain() -> dict:
    return _chain("BLOCKED")


@pytest.fixture
def unavailable_chain() -> dict:
    return _chain("UNAVAILABLE")


def _audit(chain) -> dict:
    return ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
        bundle=chain["bundle"],
    )


# ---------------------------------------------------------------------------
# Audit verdict tests
# ---------------------------------------------------------------------------


def test_audit_ready_bundle_is_consistent(ready_chain) -> None:
    audit = _audit(ready_chain)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["published_bundle_status"] == "READY"
    assert audit["expected_bundle_status"] == "READY"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["session_id"] == ready_chain["session_id"]
    assert audit["audit_source"] == AUDIT_SOURCE


def test_audit_blocked_bundle_is_consistent(blocked_chain) -> None:
    audit = _audit(blocked_chain)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["published_bundle_status"] == "BLOCKED"
    assert audit["expected_bundle_status"] == "BLOCKED"
    assert audit["findings"] == []


def test_audit_unavailable_bundle_is_consistent(unavailable_chain) -> None:
    """A correctly represented unavailable readiness outcome is not a contradiction."""
    audit = _audit(unavailable_chain)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["findings"] == []


# ---------------------------------------------------------------------------
# Forgery and mismatch detection
# ---------------------------------------------------------------------------


def test_audit_detects_forged_ready_bundle(ready_chain) -> None:
    """A bundle claiming BLOCKED under READY evidence is forged."""
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_status = "BLOCKED"
    bundle.bundle_finding_count = 1
    bundle.bundle_findings = ["FORGED_BLOCKED"]
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_bundle_status"] == "READY"


def test_audit_detects_forged_blocked_under_ready_evidence(ready_chain) -> None:
    """READY bundle whose Task 174 projection actually says BLOCKED is forged."""
    projection = copy.deepcopy(ready_chain["projection"])
    projection.readiness_status = "BLOCKED"
    projection.finding_count = 1
    projection.findings = ["HIDDEN_BLOCKING"]
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=projection,
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=ready_chain["bundle"],
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]
    assert audit["expected_bundle_status"] == "BLOCKED"


def test_audit_detects_status_echo_mismatches(ready_chain) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.readiness_audit_status = "UNAVAILABLE"
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_ECHO_MISMATCH" in audit["findings"]


def test_audit_detects_session_binding_mismatch(ready_chain) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.session_id = str(uuid4())
    bundle.bundle_status = "UNAVAILABLE"
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit["findings"]
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]


def test_audit_detects_wrong_bundle_source(ready_chain) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_source = "FORGED_SOURCE"
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_SOURCE_INVALID" in audit["findings"]


def test_audit_detects_wrong_upstream_source(ready_chain) -> None:
    projection = copy.deepcopy(ready_chain["projection"])
    projection.projection_source = "FORGED_SOURCE"
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=projection,
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=ready_chain["bundle"],
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "PROJECTION_SOURCE_INVALID" in audit["findings"]


def test_audit_detects_finding_count_tampering(ready_chain) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_finding_count = 5
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_FINDINGS_COHERENCE_INVALID" in audit["findings"]


# ---------------------------------------------------------------------------
# Malformed input, mutation, wrong types
# ---------------------------------------------------------------------------


def test_audit_malformed_bundle_dict_is_unavailable(ready_chain) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle={"bundle_status": "GARBAGE"},
    )
    assert audit["bundle_audit_status"] == "UNAVAILABLE"
    assert "BUNDLE_INVALID" in audit["findings"]


def test_audit_forged_ready_claim_over_garbage_bundle_is_inconsistent(
    ready_chain,
) -> None:
    """A readable forged READY claim over an unreadable record is detected."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle={"bundle_status": "READY", "session_id": "x"},
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "BUNDLE_INVALID" in audit["findings"]
    assert audit["published_bundle_status"] == "READY"


@pytest.mark.parametrize("bad_value", [None, 7, []])
def test_audit_rejects_mutated_upstream_identity(ready_chain, bad_value) -> None:
    projection = copy.deepcopy(ready_chain["projection"])
    projection.session_id = bad_value
    result = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=projection,
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=ready_chain["bundle"],
    )
    assert result["bundle_audit_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_wrong_type_bundle_returns_unavailable(ready_chain) -> None:
    result = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=ready_chain["projection"],
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle="not a bundle",
    )
    assert result["bundle_audit_status"] == "UNAVAILABLE"
    assert "BUNDLE_INVALID" in result["findings"]


def test_wrong_type_projection_returns_unavailable(ready_chain) -> None:
    result = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174="not a projection",
        audit175=ready_chain["audit"],
        consistency176=ready_chain["consistency"],
        bundle=ready_chain["bundle"],
    )
    assert result["bundle_audit_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


# ---------------------------------------------------------------------------
# Immutability, determinism, schema
# ---------------------------------------------------------------------------


def test_audit_does_not_mutate_inputs(ready_chain) -> None:
    before = {
        "projection": ready_chain["projection"].model_dump(),
        "audit": ready_chain["audit"].model_dump(),
        "consistency": ready_chain["consistency"].model_dump(),
        "bundle": ready_chain["bundle"].model_dump(),
    }
    _audit(ready_chain)
    after = {
        "projection": ready_chain["projection"].model_dump(),
        "audit": ready_chain["audit"].model_dump(),
        "consistency": ready_chain["consistency"].model_dump(),
        "bundle": ready_chain["bundle"].model_dump(),
    }
    assert before == after


def test_audit_is_deterministic(ready_chain) -> None:
    assert _audit(ready_chain) == _audit(ready_chain)


def test_schema_rejects_incoherent_flags() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
            session_id="s",
            bundle_audit_status="CONSISTENT",
            available=False,
            consistent=True,
            published_bundle_status="READY",
            expected_bundle_status="READY",
            finding_count=0,
            findings=[],
            audit_source=AUDIT_SOURCE,
        )


def test_schema_rejects_forged_source() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
            session_id="s",
            bundle_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_bundle_status="READY",
            expected_bundle_status="READY",
            finding_count=0,
            findings=[],
            audit_source="FORGED",
        )


def test_source_constant_is_correct() -> None:
    assert (
        AUDIT_SOURCE
        == "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_TASK_178"
    )

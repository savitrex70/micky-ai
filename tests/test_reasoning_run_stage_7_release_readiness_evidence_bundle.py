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


# ---------------------------------------------------------------------------
# Task 177 correction: aggregate-findings contract
# ---------------------------------------------------------------------------

_SERVICE = ReasoningRunStage7ReleaseReadinessEvidenceBundleService
_BUNDLE_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead


def _ready_bundle_dict() -> dict:
    bundle, _ = _bundle(_ready_chain())
    return bundle


def test_schema_accepts_empty_aggregate_findings() -> None:
    bundle = _ready_bundle_dict()
    assert bundle["bundle_findings"] == []
    assert bundle["bundle_finding_count"] == 0
    validated = _BUNDLE_READ.model_validate(bundle)
    assert validated.model_dump() == bundle


def test_schema_accepts_sorted_non_empty_aggregate_findings() -> None:
    bundle = _ready_bundle_dict()
    bundle["session_id"] = ""
    bundle["bundle_status"] = "UNAVAILABLE"
    bundle["bundle_findings"] = ["EVIDENCE_INPUT_INVALID", "STAGE_7_SESSION_MISMATCH"]
    bundle["bundle_finding_count"] = 2
    validated = _BUNDLE_READ.model_validate(bundle)
    assert validated.bundle_findings == [
        "EVIDENCE_INPUT_INVALID",
        "STAGE_7_SESSION_MISMATCH",
    ]
    assert validated.bundle_finding_count == 2


def test_schema_accepts_service_produced_non_empty_aggregate() -> None:
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
    bundle = _SERVICE.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=consistency,
    )
    assert bundle["bundle_findings"] == ["STAGE_7_SESSION_MISMATCH"]
    assert bundle["bundle_finding_count"] == 1
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


def test_schema_rejects_incorrect_bundle_finding_count() -> None:
    bundle = _ready_bundle_dict()
    bundle["bundle_finding_count"] = 1
    with pytest.raises(ValidationError, match="bundle_finding_count must equal"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_incorrect_bundle_finding_count_on_non_empty() -> None:
    bundle = _ready_bundle_dict()
    bundle["session_id"] = ""
    bundle["bundle_status"] = "UNAVAILABLE"
    bundle["bundle_findings"] = ["STAGE_7_SESSION_MISMATCH"]
    bundle["bundle_finding_count"] = 0
    with pytest.raises(ValidationError, match="bundle_finding_count must equal"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_duplicate_bundle_findings() -> None:
    bundle = _ready_bundle_dict()
    bundle["session_id"] = ""
    bundle["bundle_status"] = "UNAVAILABLE"
    bundle["bundle_findings"] = ["STAGE_7_SESSION_MISMATCH"] * 2
    bundle["bundle_finding_count"] = 2
    with pytest.raises(ValidationError, match="bundle_findings must not contain"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_unsorted_bundle_findings() -> None:
    bundle = _ready_bundle_dict()
    bundle["session_id"] = ""
    bundle["bundle_status"] = "UNAVAILABLE"
    bundle["bundle_findings"] = ["STAGE_7_SESSION_MISMATCH", "EVIDENCE_INPUT_INVALID"]
    bundle["bundle_finding_count"] = 2
    with pytest.raises(ValidationError, match="bundle_findings must be sorted"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_ready_with_aggregate_findings() -> None:
    """A READY bundle must be free of its own aggregate findings."""
    bundle = _ready_bundle_dict()
    bundle["bundle_findings"] = ["EVIDENCE_INPUT_INVALID"]
    bundle["bundle_finding_count"] = 1
    with pytest.raises(ValidationError, match="READY bundle requires complete"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_session_mismatch_finding_claiming_a_session() -> None:
    for status in ("READY", "UNAVAILABLE"):
        bundle = _ready_bundle_dict()
        bundle["bundle_status"] = status
        bundle["bundle_findings"] = ["STAGE_7_SESSION_MISMATCH"]
        bundle["bundle_finding_count"] = 1
        assert bundle["session_id"] != ""
        with pytest.raises(ValidationError, match="shared session_id"):
            _BUNDLE_READ.model_validate(bundle)


# ---------------------------------------------------------------------------
# Task 177 correction: verdict precedence and coherence
# ---------------------------------------------------------------------------

_READINESS = ("READY", "BLOCKED", "UNAVAILABLE")
_CHECKS = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")
_MATRIX = [(r, a, c) for r in _READINESS for a in _CHECKS for c in _CHECKS]
_MATRIX_IDS = [f"proj-{r}-audit-{a}-cons-{c}" for r, a, c in _MATRIX]


def _matrix_chain(readiness, audit_status, consistency_status, session_id=None):
    """Build a schema-valid chain for any combination of upstream statuses.

    Follows the established contracts: a projection carries findings unless
    READY, a CONSISTENT audit publishes and expects the projected status, an
    INCONSISTENT audit or consistency verdict carries a finding, and an
    UNAVAILABLE audit or consistency verdict carries a finding and an empty
    session identity (Tasks 175 and 176).
    """
    session_id = session_id or str(uuid4())
    attestation = {
        "READY": "CERTIFIED",
        "BLOCKED": "BLOCKED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[readiness]
    projection_findings = {
        "READY": [],
        "BLOCKED": ["BLOCKING_EVIDENCE"],
        "UNAVAILABLE": ["INSUFFICIENT_EVIDENCE"],
    }[readiness]
    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=session_id,
        readiness_status=readiness,
        attestation_status=attestation,
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=len(projection_findings),
        findings=projection_findings,
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )

    if audit_status == "CONSISTENT":
        audit_findings, expected = [], readiness
    elif audit_status == "INCONSISTENT":
        audit_findings = ["EXPECTED_STATUS_MISMATCH"]
        expected = "BLOCKED" if readiness != "BLOCKED" else "UNAVAILABLE"
    else:
        audit_findings, expected = ["PROJECTION_UNAVAILABLE"], "UNAVAILABLE"
    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id="" if audit_status == "UNAVAILABLE" else session_id,
        readiness_audit_status=audit_status,
        available=audit_status != "UNAVAILABLE",
        consistent=audit_status == "CONSISTENT",
        published_readiness_status=(
            "UNAVAILABLE" if audit_status == "UNAVAILABLE" else readiness
        ),
        expected_readiness_status=expected,
        finding_count=len(audit_findings),
        findings=audit_findings,
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )

    consistency_findings = {
        "CONSISTENT": [],
        "INCONSISTENT": ["AUDIT_DETACHED"],
        "UNAVAILABLE": ["AUDIT_UNAVAILABLE"],
    }[consistency_status]
    consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id="" if consistency_status == "UNAVAILABLE" else session_id,
        consistency_status=consistency_status,
        available=consistency_status != "UNAVAILABLE",
        consistent=consistency_status == "CONSISTENT",
        finding_count=len(consistency_findings),
        findings=consistency_findings,
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


def _expected_verdict(readiness, audit_status, consistency_status) -> str:
    """Independent oracle derived from the published Task 174-176 contracts."""
    if (
        readiness == "BLOCKED"
        or audit_status == "INCONSISTENT"
        or consistency_status == "INCONSISTENT"
    ):
        return "BLOCKED"
    if (
        readiness == "READY"
        and audit_status == "CONSISTENT"
        and consistency_status == "CONSISTENT"
    ):
        return "READY"
    return "UNAVAILABLE"


@pytest.mark.parametrize(("readiness", "audit", "cons"), _MATRIX, ids=_MATRIX_IDS)
def test_verdict_matrix_matches_established_contracts(readiness, audit, cons) -> None:
    bundle, chain = _bundle(_matrix_chain(readiness, audit, cons))
    assert bundle["bundle_status"] == _expected_verdict(readiness, audit, cons)
    # Service output is always schema-valid and round-trips unchanged.
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle
    if "UNAVAILABLE" in (audit, cons):
        # Unavailable evidence cannot establish a shared session.
        assert bundle["session_id"] == ""
        assert "STAGE_7_SESSION_MISMATCH" in bundle["bundle_findings"]
        assert bundle["bundle_status"] != "READY"
    else:
        assert bundle["session_id"] == chain["session_id"]
        assert bundle["bundle_findings"] == []
    assert bundle["bundle_finding_count"] == len(bundle["bundle_findings"])


@pytest.mark.parametrize(("readiness", "audit", "cons"), _MATRIX, ids=_MATRIX_IDS)
def test_forged_aggregate_status_is_rejected_for_every_combination(
    readiness, audit, cons
) -> None:
    bundle, _ = _bundle(_matrix_chain(readiness, audit, cons))
    for forged in _READINESS:
        if forged == bundle["bundle_status"]:
            continue
        with pytest.raises(ValidationError):
            _BUNDLE_READ.model_validate({**bundle, "bundle_status": forged})


def test_only_the_fully_supported_chain_is_ready() -> None:
    ready = [
        combo
        for combo in _MATRIX
        if _bundle(_matrix_chain(*combo))[0]["bundle_status"] == "READY"
    ]
    assert ready == [("READY", "CONSISTENT", "CONSISTENT")]


@pytest.mark.parametrize(
    ("readiness", "audit", "cons"),
    [
        ("BLOCKED", "CONSISTENT", "UNAVAILABLE"),
        ("BLOCKED", "UNAVAILABLE", "CONSISTENT"),
        ("BLOCKED", "UNAVAILABLE", "UNAVAILABLE"),
        ("READY", "INCONSISTENT", "UNAVAILABLE"),
        ("READY", "UNAVAILABLE", "INCONSISTENT"),
        ("UNAVAILABLE", "INCONSISTENT", "UNAVAILABLE"),
        ("UNAVAILABLE", "UNAVAILABLE", "INCONSISTENT"),
    ],
)
def test_blocking_condition_takes_precedence_over_unavailable_evidence(
    readiness, audit, cons
) -> None:
    bundle, _ = _bundle(_matrix_chain(readiness, audit, cons))
    assert bundle["bundle_status"] == "BLOCKED"
    assert bundle["session_id"] == ""
    assert "STAGE_7_SESSION_MISMATCH" in bundle["bundle_findings"]


@pytest.mark.parametrize(
    ("audit", "cons"),
    [
        ("UNAVAILABLE", "CONSISTENT"),
        ("CONSISTENT", "UNAVAILABLE"),
        ("UNAVAILABLE", "UNAVAILABLE"),
    ],
)
def test_unavailable_upstream_evidence_never_becomes_ready(audit, cons) -> None:
    bundle, _ = _bundle(_matrix_chain("READY", audit, cons))
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["session_id"] == ""


@pytest.mark.parametrize("position", ["projection", "audit", "consistency"])
def test_session_mismatch_never_ready_and_never_claims_a_session(position) -> None:
    chain = _ready_chain()
    other = _matrix_chain("READY", "CONSISTENT", "CONSISTENT")
    chain[position] = other[position]
    bundle, _ = _bundle(chain)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["session_id"] == ""
    assert bundle["bundle_findings"] == ["STAGE_7_SESSION_MISMATCH"]
    assert bundle["bundle_finding_count"] == 1


def test_session_mismatch_with_blocking_evidence_stays_blocked_without_session() -> (
    None
):
    chain = _matrix_chain("BLOCKED", "CONSISTENT", "CONSISTENT")
    other = _matrix_chain("BLOCKED", "CONSISTENT", "CONSISTENT")
    chain["consistency"] = other["consistency"]
    bundle, _ = _bundle(chain)
    assert bundle["bundle_status"] == "BLOCKED"
    assert bundle["session_id"] == ""
    assert "STAGE_7_SESSION_MISMATCH" in bundle["bundle_findings"]


def test_audit_over_non_ready_status_cannot_support_ready_projection() -> None:
    """A CONSISTENT audit that does not confirm READY never yields READY."""
    chain = _ready_chain()
    session_id = chain["session_id"]
    chain["audit"] = ReasoningRunStage7ReleaseReadinessAuditRead(
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
    bundle, _ = _bundle(chain)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["bundle_status"] != "READY"


def test_inconsistent_audit_evidence_is_blocked_not_ready() -> None:
    bundle, _ = _bundle(_inconsistent_chain(_ready_chain()))
    assert bundle["bundle_status"] == "BLOCKED"
    assert bundle["readiness_audit_status"] == "INCONSISTENT"


def test_fully_supported_chain_produces_ready_with_shared_session() -> None:
    bundle, chain = _bundle(_matrix_chain("READY", "CONSISTENT", "CONSISTENT"))
    assert bundle["bundle_status"] == "READY"
    assert bundle["session_id"] == chain["session_id"]
    assert bundle["bundle_findings"] == []


# ---------------------------------------------------------------------------
# Task 177 correction: input integrity
# ---------------------------------------------------------------------------

_MALFORMED_VALUES = [
    pytest.param(None, id="none"),
    pytest.param({}, id="empty-dict"),
    pytest.param(42, id="int"),
    pytest.param("not a model", id="str"),
    pytest.param([], id="list"),
    pytest.param(object(), id="object"),
]


@pytest.mark.parametrize("bad", _MALFORMED_VALUES)
@pytest.mark.parametrize("position", ["projection174", "audit175", "consistency176"])
def test_malformed_input_is_unavailable_never_ready(position, bad) -> None:
    chain = _ready_chain()
    kwargs = {
        "projection174": chain["projection"],
        "audit175": chain["audit"],
        "consistency176": chain["consistency"],
    }
    kwargs[position] = bad
    bundle = _SERVICE.assemble(**kwargs)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["readiness_status"] == "UNAVAILABLE"
    assert bundle["session_id"] == ""
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


@pytest.mark.parametrize("position", ["projection174", "audit175", "consistency176"])
def test_valid_model_dump_dict_is_not_accepted_as_model(position) -> None:
    chain = _ready_chain()
    kwargs = {
        "projection174": chain["projection"],
        "audit175": chain["audit"],
        "consistency176": chain["consistency"],
    }
    kwargs[position] = kwargs[position].model_dump()
    bundle = _SERVICE.assemble(**kwargs)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]


@pytest.mark.parametrize(
    ("position", "attribute", "value"),
    [
        ("projection", "session_id", ""),
        ("projection", "finding_count", 5),
        ("projection", "projection_source", "FORGED"),
        ("audit", "findings", ["B", "A"]),
        ("audit", "audit_source", "FORGED"),
        ("audit", "finding_count", 3),
        ("consistency", "findings", ["UNEXPECTED"]),
        ("consistency", "consistency_source", "FORGED"),
        ("consistency", "available", False),
    ],
)
def test_post_construction_mutation_never_yields_ready(
    position, attribute, value
) -> None:
    chain = _ready_chain()
    setattr(chain[position], attribute, value)
    mutated_before = chain[position].model_dump()
    bundle, _ = _bundle(chain)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    # The invalid caller object is reported on, never repaired in place.
    assert chain[position].model_dump() == mutated_before


def _session_mismatch_chain():
    chain = _ready_chain()
    chain["consistency"] = _matrix_chain("READY", "CONSISTENT", "CONSISTENT")[
        "consistency"
    ]
    return chain


@pytest.mark.parametrize(
    "factory",
    [
        _ready_chain,
        _blocked_chain,
        _unavailable_chain,
        _session_mismatch_chain,
        lambda: _inconsistent_chain(_ready_chain()),
    ],
    ids=["ready", "blocked", "unavailable", "session-mismatch", "inconsistent"],
)
def test_assembly_is_deterministic_and_leaves_inputs_unchanged(factory) -> None:
    chain = factory()
    before = tuple(
        chain[k].model_dump() for k in ("projection", "audit", "consistency")
    )
    first, _ = _bundle(chain)
    second, _ = _bundle(chain)
    copies, _ = _bundle(
        {
            k: chain[k].model_copy(deep=True)
            for k in ("projection", "audit", "consistency")
        }
    )
    after = tuple(chain[k].model_dump() for k in ("projection", "audit", "consistency"))
    assert first == second == copies
    assert before == after


def test_returned_bundle_does_not_alias_caller_inputs() -> None:
    chain = _blocked_chain()
    bundle, _ = _bundle(chain)
    bundle["findings"].append("MUTATED")
    bundle["audit_findings"].append("MUTATED")
    bundle["consistency_findings"].append("MUTATED")
    assert chain["projection"].findings == ["BLOCKING_EVIDENCE"]
    assert chain["audit"].findings == []
    assert chain["consistency"].findings == []


def test_bundle_echoes_child_sources_and_never_child_findings_as_own() -> None:
    bundle, _ = _bundle(_matrix_chain("BLOCKED", "INCONSISTENT", "INCONSISTENT"))
    assert bundle["bundle_status"] == "BLOCKED"
    assert bundle["projection_source"] == (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
    )
    assert bundle["audit_source"] == (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
    )
    assert bundle["consistency_source"] == (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
    )
    assert bundle["bundle_source"] == (
        REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
    )
    for child_code in (
        "BLOCKING_EVIDENCE",
        "EXPECTED_STATUS_MISMATCH",
        "AUDIT_DETACHED",
    ):
        assert child_code not in bundle["bundle_findings"]


def test_service_module_references_no_child_services() -> None:
    import rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle as mod

    service_names = {name for name in vars(mod) if name.endswith("Service")}
    assert service_names == {"ReasoningRunStage7ReleaseReadinessEvidenceBundleService"}

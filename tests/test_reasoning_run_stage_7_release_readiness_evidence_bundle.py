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
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_FINDING_CODES_TASK_177,
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


# Keyword argument of ``assemble`` -> its per-input evidence-validity flag.
_POSITION_FLAGS = {
    "projection174": "projection_evidence_valid",
    "audit175": "audit_evidence_valid",
    "consistency176": "consistency_evidence_valid",
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
    assert bundle["projection_evidence_valid"] is True
    assert bundle["audit_evidence_valid"] is True
    assert bundle["consistency_evidence_valid"] is True


def test_evidence_validity_flags_follow_inputs() -> None:
    """Genuine non-READY bundles still mark validated child evidence valid."""
    bundle, _ = _bundle(_blocked_chain())
    assert bundle["bundle_status"] == "BLOCKED"
    assert bundle["projection_evidence_valid"] is True
    assert bundle["audit_evidence_valid"] is True
    assert bundle["consistency_evidence_valid"] is True


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
    assert forged["consistency_findings"] == []


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
    # The Task 177 structural finding must not be misattributed as a
    # genuine Task 176 consistency finding.
    assert bundle["consistency_findings"] == []
    assert bundle["consistency_finding_count"] == 0


def test_wrong_type_audit_bundles_unavailable() -> None:
    chain = _ready_chain()
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175="not a model",
        consistency176=chain["consistency"],
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert bundle["consistency_findings"] == []
    assert bundle["consistency_finding_count"] == 0


def test_wrong_type_consistency_bundles_unavailable() -> None:
    chain = _ready_chain()
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176="not a model",
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert bundle["consistency_findings"] == []
    assert bundle["consistency_finding_count"] == 0


def test_invalid_fallback_never_fabricates_child_findings() -> None:
    """A single invalid input reports exactly one Task 177 finding.

    No Task 174, 175, or 176 finding may be fabricated to signal the
    Task 177 assembly error: every child findings surface stays empty,
    the bundle is never READY, and the result validates against the
    revised contract. Only the invalid child is marked invalid. Each
    input position is exercised separately.
    """
    for position, flag in _POSITION_FLAGS.items():
        chain = _ready_chain()
        kwargs = {
            "projection174": chain["projection"],
            "audit175": chain["audit"],
            "consistency176": chain["consistency"],
        }
        kwargs[position] = "not a model"
        bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
            **kwargs
        )
        assert bundle["bundle_status"] == "UNAVAILABLE"
        assert bundle["session_id"] == ""
        assert bundle["bundle_findings"] == ["EVIDENCE_INPUT_INVALID"]
        assert bundle["bundle_finding_count"] == 1
        assert bundle["findings"] == []
        assert bundle["audit_findings"] == []
        assert bundle["consistency_findings"] == []
        assert bundle["consistency_finding_count"] == 0
        # Only the invalid child is marked invalid; the others stay valid.
        for other_flag in _POSITION_FLAGS.values():
            assert bundle[other_flag] is (other_flag != flag)
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)


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
    assert bundle["consistency_findings"] == []


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
    assert bundle["consistency_findings"] == []


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
_APPROVED_CODES = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_FINDING_CODES_TASK_177
)


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
    # Two valid children from different sessions plus one invalid child
    # genuinely produce both approved aggregate codes.
    chain = _ready_chain()
    other = _ready_chain()
    bundle = _SERVICE.assemble(
        projection174=chain["projection"],
        audit175=other["audit"],
        consistency176="not a model",
    )
    assert bundle["bundle_findings"] == [
        "EVIDENCE_INPUT_INVALID",
        "STAGE_7_SESSION_MISMATCH",
    ]
    assert bundle["bundle_finding_count"] == 2
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


@pytest.mark.parametrize("code", ["EVIDENCE_INPUT_INVALID", "STAGE_7_SESSION_MISMATCH"])
def test_schema_rejects_ready_with_aggregate_findings(code) -> None:
    """A READY bundle must be free of its own aggregate findings."""
    bundle = _ready_bundle_dict()
    bundle["bundle_findings"] = [code]
    bundle["bundle_finding_count"] = 1
    with pytest.raises(
        ValidationError,
        match="EVIDENCE_INPUT_INVALID must be present|shared session_id",
    ):
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


def _unavailable_bundle_dict_with(findings: list[str]) -> dict:
    """A session-less UNAVAILABLE bundle carrying the given aggregate findings."""
    bundle = _ready_bundle_dict()
    bundle["session_id"] = ""
    bundle["bundle_status"] = "UNAVAILABLE"
    bundle["bundle_findings"] = findings
    bundle["bundle_finding_count"] = len(findings)
    return bundle


def test_approved_bundle_finding_code_set_is_exact() -> None:
    assert _APPROVED_CODES == frozenset(
        {"EVIDENCE_INPUT_INVALID", "STAGE_7_SESSION_MISMATCH"}
    )


@pytest.mark.parametrize("code", ["EVIDENCE_INPUT_INVALID", "STAGE_7_SESSION_MISMATCH"])
def test_schema_accepts_each_approved_bundle_finding_code(code) -> None:
    if code == "EVIDENCE_INPUT_INVALID":
        # This code is honest only alongside an invalid evidence flag.
        bundle = _invalid_bundle_dict()
    else:
        bundle = _unavailable_bundle_dict_with([code])
    assert _BUNDLE_READ.model_validate(bundle).bundle_findings == [code]


def test_schema_rejects_unknown_bundle_finding_code() -> None:
    bundle = _unavailable_bundle_dict_with(["TOTALLY_UNKNOWN_CODE"])
    with pytest.raises(ValidationError, match="unapproved Task 177 finding codes"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_unknown_code_alongside_approved_code() -> None:
    bundle = _unavailable_bundle_dict_with(
        ["STAGE_7_SESSION_MISMATCH", "ZZZ_UNKNOWN_CODE"]
    )
    with pytest.raises(ValidationError, match="ZZZ_UNKNOWN_CODE"):
        _BUNDLE_READ.model_validate(bundle)


@pytest.mark.parametrize(
    "child_code",
    [
        "BLOCKING_EVIDENCE",  # Task 174 projection finding
        "INSUFFICIENT_EVIDENCE",  # Task 174 projection finding
        "EXPECTED_STATUS_MISMATCH",  # Task 175 audit finding
        "PROJECTION_UNAVAILABLE",  # Task 175 audit finding
        "AUDIT_DETACHED",  # Task 176 consistency finding
        "AUDIT_UNAVAILABLE",  # Task 176 consistency finding
    ],
)
def test_schema_rejects_copied_upstream_finding_in_bundle_findings(
    child_code,
) -> None:
    bundle = _unavailable_bundle_dict_with([child_code])
    with pytest.raises(ValidationError, match="unapproved Task 177 finding codes"):
        _BUNDLE_READ.model_validate(bundle)


def test_approved_codes_are_exactly_the_codes_the_service_can_emit() -> None:
    """Every emitted aggregate code is approved, and every approved code is used."""
    emitted: set[str] = set()
    for combo in _MATRIX:
        bundle, _ = _bundle(_matrix_chain(*combo))
        emitted.update(bundle["bundle_findings"])
    chain = _ready_chain()
    invalid = _SERVICE.assemble(
        projection174=None,
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    emitted.update(invalid["bundle_findings"])
    assert emitted == _APPROVED_CODES


def _invalid_bundle_dict() -> dict:
    """A bundle dict with all three child evidence surfaces marked invalid."""
    return _SERVICE.assemble(projection174=None, audit175=None, consistency176=None)


def test_schema_accepts_invalid_flags_with_exact_placeholder() -> None:
    """All-invalid flags validate exactly with the canonical placeholder."""
    bundle = _invalid_bundle_dict()
    assert bundle["projection_evidence_valid"] is False
    assert bundle["audit_evidence_valid"] is False
    assert bundle["consistency_evidence_valid"] is False
    validated = _BUNDLE_READ.model_validate(bundle)
    assert validated.model_dump() == bundle


def test_schema_rejects_invalid_flag_with_genuine_surface() -> None:
    """A False flag cannot be paired with a genuine child surface."""
    bundle = _invalid_bundle_dict()
    bundle["readiness_status"] = "READY"
    with pytest.raises(ValidationError, match="invalid projection surface must carry"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_invalid_audit_flag_with_genuine_surface() -> None:
    """A False audit flag cannot be paired with genuine audit output."""
    bundle = _invalid_bundle_dict()
    bundle["audit_findings"] = ["SOME_FINDING"]
    bundle["audit_finding_count"] = 1
    with pytest.raises(ValidationError, match="invalid audit surface must carry"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_invalid_consistency_flag_with_genuine_surface() -> None:
    """A False consistency flag cannot be paired with genuine output."""
    bundle = _invalid_bundle_dict()
    bundle["consistency_findings"] = ["SOME_FINDING"]
    bundle["consistency_finding_count"] = 1
    with pytest.raises(ValidationError, match="invalid consistency surface must carry"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_valid_flag_with_empty_unavailable_projection() -> None:
    """A valid flag cannot mark an empty UNAVAILABLE projection surface."""
    bundle = _invalid_bundle_dict()
    bundle["projection_evidence_valid"] = True
    with pytest.raises(
        ValidationError, match="valid unavailable projection surface requires"
    ):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_valid_flag_with_empty_unavailable_audit() -> None:
    """A valid flag cannot mark an empty UNAVAILABLE audit surface."""
    bundle = _invalid_bundle_dict()
    bundle["audit_evidence_valid"] = True
    with pytest.raises(
        ValidationError, match="valid unavailable audit surface requires"
    ):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_valid_flag_with_empty_unavailable_consistency() -> None:
    """A valid flag cannot mark an empty UNAVAILABLE consistency surface."""
    bundle = _invalid_bundle_dict()
    bundle["consistency_evidence_valid"] = True
    with pytest.raises(
        ValidationError, match="valid unavailable consistency surface requires"
    ):
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
    assert bundle["session_id"] == ""
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert bundle[_POSITION_FLAGS[position]] is False
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


# ---------------------------------------------------------------------------
# Task 177 final provenance correction: per-input evidence validity
# ---------------------------------------------------------------------------

_POSITIONS = list(_POSITION_FLAGS)
_CHAIN_KEYS = {
    "projection174": "projection",
    "audit175": "audit",
    "consistency176": "consistency",
}


def _projection_surface(child) -> dict:
    return {
        "readiness_status": child.readiness_status,
        "attestation_status": child.attestation_status,
        "attestation_audit_status": child.attestation_audit_status,
        "consistency_status": child.consistency_status,
        "finding_count": child.finding_count,
        "findings": list(child.findings),
        "projection_source": child.projection_source,
    }


def _audit_surface(child) -> dict:
    return {
        "readiness_audit_status": child.readiness_audit_status,
        "audit_available": child.available,
        "audit_consistent": child.consistent,
        "published_readiness_status": child.published_readiness_status,
        "expected_readiness_status": child.expected_readiness_status,
        "audit_finding_count": child.finding_count,
        "audit_findings": list(child.findings),
        "audit_source": child.audit_source,
    }


def _consistency_surface(child) -> dict:
    return {
        "audit_consistency_status": child.consistency_status,
        "consistency_available": child.available,
        "consistency_consistent": child.consistent,
        "consistency_finding_count": child.finding_count,
        "consistency_findings": list(child.findings),
        "consistency_source": child.consistency_source,
    }


_SURFACE_BUILDERS = {
    "projection174": _projection_surface,
    "audit175": _audit_surface,
    "consistency176": _consistency_surface,
}

_PLACEHOLDERS = {
    "projection174": {
        "readiness_status": "UNAVAILABLE",
        "attestation_status": "UNAVAILABLE",
        "attestation_audit_status": "UNAVAILABLE",
        "consistency_status": "UNAVAILABLE",
        "finding_count": 0,
        "findings": [],
        "projection_source": (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
        ),
    },
    "audit175": {
        "readiness_audit_status": "UNAVAILABLE",
        "audit_available": False,
        "audit_consistent": False,
        "published_readiness_status": "UNAVAILABLE",
        "expected_readiness_status": "UNAVAILABLE",
        "audit_finding_count": 0,
        "audit_findings": [],
        "audit_source": REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    },
    "consistency176": {
        "audit_consistency_status": "UNAVAILABLE",
        "consistency_available": False,
        "consistency_consistent": False,
        "consistency_finding_count": 0,
        "consistency_findings": [],
        "consistency_source": (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    },
}


def _break_wrong_type(model):
    return "not a model"


def _break_by_mutation(model):
    """Mutate a constructed model so its state violates its own contract."""
    model.finding_count = model.finding_count + 7
    return model


_BREAKERS = [
    pytest.param(_break_wrong_type, id="wrong-type"),
    pytest.param(_break_by_mutation, id="mutated-instance"),
]


def _genuine_chain():
    """A chain whose every child carries distinctive, non-empty evidence."""
    return _matrix_chain("BLOCKED", "INCONSISTENT", "INCONSISTENT")


def _assemble_with_invalid(chain, invalid_positions, breaker):
    kwargs = {
        "projection174": chain["projection"],
        "audit175": chain["audit"],
        "consistency176": chain["consistency"],
    }
    for position in invalid_positions:
        kwargs[position] = breaker(kwargs[position])
    return _SERVICE.assemble(**kwargs), kwargs


def _assert_surfaces(bundle, kwargs, invalid_positions) -> None:
    """Each flag is truthful and each surface matches its flag exactly."""
    for position, flag in _POSITION_FLAGS.items():
        if position in invalid_positions:
            assert bundle[flag] is False
            expected = _PLACEHOLDERS[position]
        else:
            assert bundle[flag] is True
            expected = _SURFACE_BUILDERS[position](kwargs[position])
        actual = {key: bundle[key] for key in expected}
        assert actual == expected, position


@pytest.mark.parametrize("breaker", _BREAKERS)
@pytest.mark.parametrize("position", _POSITIONS)
def test_single_invalid_input_preserves_the_other_children(position, breaker) -> None:
    chain = _genuine_chain()
    bundle, kwargs = _assemble_with_invalid(chain, [position], breaker)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert bundle["bundle_finding_count"] == len(bundle["bundle_findings"])
    assert bundle["session_id"] == ""
    _assert_surfaces(bundle, kwargs, [position])
    # Genuine blocking evidence of the valid children stays visible, yet
    # never upgrades or downgrades the bundle beyond UNAVAILABLE.
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


@pytest.mark.parametrize("breaker", _BREAKERS)
@pytest.mark.parametrize("position", _POSITIONS)
def test_single_invalid_input_keeps_genuine_valid_evidence_verbatim(
    position, breaker
) -> None:
    chain = _genuine_chain()
    bundle, _ = _assemble_with_invalid(chain, [position], breaker)
    if position != "projection174":
        assert bundle["readiness_status"] == "BLOCKED"
        assert bundle["findings"] == ["BLOCKING_EVIDENCE"]
        assert bundle["finding_count"] == 1
    if position != "audit175":
        assert bundle["readiness_audit_status"] == "INCONSISTENT"
        assert bundle["audit_findings"] == ["EXPECTED_STATUS_MISMATCH"]
        assert bundle["audit_finding_count"] == 1
    if position != "consistency176":
        assert bundle["audit_consistency_status"] == "INCONSISTENT"
        assert bundle["consistency_findings"] == ["AUDIT_DETACHED"]
        assert bundle["consistency_finding_count"] == 1


@pytest.mark.parametrize("breaker", _BREAKERS)
@pytest.mark.parametrize("position", _POSITIONS)
def test_invalid_input_with_ready_children_is_never_ready(position, breaker) -> None:
    chain = _ready_chain()
    bundle, kwargs = _assemble_with_invalid(chain, [position], breaker)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["bundle_findings"] == ["EVIDENCE_INPUT_INVALID"]
    assert bundle["session_id"] == ""
    _assert_surfaces(bundle, kwargs, [position])


@pytest.mark.parametrize("breaker", _BREAKERS)
@pytest.mark.parametrize(
    "invalid_positions",
    [
        ["projection174", "audit175"],
        ["projection174", "consistency176"],
        ["audit175", "consistency176"],
        ["projection174", "audit175", "consistency176"],
    ],
    ids=["174+175", "174+176", "175+176", "all-three"],
)
def test_multiple_invalid_inputs_are_tracked_independently(
    invalid_positions, breaker
) -> None:
    chain = _genuine_chain()
    bundle, kwargs = _assemble_with_invalid(chain, invalid_positions, breaker)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert bundle["session_id"] == ""
    _assert_surfaces(bundle, kwargs, invalid_positions)
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


def test_all_three_invalid_never_fabricates_any_child_finding() -> None:
    bundle = _SERVICE.assemble(projection174=None, audit175=None, consistency176=None)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["bundle_findings"] == ["EVIDENCE_INPUT_INVALID"]
    for position, flag in _POSITION_FLAGS.items():
        assert bundle[flag] is False
        assert {key: bundle[key] for key in _PLACEHOLDERS[position]} == (
            _PLACEHOLDERS[position]
        )
    assert bundle["findings"] == []
    assert bundle["audit_findings"] == []
    assert bundle["consistency_findings"] == []


@pytest.mark.parametrize("position", _POSITIONS)
@pytest.mark.parametrize(("readiness", "audit", "cons"), _MATRIX, ids=_MATRIX_IDS)
def test_status_matrix_with_one_invalid_input_is_always_unavailable(
    readiness, audit, cons, position
) -> None:
    """Invalid evidence outranks every published READY or BLOCKED state."""
    chain = _matrix_chain(readiness, audit, cons)
    bundle, kwargs = _assemble_with_invalid(chain, [position], _break_wrong_type)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in bundle["bundle_findings"]
    assert bundle["session_id"] == ""
    _assert_surfaces(bundle, kwargs, [position])
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


@pytest.mark.parametrize("position", _POSITIONS)
def test_invalid_input_with_disagreeing_valid_sessions_reports_mismatch(
    position,
) -> None:
    chain = _ready_chain()
    other = _ready_chain()
    chain_keys = [key for pos, key in _CHAIN_KEYS.items() if pos != position]
    # Give one of the two valid children a different session.
    chain[chain_keys[0]] = other[chain_keys[0]]
    bundle, _ = _assemble_with_invalid(chain, [position], _break_wrong_type)
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["bundle_findings"] == [
        "EVIDENCE_INPUT_INVALID",
        "STAGE_7_SESSION_MISMATCH",
    ]
    assert bundle["session_id"] == ""
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


@pytest.mark.parametrize("position", _POSITIONS)
def test_invalid_input_never_claims_a_shared_session(position) -> None:
    chain = _ready_chain()
    bundle, _ = _assemble_with_invalid(chain, [position], _break_wrong_type)
    assert chain["session_id"] != ""
    assert bundle["session_id"] == ""
    assert "STAGE_7_SESSION_MISMATCH" not in bundle["bundle_findings"]


@pytest.mark.parametrize("breaker", _BREAKERS)
@pytest.mark.parametrize("position", _POSITIONS)
def test_invalid_input_assembly_is_deterministic_and_never_repairs_inputs(
    position, breaker
) -> None:
    chain = _genuine_chain()
    bundle, kwargs = _assemble_with_invalid(chain, [position], breaker)
    before = {
        key: value.model_dump() if hasattr(value, "model_dump") else value
        for key, value in kwargs.items()
    }
    again = _SERVICE.assemble(**kwargs)
    after = {
        key: value.model_dump() if hasattr(value, "model_dump") else value
        for key, value in kwargs.items()
    }
    assert bundle == again
    assert before == after


@pytest.mark.parametrize("position", _POSITIONS)
def test_returned_bundle_does_not_alias_valid_child_findings(position) -> None:
    chain = _genuine_chain()
    bundle, kwargs = _assemble_with_invalid(chain, [position], _break_wrong_type)
    bundle["findings"].append("MUTATED")
    bundle["audit_findings"].append("MUTATED")
    bundle["consistency_findings"].append("MUTATED")
    assert chain["projection"].findings == ["BLOCKING_EVIDENCE"]
    assert chain["audit"].findings == ["EXPECTED_STATUS_MISMATCH"]
    assert chain["consistency"].findings == ["AUDIT_DETACHED"]


def _mixed_bundle(position: str) -> dict:
    """A service-produced bundle with exactly one invalid child."""
    chain = _genuine_chain()
    bundle, _ = _assemble_with_invalid(chain, [position], _break_wrong_type)
    return bundle


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_accepts_mixed_validity_bundle(position) -> None:
    bundle = _mixed_bundle(position)
    assert _BUNDLE_READ.model_validate(bundle).model_dump() == bundle


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_non_placeholder_surface_under_false_flag(position) -> None:
    bundle = _genuine_chain_bundle_with_flag_false(position)
    with pytest.raises(ValidationError, match="must carry the canonical unavailable"):
        _BUNDLE_READ.model_validate(bundle)


def _genuine_chain_bundle_with_flag_false(position: str) -> dict:
    """A fully valid bundle whose flag for ``position`` is forged to False."""
    chain = _genuine_chain()
    bundle, _ = _bundle(chain)
    bundle[_POSITION_FLAGS[position]] = False
    # Keep the finding code and status consistent with a forged flag so the
    # surface check is the rule under test.
    bundle["bundle_status"] = "UNAVAILABLE"
    bundle["bundle_findings"] = ["EVIDENCE_INPUT_INVALID"]
    bundle["bundle_finding_count"] = 1
    bundle["session_id"] = ""
    return bundle


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_partially_forged_placeholder(position) -> None:
    """Any deviation from the canonical placeholder is rejected."""
    bundle = _mixed_bundle(position)
    placeholder = _PLACEHOLDERS[position]
    for key, value in placeholder.items():
        if isinstance(value, bool):
            forged = not value
        elif isinstance(value, int):
            forged = value + 1
        elif isinstance(value, list):
            forged = ["FORGED"]
        elif value == "UNAVAILABLE":
            forged = "BLOCKED"
        else:
            continue  # source constants have their own canonical-source rule
        tampered = dict(bundle)
        tampered[key] = forged
        # Keep unrelated coherence rules satisfied where the field is a count.
        if key.endswith("finding_count") or key == "finding_count":
            list_key = (
                key.replace("_count", "s") if key != "finding_count" else "findings"
            )
            tampered[list_key] = ["FORGED"] * forged
        with pytest.raises(ValidationError):
            _BUNDLE_READ.model_validate(tampered)


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_true_flag_over_placeholder_surface(position) -> None:
    # READY children keep the other surfaces non-blocking so the placeholder
    # rule itself is the one exercised.
    bundle, _ = _assemble_with_invalid(_ready_chain(), [position], _break_wrong_type)
    bundle[_POSITION_FLAGS[position]] = True
    bundle["bundle_findings"] = []
    bundle["bundle_finding_count"] = 0
    with pytest.raises(ValidationError, match="valid unavailable .* requires findings"):
        _BUNDLE_READ.model_validate(bundle)


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_forged_ready_over_mixed_validity(position) -> None:
    bundle = _mixed_bundle(position)
    bundle["bundle_status"] = "READY"
    with pytest.raises(ValidationError, match="must be UNAVAILABLE"):
        _BUNDLE_READ.model_validate(bundle)


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_forged_ready_over_ready_children_with_invalid_flag(
    position,
) -> None:
    """Even otherwise READY-looking evidence cannot hide an invalid child."""
    chain = _ready_chain()
    bundle, _ = _assemble_with_invalid(chain, [position], _break_wrong_type)
    for status in ("READY", "BLOCKED"):
        forged = dict(bundle)
        forged["bundle_status"] = status
        with pytest.raises(ValidationError):
            _BUNDLE_READ.model_validate(forged)


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_missing_invalid_code_under_false_flag(position) -> None:
    bundle = _mixed_bundle(position)
    bundle["bundle_findings"] = []
    bundle["bundle_finding_count"] = 0
    with pytest.raises(ValidationError, match="EVIDENCE_INPUT_INVALID must be present"):
        _BUNDLE_READ.model_validate(bundle)


def test_schema_rejects_invalid_code_when_every_flag_is_true() -> None:
    bundle = _unavailable_bundle_dict_with(["EVIDENCE_INPUT_INVALID"])
    with pytest.raises(ValidationError, match="EVIDENCE_INPUT_INVALID must be present"):
        _BUNDLE_READ.model_validate(bundle)


@pytest.mark.parametrize("position", _POSITIONS)
def test_schema_rejects_shared_session_under_false_flag(position) -> None:
    bundle = _mixed_bundle(position)
    bundle["session_id"] = str(uuid4())
    with pytest.raises(ValidationError, match="must not claim a shared session_id"):
        _BUNDLE_READ.model_validate(bundle)

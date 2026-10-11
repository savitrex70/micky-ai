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


# ---------------------------------------------------------------------------
# Session-binding correction: unavailable, unsupported and differing sessions
# ---------------------------------------------------------------------------


def _sessionless_chain():
    """Valid Task 174-176 records that all carry an empty session identity.

    Each record satisfies its own child contract independently: Tasks 175
    and 176 require an empty session when UNAVAILABLE, and an UNAVAILABLE
    Task 174 projection may carry one. The bundle comes from the real
    Task 177 service.
    """
    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id="",
        readiness_status="UNAVAILABLE",
        attestation_status="UNAVAILABLE",
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=1,
        findings=["INSUFFICIENT_EVIDENCE"],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )
    audit = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id="",
        readiness_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_readiness_status="UNAVAILABLE",
        expected_readiness_status="UNAVAILABLE",
        finding_count=1,
        findings=["PROJECTION_UNAVAILABLE"],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )
    consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id="",
        consistency_status="UNAVAILABLE",
        available=False,
        consistent=False,
        finding_count=1,
        findings=["AUDIT_UNAVAILABLE"],
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    )
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=projection,
        audit175=audit,
        consistency176=consistency,
    )
    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "bundle": ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
            bundle
        ),
        "session_id": "",
    }


def test_sessionless_chain_fixture_is_genuinely_valid() -> None:
    chain = _sessionless_chain()
    assert chain["projection"].session_id == ""
    assert chain["audit"].session_id == ""
    assert chain["consistency"].session_id == ""
    assert chain["bundle"].session_id == ""
    assert chain["bundle"].bundle_status == "UNAVAILABLE"
    assert chain["bundle"].bundle_findings == ["STAGE_7_SESSION_MISMATCH"]


def test_audit_with_no_session_anywhere_is_unavailable_not_a_contract_error() -> None:
    audit = _audit(_sessionless_chain())
    assert audit["bundle_audit_status"] == "UNAVAILABLE"
    assert audit["available"] is False
    assert audit["consistent"] is False
    assert audit["session_id"] == ""
    assert audit["findings"] == ["SESSION_BINDING_UNAVAILABLE"]
    assert audit["finding_count"] == 1
    assert audit["published_bundle_status"] == "UNAVAILABLE"
    assert audit["expected_bundle_status"] == "UNAVAILABLE"
    assert audit["audit_source"] == AUDIT_SOURCE
    assert (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead.model_validate(
            audit
        ).model_dump()
        == audit
    )


def test_audit_with_no_session_is_deterministic_and_leaves_inputs_unchanged() -> None:
    chain = _sessionless_chain()
    keys = ("projection", "audit", "consistency", "bundle")
    before = {key: chain[key].model_dump() for key in keys}
    first = _audit(chain)
    second = _audit(chain)
    after = {key: chain[key].model_dump() for key in keys}
    assert first == second
    assert before == after


def test_bundle_claiming_unsupported_session_is_not_consistent() -> None:
    chain = _sessionless_chain()
    claimed = chain["bundle"].model_dump()
    claimed["session_id"] = str(uuid4())
    # Drop the mismatch finding a sessionless bundle carries so the forged
    # record stays schema-valid and the audit itself must catch the claim.
    claimed["bundle_findings"] = []
    claimed["bundle_finding_count"] = 0
    forged = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
        claimed
    )
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
        bundle=forged,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit["findings"]
    assert "SESSION_BINDING_UNAVAILABLE" not in audit["findings"]
    assert audit["consistent"] is False


def test_independent_contradiction_stays_inconsistent_without_a_session() -> None:
    chain = _sessionless_chain()
    bundle = copy.deepcopy(chain["bundle"])
    bundle.readiness_audit_status = "CONSISTENT"
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_ECHO_MISMATCH" in audit["findings"]
    assert "SESSION_BINDING_UNAVAILABLE" not in audit["findings"]


@pytest.mark.parametrize("position", ["projection", "audit", "consistency"])
def test_differing_upstream_sessions_are_detected(position) -> None:
    chain = _chain("READY")
    other = _chain("READY")
    chain[position] = other[position]
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
    )
    assert bundle["bundle_findings"] == ["STAGE_7_SESSION_MISMATCH"]
    chain["bundle"] = (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(bundle)
    )
    audit = _audit(chain)
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit["findings"]
    assert audit["consistent"] is False


def test_matching_non_empty_sessions_still_audit_consistent(ready_chain) -> None:
    audit = _audit(ready_chain)
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["session_id"] == ready_chain["session_id"] != ""
    assert audit["findings"] == []


# ---------------------------------------------------------------------------
# Final session-binding correction: a shared session is proven only when all
# three upstream records establish it
# ---------------------------------------------------------------------------


def _partial_session_chain(
    upstream: tuple[str, str, str],
    bundle_session: str,
):
    """Schema-valid Task 174-177 chain with explicit per-record sessions.

    A record with an empty session is the genuine UNAVAILABLE variant of its
    child contract (Tasks 175 and 176 forbid a session when UNAVAILABLE); a
    record with a session is a genuine CONSISTENT/UNAVAILABLE-status record.
    The published bundle comes from the real Task 177 service. When the test
    needs a bundle that claims a session the real service would not publish,
    the claim is applied to a dump and revalidated, so the forged bundle is
    still a valid ``EvidenceBundleRead`` and only the audit can reject it.
    """
    projection_sid, audit_sid, consistency_sid = upstream
    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=projection_sid,
        readiness_status="UNAVAILABLE",
        attestation_status="UNAVAILABLE",
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=1,
        findings=["INSUFFICIENT_EVIDENCE"],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )
    if audit_sid == "":
        audit = ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id="",
            readiness_audit_status="UNAVAILABLE",
            available=False,
            consistent=False,
            published_readiness_status="UNAVAILABLE",
            expected_readiness_status="UNAVAILABLE",
            finding_count=1,
            findings=["PROJECTION_UNAVAILABLE"],
            audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
        )
    else:
        audit = ReasoningRunStage7ReleaseReadinessAuditRead(
            session_id=audit_sid,
            readiness_audit_status="CONSISTENT",
            available=True,
            consistent=True,
            published_readiness_status="UNAVAILABLE",
            expected_readiness_status="UNAVAILABLE",
            finding_count=0,
            findings=[],
            audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
        )
    if consistency_sid == "":
        consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
            session_id="",
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=1,
            findings=["AUDIT_UNAVAILABLE"],
            consistency_source=(
                REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
            ),
        )
    else:
        consistency = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
            session_id=consistency_sid,
            consistency_status="CONSISTENT",
            available=True,
            consistent=True,
            finding_count=0,
            findings=[],
            consistency_source=(
                REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
            ),
        )
    published = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=projection,
        audit175=audit,
        consistency176=consistency,
    )
    claimed = dict(published)
    claimed["session_id"] = bundle_session
    if bundle_session != "":
        # A bundle that claims a shared session carries no mismatch finding.
        claimed["bundle_findings"] = []
        claimed["bundle_finding_count"] = 0
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
        claimed
    )
    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "bundle": bundle,
        "session_id": bundle_session,
    }


def _assert_unavailable_binding(audit: dict) -> None:
    assert audit["bundle_audit_status"] == "UNAVAILABLE"
    assert audit["available"] is False
    assert audit["consistent"] is False
    assert audit["session_id"] == ""
    assert audit["findings"] == ["SESSION_BINDING_UNAVAILABLE"]
    assert audit["finding_count"] == 1
    assert audit["audit_source"] == AUDIT_SOURCE
    assert (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead.model_validate(
            audit
        ).model_dump()
        == audit
    )


def _assert_inconsistent_binding(audit: dict) -> None:
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is False
    assert "SESSION_BINDING_MISMATCH" in audit["findings"]
    assert "SESSION_BINDING_UNAVAILABLE" not in audit["findings"]
    assert audit["findings"] == sorted(set(audit["findings"]))
    assert audit["finding_count"] == len(audit["findings"])
    assert (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead.model_validate(
            audit
        ).model_dump()
        == audit
    )


def test_partial_session_fixtures_are_genuinely_valid() -> None:
    for upstream in (("s", "", ""), ("s", "s", ""), ("s", "s", "s")):
        chain = _partial_session_chain(upstream, "s")
        assert chain["projection"].session_id == upstream[0]
        assert chain["audit"].session_id == upstream[1]
        assert chain["consistency"].session_id == upstream[2]
        assert chain["bundle"].session_id == "s"
        assert chain["bundle"].bundle_findings == []


def test_all_four_session_ids_empty_is_unavailable() -> None:
    _assert_unavailable_binding(_audit(_partial_session_chain(("", "", ""), "")))


@pytest.mark.parametrize(
    "upstream",
    [("s", "", ""), ("", "s", ""), ("", "", "s")],
    ids=["only-projection", "only-audit", "only-consistency"],
)
def test_exactly_one_upstream_session_matching_bundle_is_unavailable(
    upstream,
) -> None:
    _assert_unavailable_binding(_audit(_partial_session_chain(upstream, "s")))


@pytest.mark.parametrize(
    "upstream",
    [("", "s", "s"), ("s", "", "s"), ("s", "s", "")],
    ids=["missing-projection", "missing-audit", "missing-consistency"],
)
def test_two_upstream_sessions_matching_bundle_with_third_empty_is_unavailable(
    upstream,
) -> None:
    _assert_unavailable_binding(_audit(_partial_session_chain(upstream, "s")))


def test_all_three_upstream_sessions_matching_bundle_is_proven() -> None:
    audit = _audit(_partial_session_chain(("s", "s", "s"), "s"))
    assert audit["bundle_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["consistent"] is True
    assert audit["session_id"] == "s"
    assert audit["findings"] == []
    assert audit["finding_count"] == 0


@pytest.mark.parametrize(
    "upstream",
    [
        ("s", "t", "s"),
        ("s", "s", "t"),
        ("t", "s", "s"),
        ("s", "t", ""),
        ("", "s", "t"),
    ],
)
@pytest.mark.parametrize("bundle_session", ["s", "t", "u", ""])
def test_conflicting_non_empty_upstream_identities_are_inconsistent(
    upstream, bundle_session
) -> None:
    _assert_inconsistent_binding(
        _audit(_partial_session_chain(upstream, bundle_session))
    )


@pytest.mark.parametrize(
    "upstream",
    [
        ("s", "s", "s"),
        ("s", "s", ""),
        ("s", "", "s"),
        ("", "s", "s"),
        ("s", "", ""),
        ("", "s", ""),
        ("", "", "s"),
    ],
)
def test_bundle_identity_conflicting_with_available_upstream_is_inconsistent(
    upstream,
) -> None:
    _assert_inconsistent_binding(_audit(_partial_session_chain(upstream, "other")))


@pytest.mark.parametrize(
    "upstream",
    [
        ("s", "s", "s"),
        ("s", "s", ""),
        ("s", "", ""),
        ("", "", "s"),
    ],
)
def test_bundle_omitting_identity_that_upstream_establishes_is_inconsistent(
    upstream,
) -> None:
    _assert_inconsistent_binding(_audit(_partial_session_chain(upstream, "")))


def test_bundle_claiming_identity_over_sessionless_upstream_is_inconsistent() -> None:
    _assert_inconsistent_binding(_audit(_partial_session_chain(("", "", ""), "s")))


@pytest.mark.parametrize(
    "upstream",
    [("s", "", ""), ("s", "s", ""), ("", "", "")],
    ids=["one-session", "two-sessions", "no-session"],
)
def test_independent_contradiction_beats_unavailable_binding(upstream) -> None:
    bundle_session = "" if upstream == ("", "", "") else "s"
    chain = _partial_session_chain(upstream, bundle_session)
    bundle = copy.deepcopy(chain["bundle"])
    bundle.bundle_status = "READY"
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
        bundle=bundle,
    )
    assert audit["bundle_audit_status"] == "INCONSISTENT"
    assert audit["consistent"] is False
    assert "BUNDLE_STATUS_MISMATCH" in audit["findings"]
    assert "SESSION_BINDING_UNAVAILABLE" not in audit["findings"]
    assert audit["findings"] == sorted(set(audit["findings"]))
    assert audit["finding_count"] == len(audit["findings"])


@pytest.mark.parametrize(
    "upstream",
    [("s", "", ""), ("", "s", ""), ("", "", "s"), ("s", "s", ""), ("", "", "")],
)
def test_partial_binding_audit_is_deterministic_and_leaves_inputs_unchanged(
    upstream,
) -> None:
    bundle_session = "" if upstream == ("", "", "") else "s"
    chain = _partial_session_chain(upstream, bundle_session)
    keys = ("projection", "audit", "consistency", "bundle")
    before = {key: chain[key].model_dump() for key in keys}
    first = _audit(chain)
    second = _audit(chain)
    after = {key: chain[key].model_dump() for key in keys}
    assert first == second
    assert before == after
    _assert_unavailable_binding(first)


def test_partial_binding_with_dict_bundle_matches_model_bundle() -> None:
    chain = _partial_session_chain(("s", "", ""), "s")
    from_model = _audit(chain)
    from_dict = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=chain["projection"],
        audit175=chain["audit"],
        consistency176=chain["consistency"],
        bundle=chain["bundle"].model_dump(),
    )
    assert from_dict == from_model
    _assert_unavailable_binding(from_dict)

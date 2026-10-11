"""Task 179: Stage 7 release-readiness bundle-audit consistency tests.

Comprehensive tests for the consistency boundary between the Task 177
release-readiness evidence bundle and its Task 178 independent audit.
The tests compose Tasks 174-178 externally; the consistency service never
invokes them itself.
"""

from __future__ import annotations

import copy
import inspect
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

# Set environment for imports
os.environ.setdefault("ROP_APP_NAME", "test")
os.environ.setdefault("ROP_ENVIRONMENT", "testing")
os.environ.setdefault("ROP_LOG_LEVEL", "INFO")
os.environ.setdefault(
    "ROP_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test"
)

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
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
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
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService,
)

CONSISTENCY_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179  # noqa: E501
AUDIT_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
)

# ---------------------------------------------------------------------------
# Fixtures: externally composed Task 174-178 chains
# ---------------------------------------------------------------------------


def _chain(status: str):
    """Build a schema-valid Task 174-177 chain for the requested status."""
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

    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
            projection174=projection,
            audit175=audit,
            consistency176=consistency,
        )
    )
    return {
        "projection": projection,
        "audit": audit,
        "consistency": consistency,
        "bundle": bundle,
        "session_id": session_id,
    }


def _bundle_audit(chain) -> ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead:
    """Run the real Task 178 service externally over the chain's evidence."""
    return ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead.model_validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
            projection174=chain["projection"],
            audit175=chain["audit"],
            consistency176=chain["consistency"],
            bundle=chain["bundle"],
        )
    )


def _verify(bundle, audit) -> dict:
    return (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService.verify(
            bundle=bundle, audit=audit
        )
    )


@pytest.fixture
def ready_chain() -> dict:
    return _chain("READY")


@pytest.fixture
def blocked_chain() -> dict:
    return _chain("BLOCKED")


@pytest.fixture
def unavailable_chain() -> dict:
    return _chain("UNAVAILABLE")


# ---------------------------------------------------------------------------
# Consistency verdicts for all three readiness states
# ---------------------------------------------------------------------------


def test_ready_bundle_with_consistent_audit_is_consistent(ready_chain) -> None:
    result = _verify(ready_chain["bundle"], _bundle_audit(ready_chain))
    assert result["consistency_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["session_id"] == ready_chain["session_id"]
    assert result["consistency_source"] == CONSISTENCY_SOURCE


def test_blocked_bundle_with_consistent_audit_is_consistent(blocked_chain) -> None:
    result = _verify(blocked_chain["bundle"], _bundle_audit(blocked_chain))
    assert result["consistency_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["findings"] == []


def test_unavailable_bundle_with_consistent_audit_is_consistent(
    unavailable_chain,
) -> None:
    """A valid bundle status of UNAVAILABLE is not an unavailable audit."""
    result = _verify(unavailable_chain["bundle"], _bundle_audit(unavailable_chain))
    assert result["consistency_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["findings"] == []


def test_result_validates_against_strict_schema(ready_chain) -> None:
    result = _verify(ready_chain["bundle"], _bundle_audit(ready_chain))
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead.model_validate(
        result
    )


# ---------------------------------------------------------------------------
# True mismatches are INCONSISTENT
# ---------------------------------------------------------------------------


def test_session_mismatch_is_inconsistent(ready_chain) -> None:
    """A schema-valid audit bound to a different session is detached."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=str(uuid4()),
        bundle_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_bundle_status="READY",
        expected_bundle_status="READY",
        finding_count=0,
        findings=[],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in result["findings"]
    assert result["finding_count"] == len(result["findings"])


def test_published_status_mismatch_is_inconsistent(ready_chain) -> None:
    """Audit records that contradict the published bundle status."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=ready_chain["session_id"],
        bundle_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_bundle_status="BLOCKED",
        expected_bundle_status="BLOCKED",
        finding_count=0,
        findings=[],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]


def test_expected_status_mismatch_is_inconsistent(ready_chain) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=ready_chain["session_id"],
        bundle_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_bundle_status="READY",
        expected_bundle_status="BLOCKED",
        finding_count=1,
        findings=["EXPECTED_STATUS_MISMATCH"],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]
    assert "AUDIT_STATUS_MISMATCH" in result["findings"]
    assert "AUDIT_HAS_FINDINGS" in result["findings"]


def test_inconsistent_audit_with_matching_statuses_is_inconsistent(
    ready_chain,
) -> None:
    """An audit that cannot prove its own consistency cannot bind."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=ready_chain["session_id"],
        bundle_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_bundle_status="READY",
        expected_bundle_status="READY",
        finding_count=1,
        findings=["AUDIT_FINDING"],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_MISMATCH" in result["findings"]
    assert "AUDIT_HAS_FINDINGS" in result["findings"]


# ---------------------------------------------------------------------------
# Unavailable audit: unknown binding, not a proven contradiction
# ---------------------------------------------------------------------------


def test_unavailable_audit_is_unavailable_not_inconsistent(ready_chain) -> None:
    """A valid Task 178 UNAVAILABLE audit proves nothing either way."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id="",
        bundle_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_bundle_status="UNAVAILABLE",
        expected_bundle_status="UNAVAILABLE",
        finding_count=1,
        findings=["EVIDENCE_INPUT_INVALID"],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["findings"] == ["AUDIT_UNAVAILABLE"]


def test_unavailable_audit_blank_session_not_a_mismatch(ready_chain) -> None:
    """Contract-valid blank identity is never promoted to a contradiction."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id="",
        bundle_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_bundle_status="UNAVAILABLE",
        expected_bundle_status="UNAVAILABLE",
        finding_count=1,
        findings=["EVIDENCE_INPUT_INVALID"],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert "SESSION_MISMATCH" not in result["findings"]
    assert "PUBLISHED_STATUS_MISMATCH" not in result["findings"]
    assert result["consistency_status"] != "INCONSISTENT"


def test_unavailable_audit_over_unavailable_bundle_is_unavailable(
    unavailable_chain,
) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id="",
        bundle_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_bundle_status="UNAVAILABLE",
        expected_bundle_status="UNAVAILABLE",
        finding_count=1,
        findings=["EVIDENCE_INPUT_INVALID"],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(unavailable_chain["bundle"], audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["AUDIT_UNAVAILABLE"]


# ---------------------------------------------------------------------------
# Malformed input, wrong types, source forgery, mutation
# ---------------------------------------------------------------------------


def test_wrong_type_bundle_returns_unavailable(ready_chain) -> None:
    result = _verify("not a bundle", _bundle_audit(ready_chain))
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]
    assert result["session_id"] == ""


def test_wrong_type_audit_returns_unavailable(ready_chain) -> None:
    result = _verify(ready_chain["bundle"], "not an audit")
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_dict_audit_returns_unavailable(ready_chain) -> None:
    """A dict (possibly with an unknown status) is not an audit model."""
    result = _verify(
        ready_chain["bundle"],
        {"bundle_audit_status": "WHATEVER"},
    )
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_forged_bundle_source_detected(ready_chain) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_source = "FORGED_SOURCE"
    result = _verify(bundle, _bundle_audit(ready_chain))
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_forged_audit_source_detected(ready_chain) -> None:
    audit = copy.deepcopy(_bundle_audit(ready_chain))
    audit.audit_source = "FORGED_SOURCE"
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_mutated_bundle_status_detected(ready_chain) -> None:
    """A READY bundle forged to BLOCKED fails its own contract on revalidation."""
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_status = "BLOCKED"
    result = _verify(bundle, _bundle_audit(ready_chain))
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_mutated_audit_session_detected(ready_chain) -> None:
    """A surviving mutation that rebinds the audit to another session."""
    audit = copy.deepcopy(_bundle_audit(ready_chain))
    audit.session_id = str(uuid4())
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in result["findings"]


def test_mutated_audit_status_detected(ready_chain) -> None:
    """A surviving status mutation is caught by the status cross-check."""
    audit = copy.deepcopy(_bundle_audit(ready_chain))
    audit.published_bundle_status = "BLOCKED"
    audit.expected_bundle_status = "BLOCKED"
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]


@pytest.mark.parametrize("bad_value", [None, 7, []])
def test_rejects_mutated_identity_types(ready_chain, bad_value) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.session_id = bad_value
    result = _verify(bundle, _bundle_audit(ready_chain))
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_schema_rejects_extra_fields(ready_chain) -> None:
    result = _verify(ready_chain["bundle"], _bundle_audit(ready_chain))
    result["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead.model_validate(
            result
        )


def test_schema_rejects_incoherent_flags() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="CONSISTENT",
            available=False,
            consistent=True,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_consistent_with_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="CONSISTENT",
            available=True,
            consistent=True,
            finding_count=1,
            findings=["F"],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_inconsistent_without_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="INCONSISTENT",
            available=True,
            consistent=False,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_unavailable_claiming_session() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=1,
            findings=["F"],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_unavailable_without_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="",
            consistency_status="UNAVAILABLE",
            available=False,
            consistent=False,
            finding_count=0,
            findings=[],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_unsorted_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="INCONSISTENT",
            available=True,
            consistent=False,
            finding_count=2,
            findings=["Z", "A"],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_duplicate_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="INCONSISTENT",
            available=True,
            consistent=False,
            finding_count=2,
            findings=["A", "A"],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_count_mismatch() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="INCONSISTENT",
            available=True,
            consistent=False,
            finding_count=5,
            findings=["A"],
            consistency_source=CONSISTENCY_SOURCE,
        )


def test_schema_rejects_forged_source() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(
            session_id="s",
            consistency_status="CONSISTENT",
            available=True,
            consistent=True,
            finding_count=0,
            findings=[],
            consistency_source="FORGED",
        )


# ---------------------------------------------------------------------------
# Immutability, determinism, architecture
# ---------------------------------------------------------------------------


def test_service_does_not_mutate_inputs(ready_chain) -> None:
    before = {
        "bundle": ready_chain["bundle"].model_dump(),
        "audit": _bundle_audit(ready_chain).model_dump(),
    }
    audit = _bundle_audit(ready_chain)
    _verify(ready_chain["bundle"], audit)
    assert ready_chain["bundle"].model_dump() == before["bundle"]
    assert audit.model_dump() == before["audit"]


def test_service_is_deterministic(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    assert _verify(ready_chain["bundle"], audit) == _verify(
        ready_chain["bundle"], audit
    )


def test_service_has_no_provider_or_runtime_access() -> None:
    """Architecture: consistency source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency as module  # noqa: E501

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
# Source constant test
# ---------------------------------------------------------------------------


def test_source_constant_is_correct() -> None:
    assert CONSISTENCY_SOURCE == (
        "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE"
        "_AUDIT_CONSISTENCY_TASK_179"
    )


# ---------------------------------------------------------------------------
# Binding-unavailable audits: genuine claims about the audited bundle
# ---------------------------------------------------------------------------


def _unavailable_upstream(session_id: str = ""):
    """Schema-valid Task 174-176 records whose shared binding is unprovable.

    The projection may carry a session; Tasks 175 and 176 are the genuine
    UNAVAILABLE variants, which must carry an empty session.
    """
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
    audit175 = ReasoningRunStage7ReleaseReadinessAuditRead(
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
    consistency176 = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
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
    return projection, audit175, consistency176


def _binding_unavailable_pair(session_id: str):
    """A real Task 178 UNAVAILABLE(SESSION_BINDING_UNAVAILABLE) audit + bundle.

    ``session_id == ""``: every record is sessionless and the real Task 177
    bundle is published. Otherwise the projection carries the session and the
    bundle claims it (without a mismatch finding), so the audit reads a
    valid bundle whose shared binding upstream cannot prove.
    """
    projection, audit175, consistency176 = _unavailable_upstream(session_id)
    published = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=projection, audit175=audit175, consistency176=consistency176
    )
    claimed = dict(published)
    if session_id:
        claimed["session_id"] = session_id
        claimed["bundle_findings"] = []
        claimed["bundle_finding_count"] = 0
    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
        claimed
    )
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead.model_validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
            projection174=projection,
            audit175=audit175,
            consistency176=consistency176,
            bundle=bundle,
        )
    )
    return bundle, audit


@pytest.mark.parametrize("session_id", ["", "s"], ids=["sessionless", "partial"])
def test_binding_unavailable_audit_fixture_is_genuine(session_id) -> None:
    bundle, audit = _binding_unavailable_pair(session_id)
    assert audit.bundle_audit_status == "UNAVAILABLE"
    assert audit.findings == ["SESSION_BINDING_UNAVAILABLE"]
    assert audit.session_id == ""
    assert audit.published_bundle_status == bundle.bundle_status == "UNAVAILABLE"
    assert audit.expected_bundle_status == "UNAVAILABLE"


@pytest.mark.parametrize("session_id", ["", "s"], ids=["sessionless", "partial"])
def test_binding_unavailable_audit_over_its_own_bundle_is_unavailable(
    session_id,
) -> None:
    bundle, audit = _binding_unavailable_pair(session_id)
    result = _verify(bundle, audit)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["findings"] == ["AUDIT_UNAVAILABLE"]
    assert result["finding_count"] == 1


@pytest.mark.parametrize("status", ["READY", "BLOCKED"])
def test_binding_unavailable_audit_over_different_status_bundle_is_inconsistent(
    status,
) -> None:
    """The audit read an UNAVAILABLE bundle; a READY/BLOCKED one is detached."""
    _, audit = _binding_unavailable_pair("")
    other = _chain(status)
    result = _verify(other["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is False
    assert result["session_id"] == other["bundle"].session_id
    assert result["findings"] == [
        "EXPECTED_STATUS_MISMATCH",
        "PUBLISHED_STATUS_MISMATCH",
    ]
    assert result["finding_count"] == 2
    assert (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead.model_validate(
            result
        ).model_dump()
        == result
    )


@pytest.mark.parametrize(
    ("field", "expected_finding"),
    [
        ("published_bundle_status", "PUBLISHED_STATUS_MISMATCH"),
        ("expected_bundle_status", "EXPECTED_STATUS_MISMATCH"),
    ],
)
def test_binding_unavailable_audit_single_status_difference_is_reported(
    field, expected_finding
) -> None:
    bundle, audit = _binding_unavailable_pair("")
    audit = audit.model_copy(update={field: "READY"})
    result = _verify(bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["findings"] == [expected_finding]
    assert result["finding_count"] == 1


def test_unavailable_audit_with_other_findings_keeps_placeholder_statuses() -> None:
    """Only the binding-unavailable verdict makes its status fields a claim."""
    bundle = _chain("READY")["bundle"]
    for findings in (
        ["EVIDENCE_INPUT_INVALID"],
        ["BUNDLE_INVALID"],
        ["BUNDLE_INVALID", "SESSION_BINDING_UNAVAILABLE"],
    ):
        audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
            session_id="",
            bundle_audit_status="UNAVAILABLE",
            available=False,
            consistent=False,
            published_bundle_status="UNAVAILABLE",
            expected_bundle_status="UNAVAILABLE",
            finding_count=len(findings),
            findings=findings,
            audit_source=AUDIT_SOURCE,
        )
        result = _verify(bundle, audit)
        assert result["consistency_status"] == "UNAVAILABLE"
        assert result["findings"] == ["AUDIT_UNAVAILABLE"]


def test_binding_unavailable_verdict_is_deterministic_and_immutable() -> None:
    bundle, audit = _binding_unavailable_pair("s")
    other = _chain("READY")["bundle"]
    before = (bundle.model_dump(), audit.model_dump(), other.model_dump())
    first = (_verify(bundle, audit), _verify(other, audit))
    second = (_verify(bundle, audit), _verify(other, audit))
    assert first == second
    assert before == (bundle.model_dump(), audit.model_dump(), other.model_dump())


# ---------------------------------------------------------------------------
# Field-level boundary and public exports
# ---------------------------------------------------------------------------


def test_matching_session_and_status_with_audit_findings_is_not_consistent(
    ready_chain,
) -> None:
    """Matching identity and statuses never outweigh an audit that failed."""
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=ready_chain["bundle"].session_id,
        bundle_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_bundle_status=ready_chain["bundle"].bundle_status,
        expected_bundle_status=ready_chain["bundle"].bundle_status,
        finding_count=1,
        findings=["SOME_AUDIT_FINDING"],
        audit_source=AUDIT_SOURCE,
    )
    result = _verify(ready_chain["bundle"], audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["findings"] == ["AUDIT_HAS_FINDINGS", "AUDIT_STATUS_MISMATCH"]


def test_public_exports_and_task_180_imports_are_available() -> None:
    import rop.schemas as schemas
    import rop.services as services
    from rop.services import (
        reasoning_run_stage_7_release_readiness_final_attestation as task_180,
    )

    assert (
        schemas.ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead
        is ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead
    )
    assert (
        schemas.REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179
        == CONSISTENCY_SOURCE
    )
    assert (
        services.ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService
        is ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService
    )
    assert hasattr(task_180, "_CONSISTENCY_READ")

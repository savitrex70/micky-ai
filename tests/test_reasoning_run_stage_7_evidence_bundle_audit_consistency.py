"""Task 167: Stage 7 evidence-bundle audit consistency tests.

Independent consistency boundary between Task 165 Evidence Bundle and
Task 166 Evidence-Bundle Audit. The service proves the audit belongs to the
exact bundle supplied by comparing the bundle against the snapshot the audit
recorded, then checks session identity, statuses, and provenance sources.

The consistency check is pure and independent: it never calls Task 165
or Task 166 services, never recomputes fingerprints, never invokes a
provider, and never accesses a database.
"""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

CONSISTENCY_SOURCE = (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
)


@pytest.fixture
def ready_bundle() -> ReasoningRunStage7EvidenceBundleRead:
    """A READY bundle for testing."""
    session_id = str(uuid4())
    return ReasoningRunStage7EvidenceBundleRead(
        session_id=session_id,
        slice_status="READY",
        admission_status="ADMITTED",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        slice_audit_status="CONSISTENT",
        audit_available=True,
        audit_consistent=True,
        published_slice_status="READY",
        expected_slice_status="READY",
        audit_finding_count=0,
        audit_findings=[],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        request_fingerprint="a" * 64,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        bundle_status="READY",
        bundle_finding_count=0,
        bundle_findings=[],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )


def _make_audit(bundle) -> ReasoningRunStage7EvidenceBundleAuditRead:
    """Build a real Task 166 audit (with its snapshot) for a bundle.

    Test setup only: Task 167 itself never calls the Task 166 service.
    """
    return ReasoningRunStage7EvidenceBundleAuditRead(
        **ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=bundle)
    )


def _tamper(obj, **changes):
    """Copy a typed object and set fields directly, bypassing validation."""
    tampered = copy.deepcopy(obj)
    for name, value in changes.items():
        setattr(tampered, name, value)
    return tampered


def _variant(bundle, **changes) -> ReasoningRunStage7EvidenceBundleRead:
    """Build a different but fully valid bundle from a valid one."""
    data = bundle.model_dump()
    data.update(changes)
    return ReasoningRunStage7EvidenceBundleRead(**data)


def _verify(bundle, audit):
    return ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=bundle, audit=audit
    )


@pytest.fixture
def ready_audit(ready_bundle) -> ReasoningRunStage7EvidenceBundleAuditRead:
    """A CONSISTENT audit bound to the READY bundle."""
    return _make_audit(ready_bundle)


@pytest.fixture
def blocked_bundle(ready_bundle) -> ReasoningRunStage7EvidenceBundleRead:
    """A genuine BLOCKED bundle (blocking Task 163 evidence)."""
    return _variant(
        ready_bundle,
        slice_status="BLOCKED",
        admission_status="BLOCKED",
        published_slice_status="BLOCKED",
        expected_slice_status="BLOCKED",
        finding_count=1,
        findings=["BLOCKED_BY_ADMISSION"],
        bundle_status="BLOCKED",
    )


@pytest.fixture
def unavailable_bundle() -> ReasoningRunStage7EvidenceBundleRead:
    """A genuine UNAVAILABLE bundle with a blank session."""
    return ReasoningRunStage7EvidenceBundleRead(
        session_id="",
        slice_status="UNAVAILABLE",
        admission_status=None,
        diagnostics_status=None,
        provider_name=None,
        model_name=None,
        finding_count=1,
        findings=["MISSING_ADMISSION"],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        slice_audit_status="UNAVAILABLE",
        audit_available=False,
        audit_consistent=False,
        published_slice_status=None,
        expected_slice_status=None,
        audit_finding_count=1,
        audit_findings=["MISSING_ADMISSION"],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        request_fingerprint=None,
        request_audit_status=None,
        proposal_audit_status=None,
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        bundle_status="UNAVAILABLE",
        bundle_finding_count=3,
        bundle_findings=[
            "PROVIDER_ATTRIBUTION_MISSING",
            "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
            "STAGE_7_SESSION_MISMATCH",
        ],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )


# ---------------------------------------------------------------------------
# Genuine, correctly bound pairs
# ---------------------------------------------------------------------------


def test_genuine_ready_bundle_with_bound_audit_is_consistent(ready_bundle, ready_audit):
    consistency = _verify(ready_bundle, ready_audit)
    assert consistency["consistency_status"] == "CONSISTENT"
    assert consistency["available"] is True
    assert consistency["consistent"] is True
    assert consistency["finding_count"] == 0
    assert consistency["findings"] == []
    assert consistency["session_id"] == ready_bundle.session_id
    assert consistency["consistency_source"] == CONSISTENCY_SOURCE


def test_bound_blocked_pair_is_consistent_and_distinct_from_detached(
    ready_bundle, blocked_bundle
):
    audit = _make_audit(blocked_bundle)
    assert audit.bundle_audit_status == "CONSISTENT"
    assert _verify(blocked_bundle, audit)["consistency_status"] == "CONSISTENT"
    # The same audit presented with a different (READY) bundle is detached.
    detached = _verify(ready_bundle, audit)
    assert detached["consistency_status"] == "INCONSISTENT"
    assert "BUNDLE_SNAPSHOT_MISMATCH" in detached["findings"]
    assert "PUBLISHED_STATUS_MISMATCH" in detached["findings"]


def test_bound_unavailable_bundle_is_consistent(unavailable_bundle):
    audit = _make_audit(unavailable_bundle)
    result = _verify(unavailable_bundle, audit)
    assert result["consistency_status"] == "CONSISTENT"
    assert result["session_id"] == ""


# ---------------------------------------------------------------------------
# Exact evidence binding: same session and status, different content
# ---------------------------------------------------------------------------


def test_different_fingerprint_cannot_share_an_audit(ready_bundle, ready_audit):
    other = _variant(ready_bundle, request_fingerprint="b" * 64)
    assert other.session_id == ready_bundle.session_id
    assert other.bundle_status == ready_bundle.bundle_status
    result = _verify(other, ready_audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["findings"] == ["BUNDLE_SNAPSHOT_MISMATCH"]


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_name": "other-provider"},
        {"model_name": "other-model"},
        {"provider_name": "other-provider", "model_name": "other-model"},
    ],
)
def test_different_attribution_cannot_share_an_audit(
    ready_bundle, ready_audit, changes
):
    other = _variant(ready_bundle, **changes)
    result = _verify(other, ready_audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["findings"] == ["BUNDLE_SNAPSHOT_MISMATCH"]


def test_changed_bundle_finding_cannot_use_old_snapshot(blocked_bundle):
    audit = _make_audit(blocked_bundle)
    other = _variant(
        blocked_bundle,
        bundle_findings=["PROVIDER_ATTRIBUTION_MISSING"],
        bundle_finding_count=1,
        provider_name=None,
        model_name=None,
    )
    assert other.bundle_status == blocked_bundle.bundle_status
    result = _verify(other, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "BUNDLE_SNAPSHOT_MISMATCH" in result["findings"]


def test_same_session_same_status_different_content_with_findings(blocked_bundle):
    """Both sides carrying findings is not enough to prove the binding."""
    audit = _make_audit(blocked_bundle)
    other = _variant(
        blocked_bundle, findings=["BLOCKED_BY_DIAGNOSTICS"], finding_count=1
    )
    result = _verify(other, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["findings"] == ["BUNDLE_SNAPSHOT_MISMATCH"]


@pytest.mark.parametrize("fingerprint", ["A" * 64, "a" * 63])
def test_snapshot_comparison_never_normalises_or_recomputes(
    ready_bundle, ready_audit, fingerprint
):
    bundle = _tamper(ready_bundle, request_fingerprint=fingerprint)
    result = _verify(bundle, ready_audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "BUNDLE_SNAPSHOT_MISMATCH" in result["findings"]
    assert bundle.request_fingerprint == fingerprint


def test_snapshot_comparison_is_type_exact(ready_bundle, ready_audit):
    """``0 == False`` style equalities do not bind."""
    bundle = _tamper(ready_bundle, finding_count=False)
    assert _verify(bundle, ready_audit)["consistency_status"] == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_forged_bundle_source_is_detected(ready_bundle, ready_audit):
    bundle = _tamper(ready_bundle, bundle_source="FORGED")
    result = _verify(bundle, ready_audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "BUNDLE_SOURCE_MISMATCH" in result["findings"]


def test_forged_audit_source_is_detected(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, audit_source="FORGED")
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_MISMATCH" in result["findings"]


def test_forged_audit_source_in_mapping_is_unavailable(ready_bundle, ready_audit):
    """A mapping must satisfy the Task 166 contract, which pins the source."""
    payload = ready_audit.model_dump()
    payload["audit_source"] = "FORGED"
    result = _verify(ready_bundle, payload)
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["findings"][0].startswith("TASK_166_AUDIT_INVALID")


@pytest.mark.parametrize(
    "source",
    ["FORGED", "", CONSISTENCY_SOURCE + "X", None],
)
@pytest.mark.parametrize(
    ("status", "findings"),
    [("CONSISTENT", []), ("INCONSISTENT", ["X"]), ("UNAVAILABLE", ["X"])],
)
def test_forged_consistency_source_rejected_by_schema(source, status, findings):
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            {
                "session_id": "" if status == "UNAVAILABLE" else "s",
                "consistency_status": status,
                "available": status != "UNAVAILABLE",
                "consistent": status == "CONSISTENT",
                "finding_count": len(findings),
                "findings": findings,
                "consistency_source": source,
            }
        )


@pytest.mark.parametrize(
    ("status", "findings"),
    [("CONSISTENT", []), ("INCONSISTENT", ["X"]), ("UNAVAILABLE", ["X"])],
)
def test_canonical_consistency_source_is_accepted_in_every_status(status, findings):
    model = ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
        {
            "session_id": "",
            "consistency_status": status,
            "available": status != "UNAVAILABLE",
            "consistent": status == "CONSISTENT",
            "finding_count": len(findings),
            "findings": findings,
            "consistency_source": CONSISTENCY_SOURCE,
        }
    )
    assert model.consistency_source == CONSISTENCY_SOURCE


# ---------------------------------------------------------------------------
# Session and status checks
# ---------------------------------------------------------------------------


def test_session_mismatch_detected(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, session_id=str(uuid4()))
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in result["findings"]


def test_published_status_mismatch_detected(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, published_bundle_status="BLOCKED")
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]


def test_expected_status_contradiction_detected(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, expected_bundle_status="BLOCKED")
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in result["findings"]
    assert "AUDIT_INTERNAL_MISMATCH" in result["findings"]


@pytest.mark.parametrize(
    "changes",
    [
        {"available": False},
        {"consistent": False},
        {"finding_count": 3},
        {"findings": ["B", "A"], "finding_count": 2},
        {"findings": ["A"], "finding_count": 1},
    ],
)
def test_self_contradictory_audit_is_inconsistent(ready_bundle, ready_audit, changes):
    result = _verify(ready_bundle, _tamper(ready_audit, **changes))
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_INTERNAL_MISMATCH" in result["findings"]


def test_snapshot_must_describe_the_audited_subject(ready_bundle, ready_audit):
    snapshot = _tamper(ready_audit.audited_bundle, session_id=str(uuid4()))
    audit = _tamper(ready_audit, audited_bundle=snapshot)
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_INTERNAL_MISMATCH" in result["findings"]
    assert "BUNDLE_SNAPSHOT_MISMATCH" in result["findings"]


# ---------------------------------------------------------------------------
# A correctly bound audit that itself reports INCONSISTENT
# ---------------------------------------------------------------------------


def test_bound_inconsistent_audit_is_distinct_from_unavailable_and_detached(
    ready_bundle,
):
    tampered = _tamper(ready_bundle, bundle_status="BLOCKED")
    audit = _make_audit(tampered)
    assert audit.bundle_audit_status == "INCONSISTENT"
    result = _verify(tampered, audit)
    assert result["available"] is True
    assert result["consistency_status"] == "INCONSISTENT"
    # Correctly bound: the only finding is the audit's own verdict.
    assert result["findings"] == ["AUDIT_REPORTS_BUNDLE_INCONSISTENT"]
    assert result["session_id"] == tampered.session_id


def test_bound_inconsistent_audit_detached_from_bundle_adds_binding_findings(
    ready_bundle,
):
    tampered = _tamper(ready_bundle, bundle_status="BLOCKED")
    audit = _make_audit(tampered)
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_REPORTS_BUNDLE_INCONSISTENT" in result["findings"]
    assert "BUNDLE_SNAPSHOT_MISMATCH" in result["findings"]


# ---------------------------------------------------------------------------
# Missing and malformed input
# ---------------------------------------------------------------------------


def _assert_unavailable(result, *markers):
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["consistency_source"] == CONSISTENCY_SOURCE
    assert result["findings"] == sorted(result["findings"])
    assert result["finding_count"] == len(result["findings"])
    for marker in markers:
        assert any(f.startswith(marker) for f in result["findings"])


def test_missing_bundle_is_unavailable(ready_audit):
    _assert_unavailable(
        ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
            audit=ready_audit
        ),
        "TASK_165_BUNDLE_MISSING",
    )


def test_missing_audit_is_unavailable(ready_bundle):
    _assert_unavailable(
        ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
            bundle=ready_bundle
        ),
        "TASK_166_AUDIT_MISSING",
    )


def test_both_missing_reports_both_diagnostics():
    result = ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
        bundle=None, audit=None
    )
    _assert_unavailable(result, "TASK_165_BUNDLE_MISSING", "TASK_166_AUDIT_MISSING")
    assert result["finding_count"] == 2


@pytest.mark.parametrize("bad", ["x", 5, [], object(), True])
def test_wrong_typed_bundle_is_unavailable(bad, ready_audit):
    _assert_unavailable(_verify(bad, ready_audit), "TASK_165_BUNDLE_INVALID")


@pytest.mark.parametrize("bad", ["x", 5, [], object(), True])
def test_wrong_typed_audit_is_unavailable(bad, ready_bundle):
    _assert_unavailable(_verify(ready_bundle, bad), "TASK_166_AUDIT_INVALID")


@pytest.mark.parametrize("bad", [{}, {"session_id": "x"}])
def test_malformed_mapping_inputs_are_unavailable(bad, ready_bundle, ready_audit):
    _assert_unavailable(_verify(bad, ready_audit), "TASK_165_BUNDLE_INVALID")
    _assert_unavailable(_verify(ready_bundle, bad), "TASK_166_AUDIT_INVALID")


def test_valid_mapping_inputs_are_accepted(ready_bundle, ready_audit):
    result = _verify(ready_bundle.model_dump(), ready_audit.model_dump())
    assert result["consistency_status"] == "CONSISTENT"


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": 5},
        {"bundle_audit_status": "FORGED"},
        {"findings": "nope"},
        {"finding_count": True},
        {"available": "yes"},
        {"published_bundle_status": 7},
    ],
)
def test_malformed_audit_fields_are_unavailable(ready_bundle, ready_audit, changes):
    result = _verify(ready_bundle, _tamper(ready_audit, **changes))
    _assert_unavailable(result, "TASK_166_AUDIT_INVALID")


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": 5},
        {"findings": ["a", 1]},
        {"audit_available": "yes"},
        {"request_fingerprint": 5},
        {"bundle_finding_count": 1.5},
    ],
)
def test_malformed_bundle_fields_are_unavailable(ready_bundle, ready_audit, changes):
    result = _verify(_tamper(ready_bundle, **changes), ready_audit)
    _assert_unavailable(result, "TASK_165_BUNDLE_INVALID")


def test_audit_without_snapshot_is_unavailable(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, audited_bundle=None)
    _assert_unavailable(_verify(ready_bundle, audit), "TASK_166_AUDITED_BUNDLE_MISSING")


def test_legacy_audit_without_snapshot_field_is_unavailable(ready_bundle, ready_audit):
    payload = ready_audit.model_dump()
    payload.pop("audited_bundle")
    _assert_unavailable(
        _verify(ready_bundle, payload), "TASK_166_AUDITED_BUNDLE_MISSING"
    )


def test_malformed_snapshot_is_unavailable(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, audited_bundle={"session_id": "x"})
    _assert_unavailable(_verify(ready_bundle, audit), "TASK_166_AUDIT_INVALID")


def test_unavailable_audit_is_unavailable_not_inconsistent(ready_bundle):
    audit = _make_audit(None)
    assert audit.bundle_audit_status == "UNAVAILABLE"
    _assert_unavailable(_verify(ready_bundle, audit), "TASK_166_AUDIT_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Purity, determinism, and schema contract
# ---------------------------------------------------------------------------


def test_consistency_does_not_mutate_inputs(ready_bundle, ready_audit):
    bundle_before = copy.deepcopy(ready_bundle)
    audit_before = copy.deepcopy(ready_audit)
    _verify(ready_bundle, ready_audit)
    _verify(_variant(ready_bundle, request_fingerprint="c" * 64), ready_audit)
    assert ready_bundle == bundle_before
    assert ready_audit == audit_before
    assert ready_bundle.request_fingerprint == "a" * 64


def test_consistency_is_deterministic(ready_bundle, ready_audit):
    other = _variant(ready_bundle, request_fingerprint="b" * 64)
    assert _verify(ready_bundle, ready_audit) == _verify(ready_bundle, ready_audit)
    assert _verify(other, ready_audit) == _verify(other, ready_audit)


def test_findings_are_sorted_and_deduplicated(ready_bundle, ready_audit):
    audit = _tamper(
        ready_audit,
        session_id=str(uuid4()),
        published_bundle_status="BLOCKED",
        expected_bundle_status="BLOCKED",
        audit_source="FORGED",
    )
    bundle = _tamper(ready_bundle, bundle_source="FORGED2")
    result = _verify(bundle, audit)
    assert result["findings"] == sorted(set(result["findings"]))
    assert result["finding_count"] == len(result["findings"])
    assert result["consistency_status"] == "INCONSISTENT"


def test_no_fingerprint_recomputation_or_child_service_calls(
    ready_bundle, ready_audit, monkeypatch
):
    """Task 167 never invokes the Task 165/166 services or hashing."""

    def _boom(*args, **kwargs):
        raise AssertionError("must not be called from Task 167")

    monkeypatch.setattr(ReasoningRunStage7EvidenceBundleAuditService, "audit", _boom)
    import hashlib

    monkeypatch.setattr(hashlib, "sha256", _boom)
    assert _verify(ready_bundle, ready_audit)["consistency_status"] == "CONSISTENT"


def test_service_module_imports_no_child_services():
    import rop.services.reasoning_run_stage_7_evidence_bundle_audit_consistency as m

    source = open(m.__file__, encoding="utf-8").read()
    assert "EvidenceBundleAuditService" not in source
    assert "ReasoningRunStage7EvidenceBundleService" not in source
    assert "hashlib" not in source


def test_consistency_schema_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            {
                "session_id": "s",
                "consistency_status": "CONSISTENT",
                "available": True,
                "consistent": True,
                "finding_count": 0,
                "findings": [],
                "consistency_source": CONSISTENCY_SOURCE,
                "extra": 1,
            }
        )


def test_consistency_schema_rejects_missing_fields():
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            {"session_id": "s"}
        )


_BASE = {
    "session_id": "s",
    "consistency_status": "CONSISTENT",
    "available": True,
    "consistent": True,
    "finding_count": 0,
    "findings": [],
    "consistency_source": CONSISTENCY_SOURCE,
}


@pytest.mark.parametrize(
    "changes",
    [
        {"available": False},
        {"consistent": False},
        {"finding_count": 1},
        {"findings": ["X"], "finding_count": 1},
        {"consistency_status": "INCONSISTENT", "consistent": False},
        {
            "consistency_status": "UNAVAILABLE",
            "available": False,
            "consistent": False,
        },
        {
            "consistency_status": "INCONSISTENT",
            "consistent": False,
            "findings": ["B", "A"],
            "finding_count": 2,
        },
        {
            "consistency_status": "INCONSISTENT",
            "consistent": False,
            "findings": ["A", "A"],
            "finding_count": 2,
        },
    ],
)
def test_consistency_schema_coherence_rules(changes):
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            {**_BASE, **changes}
        )


def test_consistency_source_constant_is_correct():
    assert (
        REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
        == "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_TASK_167"
    )


# ---------------------------------------------------------------------------
# Status enums are enforced on objects altered after construction
# ---------------------------------------------------------------------------

_FORGED_STATUSES = ["FORGED", "ready", "", " READY", "READY\n"]


@pytest.mark.parametrize("forged", _FORGED_STATUSES)
def test_mutated_bundle_status_is_never_consistent(ready_bundle, ready_audit, forged):
    bundle = _tamper(ready_bundle, bundle_status=forged)
    result = _verify(bundle, ready_audit)
    assert result["consistency_status"] != "CONSISTENT"
    _assert_unavailable(result, "TASK_165_BUNDLE_INVALID:bundle_status")


@pytest.mark.parametrize("forged", _FORGED_STATUSES)
def test_mutated_audit_published_status_is_never_consistent(
    ready_bundle, ready_audit, forged
):
    audit = _tamper(ready_audit, published_bundle_status=forged)
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] != "CONSISTENT"
    _assert_unavailable(result, "TASK_166_AUDIT_INVALID:published_bundle_status")


@pytest.mark.parametrize("forged", _FORGED_STATUSES)
def test_mutated_audit_expected_status_is_never_consistent(
    ready_bundle, ready_audit, forged
):
    audit = _tamper(ready_audit, expected_bundle_status=forged)
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] != "CONSISTENT"
    _assert_unavailable(result, "TASK_166_AUDIT_INVALID:expected_bundle_status")


@pytest.mark.parametrize("forged", _FORGED_STATUSES)
def test_matching_forged_statuses_across_bundle_audit_and_snapshot(
    ready_bundle, ready_audit, forged
):
    """Agreement between forged values must not read as consistency."""
    bundle = _tamper(ready_bundle, bundle_status=forged)
    snapshot = _tamper(ready_audit.audited_bundle, bundle_status=forged)
    audit = _tamper(
        ready_audit,
        published_bundle_status=forged,
        expected_bundle_status=forged,
        audited_bundle=snapshot,
    )
    assert bundle.bundle_status == audit.published_bundle_status == forged
    assert audit.expected_bundle_status == snapshot.bundle_status == forged
    result = _verify(bundle, audit)
    assert result["consistency_status"] != "CONSISTENT"
    assert result["consistency_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["session_id"] == ""


def test_forged_audit_status_is_never_consistent(ready_bundle, ready_audit):
    audit = _tamper(ready_audit, bundle_audit_status="FORGED")
    result = _verify(ready_bundle, audit)
    _assert_unavailable(result, "TASK_166_AUDIT_INVALID:bundle_audit_status")


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("slice_status", "FORGED"),
        ("admission_status", "FORGED"),
        ("admission_status", "READY"),
        ("diagnostics_status", "FORGED"),
        ("diagnostics_status", "ADMITTED"),
        ("slice_audit_status", "READY"),
        ("published_slice_status", "CONSISTENT"),
        ("expected_slice_status", "FORGED"),
        ("request_audit_status", "READY"),
        ("proposal_audit_status", "FORGED"),
    ],
)
def test_other_mutated_bundle_statuses_are_unavailable(
    ready_bundle, ready_audit, field, forged
):
    bundle = _tamper(ready_bundle, **{field: forged})
    _assert_unavailable(
        _verify(bundle, ready_audit), f"TASK_165_BUNDLE_INVALID:{field}"
    )


@pytest.mark.parametrize(
    "field",
    [
        "slice_status",
        "admission_status",
        "diagnostics_status",
        "slice_audit_status",
        "published_slice_status",
        "expected_slice_status",
        "request_audit_status",
        "proposal_audit_status",
        "bundle_status",
    ],
)
def test_mutated_snapshot_status_is_never_consistent(ready_bundle, ready_audit, field):
    """A forged status recorded only in the snapshot is malformed evidence."""
    snapshot = _tamper(ready_audit.audited_bundle, **{field: "FORGED"})
    audit = _tamper(ready_audit, audited_bundle=snapshot)
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] != "CONSISTENT"
    _assert_unavailable(result, f"TASK_166_AUDIT_INVALID:audited_bundle.{field}")


@pytest.mark.parametrize("field", ["slice_status", "request_audit_status"])
def test_forged_status_matching_in_bundle_and_snapshot_is_never_consistent(
    ready_bundle, ready_audit, field
):
    bundle = _tamper(ready_bundle, **{field: "FORGED"})
    snapshot = _tamper(ready_audit.audited_bundle, **{field: "FORGED"})
    audit = _tamper(ready_audit, audited_bundle=snapshot)
    result = _verify(bundle, audit)
    assert result["consistency_status"] == "UNAVAILABLE"


def test_forged_status_in_mapping_inputs_is_unavailable(ready_bundle, ready_audit):
    bundle = ready_bundle.model_dump()
    bundle["bundle_status"] = "FORGED"
    _assert_unavailable(_verify(bundle, ready_audit), "TASK_165_BUNDLE_INVALID")
    audit = ready_audit.model_dump()
    audit["expected_bundle_status"] = "FORGED"
    _assert_unavailable(_verify(ready_bundle, audit), "TASK_166_AUDIT_INVALID")


@pytest.mark.parametrize("fixture_name", ["ready_bundle", "blocked_bundle"])
def test_valid_permitted_statuses_still_bind_consistently(fixture_name, request):
    bundle = request.getfixturevalue(fixture_name)
    result = _verify(bundle, _make_audit(bundle))
    assert result["consistency_status"] == "CONSISTENT"
    assert result["findings"] == []


def test_valid_unavailable_bundle_still_binds_consistently(unavailable_bundle):
    result = _verify(unavailable_bundle, _make_audit(unavailable_bundle))
    assert result["consistency_status"] == "CONSISTENT"


@pytest.mark.parametrize(
    "changes",
    [
        {"published_bundle_status": "BLOCKED"},
        {"published_bundle_status": "UNAVAILABLE"},
        {"expected_bundle_status": "BLOCKED"},
        {"expected_bundle_status": "UNAVAILABLE"},
    ],
)
def test_valid_but_contradictory_statuses_are_inconsistent(
    ready_bundle, ready_audit, changes
):
    result = _verify(ready_bundle, _tamper(ready_audit, **changes))
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["available"] is True
    assert result["findings"]


def test_valid_but_contradictory_bundle_status_is_inconsistent(
    ready_bundle, ready_audit
):
    bundle = _tamper(ready_bundle, bundle_status="BLOCKED")
    result = _verify(bundle, ready_audit)
    assert result["consistency_status"] == "INCONSISTENT"
    assert "BUNDLE_SNAPSHOT_MISMATCH" in result["findings"]
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]


def test_status_enum_checks_do_not_mutate_inputs(ready_bundle, ready_audit):
    bundle = _tamper(ready_bundle, bundle_status="FORGED")
    audit = _tamper(ready_audit, expected_bundle_status="FORGED")
    bundle_before = copy.deepcopy(bundle)
    audit_before = copy.deepcopy(audit)
    first = _verify(bundle, audit)
    assert _verify(bundle, audit) == first
    assert bundle == bundle_before
    assert audit == audit_before


# ---------------------------------------------------------------------------
# Required audit statuses are enforced on objects altered after construction
# ---------------------------------------------------------------------------

_REQUIRED_STATUS_FIELDS = ["published_bundle_status", "expected_bundle_status"]


def _missing_status_marker(field: str) -> str:
    return f"TASK_166_AUDIT_INVALID:{field}:required_status_missing"


@pytest.fixture
def inconsistent_pair(ready_bundle):
    """A tampered bundle and the genuine INCONSISTENT audit bound to it."""
    bundle = _tamper(ready_bundle, bundle_status="BLOCKED")
    audit = _make_audit(bundle)
    assert audit.bundle_audit_status == "INCONSISTENT"
    assert audit.published_bundle_status is not None
    assert audit.expected_bundle_status is not None
    return bundle, audit


@pytest.mark.parametrize("field", _REQUIRED_STATUS_FIELDS)
def test_consistent_audit_missing_required_status_is_unavailable(
    ready_bundle, ready_audit, field
):
    assert ready_audit.bundle_audit_status == "CONSISTENT"
    audit = _tamper(ready_audit, **{field: None})
    assert getattr(audit, field) is None
    result = _verify(ready_bundle, audit)
    assert result["consistency_status"] != "INCONSISTENT"
    _assert_unavailable(result, f"TASK_166_AUDIT_INVALID:{field}")
    assert result["findings"] == [_missing_status_marker(field)]


@pytest.mark.parametrize("field", _REQUIRED_STATUS_FIELDS)
def test_inconsistent_audit_missing_required_status_is_unavailable(
    inconsistent_pair, field
):
    bundle, genuine = inconsistent_pair
    audit = _tamper(genuine, **{field: None})
    assert getattr(audit, field) is None
    result = _verify(bundle, audit)
    assert result["consistency_status"] != "INCONSISTENT"
    _assert_unavailable(result, f"TASK_166_AUDIT_INVALID:{field}")
    assert result["findings"] == [_missing_status_marker(field)]


def test_missing_required_status_is_unavailable_not_a_finding(
    ready_bundle, ready_audit
):
    """Malformed audit evidence is never read onward as a contradiction."""
    audit = _tamper(
        ready_audit, published_bundle_status=None, expected_bundle_status=None
    )
    result = _verify(ready_bundle, audit)
    _assert_unavailable(result, "TASK_166_AUDIT_INVALID:published_bundle_status")
    assert result["finding_count"] == 1
    for code in (
        "AUDIT_INTERNAL_MISMATCH",
        "PUBLISHED_STATUS_MISMATCH",
        "EXPECTED_STATUS_CONTRADICTION",
        "BUNDLE_SNAPSHOT_MISMATCH",
    ):
        assert code not in result["findings"]


def test_genuinely_unavailable_audit_keeps_existing_behaviour(ready_bundle):
    audit = _make_audit(None)
    assert audit.bundle_audit_status == "UNAVAILABLE"
    assert audit.published_bundle_status is None
    assert audit.expected_bundle_status is None
    result = _verify(ready_bundle, audit)
    _assert_unavailable(result, "TASK_166_AUDIT_UNAVAILABLE")
    # Absent statuses are legitimate here: it is not reported as malformed.
    assert not any(f.startswith("TASK_166_AUDIT_INVALID") for f in result["findings"])


_BUNDLE_STATUS_VALUES = ["READY", "BLOCKED", "UNAVAILABLE"]


@pytest.mark.parametrize("expected", _BUNDLE_STATUS_VALUES)
@pytest.mark.parametrize("published", _BUNDLE_STATUS_VALUES)
def test_permitted_but_contradictory_statuses_stay_inconsistent(
    ready_bundle, ready_audit, published, expected
):
    audit = _tamper(
        ready_audit,
        published_bundle_status=published,
        expected_bundle_status=expected,
    )
    result = _verify(ready_bundle, audit)
    if published == "READY" and expected == "READY":
        assert result["consistency_status"] == "CONSISTENT"
        return
    assert result["consistency_status"] == "INCONSISTENT"
    assert result["available"] is True
    assert result["session_id"] == ready_bundle.session_id
    assert result["findings"]
    assert not any(f.startswith("TASK_166_AUDIT_INVALID") for f in result["findings"])


@pytest.mark.parametrize("field", _REQUIRED_STATUS_FIELDS)
def test_missing_required_status_is_deterministic_and_unmodified(
    inconsistent_pair, ready_bundle, ready_audit, field
):
    cases = [
        (ready_bundle, _tamper(ready_audit, **{field: None})),
        (inconsistent_pair[0], _tamper(inconsistent_pair[1], **{field: None})),
    ]
    for bundle, audit in cases:
        bundle_before = copy.deepcopy(bundle)
        audit_before = copy.deepcopy(audit)
        first = _verify(bundle, audit)
        assert _verify(bundle, audit) == first
        assert first["consistency_status"] == "UNAVAILABLE"
        assert bundle == bundle_before
        assert audit == audit_before
        assert getattr(audit, field) is None

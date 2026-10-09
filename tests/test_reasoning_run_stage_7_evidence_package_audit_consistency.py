"""Task 170: Stage 7 evidence-package audit consistency tests.

Independent consistency boundary between Task 168 Evidence Package and
Task 169 Evidence-Package Audit. The service verifies exact binding of
session identity, package status, package source, evidence presence,
findings, finding counts, published versus expected status, audit source,
and audit status.

The consistency check is pure and independent: it never calls Task 168
or Task 169 services, never recomputes fingerprints, never invokes a
provider, and never accesses a database.

The tests pin the boundary between *readable but contradictory* evidence
(``INCONSISTENT`` with specific findings) and *unreadable* evidence
(``UNAVAILABLE``), plus the distinct case of a structurally valid Task 169
audit that is itself ``UNAVAILABLE``.
"""

from __future__ import annotations

import copy
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
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageService,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit import (
    ReasoningRunStage7EvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit_consistency import (
    ReasoningRunStage7EvidencePackageAuditConsistencyService,
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
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
)


@pytest.fixture
def ready_package(
    ready_bundle_evidence,
) -> ReasoningRunStage7EvidencePackageRead:
    """A READY package for testing."""
    session_id = str(uuid4())
    fingerprint = "a" * 64
    return ReasoningRunStage7EvidencePackageRead(
        session_id=session_id,
        t162_session_id=session_id,
        t162_admission_status="ADMITTED",
        t162_diagnostics_status="HEALTHY",
        t162_request_fingerprint=fingerprint,
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
        t165_bundle_evidence=ready_bundle_evidence(session_id, fingerprint),
        t166_session_id=session_id,
        t166_bundle_audit_status="CONSISTENT",
        t166_available=True,
        t166_consistent=True,
        t166_published_bundle_status="READY",
        t166_expected_bundle_status="READY",
        t166_finding_count=0,
        t166_findings=[],
        t166_audit_source="REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166",
        t166_audited_bundle=ready_bundle_evidence(session_id, fingerprint),
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
def ready_audit(
    ready_package: ReasoningRunStage7EvidencePackageRead,
) -> ReasoningRunStage7EvidencePackageAuditRead:
    """A CONSISTENT audit for the READY package."""
    return ReasoningRunStage7EvidencePackageAuditRead(
        session_id=ready_package.session_id,
        package_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_package_status="READY",
        expected_package_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify(package, audit):
    return ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=package, audit=audit
    )


def _set_attr(name, value):
    """Mutate a model after construction (assignment is not revalidated)."""

    def mutate(model):
        setattr(model, name, value)

    return mutate


def _drop_attr(name):
    """Remove a declared attribute so it can no longer be read."""

    def mutate(model):
        del model.__dict__[name]

    return mutate


def _set_nested(parent, name, value):
    def mutate(model):
        setattr(getattr(model, parent), name, value)

    return mutate


def _drop_nested(parent, name):
    def mutate(model):
        del getattr(model, parent).__dict__[name]

    return mutate


def _mutated(model, mutate):
    clone = copy.deepcopy(model)
    mutate(clone)
    return clone


def _assert_unreadable(consistency):
    """An unreadable-input result is a schema-valid, deterministic UNAVAILABLE."""
    validated = ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
        consistency
    )
    assert validated.consistency_status == "UNAVAILABLE"
    assert validated.session_id == ""
    assert validated.available is False
    assert validated.consistent is False
    assert validated.finding_count >= 1
    assert "PACKAGE_OR_AUDIT_INVALID" in validated.findings
    assert validated.findings == sorted(set(validated.findings))
    assert validated.consistency_source == CONSISTENCY_SOURCE


UNREADABLE_PACKAGE_MUTATIONS = {
    "session_id_not_a_string": _set_attr("session_id", None),
    "finding_count_string": _set_attr("finding_count", "1"),
    "finding_count_bool": _set_attr("finding_count", True),
    "findings_not_a_list": _set_attr("findings", ("A",)),
    "finding_item_not_a_string": _set_attr("findings", [1]),
    "status_outside_permitted_set": _set_attr("package_status", "BOGUS"),
    "missing_required_attribute": _drop_attr("package_source"),
    "missing_identity_attribute": _drop_attr("session_id"),
    "nested_evidence_is_a_dict": _set_attr("t165_bundle_evidence", {"session_id": "x"}),
    "nested_evidence_is_none": _set_attr("t165_bundle_evidence", None),
    "nested_audited_bundle_wrong_type": _set_attr("t166_audited_bundle", object()),
    "nested_evidence_field_wrong_type": _set_nested(
        "t165_bundle_evidence", "finding_count", "x"
    ),
    "nested_audited_bundle_field_wrong_type": _set_nested(
        "t166_audited_bundle", "findings", "not-a-list"
    ),
    "nested_evidence_missing_field": _drop_nested(
        "t165_bundle_evidence", "bundle_status"
    ),
}

UNREADABLE_AUDIT_MUTATIONS = {
    "session_id_not_a_string": _set_attr("session_id", None),
    "finding_count_string": _set_attr("finding_count", "0"),
    "available_not_a_bool": _set_attr("available", "yes"),
    "findings_not_a_list": _set_attr("findings", ("A",)),
    "audit_status_outside_permitted_set": _set_attr("package_audit_status", "BOGUS"),
    "published_status_outside_permitted_set": _set_attr(
        "published_package_status", "BOGUS"
    ),
    "expected_status_outside_permitted_set": _set_attr(
        "expected_package_status", "BOGUS"
    ),
    "missing_required_attribute": _drop_attr("audit_source"),
    "missing_findings_attribute": _drop_attr("findings"),
}


def _valid_unavailable_audit() -> ReasoningRunStage7EvidencePackageAuditRead:
    """A structurally valid Task 169 audit that verified nothing."""
    return ReasoningRunStage7EvidencePackageAuditRead(
        session_id="",
        package_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_package_status=None,
        expected_package_status=None,
        finding_count=1,
        findings=["PACKAGE_NOT_READABLE"],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    )


# ---------------------------------------------------------------------------
# Genuine consistency
# ---------------------------------------------------------------------------


def test_genuine_ready_package_with_consistent_audit_is_consistent(
    ready_package, ready_audit
):
    """A genuine READY package with a CONSISTENT audit is CONSISTENT."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "CONSISTENT"
    assert consistency["available"] is True
    assert consistency["consistent"] is True
    assert consistency["finding_count"] == 0
    assert consistency["findings"] == []
    assert consistency["consistency_source"] == CONSISTENCY_SOURCE


# ---------------------------------------------------------------------------
# Session mismatch detection
# ---------------------------------------------------------------------------


def test_session_mismatch_detected(ready_package, ready_audit):
    """Session mismatch between package and audit is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = str(uuid4())
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]


def test_cross_session_audit_detected(ready_package, ready_audit):
    """Audit from different session is detected as inconsistent."""
    different_session = str(uuid4())
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = different_session
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]


# ---------------------------------------------------------------------------
# Source forgery detection
# ---------------------------------------------------------------------------


def test_package_source_mismatch_detected(ready_package, ready_audit):
    """A forged package source is a readable contradiction, not unavailable."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.package_source = "FORGED_PACKAGE_SOURCE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PACKAGE_SOURCE_MISMATCH" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]
    assert consistency["session_id"] == ready_package.session_id
    assert consistency["available"] is True
    assert consistency["consistent"] is False


def test_audit_source_mismatch_detected(ready_package, ready_audit):
    """A forged audit source is a readable contradiction, not unavailable."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.audit_source = "FORGED_AUDIT_SOURCE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_SOURCE_MISMATCH" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]
    assert consistency["session_id"] == ready_package.session_id


# ---------------------------------------------------------------------------
# Status mismatch detection
# ---------------------------------------------------------------------------


def test_published_status_mismatch_detected(ready_package, ready_audit):
    """Published status mismatch is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.published_package_status = "BLOCKED"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


def test_expected_status_contradiction_detected(ready_package, ready_audit):
    """Expected status contradiction is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.expected_package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


def test_forged_package_status_detected(ready_package, ready_audit):
    """A package status the audit independently contradicts is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.package_status = "BLOCKED"
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.published_package_status = "BLOCKED"
    tampered_audit.expected_package_status = "READY"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]
    # The audit published the forged status faithfully, so only the audit's
    # independently derived status disagrees with the package.
    assert "PUBLISHED_STATUS_MISMATCH" not in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


# ---------------------------------------------------------------------------
# Audit status detection
# ---------------------------------------------------------------------------


def test_audit_not_consistent_detected(ready_package, ready_audit):
    """Audit that is not CONSISTENT is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_ISSUE"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]


def test_mutated_unavailable_audit_is_readable_contradiction(
    ready_package, ready_audit
):
    """An audit mutated to claim UNAVAILABLE but still naming statuses is readable.

    It is not a structurally valid UNAVAILABLE audit (that names no status and
    no session), so it is compared and reported as a contradiction rather than
    treated as unreadable or as an honest UNAVAILABLE audit.
    """
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.package_audit_status = "UNAVAILABLE"
    tampered_audit.available = False
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["UNAVAILABLE_REASON"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_UNAVAILABLE" in consistency["findings"]
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]
    assert "AUDIT_CONTRACT_INVALID" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


# ---------------------------------------------------------------------------
# Finding count mismatch detection
# ---------------------------------------------------------------------------


def test_finding_count_mismatch_package_has_findings(ready_package, ready_audit):
    """A package finding_count that disagrees with its findings is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.finding_count = 3
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


def test_finding_count_mismatch_audit_count_disagrees(ready_package, ready_audit):
    """An audit finding_count that disagrees with its findings is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 2
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "FINDING_COUNT_MISMATCH" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


def test_consistent_audit_with_findings_is_mismatch(ready_package, ready_audit):
    """An audit claiming CONSISTENT while carrying findings is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_FINDING"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_FINDINGS_MISMATCH" in consistency["findings"]


def test_finding_count_mismatch_audit_has_findings(ready_package, ready_audit):
    """Finding count mismatch when audit has findings is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_FINDING"]
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]


def test_same_session_different_content_detected(ready_package, ready_audit):
    """Same session but different content is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.t162_admission_status = "BLOCKED"
    tampered_package.package_status = "BLOCKED"
    # Audit still says READY
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=ready_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency["findings"]


# ---------------------------------------------------------------------------
# Evidence presence detection
# ---------------------------------------------------------------------------


def test_audit_unavailable_flag_detected(ready_package, ready_audit):
    """An audit whose availability flag was flipped is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.available = False
    tampered_audit.package_audit_status = "UNAVAILABLE"
    tampered_audit.consistent = False
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["UNAVAILABLE"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_UNAVAILABLE" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


def test_audit_inconsistent_flag_detected(ready_package, ready_audit):
    """Audit with consistent=False is detected."""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.consistent = False
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["SOME_ISSUE"]
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_INCONSISTENT" in consistency["findings"]


def test_package_empty_session_detected(ready_package, ready_audit):
    """Package with empty session_id is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.session_id = ""
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.session_id = ""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "PACKAGE_SESSION_EMPTY" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]
    assert consistency["session_id"] == ""


# ---------------------------------------------------------------------------
# Adversarial tests
# ---------------------------------------------------------------------------


def test_detached_audit_from_different_package(ready_package, ready_audit):
    """Detached audit from a completely different package is detected."""
    different_session = str(uuid4())
    detached_audit = copy.deepcopy(ready_audit)
    detached_audit.session_id = different_session
    detached_audit.published_package_status = "BLOCKED"
    detached_audit.expected_package_status = "BLOCKED"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=detached_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency["findings"]
    assert "PUBLISHED_STATUS_MISMATCH" in consistency["findings"]


def test_finding_tampering_detected(ready_package, ready_audit):
    """Finding tampering across package and audit is detected."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.finding_count = 2
    tampered_package.findings = ["FINDING_A", "FINDING_B"]
    tampered_package.package_status = "UNAVAILABLE"
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.finding_count = 1
    tampered_audit.findings = ["FINDING_C"]
    tampered_audit.package_audit_status = "INCONSISTENT"
    tampered_audit.available = True
    tampered_audit.consistent = False
    tampered_audit.published_package_status = "UNAVAILABLE"
    tampered_audit.expected_package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency["findings"]
    # The package's findings no longer equal its child and package-level
    # findings, which its own contract forbids.
    assert "PACKAGE_CONTRACT_INVALID" in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]


def test_multiple_forgeries_detected(ready_package, ready_audit):
    """Multiple forgeries are all reported, sorted and deduplicated."""
    tampered_package = copy.deepcopy(ready_package)
    tampered_package.package_source = "FORGED"
    tampered_audit = copy.deepcopy(ready_audit)
    tampered_audit.audit_source = "FORGED"
    tampered_audit.published_package_status = "BLOCKED"
    tampered_audit.expected_package_status = "UNAVAILABLE"
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=tampered_package, audit=tampered_audit
    )
    assert consistency["consistency_status"] == "INCONSISTENT"
    for expected in (
        "PACKAGE_SOURCE_MISMATCH",
        "AUDIT_SOURCE_MISMATCH",
        "PUBLISHED_STATUS_MISMATCH",
        "EXPECTED_STATUS_CONTRADICTION",
    ):
        assert expected in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]
    assert consistency["findings"] == sorted(set(consistency["findings"]))
    assert consistency["finding_count"] == len(consistency["findings"])
    ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(consistency)


def test_service_revalidates_postconstruction_package_mutation(
    ready_package, ready_audit
):
    """A readable package mutated after construction is never CONSISTENT.

    The nested counts are still readable integers, so the package is evidence
    to compare, not unreadable evidence: the result is INCONSISTENT and says
    that the package no longer satisfies its own Task 168 contract.
    """
    ready_package.t165_bundle_evidence.bundle_finding_count = 1
    ready_package.t166_audited_bundle.bundle_finding_count = 1

    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )

    assert consistency["consistency_status"] == "INCONSISTENT"
    assert consistency["findings"] == ["PACKAGE_CONTRACT_INVALID"]
    assert consistency["session_id"] == ready_package.session_id
    assert consistency["available"] is True
    assert consistency["consistent"] is False


@pytest.mark.parametrize(
    ("package", "audit"),
    [(None, None), (object(), object())],
)
def test_missing_or_malformed_inputs_are_unavailable(package, audit):
    """Missing/unreadable inputs do not escape as attribute errors."""
    consistency = _verify(package, audit)

    _assert_unreadable(consistency)
    assert "PACKAGE_UNREADABLE" in consistency["findings"]
    assert "AUDIT_UNREADABLE" in consistency["findings"]


def test_unsupported_object_types_are_unavailable(ready_package, ready_audit):
    """Wrong model types, including swapped inputs, are unreadable."""
    swapped = _verify(ready_audit, ready_package)
    _assert_unreadable(swapped)
    assert "PACKAGE_UNREADABLE" in swapped["findings"]
    assert "AUDIT_UNREADABLE" in swapped["findings"]

    dict_inputs = _verify(ready_package.model_dump(), ready_audit.model_dump())
    _assert_unreadable(dict_inputs)

    only_package_missing = _verify(None, ready_audit)
    _assert_unreadable(only_package_missing)
    assert "PACKAGE_UNREADABLE" in only_package_missing["findings"]
    assert "AUDIT_UNREADABLE" not in only_package_missing["findings"]

    only_audit_missing = _verify(ready_package, None)
    _assert_unreadable(only_audit_missing)
    assert "AUDIT_UNREADABLE" in only_audit_missing["findings"]
    assert "PACKAGE_UNREADABLE" not in only_audit_missing["findings"]


@pytest.mark.parametrize("name", sorted(UNREADABLE_PACKAGE_MUTATIONS))
def test_malformed_package_is_unavailable_without_raising(
    name, ready_package, ready_audit
):
    """Malformed package fields and nested evidence are unreadable."""
    malformed = _mutated(ready_package, UNREADABLE_PACKAGE_MUTATIONS[name])

    consistency = _verify(malformed, ready_audit)

    _assert_unreadable(consistency)
    assert "PACKAGE_UNREADABLE" in consistency["findings"]
    assert "AUDIT_UNREADABLE" not in consistency["findings"]
    assert consistency == _verify(malformed, ready_audit)


@pytest.mark.parametrize("name", sorted(UNREADABLE_AUDIT_MUTATIONS))
def test_malformed_audit_is_unavailable_without_raising(
    name, ready_package, ready_audit
):
    """Malformed audit fields are unreadable."""
    malformed = _mutated(ready_audit, UNREADABLE_AUDIT_MUTATIONS[name])

    consistency = _verify(ready_package, malformed)

    _assert_unreadable(consistency)
    assert "AUDIT_UNREADABLE" in consistency["findings"]
    assert "PACKAGE_UNREADABLE" not in consistency["findings"]
    assert consistency == _verify(ready_package, malformed)


def test_unreadable_input_hides_no_partial_comparison(ready_package, ready_audit):
    """When either input is unreadable, no half-evaluated findings leak out."""
    detached_audit = _mutated(ready_audit, _set_attr("session_id", str(uuid4())))
    malformed_package = _mutated(ready_package, _drop_attr("package_source"))

    consistency = _verify(malformed_package, detached_audit)

    _assert_unreadable(consistency)
    assert consistency["findings"] == ["PACKAGE_OR_AUDIT_INVALID", "PACKAGE_UNREADABLE"]


# ---------------------------------------------------------------------------
# Readable contradictions are never downgraded to UNAVAILABLE
# ---------------------------------------------------------------------------


READABLE_CONTRADICTIONS = {
    "forged_package_source": (
        _set_attr("package_source", "FORGED"),
        None,
        "PACKAGE_SOURCE_MISMATCH",
    ),
    "forged_audit_source": (
        None,
        _set_attr("audit_source", "FORGED"),
        "AUDIT_SOURCE_MISMATCH",
    ),
    "detached_session": (
        None,
        _set_attr("session_id", "another-session"),
        "SESSION_MISMATCH",
    ),
    "published_status_conflict": (
        None,
        _set_attr("published_package_status", "BLOCKED"),
        "PUBLISHED_STATUS_MISMATCH",
    ),
    "expected_status_conflict": (
        None,
        _set_attr("expected_package_status", "BLOCKED"),
        "EXPECTED_STATUS_CONTRADICTION",
    ),
    "package_finding_count_conflict": (
        _set_attr("finding_count", 4),
        None,
        "FINDING_COUNT_MISMATCH",
    ),
    "audit_finding_count_conflict": (
        None,
        _set_attr("finding_count", 4),
        "FINDING_COUNT_MISMATCH",
    ),
    "audit_flag_conflict": (
        None,
        _set_attr("consistent", False),
        "AUDIT_INCONSISTENT",
    ),
}


@pytest.mark.parametrize("name", sorted(READABLE_CONTRADICTIONS))
def test_readable_contradiction_keeps_specific_finding(
    name, ready_package, ready_audit
):
    """A contract failure on readable fields reports what disagrees."""
    mutate_package, mutate_audit, expected = READABLE_CONTRADICTIONS[name]
    package = (
        _mutated(ready_package, mutate_package) if mutate_package else ready_package
    )
    audit = _mutated(ready_audit, mutate_audit) if mutate_audit else ready_audit

    consistency = _verify(package, audit)

    assert consistency["consistency_status"] == "INCONSISTENT"
    assert consistency["available"] is True
    assert consistency["consistent"] is False
    assert expected in consistency["findings"]
    assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]
    assert "PACKAGE_UNREADABLE" not in consistency["findings"]
    assert "AUDIT_UNREADABLE" not in consistency["findings"]
    assert consistency["findings"] == sorted(set(consistency["findings"]))
    ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(consistency)


def test_readable_contract_failure_is_never_consistent(ready_package, ready_audit):
    """A readable object that fails its own contract can never be CONSISTENT."""
    nested_mutation = _mutated(
        ready_package, _set_nested("t165_bundle_evidence", "bundle_finding_count", 1)
    )
    missing_snapshot = _mutated(ready_package, _set_attr("t166_audited_bundle", None))

    for package in (nested_mutation, missing_snapshot):
        consistency = _verify(package, ready_audit)
        assert consistency["consistency_status"] == "INCONSISTENT"
        assert "PACKAGE_CONTRACT_INVALID" in consistency["findings"]
        assert "PACKAGE_OR_AUDIT_INVALID" not in consistency["findings"]

    # The same package/audit pair is CONSISTENT before it is mutated.
    assert _verify(ready_package, ready_audit)["consistency_status"] == "CONSISTENT"


# ---------------------------------------------------------------------------
# A structurally valid Task 169 UNAVAILABLE audit
# ---------------------------------------------------------------------------


def test_valid_unavailable_audit_is_unavailable_not_malformed(ready_package):
    """A valid UNAVAILABLE audit verified nothing: UNAVAILABLE, AUDIT_UNAVAILABLE.

    Task 170's contract: UNAVAILABLE when the audit cannot be bound to the
    package. The audit is readable and honest, so this must not be reported as
    the generic malformed-input finding.
    """
    audit = _valid_unavailable_audit()

    consistency = _verify(ready_package, audit)

    validated = ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
        consistency
    )
    assert validated.consistency_status == "UNAVAILABLE"
    assert validated.session_id == ""
    assert validated.available is False
    assert validated.consistent is False
    assert validated.findings == ["AUDIT_UNAVAILABLE"]
    assert validated.finding_count == 1
    assert "PACKAGE_OR_AUDIT_INVALID" not in validated.findings
    assert "AUDIT_UNREADABLE" not in validated.findings
    assert consistency == _verify(ready_package, audit)


def test_valid_unavailable_audit_differs_from_malformed_audit(
    ready_package, ready_audit
):
    """The valid-UNAVAILABLE and malformed-audit results are distinguishable."""
    valid_unavailable = _verify(ready_package, _valid_unavailable_audit())
    malformed = _verify(ready_package, _mutated(ready_audit, _drop_attr("findings")))

    assert valid_unavailable["consistency_status"] == "UNAVAILABLE"
    assert malformed["consistency_status"] == "UNAVAILABLE"
    assert valid_unavailable["findings"] == ["AUDIT_UNAVAILABLE"]
    assert "AUDIT_UNREADABLE" in malformed["findings"]
    assert valid_unavailable["findings"] != malformed["findings"]


def test_valid_unavailable_audit_does_not_claim_a_session_match(ready_package):
    """Because the audit names no session, a package session is never echoed."""
    consistency = _verify(ready_package, _valid_unavailable_audit())

    assert consistency["session_id"] == ""
    assert "SESSION_MISMATCH" not in consistency["findings"]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_consistency_schema_rejects_extra_fields(ready_package, ready_audit):
    """Consistency schema rejects extra fields."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_schema_rejects_missing_fields(ready_package, ready_audit):
    """Consistency schema rejects missing fields."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    del consistency["session_id"]
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_available_consistent_enforced(ready_package, ready_audit):
    """available must equal (consistency_status != 'UNAVAILABLE')."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["available"] = False
    with pytest.raises(ValidationError, match="available must equal"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_consistent_enforced(ready_package, ready_audit):
    """consistent must equal (consistency_status == 'CONSISTENT')."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistent_requires_no_findings(ready_package, ready_audit):
    """CONSISTENT requires a finding-free consistency check."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["findings"] = ["FORGED"]
    consistency["finding_count"] = 1
    with pytest.raises(ValidationError, match="CONSISTENT requires"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_inconsistent_requires_findings(ready_package, ready_audit):
    """INCONSISTENT requires at least one finding."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistency_status"] = "INCONSISTENT"
    consistency["available"] = True
    consistency["consistent"] = False
    with pytest.raises(ValidationError, match="INCONSISTENT requires"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_unavailable_requires_findings(ready_package, ready_audit):
    """UNAVAILABLE requires at least one diagnostic finding."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistency_status"] = "UNAVAILABLE"
    consistency["available"] = False
    consistency["consistent"] = False
    consistency["session_id"] = ""
    with pytest.raises(ValidationError, match="UNAVAILABLE requires"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_consistency_schema_requires_canonical_source(ready_package, ready_audit):
    """The Task 170 read schema rejects a forged source."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistency_source"] = "FORGED_SOURCE"

    with pytest.raises(ValidationError, match="canonical Task 170 source"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


def test_unavailable_consistency_cannot_claim_session(ready_package, ready_audit):
    """UNAVAILABLE evidence must not expose a session as verified."""
    consistency = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency["consistency_status"] = "UNAVAILABLE"
    consistency["available"] = False
    consistency["consistent"] = False
    consistency["finding_count"] = 1
    consistency["findings"] = ["UNAVAILABLE_REASON"]

    with pytest.raises(ValidationError, match="must not claim a session"):
        ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
            consistency
        )


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_consistency_does_not_mutate_inputs(ready_package, ready_audit):
    """Consistency check does not mutate inputs."""
    original_package = ready_package.model_dump()
    original_audit = ready_audit.model_dump()
    ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    assert ready_package.model_dump() == original_package
    assert ready_audit.model_dump() == original_audit


def test_consistency_does_not_mutate_tampered_or_malformed_inputs(
    ready_package, ready_audit
):
    """Contradictory and malformed inputs are read, never repaired or changed."""
    cases = [
        (
            _mutated(ready_package, _set_attr("package_source", "FORGED")),
            _mutated(ready_audit, _set_attr("session_id", "other")),
        ),
        (
            _mutated(ready_package, _set_nested("t165_bundle_evidence", "findings", 1)),
            ready_audit,
        ),
        (ready_package, _valid_unavailable_audit()),
        (ready_package, _mutated(ready_audit, _drop_attr("audit_source"))),
    ]
    for package, audit in cases:
        package_state = copy.deepcopy(package.__dict__)
        audit_state = copy.deepcopy(audit.__dict__)

        _verify(package, audit)

        assert package.__dict__ == package_state
        assert audit.__dict__ == audit_state


# ---------------------------------------------------------------------------
# Independence protections
# ---------------------------------------------------------------------------


def test_consistency_is_pure_function(ready_package, ready_audit):
    """Consistency check is a pure function."""
    consistency1 = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    consistency2 = ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
        package=ready_package, audit=ready_audit
    )
    assert consistency1 == consistency2


def test_consistency_is_independent_of_upstream_services(
    ready_package, ready_audit, monkeypatch
):
    """The check reads published objects and never calls Task 168 or Task 169."""

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("Task 170 must not call an upstream service")

    monkeypatch.setattr(
        ReasoningRunStage7EvidencePackageService,
        "assemble",
        staticmethod(_must_not_be_called),
    )
    monkeypatch.setattr(
        ReasoningRunStage7EvidencePackageAuditService,
        "audit",
        staticmethod(_must_not_be_called),
    )

    assert _verify(ready_package, ready_audit)["consistency_status"] == "CONSISTENT"
    assert (
        _verify(
            _mutated(ready_package, _set_attr("package_source", "FORGED")), ready_audit
        )["consistency_status"]
        == "INCONSISTENT"
    )
    assert _verify(None, None)["consistency_status"] == "UNAVAILABLE"


def test_consistency_source_constant_is_correct():
    """Consistency source constant is exported correctly."""
    assert CONSISTENCY_SOURCE == (
        "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_170"
    )


def test_no_provider_invocation():
    """Service never invokes provider or network."""
    # This is a structural test - the service signature accepts only
    # validated Pydantic objects and has no DB session or provider parameter
    import inspect

    sig = inspect.signature(
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify
    )
    param_names = list(sig.parameters.keys())
    assert "db" not in param_names
    assert "session" not in param_names
    assert "provider" not in param_names
    assert "client" not in param_names


def test_no_mutation():
    """Service never performs mutation."""
    # This is a structural test - the service returns a dict,
    # not a database object or mutated input
    import inspect

    sig = inspect.signature(
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify
    )
    return_annotation = sig.return_annotation
    assert "dict" in str(return_annotation).lower()

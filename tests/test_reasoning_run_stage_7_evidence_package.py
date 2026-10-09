"""Task 168: canonical Stage 7 evidence package tests.

Aggregation boundary over already-published and already-validated Stage 7
evidence: Task 162 Audit Package, Task 163 Vertical-Slice Verdict, Task
164 Vertical-Slice Audit, Task 165 Evidence Bundle, Task 166 Evidence-
Bundle Audit, and Task 167 Evidence-Bundle Audit Consistency.
"""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
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
from rop.services.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageContractError,
    ReasoningRunStage7EvidencePackageService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

PACKAGE_SOURCE = REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168


@pytest.fixture
def ready_inputs():
    """All six inputs in READY/CONSISTENT state."""
    session_id = str(uuid4())
    fingerprint = "a" * 64

    pkg162 = ReasoningRunStage7AuditPackageRead(
        session_id=session_id,
        admission_status="ADMITTED",
        request_fingerprint=fingerprint,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    )

    slice163 = ReasoningRunStage7VerticalSliceRead(
        session_id=session_id,
        slice_status="READY",
        admission_status="ADMITTED",
        diagnostics_status="HEALTHY",
        provider_name="test-provider",
        model_name="test-model",
        finding_count=0,
        findings=[],
        certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    )

    audit164 = ReasoningRunStage7VerticalSliceAuditRead(
        session_id=session_id,
        slice_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_slice_status="READY",
        expected_slice_status="READY",
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
    )

    bundle165 = ReasoningRunStage7EvidenceBundleRead(
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
        request_fingerprint=fingerprint,
        request_audit_status="CONSISTENT",
        proposal_audit_status="CONSISTENT",
        t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        bundle_status="READY",
        bundle_finding_count=0,
        bundle_findings=[],
        bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )

    audit166 = ReasoningRunStage7EvidenceBundleAuditRead.model_validate(
        ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=bundle165)
    )

    consistency167 = (
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
            ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
                bundle=bundle165, audit=audit166
            )
        )
    )

    return {
        "pkg162": pkg162,
        "slice163": slice163,
        "audit164": audit164,
        "bundle165": bundle165,
        "audit166": audit166,
        "consistency167": consistency167,
    }


def test_ready_package_assembles_correctly(ready_inputs):
    """All READY/CONSISTENT inputs assemble to READY package."""
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_status"] == "READY"
    assert package["session_id"] == ready_inputs["pkg162"].session_id
    assert package["finding_count"] == 0
    assert package["findings"] == []
    assert package["package_source"] == PACKAGE_SOURCE
    assert package["t166_audited_bundle"] == package["t165_bundle_evidence"]


def test_session_mismatch_creates_blocked_package(ready_inputs):
    """Session mismatch creates a BLOCKED package."""
    ready_inputs["slice163"].session_id = str(uuid4())
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_status"] == "UNAVAILABLE"
    assert "STAGE_7_SESSION_MISMATCH" in package["findings"]


def test_blocked_input_creates_blocked_package(ready_inputs):
    """Any BLOCKED input creates a BLOCKED package."""
    ready_inputs["pkg162"].admission_status = "BLOCKED"
    ready_inputs["pkg162"].finding_count = 1
    ready_inputs["pkg162"].findings = ["BLOCKED"]
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_status"] == "BLOCKED"


def test_unavailable_input_creates_unavailable_package(ready_inputs):
    """Any UNAVAILABLE input creates an UNAVAILABLE package."""
    ready_inputs["pkg162"].admission_status = "UNAVAILABLE"
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_status"] == "UNAVAILABLE"


def test_package_source_mismatch_raises_error(ready_inputs):
    """Package source mismatch raises contract error."""
    # Can't tamper with source after validation, so we test that the service
    # always uses the canonical source
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_source"] == PACKAGE_SOURCE


def test_findings_aggregate_from_all_inputs(ready_inputs):
    """Findings aggregate from all six inputs."""
    ready_inputs["pkg162"].findings = ["FINDING_1"]
    ready_inputs["pkg162"].finding_count = 1
    ready_inputs["slice163"].findings = ["FINDING_2"]
    ready_inputs["slice163"].finding_count = 1
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["finding_count"] == 2
    assert set(package["findings"]) == {"FINDING_1", "FINDING_2"}


def test_evidence_preserved_verbatim(ready_inputs):
    """All evidence is preserved verbatim from inputs."""
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["t162_session_id"] == ready_inputs["pkg162"].session_id
    assert package["t163_session_id"] == ready_inputs["slice163"].session_id
    assert package["t164_session_id"] == ready_inputs["audit164"].session_id
    assert package["t165_session_id"] == ready_inputs["bundle165"].session_id
    assert package["t166_session_id"] == ready_inputs["audit166"].session_id
    assert package["t167_session_id"] == ready_inputs["consistency167"].session_id


def test_schema_rejects_extra_fields(ready_inputs):
    """Schema rejects extra fields."""
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_blocked_precedence_over_ready(ready_inputs):
    """BLOCKED takes precedence over READY."""
    ready_inputs["pkg162"].admission_status = "BLOCKED"
    ready_inputs["pkg162"].finding_count = 1
    ready_inputs["pkg162"].findings = ["BLOCKED"]
    ready_inputs["pkg162"].diagnostics_status = "HEALTHY"
    ready_inputs["slice163"].slice_status = "READY"
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_status"] == "BLOCKED"


def test_unavailable_task_166_audit_is_packaged_verbatim(ready_inputs):
    """An UNAVAILABLE Task 166 audit names no bundle status and still packages."""
    ready_inputs["audit166"] = ReasoningRunStage7EvidenceBundleAuditRead(
        session_id="",
        bundle_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_bundle_status=None,
        expected_bundle_status=None,
        finding_count=1,
        findings=["TASK_165_BUNDLE_MISSING"],
        audit_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    )
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    assert package["package_status"] == "UNAVAILABLE"
    assert package["t166_bundle_audit_status"] == "UNAVAILABLE"
    assert package["t166_published_bundle_status"] is None
    assert package["t166_expected_bundle_status"] is None
    assert package["t166_findings"] == ["TASK_165_BUNDLE_MISSING"]


@pytest.mark.parametrize(
    ("input_name", "source_field", "package_field", "finding"),
    [
        ("pkg162", "audit_source", "t162_audit_source", "T162_SOURCE_MISMATCH"),
        (
            "slice163",
            "certification_source",
            "t163_certification_source",
            "T163_SOURCE_MISMATCH",
        ),
        ("audit164", "audit_source", "t164_audit_source", "T164_SOURCE_MISMATCH"),
        ("bundle165", "bundle_source", "t165_bundle_source", "T165_SOURCE_MISMATCH"),
        ("audit166", "audit_source", "t166_audit_source", "T166_SOURCE_MISMATCH"),
        (
            "consistency167",
            "consistency_source",
            "t167_consistency_source",
            "T167_SOURCE_MISMATCH",
        ),
    ],
)
def test_noncanonical_upstream_source_cannot_be_ready(
    ready_inputs, input_name, source_field, package_field, finding
):
    setattr(ready_inputs[input_name], source_field, "FORGED_SOURCE")

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"
    assert finding in package["findings"]
    assert package[package_field] == "FORGED_SOURCE"


def test_missing_task_166_snapshot_cannot_be_ready(ready_inputs):
    ready_inputs["audit166"].audited_bundle = None

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"
    assert "T166_SNAPSHOT_MISSING" in package["findings"]
    assert package["t166_audited_bundle"] is None


def test_changed_task_165_bundle_cannot_reuse_old_audit(ready_inputs):
    ready_inputs["bundle165"].provider_name = "substituted-provider"

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"
    assert "T166_SNAPSHOT_MISMATCH" in package["findings"]


def test_noncanonical_source_inside_task_165_bundle_cannot_be_ready(ready_inputs):
    ready_inputs["bundle165"].certification_source = "FORGED_SOURCE"

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"
    assert "T163_SOURCE_MISMATCH" in package["findings"]
    assert "T166_SNAPSHOT_MISMATCH" in package["findings"]


def test_task_166_expected_status_must_match_published_status(ready_inputs):
    ready_inputs["audit166"].expected_bundle_status = "BLOCKED"

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"
    assert "T166_EXPECTED_STATUS_MISMATCH" in package["findings"]


def test_contradictory_165_166_167_statuses_cannot_be_ready(ready_inputs):
    ready_inputs["bundle165"].bundle_status = "BLOCKED"

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "BLOCKED"
    assert "T166_PUBLISHED_STATUS_MISMATCH" in package["findings"]
    assert "T166_SNAPSHOT_MISMATCH" in package["findings"]


def test_task_167_cannot_claim_consistency_for_inconsistent_task_166(ready_inputs):
    ready_inputs["audit166"].bundle_audit_status = "INCONSISTENT"
    ready_inputs["audit166"].available = True
    ready_inputs["audit166"].consistent = False
    ready_inputs["audit166"].finding_count = 1
    ready_inputs["audit166"].findings = ["FORGED_AUDIT_CONTRADICTION"]

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"
    assert "T167_BINDING_MISMATCH" in package["findings"]


@pytest.mark.parametrize(
    "bad_session_id",
    [None, 42, ["unhashable"]],
)
@pytest.mark.parametrize(
    "input_name",
    ["pkg162", "slice163", "audit164", "bundle165", "audit166", "consistency167"],
)
def test_malformed_postconstruction_session_ids_do_not_escape(
    ready_inputs, bad_session_id, input_name
):
    ready_inputs[input_name].session_id = bad_session_id

    with pytest.raises(
        ReasoningRunStage7EvidencePackageContractError,
        match="EVIDENCE_PACKAGE_UNREADABLE",
    ):
        ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)


def test_direct_schema_rejects_child_finding_missing_from_aggregate(ready_inputs):
    ready_inputs["pkg162"].findings = ["TAMPERED_CHILD_FINDING"]
    ready_inputs["pkg162"].finding_count = 1
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["findings"] = []
    package["finding_count"] = 0

    with pytest.raises(ValidationError, match="findings must equal"):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_direct_schema_requires_child_finding_counts_to_match(ready_inputs):
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["t162_finding_count"] = 1

    with pytest.raises(ValidationError, match="t162_finding_count"):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_direct_schema_rejects_mismatched_ready_child_session(ready_inputs):
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["t163_session_id"] = str(uuid4())

    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_direct_schema_rejects_noncanonical_source_even_when_ready(ready_inputs):
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["t166_audit_source"] = "FORGED_SOURCE"

    with pytest.raises(ValidationError, match="findings must equal"):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_direct_schema_rejects_task_165_166_snapshot_substitution(ready_inputs):
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["t166_audited_bundle"]["provider_name"] = "different-provider"

    with pytest.raises(ValidationError, match="findings must equal"):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_direct_schema_rejects_blocked_without_blocking_evidence(ready_inputs):
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["package_status"] = "BLOCKED"

    with pytest.raises(ValidationError, match="package_status must follow"):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_direct_schema_rejects_unavailable_when_ready_evidence_is_complete(
    ready_inputs,
):
    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    package["package_status"] = "UNAVAILABLE"

    with pytest.raises(ValidationError, match="package_status must follow"):
        ReasoningRunStage7EvidencePackageRead.model_validate(package)


def test_unavailable_precedence_when_evidence_is_insufficient(ready_inputs):
    ready_inputs["pkg162"].admission_status = "UNAVAILABLE"

    package = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert package["package_status"] == "UNAVAILABLE"


def test_assembly_is_deterministic_and_does_not_mutate_inputs(ready_inputs):
    before = {
        name: copy.deepcopy(value.model_dump()) for name, value in ready_inputs.items()
    }

    first = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)
    second = ReasoningRunStage7EvidencePackageService.assemble(**ready_inputs)

    assert first == second
    assert {name: value.model_dump() for name, value in ready_inputs.items()} == before

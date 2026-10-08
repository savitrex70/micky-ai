"""Task 168: canonical Stage 7 evidence package service.

Aggregation boundary over already-published and already-validated Stage 7
evidence: Task 162 Audit Package, Task 163 Vertical-Slice Verdict, Task
164 Vertical-Slice Audit, Task 165 Evidence Bundle, Task 166 Evidence-
Bundle Audit, and Task 167 Evidence-Bundle Audit Consistency.

The assembler preserves exact session identity only when all inputs agree,
preserves canonical sources, preserves all evidence verbatim, and maintains
sorted/deduplicated findings. The assembler adds an aggregate package status
(READY/BLOCKED/UNAVAILABLE) with BLOCKED precedence over READY and
UNAVAILABLE.

The assembler never calls any child service, never writes to a database,
never invokes a provider, and never recomputes a fingerprint.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168",
    "ReasoningRunStage7EvidencePackageContractError",
    "ReasoningRunStage7EvidencePackageService",
]


class ReasoningRunStage7EvidencePackageContractError(Exception):
    """Task 168: the evidence package cannot be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7EvidencePackageService:
    """Deterministic read-only assembly of one Stage 7 evidence package."""

    @staticmethod
    def assemble(
        *,
        pkg162: ReasoningRunStage7AuditPackageRead,
        slice163: ReasoningRunStage7VerticalSliceRead,
        audit164: ReasoningRunStage7VerticalSliceAuditRead,
        bundle165: ReasoningRunStage7EvidenceBundleRead,
        audit166: ReasoningRunStage7EvidenceBundleAuditRead,
        consistency167: ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
    ) -> dict[str, Any]:
        """Aggregate six already-published, already-validated pieces of material.

        ``READY`` only when all six inputs fully agree on every READY
        condition. ``BLOCKED`` when the validated evidence carries an
        approved blocking state. ``UNAVAILABLE`` for everything else,
        including session mismatches, missing sources, missing evidence,
        and any INCONSISTENT or UNAVAILABLE status.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A — Session binding
        ids = {
            pkg162.session_id,
            slice163.session_id,
            audit164.session_id,
            bundle165.session_id,
            audit166.session_id,
            consistency167.session_id,
        }
        if len(ids) == 1 and pkg162.session_id != "":
            session_id = pkg162.session_id
        else:
            findings.append("STAGE_7_SESSION_MISMATCH")
            session_id = ""

        # Step B — Aggregate findings from all inputs
        all_findings = (
            pkg162.findings
            + slice163.findings
            + audit164.findings
            + bundle165.bundle_findings
            + audit166.findings
            + consistency167.findings
        )
        findings.extend(all_findings)
        findings = sorted(set(findings))

        # Step C — Determine package status
        # BLOCKED takes precedence
        blocked = (
            pkg162.admission_status == "BLOCKED"
            or pkg162.diagnostics_status == "UNHEALTHY"
            or slice163.slice_status == "BLOCKED"
            or slice163.admission_status == "BLOCKED"
            or slice163.diagnostics_status == "UNHEALTHY"
            or bundle165.bundle_status == "BLOCKED"
        )

        # READY requires all inputs to be READY/CONSISTENT
        ready = (
            not findings
            and pkg162.admission_status == "ADMITTED"
            and pkg162.diagnostics_status == "HEALTHY"
            and pkg162.request_audit_status == "CONSISTENT"
            and pkg162.proposal_audit_status == "CONSISTENT"
            and slice163.slice_status == "READY"
            and slice163.admission_status == "ADMITTED"
            and slice163.diagnostics_status == "HEALTHY"
            and audit164.slice_audit_status == "CONSISTENT"
            and bundle165.bundle_status == "READY"
            and audit166.bundle_audit_status == "CONSISTENT"
            and consistency167.consistency_status == "CONSISTENT"
            and session_id != ""
        )

        # Priority: BLOCKED first, then READY, then UNAVAILABLE
        if blocked:
            package_status = "BLOCKED"
        elif ready:
            package_status = "READY"
        else:
            package_status = "UNAVAILABLE"

        # Step D — Populate result dict
        result: dict[str, Any] = {
            # Identity
            "session_id": session_id,
            # Task 162 evidence (verbatim)
            "t162_session_id": pkg162.session_id,
            "t162_admission_status": pkg162.admission_status,
            "t162_diagnostics_status": pkg162.diagnostics_status,
            "t162_request_fingerprint": pkg162.request_fingerprint,
            "t162_request_audit_status": pkg162.request_audit_status,
            "t162_proposal_audit_status": pkg162.proposal_audit_status,
            "t162_provider_name": pkg162.provider_name,
            "t162_model_name": pkg162.model_name,
            "t162_finding_count": pkg162.finding_count,
            "t162_findings": list(pkg162.findings),
            "t162_audit_source": pkg162.audit_source,
            # Task 163 evidence (verbatim)
            "t163_session_id": slice163.session_id,
            "t163_slice_status": slice163.slice_status,
            "t163_admission_status": slice163.admission_status,
            "t163_diagnostics_status": slice163.diagnostics_status,
            "t163_provider_name": slice163.provider_name,
            "t163_model_name": slice163.model_name,
            "t163_finding_count": slice163.finding_count,
            "t163_findings": list(slice163.findings),
            "t163_certification_source": slice163.certification_source,
            # Task 164 evidence (verbatim)
            "t164_session_id": audit164.session_id,
            "t164_slice_audit_status": audit164.slice_audit_status,
            "t164_available": audit164.available,
            "t164_consistent": audit164.consistent,
            "t164_published_slice_status": audit164.published_slice_status,
            "t164_expected_slice_status": audit164.expected_slice_status,
            "t164_finding_count": audit164.finding_count,
            "t164_findings": list(audit164.findings),
            "t164_audit_source": audit164.audit_source,
            # Task 165 evidence (verbatim)
            "t165_session_id": bundle165.session_id,
            "t165_bundle_status": bundle165.bundle_status,
            "t165_bundle_finding_count": bundle165.bundle_finding_count,
            "t165_bundle_findings": list(bundle165.bundle_findings),
            "t165_bundle_source": bundle165.bundle_source,
            # Task 166 evidence (verbatim)
            "t166_session_id": audit166.session_id,
            "t166_bundle_audit_status": audit166.bundle_audit_status,
            "t166_available": audit166.available,
            "t166_consistent": audit166.consistent,
            "t166_published_bundle_status": audit166.published_bundle_status,
            "t166_expected_bundle_status": audit166.expected_bundle_status,
            "t166_finding_count": audit166.finding_count,
            "t166_findings": list(audit166.findings),
            "t166_audit_source": audit166.audit_source,
            # Task 167 evidence (verbatim)
            "t167_session_id": consistency167.session_id,
            "t167_consistency_status": consistency167.consistency_status,
            "t167_available": consistency167.available,
            "t167_consistent": consistency167.consistent,
            "t167_finding_count": consistency167.finding_count,
            "t167_findings": list(consistency167.findings),
            "t167_consistency_source": consistency167.consistency_source,
            # Aggregate
            "package_status": package_status,
            "finding_count": len(findings),
            "findings": findings,
            "package_source": REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
        }

        # Step E — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidencePackageService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the assembled package through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidencePackageRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7EvidencePackageContractError(
                "EVIDENCE_PACKAGE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

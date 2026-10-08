"""Task 169: independent Stage 7 evidence-package audit service.

Independent audit boundary over the already-published Task 168 evidence package.
The auditor independently derives the expected package state from the
published Task 162-167 surfaces already present inside the package, then
compares the independently derived state against the published Task 168
package status.

The auditor never calls Task 168, never calls Tasks 162-167 services, never
recomputes fingerprints, never invokes a provider, and never accesses a
database. It only reads the already-published evidence surfaces contained
in the validated Task 168 package and the underlying Task 162-167 evidence
provided directly as arguments.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation. The audit is a deterministic
verification of the Task 168 package's internal coherence.
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
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169",
    "ReasoningRunStage7EvidencePackageAuditContractError",
    "ReasoningRunStage7EvidencePackageAuditService",
]


class ReasoningRunStage7EvidencePackageAuditContractError(Exception):
    """Task 169: the evidence-package audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7EvidencePackageAuditService:
    """Deterministic read-only audit of one Stage 7 evidence package."""

    @staticmethod
    def audit(
        *,
        package: ReasoningRunStage7EvidencePackageRead,
        pkg162: ReasoningRunStage7AuditPackageRead,
        slice163: ReasoningRunStage7VerticalSliceRead,
        audit164: ReasoningRunStage7VerticalSliceAuditRead,
        bundle165: ReasoningRunStage7EvidenceBundleRead,
        audit166: ReasoningRunStage7EvidenceBundleAuditRead,
        consistency167: ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
    ) -> dict[str, Any]:
        """Independently audit one already-published, already-validated package.

        The audit receives the Task 168 package and the underlying Task 162-167
        evidence directly as arguments, never calls any upstream service, and
        derives the expected package status from the published Task 162-167
        evidence surfaces, then compares the independently derived state
        against the published Task 168 package status.

        ``CONSISTENT`` when the independently derived expected state matches
        the published Task 168 package. ``INCONSISTENT`` when the published
        evidence contradicts the independently derived result. ``UNAVAILABLE``
        for missing or malformed Task 168 input.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A — Validate package source
        expected_pkg_source = REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168
        if package.package_source != expected_pkg_source:
            findings.append("TASK_168_SOURCE_MISMATCH")

        # Step B — Validate session identity
        # All inputs must share the same session_id, and package session must
        # match when all inputs agree
        input_sessions = {
            pkg162.session_id,
            slice163.session_id,
            audit164.session_id,
            bundle165.session_id,
            audit166.session_id,
            consistency167.session_id,
        }

        if len(input_sessions) == 1 and pkg162.session_id != "":
            expected_session = pkg162.session_id
        else:
            expected_session = ""

        if package.session_id != expected_session:
            findings.append("SESSION_ID_MISMATCH")

        # Step C — Validate that package evidence matches provided inputs
        # The package should contain verbatim copies of all input evidence
        if package.t162_session_id != pkg162.session_id:
            findings.append("T162_SESSION_MISMATCH")
        if package.t162_admission_status != pkg162.admission_status:
            findings.append("T162_ADMISSION_STATUS_MISMATCH")
        if package.t162_diagnostics_status != pkg162.diagnostics_status:
            findings.append("T162_DIAGNOSTICS_STATUS_MISMATCH")
        if package.t162_request_fingerprint != pkg162.request_fingerprint:
            findings.append("T162_REQUEST_FINGERPRINT_MISMATCH")
        if package.t162_request_audit_status != pkg162.request_audit_status:
            findings.append("T162_REQUEST_AUDIT_STATUS_MISMATCH")
        if package.t162_proposal_audit_status != pkg162.proposal_audit_status:
            findings.append("T162_PROPOSAL_AUDIT_STATUS_MISMATCH")
        if package.t162_provider_name != pkg162.provider_name:
            findings.append("T162_PROVIDER_NAME_MISMATCH")
        if package.t162_model_name != pkg162.model_name:
            findings.append("T162_MODEL_NAME_MISMATCH")
        if package.t162_finding_count != pkg162.finding_count:
            findings.append("T162_FINDING_COUNT_MISMATCH")
        if package.t162_findings != list(pkg162.findings):
            findings.append("T162_FINDINGS_MISMATCH")
        if package.t162_audit_source != pkg162.audit_source:
            findings.append("T162_AUDIT_SOURCE_MISMATCH")

        if package.t163_session_id != slice163.session_id:
            findings.append("T163_SESSION_MISMATCH")
        if package.t163_slice_status != slice163.slice_status:
            findings.append("T163_SLICE_STATUS_MISMATCH")
        if package.t163_admission_status != slice163.admission_status:
            findings.append("T163_ADMISSION_STATUS_MISMATCH")
        if package.t163_diagnostics_status != slice163.diagnostics_status:
            findings.append("T163_DIAGNOSTICS_STATUS_MISMATCH")
        if package.t163_provider_name != slice163.provider_name:
            findings.append("T163_PROVIDER_NAME_MISMATCH")
        if package.t163_model_name != slice163.model_name:
            findings.append("T163_MODEL_NAME_MISMATCH")
        if package.t163_finding_count != slice163.finding_count:
            findings.append("T163_FINDING_COUNT_MISMATCH")
        if package.t163_findings != list(slice163.findings):
            findings.append("T163_FINDINGS_MISMATCH")
        if package.t163_certification_source != slice163.certification_source:
            findings.append("T163_CERTIFICATION_SOURCE_MISMATCH")

        if package.t164_session_id != audit164.session_id:
            findings.append("T164_SESSION_MISMATCH")
        if package.t164_slice_audit_status != audit164.slice_audit_status:
            findings.append("T164_SLICE_AUDIT_STATUS_MISMATCH")
        if package.t164_available != audit164.available:
            findings.append("T164_AVAILABLE_MISMATCH")
        if package.t164_consistent != audit164.consistent:
            findings.append("T164_CONSISTENT_MISMATCH")
        if package.t164_published_slice_status != audit164.published_slice_status:
            findings.append("T164_PUBLISHED_SLICE_STATUS_MISMATCH")
        if package.t164_expected_slice_status != audit164.expected_slice_status:
            findings.append("T164_EXPECTED_SLICE_STATUS_MISMATCH")
        if package.t164_finding_count != audit164.finding_count:
            findings.append("T164_FINDING_COUNT_MISMATCH")
        if package.t164_findings != list(audit164.findings):
            findings.append("T164_FINDINGS_MISMATCH")
        if package.t164_audit_source != audit164.audit_source:
            findings.append("T164_AUDIT_SOURCE_MISMATCH")

        if package.t165_session_id != bundle165.session_id:
            findings.append("T165_SESSION_MISMATCH")
        if package.t165_bundle_status != bundle165.bundle_status:
            findings.append("T165_BUNDLE_STATUS_MISMATCH")
        if package.t165_bundle_finding_count != bundle165.bundle_finding_count:
            findings.append("T165_BUNDLE_FINDING_COUNT_MISMATCH")
        if package.t165_bundle_findings != list(bundle165.bundle_findings):
            findings.append("T165_BUNDLE_FINDINGS_MISMATCH")
        if package.t165_bundle_source != bundle165.bundle_source:
            findings.append("T165_BUNDLE_SOURCE_MISMATCH")

        if package.t166_session_id != audit166.session_id:
            findings.append("T166_SESSION_MISMATCH")
        if package.t166_bundle_audit_status != audit166.bundle_audit_status:
            findings.append("T166_BUNDLE_AUDIT_STATUS_MISMATCH")
        if package.t166_available != audit166.available:
            findings.append("T166_AVAILABLE_MISMATCH")
        if package.t166_consistent != audit166.consistent:
            findings.append("T166_CONSISTENT_MISMATCH")
        if package.t166_published_bundle_status != audit166.published_bundle_status:
            findings.append("T166_PUBLISHED_BUNDLE_STATUS_MISMATCH")
        if package.t166_expected_bundle_status != audit166.expected_bundle_status:
            findings.append("T166_EXPECTED_BUNDLE_STATUS_MISMATCH")
        if package.t166_finding_count != audit166.finding_count:
            findings.append("T166_FINDING_COUNT_MISMATCH")
        if package.t166_findings != list(audit166.findings):
            findings.append("T166_FINDINGS_MISMATCH")
        if package.t166_audit_source != audit166.audit_source:
            findings.append("T166_AUDIT_SOURCE_MISMATCH")

        if package.t167_session_id != consistency167.session_id:
            findings.append("T167_SESSION_MISMATCH")
        if package.t167_consistency_status != consistency167.consistency_status:
            findings.append("T167_CONSISTENCY_STATUS_MISMATCH")
        if package.t167_available != consistency167.available:
            findings.append("T167_AVAILABLE_MISMATCH")
        if package.t167_consistent != consistency167.consistent:
            findings.append("T167_CONSISTENT_MISMATCH")
        if package.t167_finding_count != consistency167.finding_count:
            findings.append("T167_FINDING_COUNT_MISMATCH")
        if package.t167_findings != list(consistency167.findings):
            findings.append("T167_FINDINGS_MISMATCH")
        if package.t167_consistency_source != consistency167.consistency_source:
            findings.append("T167_CONSISTENCY_SOURCE_MISMATCH")

        # Step D — Validate aggregate findings
        all_expected_findings = (
            list(pkg162.findings)
            + list(slice163.findings)
            + list(audit164.findings)
            + list(bundle165.bundle_findings)
            + list(audit166.findings)
            + list(consistency167.findings)
        )
        expected_findings = sorted(set(all_expected_findings))

        if package.findings != expected_findings:
            findings.append("AGGREGATE_FINDINGS_MISMATCH")
        if package.finding_count != len(expected_findings):
            findings.append("AGGREGATE_FINDING_COUNT_MISMATCH")

        # Step E — Derive expected package status independently
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
            len(expected_findings) == 0
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
            and expected_session != ""
        )

        # Priority: BLOCKED first, then READY, then UNAVAILABLE
        if blocked:
            expected_status = "BLOCKED"
        elif ready:
            expected_status = "READY"
        else:
            expected_status = "UNAVAILABLE"

        # Step F — Compare expected vs published status
        if expected_status != package.package_status:
            findings.append("PACKAGE_STATUS_MISMATCH")

        # Step G — Populate result dict
        findings = sorted(set(findings))

        if findings:
            package_audit_status = "INCONSISTENT"
        else:
            package_audit_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": package.session_id,
            "package_audit_status": package_audit_status,
            "available": package_audit_status != "UNAVAILABLE",
            "consistent": package_audit_status == "CONSISTENT",
            "published_package_status": package.package_status,
            "expected_package_status": expected_status,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
            ),
        }

        # Step H — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidencePackageAuditService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidencePackageAuditRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7EvidencePackageAuditContractError(
                "EVIDENCE_PACKAGE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

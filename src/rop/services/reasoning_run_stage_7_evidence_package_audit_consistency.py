"""Task 170: Stage 7 evidence-package audit consistency service.

Independent consistency boundary between Task 168 Evidence Package and
Task 169 Evidence-Package Audit. The service verifies exact binding of
session identity, package status, package source, evidence presence,
findings, finding counts, published versus expected status, audit source,
and audit status.

The service never calls Task 168 or Task 169 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database. It
only reads the already-published validated Pydantic objects.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170",
    "ReasoningRunStage7EvidencePackageAuditConsistencyContractError",
    "ReasoningRunStage7EvidencePackageAuditConsistencyService",
]


class ReasoningRunStage7EvidencePackageAuditConsistencyContractError(Exception):
    """Task 170: the package-audit consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7EvidencePackageAuditConsistencyService:
    """Deterministic read-only consistency check for package-audit binding."""

    @staticmethod
    def verify(
        *,
        package: ReasoningRunStage7EvidencePackageRead,
        audit: ReasoningRunStage7EvidencePackageAuditRead,
    ) -> dict[str, Any]:
        """Verify exact binding between package and audit.

        ``CONSISTENT`` when the audit is canonically bound to the exact
        Task 168 package represented. ``INCONSISTENT`` when the audit is
        detached or contradicts the package. ``UNAVAILABLE`` when either input
        is missing or fails its own contract.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        try:
            if not isinstance(package, ReasoningRunStage7EvidencePackageRead):
                raise TypeError("package has an unexpected model type")
            if not isinstance(audit, ReasoningRunStage7EvidencePackageAuditRead):
                raise TypeError("audit has an unexpected model type")
            package = ReasoningRunStage7EvidencePackageRead.model_validate(
                package.model_dump()
            )
            audit = ReasoningRunStage7EvidencePackageAuditRead.model_validate(
                audit.model_dump()
            )
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7EvidencePackageAuditConsistencyService._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": 1,
                    "findings": ["PACKAGE_OR_AUDIT_INVALID"],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
                    ),
                }
            )

        findings: list[str] = []

        # Step A — Session identity must match exactly
        if package.session_id != audit.session_id:
            findings.append("SESSION_MISMATCH")

        # Step B — Package source must be canonical Task 168 source
        expected_package_source = "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_TASK_168"
        if package.package_source != expected_package_source:
            findings.append("PACKAGE_SOURCE_MISMATCH")

        # Step C — Audit source must be canonical Task 169 source
        expected_audit_source = "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_TASK_169"
        if audit.audit_source != expected_audit_source:
            findings.append("AUDIT_SOURCE_MISMATCH")

        # Step D — Published package status must match audit's published status
        if package.package_status != audit.published_package_status:
            findings.append("PUBLISHED_STATUS_MISMATCH")

        # Step E — Expected package status must match audit's expected status
        # The audit independently derives expected status, and it should match
        # the actual package status if everything is consistent
        if package.package_status != audit.expected_package_status:
            findings.append("EXPECTED_STATUS_CONTRADICTION")

        # Step F — Audit status must be CONSISTENT for the binding to be valid
        # If the audit found inconsistencies, the binding is not valid
        if audit.package_audit_status != "CONSISTENT":
            findings.append("AUDIT_STATUS_NOT_CONSISTENT")

        # Findings describe different layers: Task 168 carries evidence
        # findings; Task 169 carries findings about package coherence. A
        # valid Task 169 audit must be finding-free when it claims consistency.
        if audit.package_audit_status == "CONSISTENT" and audit.findings:
            findings.append("AUDIT_FINDINGS_MISMATCH")
        if package.finding_count != len(package.findings):
            findings.append("FINDING_COUNT_MISMATCH")

        # Step I — Audit availability and consistency flags must align with
        # the published audit status (also revalidated above).
        if not audit.available:
            findings.append("AUDIT_UNAVAILABLE")
        if not audit.consistent:
            findings.append("AUDIT_INCONSISTENT")

        if package.session_id == "":
            findings.append("PACKAGE_SESSION_EMPTY")

        # Step L — Populate result dict
        findings = sorted(set(findings))
        if findings:
            consistency_status = "INCONSISTENT"
        else:
            consistency_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": (
                package.session_id if consistency_status != "UNAVAILABLE" else ""
            ),
            "consistency_status": consistency_status,
            "available": consistency_status != "UNAVAILABLE",
            "consistent": consistency_status == "CONSISTENT",
            "finding_count": len(findings),
            "findings": findings,
            "consistency_source": (
                REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
            ),
        }

        # Step M — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidencePackageAuditConsistencyService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
                    result
                )
            )
        except ValidationError as exc:
            raise ReasoningRunStage7EvidencePackageAuditConsistencyContractError(
                "PACKAGE_AUDIT_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

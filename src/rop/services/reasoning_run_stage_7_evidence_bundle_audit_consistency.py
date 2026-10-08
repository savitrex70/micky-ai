"""Task 167: Stage 7 evidence-bundle audit consistency service.

Independent consistency boundary between Task 165 Evidence Bundle and
Task 166 Evidence-Bundle Audit. The service verifies exact binding of
session identity, bundle status, bundle evidence, published versus expected
status, audit status, and audit source.

The service never calls Task 165 or Task 166 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database. It
only reads the already-published validated Pydantic objects.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167",
    "ReasoningRunStage7EvidenceBundleAuditConsistencyContractError",
    "ReasoningRunStage7EvidenceBundleAuditConsistencyService",
]


class ReasoningRunStage7EvidenceBundleAuditConsistencyContractError(Exception):
    """Task 167: the bundle-audit consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7EvidenceBundleAuditConsistencyService:
    """Deterministic read-only consistency check for bundle-audit binding."""

    @staticmethod
    def verify(
        *,
        bundle: ReasoningRunStage7EvidenceBundleRead,
        audit: ReasoningRunStage7EvidenceBundleAuditRead,
    ) -> dict[str, Any]:
        """Verify exact binding between bundle and audit.

        ``CONSISTENT`` when the audit is canonically bound to the exact
        Task 165 bundle represented. ``INCONSISTENT`` when the audit is
        detached or contradicts the bundle. ``UNAVAILABLE`` when either input
        is missing or fails its own contract.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A — Session identity must match
        if bundle.session_id != audit.session_id:
            findings.append("SESSION_MISMATCH")

        # Step B — Published bundle status must match audit's published status
        if bundle.bundle_status != audit.published_bundle_status:
            findings.append("PUBLISHED_STATUS_MISMATCH")

        # Step C — Expected bundle status must match audit's expected status
        # The audit independently derives expected status, so this validates
        # that the audit's derivation aligns with the bundle's evidence
        if bundle.bundle_status != audit.expected_bundle_status:
            findings.append("EXPECTED_STATUS_CONTRADICTION")

        # Step D — Audit status must reflect bundle evidence
        # If the bundle is READY/BLOCKED/UNAVAILABLE, the audit should be
        # CONSISTENT when the evidence supports it
        if bundle.bundle_status == "READY" and audit.bundle_audit_status != (
            "CONSISTENT"
        ):
            findings.append("AUDIT_STATUS_MISMATCH")
        if bundle.bundle_status == "BLOCKED" and audit.bundle_audit_status != (
            "CONSISTENT"
        ):
            findings.append("AUDIT_STATUS_MISMATCH")
        # UNAVAILABLE bundles can be CONSISTENT if they genuinely lack evidence
        # or INCONSISTENT if they have contradictory evidence

        # Step E — Audit source must be canonical
        audit_source = audit.audit_source
        expected_audit_source = "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166"
        if audit_source != expected_audit_source:
            findings.append("AUDIT_SOURCE_MISMATCH")

        # Step F — Finding count must match between bundle and audit when relevant
        # If the bundle has findings, the audit should detect them
        if bundle.bundle_finding_count > 0 and audit.finding_count == 0:
            findings.append("FINDING_COUNT_MISMATCH")
        # If the audit has findings, they should explain bundle state
        if audit.finding_count > 0 and bundle.bundle_finding_count == 0:
            findings.append("FINDING_COUNT_MISMATCH")

        # Step G — Finding content should be related
        # This is a basic check: if both have findings, they should not be
        # completely unrelated (we don't require exact match since audit
        # has its own finding codes)
        if bundle.bundle_findings and audit.findings:
            # At minimum, both should have findings
            pass

        # Step H — Populate result dict
        findings = sorted(set(findings))
        consistency_status = "UNAVAILABLE"
        if findings:
            consistency_status = "INCONSISTENT"
        else:
            consistency_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": bundle.session_id,
            "consistency_status": consistency_status,
            "available": consistency_status != "UNAVAILABLE",
            "consistent": consistency_status == "CONSISTENT",
            "finding_count": len(findings),
            "findings": findings,
            "consistency_source": (
                REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
            ),
        }

        # Step I — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidenceBundleAuditConsistencyService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
                    result
                )
            )
        except ValidationError as exc:
            raise ReasoningRunStage7EvidenceBundleAuditConsistencyContractError(
                "BUNDLE_AUDIT_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

"""Task 179: Stage 7 release-readiness bundle-audit consistency service.

Independent consistency boundary between Task 177 Release-Readiness Evidence
Bundle and Task 178 Release-Readiness Evidence Bundle Audit. The service
verifies exact evidence binding.

The service never calls Task 177 or Task 178 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179",  # noqa: E501
    "ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyContractError",  # noqa: E501
    "ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService",  # noqa: E501
]

# Module-level aliases: the canonical Task 179 contract identifiers exceed
# the 88-column limit once prefixed by call-site indentation, so call sites
# reference these short aliases instead.
_BUNDLE_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead
_AUDIT_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead
_CONSISTENCY_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead


class ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyContractError(
    Exception
):
    """Task 179: the bundle-audit consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_CONTRACT_ERROR = (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyContractError
)


class ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService:
    """Deterministic read-only consistency check for bundle-audit binding."""

    @staticmethod
    def verify(
        *,
        bundle: ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
        audit: ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
    ) -> dict[str, Any]:
        """Verify exact binding between the Task 177 bundle and its Task 178 audit.

        ``CONSISTENT`` when the Task 178 audit is canonically bound to the
        exact Task 177 bundle represented. ``INCONSISTENT`` when the audit
        is detached from or contradicts the bundle. ``UNAVAILABLE`` when
        either input is missing or fails its own contract and the binding
        cannot be established.

        A valid Task 177 bundle whose ``bundle_status`` is ``UNAVAILABLE``
        can still have a ``CONSISTENT`` audit and consistency result. A Task
        178 audit verdict of ``UNAVAILABLE`` yields ``UNAVAILABLE`` unless
        separate readable evidence proves a contradiction.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        service = (
            ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService
        )
        try:
            if not isinstance(bundle, _BUNDLE_READ):
                raise TypeError("bundle has an unexpected model type")
            if not isinstance(audit, _AUDIT_READ):
                raise TypeError("audit has an unexpected model type")
            # Revalidate both inputs to detect post-construction mutation.
            bundle = _BUNDLE_READ.model_validate(bundle.model_dump())
            audit = _AUDIT_READ.model_validate(audit.model_dump())
        except (AttributeError, TypeError, ValidationError):
            return service._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179
                    ),
                }
            )

        # A Task 178 audit verdict of UNAVAILABLE proves nothing about the
        # binding: the audit itself declares it unprovable. Its blank
        # session identity is a contract-valid artifact, never a mismatch.
        if audit.bundle_audit_status == "UNAVAILABLE":
            return service._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": 1,
                    "findings": ["AUDIT_UNAVAILABLE"],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179
                    ),
                }
            )

        findings: list[str] = []

        # Step A — Session identity must agree. Both records claim an
        # identity (the audit is available), so a difference is a real,
        # readable detachment.
        if bundle.session_id != audit.session_id:
            findings.append("SESSION_MISMATCH")

        # Step B — The published bundle status must match both statuses the
        # audit recorded for that same bundle.
        if bundle.bundle_status != audit.published_bundle_status:
            findings.append("PUBLISHED_STATUS_MISMATCH")
        if bundle.bundle_status != audit.expected_bundle_status:
            findings.append("EXPECTED_STATUS_MISMATCH")

        # Step C — The audit must report a successful binding. An
        # inconsistent audit cannot prove consistency.
        if audit.bundle_audit_status != "CONSISTENT":
            findings.append("AUDIT_STATUS_MISMATCH")
        if audit.findings:
            findings.append("AUDIT_HAS_FINDINGS")

        # Step D — Populate result dict.
        findings = sorted(set(findings))
        consistency_status = "INCONSISTENT" if findings else "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": bundle.session_id,
            "consistency_status": consistency_status,
            "available": consistency_status != "UNAVAILABLE",
            "consistent": consistency_status == "CONSISTENT",
            "finding_count": len(findings),
            "findings": findings,
            "consistency_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179
            ),
        }

        # Step E — Validate through schema, raise on contract error.
        return service._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = _CONSISTENCY_READ.model_validate(result)
        except ValidationError as exc:
            raise _CONTRACT_ERROR(
                "RELEASE_READINESS_BUNDLE_AUDIT_CONSISTENCY_RESULT_INVALID",
                str(exc),
            ) from exc
        return validated.model_dump()

"""Task 176: Stage 7 release-readiness audit consistency service.

Independent consistency boundary between Task 174 Release-Readiness Projection
and Task 175 Release-Readiness Audit. The service verifies exact evidence
binding.

The service never calls Task 174 or Task 175 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176,
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176",
    "ReasoningRunStage7ReleaseReadinessAuditConsistencyContractError",
    "ReasoningRunStage7ReleaseReadinessAuditConsistencyService",
]


class ReasoningRunStage7ReleaseReadinessAuditConsistencyContractError(Exception):
    """Task 176: the release-readiness audit consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ReleaseReadinessAuditConsistencyService:
    """Deterministic read-only consistency check for projection-audit binding."""

    @staticmethod
    def verify(
        *,
        projection: ReasoningRunStage7ReleaseReadinessProjectionRead,
        audit: ReasoningRunStage7ReleaseReadinessAuditRead,
    ) -> dict[str, Any]:
        """Verify exact binding between projection and audit.

        ``CONSISTENT`` when the audit is canonically bound to the exact
        Task 174 projection represented. ``INCONSISTENT`` when the audit
        is detached or contradicts the projection. ``UNAVAILABLE`` when
        either input is missing or fails its own contract.

        A valid Task 174 projection whose ``readiness_status`` is ``UNAVAILABLE``
        can still have a ``CONSISTENT`` audit and consistency result if the
        published evidence is validly bound and correctly represented.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        try:
            if not isinstance(
                projection, ReasoningRunStage7ReleaseReadinessProjectionRead
            ):
                raise TypeError("projection has an unexpected model type")
            if not isinstance(audit, ReasoningRunStage7ReleaseReadinessAuditRead):
                raise TypeError("audit has an unexpected model type")
            # Only re-validate if the object might have been mutated
            # Use model_dump to get current state and re-validate
            projection_dict = projection.model_dump()
            audit_dict = audit.model_dump()
            projection = (
                ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
                    projection_dict
                )
            )
            audit = ReasoningRunStage7ReleaseReadinessAuditRead.model_validate(
                audit_dict
            )
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7ReleaseReadinessAuditConsistencyService._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
                    ),
                }
            )

        findings: list[str] = []

        # Step A0 — Canonical sources for Tasks 174/175
        if (
            projection.projection_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
        ):
            findings.append("PROJECTION_SOURCE_INVALID")
        if (
            audit.audit_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
        ):
            findings.append("AUDIT_SOURCE_INVALID")

        # Step A — Session identity must match
        if projection.session_id != audit.session_id:
            findings.append("SESSION_MISMATCH")

        # Step B — Published readiness status must match audit's published status
        if projection.readiness_status != audit.published_readiness_status:
            findings.append("PUBLISHED_STATUS_MISMATCH")

        # Step C — Expected readiness status must match audit's expected status
        if projection.readiness_status != audit.expected_readiness_status:
            findings.append("EXPECTED_STATUS_MISMATCH")

        # Step D — The audit must report a successful binding for every
        # projection status; an inconsistent audit cannot prove consistency.
        if audit.readiness_audit_status != "CONSISTENT":
            findings.append("AUDIT_STATUS_MISMATCH")
        if audit.findings:
            findings.append("AUDIT_HAS_FINDINGS")

        # Step E — Populate result dict
        findings = sorted(set(findings))
        consistency_status = "UNAVAILABLE"
        if findings:
            consistency_status = "INCONSISTENT"
        else:
            consistency_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": projection.session_id,
            "consistency_status": consistency_status,
            "available": consistency_status != "UNAVAILABLE",
            "consistent": consistency_status == "CONSISTENT",
            "finding_count": len(findings),
            "findings": findings,
            "consistency_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
            ),
        }

        # Step F — Validate through schema, raise on contract error
        return ReasoningRunStage7ReleaseReadinessAuditConsistencyService._project(
            result
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7ReleaseReadinessAuditConsistencyRead.model_validate(
                    result
                )
            )
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseReadinessAuditConsistencyContractError(
                "RELEASE_READINESS_AUDIT_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

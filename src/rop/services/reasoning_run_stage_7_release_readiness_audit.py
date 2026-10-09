"""Task 175: independent Stage 7 release-readiness audit service.

Independent audit boundary over the already-published Task 174 release-readiness
projection. The auditor independently derives the expected readiness from the
published Task 171-173 evidence rather than trusting Task 174.

The auditor never calls Task 174, never calls Tasks 171-173 services, never
recomputes fingerprints, never invokes a provider, and never accesses a
database.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
    ReasoningRunStage7FinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_consistency import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173,
    ReasoningRunStage7FinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171,
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175",
    "ReasoningRunStage7ReleaseReadinessAuditContractError",
    "ReasoningRunStage7ReleaseReadinessAuditService",
]


class ReasoningRunStage7ReleaseReadinessAuditContractError(Exception):
    """Task 175: the release-readiness audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ReleaseReadinessAuditService:
    """Deterministic read-only audit of one Stage 7 release-readiness projection."""

    @staticmethod
    def audit(
        *,
        attestation: ReasoningRunStage7FinalEvidenceAttestationRead,
        audit: ReasoningRunStage7FinalAttestationAuditRead,
        consistency: ReasoningRunStage7FinalAttestationConsistencyRead,
        projection: dict[str, Any] | ReasoningRunStage7ReleaseReadinessProjectionRead,
    ) -> dict[str, Any]:
        """Independently audit one already-published, already-validated projection.

        The audit derives the expected readiness status from the published
        Task 171-173 evidence, then compares the independently derived state
        against the published Task 174 projection status.

        ``CONSISTENT`` when the independently derived expected state matches
        the published Task 174 projection. ``INCONSISTENT`` when the
        published evidence contradicts the independently derived result.
        ``UNAVAILABLE`` for missing or malformed Task 174 input.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A0 — Canonical sources for Tasks 171/172/173
        if (
            attestation.attestation_source
            != REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171
        ):
            findings.append("ATTESTATION_SOURCE_INVALID")
        if (
            audit.audit_source
            != REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172
        ):
            findings.append("AUDIT_SOURCE_INVALID")
        if (
            consistency.consistency_source
            != REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
        ):
            findings.append("CONSISTENCY_SOURCE_INVALID")

        # Step A — Derive expected readiness status independently
        # BLOCKED takes precedence
        blocked = (
            attestation.attestation_status == "BLOCKED"
            or audit.attestation_audit_status == "INCONSISTENT"
            or consistency.consistency_status == "INCONSISTENT"
        )

        # READY requires all conditions
        ready = (
            attestation.attestation_status == "CERTIFIED"
            and audit.attestation_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and attestation.session_id != ""
            and not attestation.findings
            and not audit.findings
            and not consistency.findings
        )

        if blocked:
            expected_status = "BLOCKED"
        elif ready:
            expected_status = "READY"
        else:
            expected_status = "UNAVAILABLE"

        # Step B — Convert projection to model if dict
        if isinstance(projection, dict):
            # Validate through schema to catch invariants
            try:
                projection_obj = (
                    ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
                        projection
                    )
                )
            except ValidationError:
                # If validation fails, treat as UNAVAILABLE
                projection_obj = None
                findings.append("PROJECTION_INVALID")
        else:
            projection_obj = projection

        if projection_obj is None:
            raw_status = (
                projection.get("readiness_status")
                if isinstance(projection, dict)
                else None
            )
            findings.append("PROJECTION_INVALID")
            if raw_status in ("READY", "BLOCKED", "UNAVAILABLE"):
                published_status = raw_status
                if raw_status != expected_status:
                    findings.append("READINESS_STATUS_MISMATCH")
                findings = sorted(set(findings))
                audit_status: str = "INCONSISTENT"
            else:
                published_status = "UNAVAILABLE"
                findings = sorted(set(findings))
                audit_status = "UNAVAILABLE"
            result: dict[str, Any] = {
                "session_id": attestation.session_id,
                "readiness_audit_status": audit_status,
                "available": audit_status != "UNAVAILABLE",
                "consistent": audit_status == "CONSISTENT",
                "published_readiness_status": published_status,
                "expected_readiness_status": expected_status,
                "finding_count": len(findings),
                "findings": findings,
                "audit_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
                ),
            }
            return ReasoningRunStage7ReleaseReadinessAuditService._project(result)

        # Step C — Validate session binding
        if (
            projection_obj.session_id != attestation.session_id
            or projection_obj.session_id != audit.session_id
            or projection_obj.session_id != consistency.session_id
        ):
            findings.append("SESSION_BINDING_MISMATCH")

        # Step D — Compare expected vs published status (expected was
        # independently derived in Step A; it is never recomputed here)
        if expected_status != projection_obj.readiness_status:
            findings.append("READINESS_STATUS_MISMATCH")

        # Step E — Validate findings coherence
        if projection_obj.finding_count != len(projection_obj.findings):
            findings.append("FINDINGS_MISMATCH")
        if len(set(projection_obj.findings)) != len(projection_obj.findings):
            findings.append("FINDINGS_MISMATCH")
        if projection_obj.findings != sorted(projection_obj.findings):
            findings.append("FINDINGS_MISMATCH")

        # Step E — Populate result dict
        findings = sorted(set(findings))
        readiness_audit_status = "UNAVAILABLE"
        if findings:
            readiness_audit_status = "INCONSISTENT"
        else:
            readiness_audit_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": projection_obj.session_id,
            "readiness_audit_status": readiness_audit_status,
            "available": readiness_audit_status != "UNAVAILABLE",
            "consistent": readiness_audit_status == "CONSISTENT",
            "published_readiness_status": projection_obj.readiness_status,
            "expected_readiness_status": expected_status,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
            ),
        }

        # Step F — Validate through schema, raise on contract error
        return ReasoningRunStage7ReleaseReadinessAuditService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = ReasoningRunStage7ReleaseReadinessAuditRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseReadinessAuditContractError(
                "RELEASE_READINESS_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

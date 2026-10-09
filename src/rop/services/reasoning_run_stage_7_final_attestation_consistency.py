"""Task 173: Stage 7 final attestation consistency service.

Independent consistency boundary between Task 171 Final Evidence Attestation
and Task 172 Final Attestation Audit. The service verifies exact evidence
binding.

The service never calls Task 171 or Task 172 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database.
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

__all__ = [
    "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173",
    "ReasoningRunStage7FinalAttestationConsistencyContractError",
    "ReasoningRunStage7FinalAttestationConsistencyService",
]


class ReasoningRunStage7FinalAttestationConsistencyContractError(Exception):
    """Task 173: the final-attestation consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7FinalAttestationConsistencyService:
    """Deterministic read-only consistency check for attestation-audit binding."""

    @staticmethod
    def verify(
        *,
        attestation: ReasoningRunStage7FinalEvidenceAttestationRead,
        audit: ReasoningRunStage7FinalAttestationAuditRead,
    ) -> dict[str, Any]:
        """Verify exact binding between attestation and audit.

        ``CONSISTENT`` when the audit is canonically bound to the exact
        Task 171 attestation represented. ``INCONSISTENT`` when the audit
        is detached or contradicts the attestation. ``UNAVAILABLE`` when
        either input is missing or fails its own contract.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A0 — Canonical sources for Tasks 171/172
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

        # Step A — Session identity must match
        if attestation.session_id != audit.session_id:
            findings.append("SESSION_MISMATCH")

        # Step B — Published attestation status must match audit's published status
        if attestation.attestation_status != audit.published_attestation_status:
            findings.append("PUBLISHED_STATUS_MISMATCH")

        # Step C — Expected attestation status must match audit's expected status
        if attestation.attestation_status != audit.expected_attestation_status:
            findings.append("EXPECTED_STATUS_MISMATCH")

        # Step D — Audit status must reflect attestation evidence
        if attestation.attestation_status == "CERTIFIED" and (
            audit.attestation_audit_status != "CONSISTENT"
        ):
            findings.append("AUDIT_STATUS_MISMATCH")
        if attestation.attestation_status == "BLOCKED" and (
            audit.attestation_audit_status != "CONSISTENT"
        ):
            findings.append("AUDIT_STATUS_MISMATCH")

        # Step E — Finding count must match
        if attestation.finding_count > 0 and audit.finding_count == 0:
            findings.append("FINDING_COUNT_MISMATCH")
        if audit.finding_count > 0 and attestation.finding_count == 0:
            findings.append("FINDING_COUNT_MISMATCH")

        # Step F — Populate result dict
        findings = sorted(set(findings))
        consistency_status = "UNAVAILABLE"
        if findings:
            consistency_status = "INCONSISTENT"
        else:
            consistency_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": attestation.session_id,
            "consistency_status": consistency_status,
            "available": consistency_status != "UNAVAILABLE",
            "consistent": consistency_status == "CONSISTENT",
            "finding_count": len(findings),
            "findings": findings,
            "consistency_source": (
                REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
            ),
        }

        # Step G — Validate through schema, raise on contract error
        return (
            ReasoningRunStage7FinalAttestationConsistencyService._project(result)
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7FinalAttestationConsistencyContractError(
                "FINAL_ATTESTATION_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

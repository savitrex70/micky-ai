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
        Task 171 attestation represented. ``INCONSISTENT`` when readable,
        contract-valid evidence demonstrates that the audit is detached or
        contradicts the attestation. ``UNAVAILABLE`` when either input is
        missing or fails its own contract, or when the Task 172 audit is
        itself ``UNAVAILABLE`` (for example because the published status is
        unknown): evidence that cannot be verified is not a contradiction.
        A valid Task 171 attestation whose own status is ``UNAVAILABLE`` is
        different from an unavailable audit and is still bound normally.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        try:
            if not isinstance(
                attestation, ReasoningRunStage7FinalEvidenceAttestationRead
            ):
                raise TypeError("attestation has an unexpected model type")
            if not isinstance(audit, ReasoningRunStage7FinalAttestationAuditRead):
                raise TypeError("audit has an unexpected model type")
            attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
                attestation.model_dump()
            )
            audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
                audit.model_dump()
            )
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7FinalAttestationConsistencyService._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
                    ),
                }
            )

        # Step 0 — An UNAVAILABLE Task 172 audit has established nothing to
        # bind against, so it is handled before any ordinary comparison. An
        # unknown published status (None) or a blank audit session is not a
        # proven contradiction and must not be escalated to INCONSISTENT.
        if audit.attestation_audit_status == "UNAVAILABLE":
            unavailable_findings = ["AUDIT_UNAVAILABLE"]
            if audit.published_attestation_status is None:
                unavailable_findings.append("PUBLISHED_STATUS_UNKNOWN")
            unavailable_findings = sorted(set(unavailable_findings))
            return ReasoningRunStage7FinalAttestationConsistencyService._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": len(unavailable_findings),
                    "findings": unavailable_findings,
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
                    ),
                }
            )

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
        # An unknown (None) published status is not a mismatch.
        if (
            audit.published_attestation_status is not None
            and attestation.attestation_status != audit.published_attestation_status
        ):
            findings.append("PUBLISHED_STATUS_MISMATCH")

        # Step C — Expected attestation status must match audit's expected status
        if attestation.attestation_status != audit.expected_attestation_status:
            findings.append("EXPECTED_STATUS_MISMATCH")

        # Step D — The audit must report a successful binding for every
        # attestation status; an inconsistent audit cannot prove consistency.
        if audit.attestation_audit_status != "CONSISTENT":
            findings.append("AUDIT_STATUS_MISMATCH")
        if audit.findings:
            findings.append("AUDIT_HAS_FINDINGS")

        # Task 171 findings and Task 172 audit findings describe different
        # layers; their counts are not expected to match.
        # Step E — Populate result dict
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
        return ReasoningRunStage7FinalAttestationConsistencyService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(result)
            )
        except ValidationError as exc:
            raise ReasoningRunStage7FinalAttestationConsistencyContractError(
                "FINAL_ATTESTATION_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

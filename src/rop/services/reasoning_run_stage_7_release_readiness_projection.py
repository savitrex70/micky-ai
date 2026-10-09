"""Task 174: Stage 7 release-readiness projection service.

Deterministic projection that answers whether the fully audited Stage 7
evidence is eligible to be considered release-ready. The projection never
releases, persists, executes, or invokes anything - it only projects
evidence.
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
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174",
    "ReasoningRunStage7ReleaseReadinessProjectionContractError",
    "ReasoningRunStage7ReleaseReadinessProjectionService",
]


class ReasoningRunStage7ReleaseReadinessProjectionContractError(Exception):
    """Task 174: the release-readiness projection cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ReleaseReadinessProjectionService:
    """Deterministic read-only projection of Stage 7 release readiness."""

    @staticmethod
    def project(
        *,
        attestation: ReasoningRunStage7FinalEvidenceAttestationRead,
        audit: ReasoningRunStage7FinalAttestationAuditRead,
        consistency: ReasoningRunStage7FinalAttestationConsistencyRead,
    ) -> dict[str, Any]:
        """Project whether the fully audited Stage 7 evidence is release-ready.

        ``READY`` when the fully audited Stage 7 evidence is eligible to be
        considered release-ready. ``BLOCKED`` when not eligible due to
        blocking evidence. ``UNAVAILABLE`` when evidence is insufficient
        but no blocking state exists.

        No release, persistence, execution, or invocation occurs. No child
        service is invoked, no fingerprint is recomputed, and no database is
        written.
        """
        try:
            if not isinstance(
                attestation, ReasoningRunStage7FinalEvidenceAttestationRead
            ):
                raise TypeError("attestation has an unexpected model type")
            if not isinstance(audit, ReasoningRunStage7FinalAttestationAuditRead):
                raise TypeError("audit has an unexpected model type")
            if not isinstance(
                consistency, ReasoningRunStage7FinalAttestationConsistencyRead
            ):
                raise TypeError("consistency has an unexpected model type")
            attestation = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
                attestation.model_dump()
            )
            audit = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
                audit.model_dump()
            )
            consistency = (
                ReasoningRunStage7FinalAttestationConsistencyRead.model_validate(
                    consistency.model_dump()
                )
            )
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7ReleaseReadinessProjectionService._project(
                {
                    "session_id": "",
                    "readiness_status": "UNAVAILABLE",
                    "attestation_status": "UNAVAILABLE",
                    "attestation_audit_status": "UNAVAILABLE",
                    "consistency_status": "UNAVAILABLE",
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "projection_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
                    ),
                }
            )

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

        # Step A — Session binding
        if (
            attestation.session_id != audit.session_id
            or attestation.session_id != consistency.session_id
        ):
            findings.append("SESSION_BINDING_MISMATCH")

        # Step B — Attestation must be CERTIFIED
        if attestation.attestation_status != "CERTIFIED":
            findings.append("ATTESTATION_NOT_CERTIFIED")
        if (
            attestation.attestation_status != audit.published_attestation_status
            or attestation.attestation_status != audit.expected_attestation_status
        ):
            findings.append("ATTESTATION_AUDIT_STATUS_MISMATCH")

        # Step C — Audit must be CONSISTENT
        if audit.attestation_audit_status != "CONSISTENT":
            findings.append("ATTESTATION_AUDIT_INCONSISTENT")
        if audit.findings:
            findings.append("ATTESTATION_AUDIT_HAS_FINDINGS")

        # Step D — Consistency must be CONSISTENT
        if consistency.consistency_status != "CONSISTENT":
            findings.append("CONSISTENCY_INCONSISTENT")
        if consistency.findings:
            findings.append("CONSISTENCY_HAS_FINDINGS")

        # Step E — Aggregate findings from all inputs
        all_findings = attestation.findings + audit.findings + consistency.findings
        if all_findings:
            findings.append("UNRESOLVED_FINDINGS_EXIST")

        # Step F — Determine readiness status
        # BLOCKED takes precedence
        blocked = (
            attestation.attestation_status == "BLOCKED"
            or audit.attestation_audit_status == "INCONSISTENT"
            or consistency.consistency_status == "INCONSISTENT"
        )

        # READY requires all conditions
        ready = (
            not findings
            and attestation.attestation_status == "CERTIFIED"
            and audit.attestation_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and attestation.session_id != ""
            and attestation.session_id == audit.session_id
            and attestation.session_id == consistency.session_id
            and attestation.attestation_status == audit.published_attestation_status
            and attestation.attestation_status == audit.expected_attestation_status
            and not attestation.findings
            and not audit.findings
            and not consistency.findings
        )

        if blocked:
            readiness_status = "BLOCKED"
        elif ready:
            readiness_status = "READY"
        else:
            readiness_status = "UNAVAILABLE"

        # Step G — Populate result dict
        findings = sorted(set(findings))
        result: dict[str, Any] = {
            "session_id": attestation.session_id,
            "readiness_status": readiness_status,
            "attestation_status": attestation.attestation_status,
            "attestation_audit_status": audit.attestation_audit_status,
            "consistency_status": consistency.consistency_status,
            "finding_count": len(findings),
            "findings": findings,
            "projection_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
            ),
        }

        # Step H — Validate through schema, raise on contract error
        return ReasoningRunStage7ReleaseReadinessProjectionService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the projection result through the strict contract."""
        try:
            validated = ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseReadinessProjectionContractError(
                "RELEASE_READINESS_PROJECTION_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

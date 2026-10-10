"""Task 183: deterministic Stage 7 final release-gate projection service.

This pure projection reads and validates only the published Task 180-182
records. It never invokes upstream services or performs release/I/O work.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183",
    "ReasoningRunStage7FinalReleaseGateProjectionContractError",
    "ReasoningRunStage7FinalReleaseGateProjectionService",
]

_ATTESTATION_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationRead
_AUDIT_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead
_CONSISTENCY_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead
_PROJECTION_READ = ReasoningRunStage7FinalReleaseGateProjectionRead
_T180_SOURCE = "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_TASK_180"
_T181_SOURCE = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_TASK_181"
)
_T182_SOURCE = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_TASK_182"
)


class ReasoningRunStage7FinalReleaseGateProjectionContractError(Exception):
    """Task 183: the final release-gate projection violates its read contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7FinalReleaseGateProjectionService:
    """Deterministic, read-only projection over the published Task 180-182 chain."""

    @staticmethod
    def project(
        *,
        attestation: _ATTESTATION_READ,
        audit: _AUDIT_READ,
        consistency: _CONSISTENCY_READ,
    ) -> dict[str, Any]:
        """Project READY, BLOCKED, or UNAVAILABLE from published evidence only."""
        try:
            if not isinstance(attestation, _ATTESTATION_READ):
                raise TypeError("attestation has an unexpected model type")
            if not isinstance(audit, _AUDIT_READ):
                raise TypeError("audit has an unexpected model type")
            if not isinstance(consistency, _CONSISTENCY_READ):
                raise TypeError("consistency has an unexpected model type")
            attestation = _ATTESTATION_READ.model_validate(attestation.model_dump())
            audit = _AUDIT_READ.model_validate(audit.model_dump())
            consistency = _CONSISTENCY_READ.model_validate(consistency.model_dump())
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7FinalReleaseGateProjectionService._project(
                {
                    "session_id": "",
                    "gate_status": "UNAVAILABLE",
                    "attestation_status": "UNAVAILABLE",
                    "attestation_audit_status": "UNAVAILABLE",
                    "consistency_status": "UNAVAILABLE",
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "projection_source": (
                        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
                    ),
                }
            )

        findings: list[str] = []

        if attestation.attestation_source != _T180_SOURCE:
            findings.append("ATTESTATION_SOURCE_INVALID")
        if audit.audit_source != _T181_SOURCE:
            findings.append("AUDIT_SOURCE_INVALID")
        if consistency.consistency_source != _T182_SOURCE:
            findings.append("CONSISTENCY_SOURCE_INVALID")

        if attestation.session_id != audit.session_id or (
            consistency.attestation_consistency_status != "UNAVAILABLE"
            and attestation.session_id != consistency.session_id
        ):
            findings.append("SESSION_BINDING_MISMATCH")

        if attestation.attestation_status != "CERTIFIED":
            findings.append("ATTESTATION_NOT_CERTIFIED")
        if (
            attestation.attestation_status != audit.published_attestation_status
            or attestation.attestation_status != audit.expected_attestation_status
        ):
            findings.append("ATTESTATION_AUDIT_STATUS_MISMATCH")
        if audit.attestation_audit_status != "CONSISTENT":
            findings.append("ATTESTATION_AUDIT_NOT_CONSISTENT")
        if audit.findings:
            findings.append("ATTESTATION_AUDIT_HAS_FINDINGS")

        if (
            consistency.published_attestation_status is not None
            and consistency.published_attestation_status
            != attestation.attestation_status
        ) or (
            consistency.expected_attestation_status != attestation.attestation_status
        ):
            findings.append("ATTESTATION_CONSISTENCY_STATUS_MISMATCH")
        if consistency.attestation_consistency_status != "CONSISTENT":
            findings.append("ATTESTATION_CONSISTENCY_NOT_CONSISTENT")
        if consistency.findings:
            findings.append("ATTESTATION_CONSISTENCY_HAS_FINDINGS")

        if attestation.findings or audit.findings or consistency.findings:
            findings.append("UNRESOLVED_FINDINGS_EXIST")

        blocking = (
            attestation.attestation_status == "BLOCKED"
            or audit.attestation_audit_status == "INCONSISTENT"
            or consistency.attestation_consistency_status == "INCONSISTENT"
        )
        ready = (
            not findings
            and attestation.session_id != ""
            and attestation.session_id == audit.session_id
            and attestation.session_id == consistency.session_id
            and attestation.attestation_status == "CERTIFIED"
            and audit.attestation_audit_status == "CONSISTENT"
            and consistency.attestation_consistency_status == "CONSISTENT"
            and audit.published_attestation_status == attestation.attestation_status
            and audit.expected_attestation_status == attestation.attestation_status
            and consistency.published_attestation_status
            == attestation.attestation_status
            and consistency.expected_attestation_status
            == attestation.attestation_status
            and not attestation.findings
            and not audit.findings
            and not consistency.findings
        )
        if blocking:
            gate_status = "BLOCKED"
        elif ready:
            gate_status = "READY"
        else:
            gate_status = "UNAVAILABLE"

        findings = sorted(set(findings))
        return ReasoningRunStage7FinalReleaseGateProjectionService._project(
            {
                "session_id": attestation.session_id,
                "gate_status": gate_status,
                "attestation_status": attestation.attestation_status,
                "attestation_audit_status": audit.attestation_audit_status,
                "consistency_status": consistency.attestation_consistency_status,
                "finding_count": len(findings),
                "findings": findings,
                "projection_source": (
                    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the projected result against the strict Task 183 contract."""
        try:
            validated = _PROJECTION_READ.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7FinalReleaseGateProjectionContractError(
                "FINAL_RELEASE_GATE_PROJECTION_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

"""Task 182: consistency verification for the final readiness attestation."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180,
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181,
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182,
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182",
    "ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyContractError",
    "ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService",
]

_ATTESTATION_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationRead
_AUDIT_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead
_CONSISTENCY_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead
_ATTESTATION_STATUSES = {"CERTIFIED", "BLOCKED", "UNAVAILABLE"}


class ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyContractError(
    Exception
):
    """Task 182 consistency result violates its read contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_CONTRACT_ERROR = (
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyContractError
)


class ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService:
    """Verify exact binding between Task 180's attestation and Task 181's audit."""

    @staticmethod
    def verify(
        *,
        attestation: dict[str, Any] | _ATTESTATION_READ,
        audit: _AUDIT_READ,
    ) -> dict[str, Any]:
        """Return a deterministic consistency verdict without invoking services.

        A valid Task 180 ``UNAVAILABLE`` result can be consistently audited.
        A Task 181 audit with status ``UNAVAILABLE`` cannot establish the
        binding; however, known and conflicting published/expected statuses
        remain demonstrable contradictions.
        """
        service = ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService
        raw_attestation = (
            attestation.model_dump()
            if isinstance(attestation, _ATTESTATION_READ)
            else attestation
        )
        published_status = None
        raw_status = (
            raw_attestation.get("attestation_status")
            if isinstance(raw_attestation, dict)
            else None
        )
        if isinstance(raw_status, str) and raw_status in _ATTESTATION_STATUSES:
            published_status = raw_status

        attestation_read = None
        try:
            if not isinstance(raw_attestation, dict):
                raise TypeError("attestation must be a read model or dictionary")
            attestation_read = _ATTESTATION_READ.model_validate(raw_attestation)
        except (TypeError, ValidationError):
            pass

        try:
            if not isinstance(audit, _AUDIT_READ):
                raise TypeError("audit has an unexpected model type")
            audit_read = _AUDIT_READ.model_validate(audit.model_dump())
        except (AttributeError, TypeError, ValidationError):
            return service._project(
                {
                    "session_id": "",
                    "attestation_consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_attestation_status": published_status,
                    "expected_attestation_status": "UNAVAILABLE",
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182
                    ),
                }
            )

        findings: list[str] = []
        contradiction = False

        if (
            audit_read.audit_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181  # noqa: E501
        ):
            findings.append("AUDIT_SOURCE_INVALID")
            contradiction = True

        raw_source = (
            raw_attestation.get("attestation_source")
            if isinstance(raw_attestation, dict)
            else None
        )
        if (
            raw_source is not None
            and raw_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
        ):
            findings.append("ATTESTATION_SOURCE_INVALID")
            contradiction = True

        if attestation_read is None:
            findings.append("ATTESTATION_INVALID")
        elif attestation_read.session_id and audit_read.session_id:
            if attestation_read.session_id != audit_read.session_id:
                findings.append("SESSION_MISMATCH")
                contradiction = True

        if published_status is None:
            findings.append("ATTESTATION_INVALID")
        else:
            if audit_read.published_attestation_status is not None and (
                published_status != audit_read.published_attestation_status
            ):
                findings.append("PUBLISHED_STATUS_MISMATCH")
                contradiction = True
            if published_status != audit_read.expected_attestation_status:
                findings.append("EXPECTED_STATUS_MISMATCH")
                contradiction = True

        if audit_read.attestation_audit_status == "INCONSISTENT":
            findings.append("AUDIT_INCONSISTENT")
            contradiction = True
        elif audit_read.attestation_audit_status == "UNAVAILABLE":
            findings.append("AUDIT_UNAVAILABLE")
        elif audit_read.findings:
            findings.append("AUDIT_HAS_FINDINGS")
            contradiction = True

        if attestation_read is None and published_status is None:
            verdict = "UNAVAILABLE"
        elif contradiction:
            verdict = "INCONSISTENT"
        elif (
            attestation_read is not None
            and audit_read.attestation_audit_status == "CONSISTENT"
            and attestation_read.session_id
            and audit_read.session_id
            and not findings
        ):
            verdict = "CONSISTENT"
        else:
            verdict = "UNAVAILABLE"

        findings = sorted(set(findings))
        if verdict == "UNAVAILABLE":
            session_id = ""
            if not findings:
                findings = ["BINDING_UNAVAILABLE"]
        else:
            session_id = attestation_read.session_id if attestation_read else ""

        return service._project(
            {
                "session_id": session_id,
                "attestation_consistency_status": verdict,
                "available": verdict != "UNAVAILABLE",
                "consistent": verdict == "CONSISTENT",
                "published_attestation_status": published_status,
                "expected_attestation_status": audit_read.expected_attestation_status,
                "finding_count": len(findings),
                "findings": findings,
                "consistency_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = _CONSISTENCY_READ.model_validate(result)
        except ValidationError as exc:
            raise _CONTRACT_ERROR(
                "RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_RESULT_INVALID",
                str(exc),
            ) from exc
        return validated.model_dump()

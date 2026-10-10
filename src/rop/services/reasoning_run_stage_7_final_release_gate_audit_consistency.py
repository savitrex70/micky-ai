"""Task 185: consistency verification for the final release-gate audit."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185,
    ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185",
    "ReasoningRunStage7FinalReleaseGateAuditConsistencyContractError",
    "ReasoningRunStage7FinalReleaseGateAuditConsistencyService",
]

_PROJECTION_READ = ReasoningRunStage7FinalReleaseGateProjectionRead
_AUDIT_READ = ReasoningRunStage7FinalReleaseGateAuditRead
_CONSISTENCY_READ = ReasoningRunStage7FinalReleaseGateAuditConsistencyRead
_GATE_STATUSES = {"READY", "BLOCKED", "UNAVAILABLE"}


def _revalidate_or_recover_semantic_conflict(model_type: Any, value: Any) -> Any:
    """Revalidate input while retaining readable root-level contradictions."""
    payload = value.model_dump()
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        if all(not error["loc"] for error in exc.errors()):
            return model_type.model_construct(**payload)
        raise


class ReasoningRunStage7FinalReleaseGateAuditConsistencyContractError(Exception):
    """Task 185 result violates its strict consistency contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7FinalReleaseGateAuditConsistencyService:
    """Deterministic, read-only binding check for projection and audit records."""

    @staticmethod
    def verify(
        *,
        projection: _PROJECTION_READ,
        audit: _AUDIT_READ,
    ) -> dict[str, Any]:
        """Compare published gate evidence without invoking other services.

        An unavailable projection may still be correctly bound when the
        independent audit establishes the same gate status and session.
        An unavailable audit cannot establish binding. Its readable published
        and expected gate statuses may nevertheless prove a contradiction.
        Empty identities from unavailable records are never treated as
        mismatches.
        """
        service = ReasoningRunStage7FinalReleaseGateAuditConsistencyService
        projection_payload = (
            projection.model_dump() if isinstance(projection, _PROJECTION_READ) else {}
        )
        audit_payload = audit.model_dump() if isinstance(audit, _AUDIT_READ) else {}
        raw_published = projection_payload.get("gate_status")
        published_status = (
            raw_published
            if isinstance(raw_published, str) and raw_published in _GATE_STATUSES
            else None
        )
        raw_expected = audit_payload.get("expected_gate_status")
        expected_status = (
            raw_expected
            if isinstance(raw_expected, str) and raw_expected in _GATE_STATUSES
            else "UNAVAILABLE"
        )
        try:
            if not isinstance(projection, _PROJECTION_READ):
                raise TypeError("projection has an unexpected model type")
            if not isinstance(audit, _AUDIT_READ):
                raise TypeError("audit has an unexpected model type")
            projection = _revalidate_or_recover_semantic_conflict(
                _PROJECTION_READ, projection
            )
            audit = _revalidate_or_recover_semantic_conflict(_AUDIT_READ, audit)
        except (AttributeError, TypeError, ValidationError):
            findings = ["EVIDENCE_INPUT_INVALID"]
            if published_status is None:
                findings.append("PROJECTION_INVALID")
            findings = sorted(set(findings))
            return service._project(
                {
                    "session_id": "",
                    "gate_consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_gate_status": published_status,
                    "expected_gate_status": expected_status,
                    "finding_count": len(findings),
                    "findings": findings,
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
                    ),
                }
            )

        findings: list[str] = []
        contradiction = False

        if (
            projection.projection_source
            != REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
        ):
            findings.append("PROJECTION_SOURCE_INVALID")
            contradiction = True
        if (
            audit.audit_source
            != REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184
        ):
            findings.append("AUDIT_SOURCE_INVALID")
            contradiction = True

        if service._projection_invariant_invalid(projection):
            findings.append("PROJECTION_INVARIANT_INVALID")
            contradiction = True
        if service._audit_invariant_invalid(audit):
            findings.append("AUDIT_INVARIANT_INVALID")
            contradiction = True

        if audit.published_gate_status is not None:
            if projection.gate_status != audit.published_gate_status:
                findings.append("PUBLISHED_STATUS_MISMATCH")
                contradiction = True
        if projection.gate_status != audit.expected_gate_status:
            findings.append("EXPECTED_STATUS_MISMATCH")
            contradiction = True
        if (
            audit.published_gate_status is not None
            and audit.published_gate_status != audit.expected_gate_status
        ):
            findings.append("AUDIT_STATUS_MISMATCH")
            contradiction = True

        audit_unavailable = audit.gate_audit_status == "UNAVAILABLE"
        if audit_unavailable:
            findings.append("AUDIT_UNAVAILABLE")
        else:
            if (
                projection.session_id
                and audit.session_id
                and projection.session_id != audit.session_id
            ):
                findings.append("SESSION_MISMATCH")
                contradiction = True
            if audit.gate_audit_status == "INCONSISTENT":
                findings.append("AUDIT_INCONSISTENT")
                contradiction = True
            elif audit.findings:
                findings.append("AUDIT_HAS_FINDINGS")
                contradiction = True

        findings = sorted(set(findings))
        if contradiction:
            status = "INCONSISTENT"
            session_id = projection.session_id or (
                audit.session_id if not audit_unavailable else ""
            )
        elif audit_unavailable:
            status = "UNAVAILABLE"
            session_id = ""
        elif not projection.session_id or not audit.session_id:
            status = "UNAVAILABLE"
            session_id = ""
            findings.append("SESSION_BINDING_UNPROVABLE")
            findings = sorted(set(findings))
        else:
            status = "CONSISTENT"
            session_id = projection.session_id

        if status == "UNAVAILABLE" and not findings:
            findings = ["BINDING_UNAVAILABLE"]

        return service._project(
            {
                "session_id": session_id,
                "gate_consistency_status": status,
                "available": status != "UNAVAILABLE",
                "consistent": status == "CONSISTENT",
                "published_gate_status": projection.gate_status,
                "expected_gate_status": audit.expected_gate_status,
                "finding_count": len(findings),
                "findings": findings,
                "consistency_source": (
                    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = _CONSISTENCY_READ.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7FinalReleaseGateAuditConsistencyContractError(
                "FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _valid_findings(count: int, findings: list[str]) -> bool:
        return (
            count == len(findings)
            and len(set(findings)) == len(findings)
            and findings == sorted(findings)
        )

    @staticmethod
    def _projection_invariant_invalid(
        projection: ReasoningRunStage7FinalReleaseGateProjectionRead,
    ) -> bool:
        service = ReasoningRunStage7FinalReleaseGateAuditConsistencyService
        if not service._valid_findings(projection.finding_count, projection.findings):
            return True
        blocking = (
            projection.attestation_status == "BLOCKED"
            or projection.attestation_audit_status == "INCONSISTENT"
            or projection.consistency_status == "INCONSISTENT"
        )
        if projection.gate_status == "READY":
            return (
                not projection.session_id
                or projection.attestation_status != "CERTIFIED"
                or projection.attestation_audit_status != "CONSISTENT"
                or projection.consistency_status != "CONSISTENT"
                or bool(projection.findings)
            )
        if projection.gate_status == "BLOCKED":
            return not blocking
        return not projection.findings or blocking

    @staticmethod
    def _audit_invariant_invalid(
        audit: ReasoningRunStage7FinalReleaseGateAuditRead,
    ) -> bool:
        service = ReasoningRunStage7FinalReleaseGateAuditConsistencyService
        if audit.available != (audit.gate_audit_status != "UNAVAILABLE"):
            return True
        if audit.consistent != (audit.gate_audit_status == "CONSISTENT"):
            return True
        if not service._valid_findings(audit.finding_count, audit.findings):
            return True
        if audit.published_gate_status is None:
            return (
                audit.gate_audit_status != "UNAVAILABLE"
                or "PROJECTION_INVALID" not in audit.findings
            )
        if audit.gate_audit_status == "UNAVAILABLE":
            return bool(audit.session_id) or not audit.findings
        if audit.gate_audit_status == "CONSISTENT":
            return (
                not audit.session_id
                or audit.published_gate_status != audit.expected_gate_status
                or bool(audit.findings)
            )
        return not audit.findings

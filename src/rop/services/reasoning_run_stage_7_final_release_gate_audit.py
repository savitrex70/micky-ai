"""Task 184: deterministic independent audit of the Task 183 final release gate."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
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
    "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184",
    "ReasoningRunStage7FinalReleaseGateAuditContractError",
    "ReasoningRunStage7FinalReleaseGateAuditService",
]

_ATTESTATION = ReasoningRunStage7ReleaseReadinessFinalAttestationRead
_UPSTREAM_AUDIT = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead
_CONSISTENCY = ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead
_PROJECTION = ReasoningRunStage7FinalReleaseGateProjectionRead
_AUDIT_RESULT = ReasoningRunStage7FinalReleaseGateAuditRead
_GATE_STATUSES = {"READY", "BLOCKED", "UNAVAILABLE"}
_T180_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
_T181_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
)
_T182_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182  # noqa: E501


def _revalidate_or_recover_semantic_conflict(model_type: Any, value: Any) -> Any:
    """Recover root-level coherence contradictions for explicit audit reporting."""
    payload = value.model_dump()
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        if all(not error["loc"] for error in exc.errors()):
            return model_type.model_construct(**payload)
        raise


class ReasoningRunStage7FinalReleaseGateAuditContractError(Exception):
    """Task 184: the final release-gate audit violates its read contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7FinalReleaseGateAuditService:
    """Pure audit of the published Task 183 gate and its Task 180-182 inputs."""

    @staticmethod
    def audit(
        *,
        attestation: _ATTESTATION,
        audit: _UPSTREAM_AUDIT,
        consistency: _CONSISTENCY,
        projection: dict[str, Any] | _PROJECTION,
    ) -> dict[str, Any]:
        """Derive the expected gate independently and compare the published record."""
        service = ReasoningRunStage7FinalReleaseGateAuditService
        raw_projection = (
            projection.model_dump()
            if isinstance(projection, _PROJECTION)
            else projection
        )
        projection_obj = None
        published_status = None
        if isinstance(raw_projection, dict):
            raw_status = raw_projection.get("gate_status")
            if isinstance(raw_status, str) and raw_status in _GATE_STATUSES:
                published_status = raw_status
            try:
                projection_obj = _PROJECTION.model_validate(raw_projection)
            except ValidationError as exc:
                if all(not error["loc"] for error in exc.errors()):
                    projection_obj = _PROJECTION.model_construct(**raw_projection)

        try:
            if not isinstance(attestation, _ATTESTATION):
                raise TypeError("attestation has an unexpected model type")
            if not isinstance(audit, _UPSTREAM_AUDIT):
                raise TypeError("audit has an unexpected model type")
            if not isinstance(consistency, _CONSISTENCY):
                raise TypeError("consistency has an unexpected model type")
            attestation = _revalidate_or_recover_semantic_conflict(
                _ATTESTATION, attestation
            )
            audit = _revalidate_or_recover_semantic_conflict(_UPSTREAM_AUDIT, audit)
            consistency = _revalidate_or_recover_semantic_conflict(
                _CONSISTENCY, consistency
            )
        except (AttributeError, TypeError, ValidationError):
            findings = ["EVIDENCE_INPUT_INVALID"]
            if projection_obj is None:
                findings.append("PROJECTION_INVALID")
            return service._project(
                {
                    "session_id": "",
                    "gate_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_gate_status": published_status,
                    "expected_gate_status": "UNAVAILABLE",
                    "finding_count": len(findings),
                    "findings": sorted(set(findings)),
                    "audit_source": (
                        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184
                    ),
                }
            )

        findings: list[str] = []

        if not isinstance(raw_projection, dict) or projection_obj is None:
            findings.append("PROJECTION_INVALID")
        if attestation.attestation_source != _T180_SOURCE:
            findings.append("ATTESTATION_SOURCE_INVALID")
        if audit.audit_source != _T181_SOURCE:
            findings.append("AUDIT_SOURCE_INVALID")
        if consistency.consistency_source != _T182_SOURCE:
            findings.append("CONSISTENCY_SOURCE_INVALID")

        if service._attestation_invariant_invalid(attestation):
            findings.append("ATTESTATION_INVARIANT_INVALID")
        if service._audit_invariant_invalid(audit):
            findings.append("AUDIT_INVARIANT_INVALID")
        if service._consistency_invariant_invalid(consistency):
            findings.append("CONSISTENCY_INVARIANT_INVALID")

        blocking = (
            attestation.attestation_status == "BLOCKED"
            or audit.attestation_audit_status == "INCONSISTENT"
            or consistency.attestation_consistency_status == "INCONSISTENT"
        )
        ready = (
            attestation.attestation_status == "CERTIFIED"
            and audit.attestation_audit_status == "CONSISTENT"
            and consistency.attestation_consistency_status == "CONSISTENT"
            and attestation.session_id != ""
            and attestation.session_id == audit.session_id
            and attestation.session_id == consistency.session_id
            and attestation.attestation_status == audit.published_attestation_status
            and attestation.attestation_status == audit.expected_attestation_status
            and attestation.attestation_status
            == consistency.published_attestation_status
            and attestation.attestation_status
            == consistency.expected_attestation_status
            and not attestation.findings
            and not audit.findings
            and not consistency.findings
            and attestation.attestation_source == _T180_SOURCE
            and audit.audit_source == _T181_SOURCE
            and consistency.consistency_source == _T182_SOURCE
        )
        if blocking:
            expected_status = "BLOCKED"
        elif ready:
            expected_status = "READY"
        else:
            expected_status = "UNAVAILABLE"

        if (
            attestation.attestation_status != audit.published_attestation_status
            or attestation.attestation_status != audit.expected_attestation_status
            or (
                consistency.published_attestation_status is not None
                and attestation.attestation_status
                != consistency.published_attestation_status
            )
            or attestation.attestation_status != consistency.expected_attestation_status
        ):
            findings.append("UPSTREAM_STATUS_MISMATCH")

        if projection_obj is not None:
            if projection_obj.projection_source != (
                REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
            ):
                findings.append("PROJECTION_SOURCE_INVALID")
            if service._projection_invariant_invalid(projection_obj):
                findings.append("PROJECTION_INVARIANT_INVALID")
            if published_status != expected_status:
                findings.append("GATE_STATUS_MISMATCH")
            if (
                projection_obj.attestation_status != attestation.attestation_status
                or projection_obj.attestation_audit_status
                != audit.attestation_audit_status
                or projection_obj.consistency_status
                != consistency.attestation_consistency_status
            ):
                findings.append("UPSTREAM_STATUS_MISMATCH")

            identities = [attestation.session_id]
            if audit.attestation_audit_status != "UNAVAILABLE":
                identities.append(audit.session_id)
            if consistency.attestation_consistency_status != "UNAVAILABLE":
                identities.append(consistency.session_id)
            if attestation.session_id and any(
                identity and identity != attestation.session_id
                for identity in identities
            ):
                findings.append("SESSION_BINDING_MISMATCH")
            if (
                projection_obj.session_id
                and attestation.session_id
                and projection_obj.session_id != attestation.session_id
            ):
                findings.append("SESSION_BINDING_MISMATCH")
            if (
                audit.attestation_audit_status != "UNAVAILABLE"
                and audit.session_id
                and projection_obj.session_id != audit.session_id
            ):
                findings.append("SESSION_BINDING_MISMATCH")
            if (
                consistency.attestation_consistency_status != "UNAVAILABLE"
                and consistency.session_id
                and projection_obj.session_id != consistency.session_id
            ):
                findings.append("SESSION_BINDING_MISMATCH")
        elif published_status is not None and published_status != expected_status:
            findings.append("GATE_STATUS_MISMATCH")

        findings = sorted(set(findings))
        unknown_published_status = published_status is None
        upstream_unavailable = (
            audit.attestation_audit_status == "UNAVAILABLE"
            or consistency.attestation_consistency_status == "UNAVAILABLE"
        )
        if unknown_published_status:
            gate_audit_status = "UNAVAILABLE"
            if "PROJECTION_INVALID" not in findings:
                findings.append("PROJECTION_INVALID")
            findings = sorted(set(findings))
        elif findings:
            gate_audit_status = "INCONSISTENT"
        elif upstream_unavailable:
            gate_audit_status = "UNAVAILABLE"
            if upstream_unavailable:
                if audit.attestation_audit_status == "UNAVAILABLE":
                    findings.append("AUDIT_UNAVAILABLE")
                if consistency.attestation_consistency_status == "UNAVAILABLE":
                    findings.append("CONSISTENCY_UNAVAILABLE")
                findings.append("SESSION_BINDING_UNPROVABLE")
            findings = sorted(set(findings))
        else:
            gate_audit_status = "CONSISTENT"

        return service._project(
            {
                "session_id": (
                    projection_obj.session_id
                    if projection_obj is not None and gate_audit_status != "UNAVAILABLE"
                    else ""
                ),
                "gate_audit_status": gate_audit_status,
                "available": gate_audit_status != "UNAVAILABLE",
                "consistent": gate_audit_status == "CONSISTENT",
                "published_gate_status": published_status,
                "expected_gate_status": expected_status,
                "finding_count": len(findings),
                "findings": findings,
                "audit_source": (
                    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184
                ),
            }
        )

    @staticmethod
    def _valid_findings(count: int, findings: list[str]) -> bool:
        return (
            count == len(findings)
            and len(set(findings)) == len(findings)
            and findings == sorted(findings)
        )

    @staticmethod
    def _attestation_invariant_invalid(attestation: _ATTESTATION) -> bool:
        return (
            attestation.certified != (attestation.attestation_status == "CERTIFIED")
            or attestation.blocked != (attestation.attestation_status == "BLOCKED")
            or attestation.available
            != (attestation.attestation_status != "UNAVAILABLE")
            or not ReasoningRunStage7FinalReleaseGateAuditService._valid_findings(
                attestation.finding_count, attestation.findings
            )
            or (
                attestation.attestation_status == "CERTIFIED"
                and (
                    not attestation.session_id
                    or attestation.findings
                    or attestation.bundle_status != "READY"
                    or attestation.bundle_audit_status != "CONSISTENT"
                    or attestation.bundle_audit_consistency_status != "CONSISTENT"
                )
            )
            or (
                attestation.attestation_status == "BLOCKED"
                and not (
                    attestation.bundle_status == "BLOCKED"
                    or attestation.bundle_audit_status == "INCONSISTENT"
                    or attestation.bundle_audit_consistency_status == "INCONSISTENT"
                )
            )
            or (
                attestation.attestation_status == "BLOCKED" and not attestation.findings
            )
            or (
                attestation.attestation_status == "UNAVAILABLE"
                and (
                    not attestation.findings
                    or attestation.bundle_status == "BLOCKED"
                    or attestation.bundle_audit_status == "INCONSISTENT"
                    or attestation.bundle_audit_consistency_status == "INCONSISTENT"
                )
            )
        )

    @staticmethod
    def _audit_invariant_invalid(audit: _UPSTREAM_AUDIT) -> bool:
        return (
            audit.available != (audit.attestation_audit_status != "UNAVAILABLE")
            or audit.consistent != (audit.attestation_audit_status == "CONSISTENT")
            or not ReasoningRunStage7FinalReleaseGateAuditService._valid_findings(
                audit.finding_count, audit.findings
            )
            or (
                audit.attestation_audit_status == "CONSISTENT"
                and (
                    audit.published_attestation_status
                    != audit.expected_attestation_status
                    or audit.findings
                )
            )
            or (audit.attestation_audit_status == "INCONSISTENT" and not audit.findings)
            or (audit.attestation_audit_status == "UNAVAILABLE" and not audit.findings)
            or (
                audit.published_attestation_status is None
                and (
                    audit.attestation_audit_status != "UNAVAILABLE"
                    or "ATTESTATION_INVALID" not in audit.findings
                )
            )
        )

    @staticmethod
    def _consistency_invariant_invalid(consistency: _CONSISTENCY) -> bool:
        return (
            consistency.available
            != (consistency.attestation_consistency_status != "UNAVAILABLE")
            or consistency.consistent
            != (consistency.attestation_consistency_status == "CONSISTENT")
            or not ReasoningRunStage7FinalReleaseGateAuditService._valid_findings(
                consistency.finding_count, consistency.findings
            )
            or (
                consistency.attestation_consistency_status == "CONSISTENT"
                and (
                    consistency.published_attestation_status
                    != consistency.expected_attestation_status
                    or consistency.findings
                )
            )
            or (
                consistency.attestation_consistency_status == "INCONSISTENT"
                and not consistency.findings
            )
            or (
                consistency.attestation_consistency_status == "UNAVAILABLE"
                and (consistency.session_id != "" or not consistency.findings)
            )
            or (
                consistency.published_attestation_status is None
                and (
                    consistency.attestation_consistency_status != "UNAVAILABLE"
                    or "ATTESTATION_INVALID" not in consistency.findings
                )
            )
        )

    @staticmethod
    def _projection_invariant_invalid(projection: _PROJECTION) -> bool:
        blocking = (
            projection.attestation_status == "BLOCKED"
            or projection.attestation_audit_status == "INCONSISTENT"
            or projection.consistency_status == "INCONSISTENT"
        )
        return (
            not ReasoningRunStage7FinalReleaseGateAuditService._valid_findings(
                projection.finding_count, projection.findings
            )
            or (
                projection.gate_status == "READY"
                and (
                    not projection.session_id
                    or projection.attestation_status != "CERTIFIED"
                    or projection.attestation_audit_status != "CONSISTENT"
                    or projection.consistency_status != "CONSISTENT"
                    or projection.findings
                )
            )
            or (projection.gate_status == "BLOCKED" and not blocking)
            or (
                projection.gate_status == "UNAVAILABLE"
                and (not projection.findings or blocking)
            )
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            return _AUDIT_RESULT.model_validate(result).model_dump()
        except ValidationError as exc:
            raise ReasoningRunStage7FinalReleaseGateAuditContractError(
                "FINAL_RELEASE_GATE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc

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
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)


def _revalidate_or_recover_semantic_conflict(model_type: Any, value: Any) -> Any:
    """Revalidate fields while retaining readable semantic contradictions."""
    payload = value.model_dump()
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        if all(not error["loc"] for error in exc.errors()):
            return model_type.model_construct(**payload)
        raise


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
            attestation = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7FinalEvidenceAttestationRead, attestation
            )
            audit = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7FinalAttestationAuditRead, audit
            )
            consistency = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7FinalAttestationConsistencyRead, consistency
            )
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7ReleaseReadinessAuditService._project(
                {
                    "session_id": "",
                    "readiness_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_readiness_status": "UNAVAILABLE",
                    "expected_readiness_status": "UNAVAILABLE",
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "audit_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
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

        if (
            attestation.certified != (attestation.attestation_status == "CERTIFIED")
            or attestation.blocked != (attestation.attestation_status == "BLOCKED")
            or attestation.available
            != (attestation.attestation_status != "UNAVAILABLE")
            or attestation.finding_count != len(attestation.findings)
            or attestation.findings != sorted(set(attestation.findings))
        ):
            findings.append("ATTESTATION_INVARIANT_INVALID")
        if (
            audit.available != (audit.attestation_audit_status != "UNAVAILABLE")
            or audit.consistent != (audit.attestation_audit_status == "CONSISTENT")
            or audit.finding_count != len(audit.findings)
            or audit.findings != sorted(set(audit.findings))
            or (
                audit.attestation_audit_status == "CONSISTENT"
                and (
                    audit.published_attestation_status
                    != audit.expected_attestation_status
                    or audit.findings
                )
            )
            or (audit.attestation_audit_status == "INCONSISTENT" and not audit.findings)
        ):
            findings.append("AUDIT_INVARIANT_INVALID")
        if (
            consistency.available != (consistency.consistency_status != "UNAVAILABLE")
            or consistency.consistent
            != (consistency.consistency_status == "CONSISTENT")
            or consistency.finding_count != len(consistency.findings)
            or consistency.findings != sorted(set(consistency.findings))
            or (consistency.consistency_status == "CONSISTENT" and consistency.findings)
            or (
                consistency.consistency_status == "INCONSISTENT"
                and not consistency.findings
            )
            or (
                consistency.consistency_status == "UNAVAILABLE"
                and consistency.session_id != ""
            )
        ):
            findings.append("CONSISTENCY_INVARIANT_INVALID")

        # Step A — Derive expected readiness status independently
        # BLOCKED takes precedence
        blocked = (
            (
                attestation.attestation_status == "BLOCKED"
                and attestation.package_status == "BLOCKED"
                and bool(attestation.findings)
            )
            or (
                audit.attestation_audit_status == "INCONSISTENT"
                and bool(audit.findings)
            )
            or (
                consistency.consistency_status == "INCONSISTENT"
                and bool(consistency.findings)
            )
        )

        # READY requires the full Task 174 projection binding, not just
        # individually positive status flags.
        ready = (
            attestation.attestation_status == "CERTIFIED"
            and audit.attestation_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and bool(attestation.session_id)
            and attestation.session_id == audit.session_id
            and attestation.session_id == consistency.session_id
            and attestation.attestation_status == audit.published_attestation_status
            and attestation.attestation_status == audit.expected_attestation_status
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

        # Step B — Revalidate the published Task 174 projection, including
        # objects mutated after Pydantic construction.
        raw_projection: Any = None
        try:
            raw_projection = (
                projection.model_dump()
                if isinstance(
                    projection, ReasoningRunStage7ReleaseReadinessProjectionRead
                )
                else projection
            )
            if not isinstance(raw_projection, dict):
                raise TypeError("projection has an unexpected model type")
            projection_model = projection
            if not isinstance(
                projection_model, ReasoningRunStage7ReleaseReadinessProjectionRead
            ):
                projection_model = (
                    ReasoningRunStage7ReleaseReadinessProjectionRead.model_construct(
                        **raw_projection
                    )
                )
            projection_obj = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7ReleaseReadinessProjectionRead,
                projection_model,
            )
        except (TypeError, ValidationError):
            projection_obj = None
            findings.append("PROJECTION_INVALID")

        if projection_obj is not None and projection_obj.projection_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
        ):
            findings.append("PROJECTION_SOURCE_INVALID")

        if projection_obj is None:
            raw_status = (
                raw_projection.get("readiness_status")
                if isinstance(raw_projection, dict)
                else None
            )
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
                "session_id": (
                    attestation.session_id
                    if audit_status != "UNAVAILABLE"
                    and attestation.session_id == audit.session_id
                    and attestation.session_id == consistency.session_id
                    else ""
                ),
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
        if (
            projection_obj.attestation_status != attestation.attestation_status
            or projection_obj.attestation_audit_status != audit.attestation_audit_status
            or projection_obj.consistency_status != consistency.consistency_status
        ):
            findings.append("UPSTREAM_STATUS_MISMATCH")

        # Step E — Validate findings coherence
        if projection_obj.finding_count != len(projection_obj.findings):
            findings.append("FINDINGS_MISMATCH")
            findings.append("PROJECTION_INVALID")
        if len(set(projection_obj.findings)) != len(projection_obj.findings):
            findings.append("FINDINGS_MISMATCH")
            findings.append("PROJECTION_INVALID")
        if projection_obj.findings != sorted(projection_obj.findings):
            findings.append("FINDINGS_MISMATCH")
            findings.append("PROJECTION_INVALID")

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

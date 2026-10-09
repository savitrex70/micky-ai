"""Task 172: independent Stage 7 final-attestation audit service.

Independent audit boundary over the already-published Task 171 final evidence
attestation. The auditor independently derives the expected certification
state from the published Task 168-170 evidence rather than trusting Task 171.

The auditor never calls Task 171, never calls Tasks 168-170 services, never
recomputes fingerprints, never invokes a provider, and never accesses a
database.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
    ReasoningRunStage7FinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172",
    "ReasoningRunStage7FinalAttestationAuditContractError",
    "ReasoningRunStage7FinalAttestationAuditService",
]


class ReasoningRunStage7FinalAttestationAuditContractError(Exception):
    """Task 172: the final-attestation audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7FinalAttestationAuditService:
    """Deterministic read-only audit of one Stage 7 final attestation."""

    @staticmethod
    def audit(
        *,
        package: ReasoningRunStage7EvidencePackageRead,
        audit: ReasoningRunStage7EvidencePackageAuditRead,
        consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
        attestation: dict[str, Any] | ReasoningRunStage7FinalEvidenceAttestationRead,
    ) -> dict[str, Any]:
        """Independently audit one already-published, already-validated attestation.

        The audit derives the expected attestation status from the published
        Task 168-170 evidence, then compares the independently derived state
        against the published Task 171 attestation status.

        ``CONSISTENT`` when the independently derived expected state matches
        the published Task 171 attestation. ``INCONSISTENT`` when the
        published evidence contradicts the independently derived result.
        ``UNAVAILABLE`` for missing or malformed Task 171 input.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A0 — Canonical sources for Tasks 168/169/170
        if (
            package.package_source
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168
        ):
            findings.append("PACKAGE_SOURCE_INVALID")
        if (
            audit.audit_source
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
        ):
            findings.append("AUDIT_SOURCE_INVALID")
        if (
            consistency.consistency_source
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
        ):
            findings.append("CONSISTENCY_SOURCE_INVALID")

        # Step A — Derive expected attestation status independently
        # BLOCKED takes precedence
        blocked = (
            package.package_status == "BLOCKED"
            or audit.package_audit_status == "INCONSISTENT"
            or consistency.consistency_status == "INCONSISTENT"
        )

        # CERTIFIED requires all conditions
        certified = (
            package.package_status == "READY"
            and audit.package_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and package.session_id != ""
            and not package.findings
            and not audit.findings
            and not consistency.findings
        )

        if blocked:
            expected_status = "BLOCKED"
        elif certified:
            expected_status = "CERTIFIED"
        else:
            expected_status = "UNAVAILABLE"

        # Step B — Convert attestation to model if dict
        if isinstance(attestation, dict):
            # Validate through schema to catch invariants
            try:
                attestation_obj = (
                    ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
                        attestation
                    )
                )
            except ValidationError:
                # If validation fails, treat as UNAVAILABLE
                attestation_obj = None
                findings.append("ATTESTATION_INVALID")
        else:
            attestation_obj = attestation

        if attestation_obj is None:
            raw_status = (
                attestation.get("attestation_status")
                if isinstance(attestation, dict)
                else None
            )
            findings.append("ATTESTATION_INVALID")
            if raw_status in ("CERTIFIED", "BLOCKED", "UNAVAILABLE"):
                published_status = raw_status
                if raw_status != expected_status:
                    findings.append("ATTESTATION_STATUS_MISMATCH")
                findings = sorted(set(findings))
                audit_status: str = "INCONSISTENT"
            else:
                published_status = "UNAVAILABLE"
                findings = sorted(set(findings))
                audit_status = "UNAVAILABLE"
            result: dict[str, Any] = {
                "session_id": package.session_id,
                "attestation_audit_status": audit_status,
                "available": audit_status != "UNAVAILABLE",
                "consistent": audit_status == "CONSISTENT",
                "published_attestation_status": published_status,
                "expected_attestation_status": expected_status,
                "finding_count": len(findings),
                "findings": findings,
                "audit_source": (
                    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172
                ),
            }
            return ReasoningRunStage7FinalAttestationAuditService._project(result)

        # Step C — Validate session binding
        if (
            attestation_obj.session_id != package.session_id
            or attestation_obj.session_id != audit.session_id
            or attestation_obj.session_id != consistency.session_id
        ):
            findings.append("SESSION_BINDING_MISMATCH")

        # Step D — Compare expected vs published status
        if expected_status != attestation_obj.attestation_status:
            findings.append("ATTESTATION_STATUS_MISMATCH")

        # Step E — Validate findings coherence
        if attestation_obj.finding_count != len(attestation_obj.findings):
            findings.append("FINDINGS_MISMATCH")
        if len(set(attestation_obj.findings)) != len(attestation_obj.findings):
            findings.append("FINDINGS_MISMATCH")
        if attestation_obj.findings != sorted(attestation_obj.findings):
            findings.append("FINDINGS_MISMATCH")

        # Step F — Populate result dict
        findings = sorted(set(findings))
        attestation_audit_status = "UNAVAILABLE"
        if findings:
            attestation_audit_status = "INCONSISTENT"
        else:
            attestation_audit_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": attestation_obj.session_id,
            "attestation_audit_status": attestation_audit_status,
            "available": attestation_audit_status != "UNAVAILABLE",
            "consistent": attestation_audit_status == "CONSISTENT",
            "published_attestation_status": attestation_obj.attestation_status,
            "expected_attestation_status": expected_status,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172
            ),
        }

        # Step F — Validate through schema, raise on contract error
        return ReasoningRunStage7FinalAttestationAuditService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = ReasoningRunStage7FinalAttestationAuditRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7FinalAttestationAuditContractError(
                "FINAL_ATTESTATION_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

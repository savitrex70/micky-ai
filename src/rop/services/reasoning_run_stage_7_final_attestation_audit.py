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
        ``UNAVAILABLE`` for missing or malformed Task 171 input, or when the
        upstream Task 168-170 evidence is unreadable or fails its contract
        and the attestation therefore cannot be independently verified.

        The published Task 171 attestation is revalidated on its own, before
        and independently of the upstream evidence, so a malformed evidence
        input never overwrites a readable published status.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        # Step 0 — Revalidate the published Task 171 object on its own,
        # including objects mutated after their original Pydantic
        # construction. This is independent of the upstream evidence so a
        # failure in one input never overwrites what another input shows.
        attestation_obj, readable_status = (
            ReasoningRunStage7FinalAttestationAuditService._read_attestation(
                attestation
            )
        )

        try:
            if not isinstance(package, ReasoningRunStage7EvidencePackageRead):
                raise TypeError("package has an unexpected model type")
            if not isinstance(audit, ReasoningRunStage7EvidencePackageAuditRead):
                raise TypeError("audit has an unexpected model type")
            if not isinstance(
                consistency, ReasoningRunStage7EvidencePackageAuditConsistencyRead
            ):
                raise TypeError("consistency has an unexpected model type")
            package = ReasoningRunStage7EvidencePackageRead.model_validate(
                package.model_dump()
            )
            audit = ReasoningRunStage7EvidencePackageAuditRead.model_validate(
                audit.model_dump()
            )
            consistency = (
                ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
                    consistency.model_dump()
                )
            )
        except (AttributeError, TypeError, ValidationError):
            # Upstream evidence is unreadable or fails its contract, so no
            # independent verification is possible: the expected status and
            # the audit verdict are UNAVAILABLE. The published status is
            # still reported exactly as Task 171 published it whenever it is
            # reliably readable; it is never fabricated.
            evidence_findings = ["EVIDENCE_INPUT_INVALID"]
            if attestation_obj is None:
                evidence_findings.append("ATTESTATION_INVALID")
            evidence_findings = sorted(set(evidence_findings))
            return ReasoningRunStage7FinalAttestationAuditService._project(
                {
                    "session_id": "",
                    "attestation_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_attestation_status": (
                        readable_status
                        if readable_status is not None
                        else "UNAVAILABLE"
                    ),
                    "expected_attestation_status": "UNAVAILABLE",
                    "finding_count": len(evidence_findings),
                    "findings": evidence_findings,
                    "audit_source": (
                        REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172
                    ),
                }
            )

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

        # Task 171 gives BLOCKED precedence only to a genuinely blocked
        # Task 168 package. Inconsistent later audits make certification
        # unavailable; they do not rewrite the package's blocking state.
        blocked = package.package_status == "BLOCKED"

        # Derive Task 171's complete certification conditions independently.
        certified = (
            package.package_status == "READY"
            and audit.package_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and package.session_id != ""
            and package.session_id == audit.session_id
            and package.session_id == consistency.session_id
            and audit.published_package_status == package.package_status
            and audit.expected_package_status == package.package_status
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

        # Step B — Use the published Task 171 object revalidated in Step 0.
        if attestation_obj is None:
            findings.append("ATTESTATION_INVALID")
            if readable_status is not None:
                published_status = readable_status
                if readable_status != expected_status:
                    findings.append("ATTESTATION_STATUS_MISMATCH")
                findings = sorted(set(findings))
                audit_status: str = "INCONSISTENT"
            else:
                published_status = "UNAVAILABLE"
                findings = sorted(set(findings))
                audit_status = "UNAVAILABLE"
            result: dict[str, Any] = {
                "session_id": (
                    package.session_id
                    if audit.session_id == package.session_id
                    and consistency.session_id == package.session_id
                    else ""
                ),
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
    def _read_attestation(
        attestation: dict[str, Any] | ReasoningRunStage7FinalEvidenceAttestationRead,
    ) -> tuple[ReasoningRunStage7FinalEvidenceAttestationRead | None, str | None]:
        """Revalidate the published Task 171 attestation on its own.

        Returns the validated attestation (or ``None`` when it is unreadable
        or fails its contract) together with the published status when that
        status is reliably readable. The status is ``None`` when it cannot be
        read as one of the known attestation statuses, so no published claim
        is ever invented. The supplied object is never mutated.
        """
        raw_attestation: Any = None
        try:
            raw_attestation = (
                attestation.model_dump()
                if isinstance(
                    attestation, ReasoningRunStage7FinalEvidenceAttestationRead
                )
                else attestation
            )
            if not isinstance(raw_attestation, dict):
                raise TypeError("attestation has an unexpected model type")
            attestation_obj = (
                ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
                    raw_attestation
                )
            )
        except (AttributeError, TypeError, ValueError):
            attestation_obj = None

        if attestation_obj is not None:
            return attestation_obj, attestation_obj.attestation_status

        raw_status = (
            raw_attestation.get("attestation_status")
            if isinstance(raw_attestation, dict)
            else None
        )
        if isinstance(raw_status, str) and raw_status in (
            "CERTIFIED",
            "BLOCKED",
            "UNAVAILABLE",
        ):
            return None, raw_status
        return None, None

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

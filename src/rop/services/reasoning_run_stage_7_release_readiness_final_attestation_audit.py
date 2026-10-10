"""Task 181: independent Stage 7 release-readiness final-attestation audit.

Independent audit boundary over the already-published Task 180
release-readiness final attestation. The auditor independently derives
the expected certification state from the published Task 177-179
evidence rather than trusting Task 180.

The auditor never calls Task 180, never calls Tasks 177-179 services,
never recomputes fingerprints, never executes a release, never invokes a
provider, and never accesses a database.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181,
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181",
    "ReasoningRunStage7ReleaseReadinessFinalAttestationAuditContractError",
    "ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService",
]

# Module-level aliases: the canonical contract identifiers exceed the
# 88-column limit once prefixed by call-site indentation, so call sites
# reference these short aliases instead.
_BUNDLE_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead
_AUDIT_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead
_CONSISTENCY_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead
_ATTESTATION_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationRead
_AUDIT_MODEL_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead

# The published attestation statuses Task 180 may claim.
_ATTESTATION_STATUSES = ("CERTIFIED", "BLOCKED", "UNAVAILABLE")


class ReasoningRunStage7ReleaseReadinessFinalAttestationAuditContractError(Exception):
    """Task 181: the final-attestation audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_CONTRACT_ERROR = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditContractError


class ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService:
    """Deterministic read-only audit of one final readiness attestation."""

    @staticmethod
    def audit(
        *,
        bundle: ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
        audit: ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
        consistency: ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,  # noqa: E501
        attestation: (
            dict[str, Any] | ReasoningRunStage7ReleaseReadinessFinalAttestationRead
        ),
    ) -> dict[str, Any]:
        """Independently audit one already-published Task 180 attestation.

        The audit derives the expected attestation status from the
        published Task 177-179 evidence, then compares the independently
        derived state against the published Task 180 attestation status.

        ``CONSISTENT`` when the independently derived expected state
        matches the published attestation. ``INCONSISTENT`` when the
        published claim contradicts the independently derived result.
        ``UNAVAILABLE`` for missing or malformed Task 180 input, or when
        the upstream evidence is unreadable or fails its contract and the
        attestation therefore cannot be independently verified.

        The published Task 180 attestation is revalidated on its own,
        before and independently of the upstream evidence, so a malformed
        evidence input never overwrites a readable published status, and
        an unknown published status is never presented as a claim.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        service = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService

        # Step 0 — Revalidate the published Task 180 object on its own,
        # including objects mutated after their original Pydantic
        # construction.
        attestation_obj, readable_status = service._read_attestation(attestation)

        try:
            if not isinstance(bundle, _BUNDLE_READ):
                raise TypeError("bundle has an unexpected model type")
            if not isinstance(audit, _AUDIT_READ):
                raise TypeError("audit has an unexpected model type")
            if not isinstance(consistency, _CONSISTENCY_READ):
                raise TypeError("consistency has an unexpected model type")
            bundle = _BUNDLE_READ.model_validate(bundle.model_dump())
            audit = _AUDIT_READ.model_validate(audit.model_dump())
            consistency = _CONSISTENCY_READ.model_validate(consistency.model_dump())
        except (AttributeError, TypeError, ValidationError):
            # Upstream evidence is unreadable or fails its contract, so no
            # independent verification is possible. The published status
            # is still reported exactly as Task 180 published it whenever
            # it is reliably readable; it is never fabricated.
            evidence_findings = ["EVIDENCE_INPUT_INVALID"]
            if attestation_obj is None:
                evidence_findings.append("ATTESTATION_INVALID")
            evidence_findings = sorted(set(evidence_findings))
            return service._project(
                {
                    "session_id": "",
                    "attestation_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_attestation_status": readable_status,
                    "expected_attestation_status": "UNAVAILABLE",
                    "finding_count": len(evidence_findings),
                    "findings": evidence_findings,
                    "audit_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
                    ),
                }
            )

        # Independently derive the expected Task 180 attestation status
        # from the published Task 177-179 evidence. Readable blocking
        # evidence takes precedence; an unavailable child audit or
        # consistency verdict is insufficient evidence, never blocking by
        # itself; certification requires every binding to agree.
        blocking = (
            bundle.bundle_status == "BLOCKED"
            or audit.bundle_audit_status == "INCONSISTENT"
            or consistency.consistency_status == "INCONSISTENT"
        )
        certified = (
            bundle.bundle_status == "READY"
            and audit.bundle_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and bundle.session_id != ""
            and bundle.session_id == audit.session_id
            and bundle.session_id == consistency.session_id
            and bundle.bundle_status == audit.published_bundle_status
            and bundle.bundle_status == audit.expected_bundle_status
            and not bundle.bundle_findings
            and not audit.findings
            and not consistency.findings
        )
        if blocking:
            expected_status = "BLOCKED"
        elif certified:
            expected_status = "CERTIFIED"
        else:
            expected_status = "UNAVAILABLE"

        # Step B — Use the published Task 180 object revalidated in Step 0.
        if attestation_obj is None:
            findings = ["ATTESTATION_INVALID"]
            if readable_status is not None:
                published_status = readable_status
                if readable_status != expected_status:
                    findings.append("ATTESTATION_STATUS_MISMATCH")
                audit_status = "INCONSISTENT"
            else:
                # No valid published status: unknown, not a published claim.
                published_status = None
                audit_status = "UNAVAILABLE"
            findings = sorted(set(findings))
            return service._project(
                {
                    "session_id": (
                        bundle.session_id
                        if audit.session_id == bundle.session_id
                        and consistency.session_id == bundle.session_id
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
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
                    ),
                }
            )

        findings: list[str] = []

        # Step C — Session binding, validated only where the evidence
        # establishes identities. A contract-valid UNAVAILABLE child
        # verdict carries no claimable identity, so its blank session is
        # insufficiency, never a demonstrated mismatch.
        if attestation_obj.session_id != bundle.session_id:
            findings.append("SESSION_BINDING_MISMATCH")
        if audit.bundle_audit_status != "UNAVAILABLE":
            if attestation_obj.session_id != audit.session_id:
                findings.append("SESSION_BINDING_MISMATCH")
        if consistency.consistency_status != "UNAVAILABLE":
            if attestation_obj.session_id != consistency.session_id:
                findings.append("SESSION_BINDING_MISMATCH")

        # Step D — Compare expected vs published status. An unknown status
        # is not a status mismatch; a readable conflicting claim is.
        if expected_status != attestation_obj.attestation_status:
            findings.append("ATTESTATION_STATUS_MISMATCH")

        # Step E — The attestation must echo the upstream verdicts it was
        # derived from, without invented or stale values.
        if attestation_obj.bundle_status != bundle.bundle_status:
            findings.append("ECHO_MISMATCH")
        if attestation_obj.bundle_audit_status != audit.bundle_audit_status:
            findings.append("ECHO_MISMATCH")
        if (
            attestation_obj.bundle_audit_consistency_status
            != consistency.consistency_status
        ):
            findings.append("ECHO_MISMATCH")

        # Step F — Populate result dict.
        findings = sorted(set(findings))
        attestation_audit_status = "INCONSISTENT" if findings else "CONSISTENT"

        return service._project(
            {
                "session_id": attestation_obj.session_id,
                "attestation_audit_status": attestation_audit_status,
                "available": attestation_audit_status != "UNAVAILABLE",
                "consistent": attestation_audit_status == "CONSISTENT",
                "published_attestation_status": attestation_obj.attestation_status,
                "expected_attestation_status": expected_status,
                "finding_count": len(findings),
                "findings": findings,
                "audit_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
                ),
            }
        )

    @staticmethod
    def _read_attestation(
        attestation: (
            dict[str, Any] | ReasoningRunStage7ReleaseReadinessFinalAttestationRead
        ),
    ) -> tuple[
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead | None, str | None
    ]:
        """Revalidate the published Task 180 attestation on its own.

        Returns the validated attestation (or ``None`` when it is
        unreadable or fails its contract) together with the published
        status when that status is reliably readable. The status is
        ``None`` when it cannot be read as one of the known attestation
        statuses, so no published claim is ever invented. The supplied
        object is never mutated.
        """
        raw_attestation: Any = None
        try:
            raw_attestation = (
                attestation.model_dump()
                if isinstance(attestation, _ATTESTATION_READ)
                else attestation
            )
            if not isinstance(raw_attestation, dict):
                raise TypeError("attestation has an unexpected model type")
            attestation_obj = _ATTESTATION_READ.model_validate(raw_attestation)
        except (AttributeError, TypeError, ValueError):
            attestation_obj = None

        if attestation_obj is not None:
            return attestation_obj, attestation_obj.attestation_status

        raw_status = (
            raw_attestation.get("attestation_status")
            if isinstance(raw_attestation, dict)
            else None
        )
        if isinstance(raw_status, str) and raw_status in _ATTESTATION_STATUSES:
            return None, raw_status
        return None, None

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = _AUDIT_MODEL_READ.model_validate(result)
        except ValidationError as exc:
            raise _CONTRACT_ERROR(
                "RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

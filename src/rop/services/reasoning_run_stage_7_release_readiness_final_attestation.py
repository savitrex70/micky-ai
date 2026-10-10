"""Task 180: Stage 7 release-readiness final attestation service.

Final provider-neutral attestation over the published Task 177
release-readiness evidence bundle, its Task 178 independent audit, and
the Task 179 bundle audit-consistency verdict. The attestation answers
only: "Does the published release-readiness evidence have complete,
mutually consistent, canonically attributable bindings?"

The attestation never performs new reasoning, never executes a release,
never invokes a provider, never accesses a database, and never calls
child services. It only reads the already-published validated objects.
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
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180,
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180",
    "ReasoningRunStage7ReleaseReadinessFinalAttestationContractError",
    "ReasoningRunStage7ReleaseReadinessFinalAttestationService",
]

# Module-level aliases: the canonical contract identifiers exceed the
# 88-column limit once prefixed by call-site indentation, so call sites
# reference these short aliases instead.
_BUNDLE_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead
_AUDIT_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead
_CONSISTENCY_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead
_ATTESTATION_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationRead


class ReasoningRunStage7ReleaseReadinessFinalAttestationContractError(Exception):
    """Task 180: the release-readiness final attestation cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_CONTRACT_ERROR = ReasoningRunStage7ReleaseReadinessFinalAttestationContractError


class ReasoningRunStage7ReleaseReadinessFinalAttestationService:
    """Deterministic read-only attestation of release-readiness evidence."""

    @staticmethod
    def attest(
        *,
        bundle: ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
        audit: ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
        consistency: ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,  # noqa: E501
    ) -> dict[str, Any]:
        """Attest to the completeness and consistency of readiness evidence.

        ``CERTIFIED`` when the published Task 177 bundle is READY, the
        Task 178 audit is CONSISTENT over that exact bundle, and the
        Task 179 consistency verdict is CONSISTENT over that exact
        binding, with every session, status and finding invariant
        agreeing. ``BLOCKED`` when readable, contract-valid blocking
        evidence exists. ``UNAVAILABLE`` when evidence is insufficient
        and no blocking state is readable.

        No child service is invoked, no fingerprint is recomputed, no
        release is executed, and no database is written.
        """
        service = ReasoningRunStage7ReleaseReadinessFinalAttestationService
        try:
            if not isinstance(bundle, _BUNDLE_READ):
                raise TypeError("bundle has an unexpected model type")
            if not isinstance(audit, _AUDIT_READ):
                raise TypeError("audit has an unexpected model type")
            if not isinstance(consistency, _CONSISTENCY_READ):
                raise TypeError("consistency has an unexpected model type")
            # Revalidate all inputs to detect post-construction mutation.
            bundle = _BUNDLE_READ.model_validate(bundle.model_dump())
            audit = _AUDIT_READ.model_validate(audit.model_dump())
            consistency = _CONSISTENCY_READ.model_validate(consistency.model_dump())
        except (AttributeError, TypeError, ValidationError):
            return service._project(
                {
                    "session_id": "",
                    "attestation_status": "UNAVAILABLE",
                    "certified": False,
                    "blocked": False,
                    "available": False,
                    "bundle_status": None,
                    "bundle_audit_status": None,
                    "bundle_audit_consistency_status": None,
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "attestation_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
                    ),
                }
            )

        findings: list[str] = []

        # Step A — Session binding, validated only where the evidence
        # establishes identities. A contract-valid UNAVAILABLE audit or
        # consistency verdict carries no claimable identity, so its blank
        # session is insufficiency, never a demonstrated mismatch.
        if audit.bundle_audit_status != "UNAVAILABLE":
            if bundle.session_id != audit.session_id:
                findings.append("BUNDLE_AUDIT_SESSION_MISMATCH")
        if consistency.consistency_status != "UNAVAILABLE":
            if bundle.session_id != consistency.session_id:
                findings.append("BUNDLE_CONSISTENCY_SESSION_MISMATCH")

        # Step B — Task 178 audit verdict and status agreement.
        if audit.bundle_audit_status == "UNAVAILABLE":
            findings.append("AUDIT_UNAVAILABLE")
        else:
            if bundle.bundle_status != audit.published_bundle_status:
                findings.append("PUBLISHED_STATUS_MISMATCH")
            if bundle.bundle_status != audit.expected_bundle_status:
                findings.append("EXPECTED_STATUS_MISMATCH")
            if audit.bundle_audit_status == "INCONSISTENT":
                findings.append("AUDIT_INCONSISTENT")
            if audit.findings:
                findings.append("AUDIT_HAS_FINDINGS")

        # Step C — Task 179 consistency verdict.
        if consistency.consistency_status == "UNAVAILABLE":
            findings.append("CONSISTENCY_UNAVAILABLE")
        else:
            if consistency.consistency_status == "INCONSISTENT":
                findings.append("CONSISTENCY_INCONSISTENT")
            if consistency.findings:
                findings.append("CONSISTENCY_HAS_FINDINGS")

        # Step D — Task 177 bundle verdict and structural findings.
        if bundle.bundle_status == "BLOCKED":
            findings.append("BUNDLE_BLOCKED")
        elif bundle.bundle_status == "UNAVAILABLE":
            findings.append("BUNDLE_UNAVAILABLE")
        if bundle.bundle_findings:
            findings.append("BUNDLE_HAS_FINDINGS")

        # Step E — Determine attestation status. Readable blocking
        # evidence takes precedence; certification requires every binding
        # to agree with no unresolved findings; everything else is
        # insufficient evidence, never a fabricated BLOCKED outcome.
        blocking = (
            bundle.bundle_status == "BLOCKED"
            or audit.bundle_audit_status == "INCONSISTENT"
            or consistency.consistency_status == "INCONSISTENT"
        )
        certified = (
            not findings
            and bundle.bundle_status == "READY"
            and audit.bundle_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and bundle.session_id != ""
        )
        if blocking:
            attestation_status = "BLOCKED"
        elif certified:
            attestation_status = "CERTIFIED"
        else:
            attestation_status = "UNAVAILABLE"

        # Step F — Populate result dict with coherent boolean projections.
        findings = sorted(set(findings))
        result: dict[str, Any] = {
            "session_id": bundle.session_id,
            "attestation_status": attestation_status,
            "certified": attestation_status == "CERTIFIED",
            "blocked": attestation_status == "BLOCKED",
            "available": attestation_status != "UNAVAILABLE",
            "bundle_status": bundle.bundle_status,
            "bundle_audit_status": audit.bundle_audit_status,
            "bundle_audit_consistency_status": consistency.consistency_status,
            "finding_count": len(findings),
            "findings": findings,
            "attestation_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
            ),
        }

        # Step G — Validate through schema, raise on contract error.
        return service._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the attestation result through the strict contract."""
        try:
            validated = _ATTESTATION_READ.model_validate(result)
        except ValidationError as exc:
            raise _CONTRACT_ERROR(
                "RELEASE_READINESS_FINAL_ATTESTATION_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

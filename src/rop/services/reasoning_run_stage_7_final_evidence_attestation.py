"""Task 171: Stage 7 final evidence attestation service.

Final provider-neutral attestation over the fully audited Stage 7 evidence
chain through Task 170. The attestation answers only: "Does the published
Stage 7 evidence package have complete, mutually consistent, canonically
attributable evidence?"

The attestation never performs new reasoning, never invokes a provider,
never accesses a database, and never calls child services. It only reads
the already-published validated Pydantic objects.
"""

from __future__ import annotations

import re
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
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171,
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
)

__all__ = [
    "REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171",
    "ReasoningRunStage7FinalEvidenceAttestationContractError",
    "ReasoningRunStage7FinalEvidenceAttestationService",
]

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class ReasoningRunStage7FinalEvidenceAttestationContractError(Exception):
    """Task 171: the final evidence attestation cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7FinalEvidenceAttestationService:
    """Deterministic read-only attestation of Stage 7 evidence."""

    @staticmethod
    def attest(
        *,
        package: ReasoningRunStage7EvidencePackageRead,
        audit: ReasoningRunStage7EvidencePackageAuditRead,
        consistency: ReasoningRunStage7EvidencePackageAuditConsistencyRead,
    ) -> dict[str, Any]:
        """Attest to the completeness and consistency of Stage 7 evidence.

        ``CERTIFIED`` when the published Stage 7 evidence package has
        complete, mutually consistent, canonically attributable evidence.
        ``BLOCKED`` when genuine blocking evidence exists. ``UNAVAILABLE``
        when evidence is insufficient and there is no blocking state.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A — Session binding across the three inputs
        if package.session_id != audit.session_id:
            findings.append("PACKAGE_AUDIT_SESSION_MISMATCH")
        if package.session_id != consistency.session_id:
            findings.append("PACKAGE_CONSISTENCY_SESSION_MISMATCH")

        # Step B — Canonical sources for Tasks 168/169/170
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

        # Step C — Canonical embedded sources for Tasks 162/163/164
        if (
            package.t162_audit_source
            != REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
        ):
            findings.append("T162_SOURCE_INVALID")
        if (
            package.t163_certification_source
            != REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
        ):
            findings.append("T163_SOURCE_INVALID")
        if (
            package.t164_audit_source
            != REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
        ):
            findings.append("T164_SOURCE_INVALID")

        # Step D — Request fingerprint shape (never recomputed)
        fingerprint = package.t162_request_fingerprint or ""
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            findings.append("FINGERPRINT_INVALID_LENGTH")
        elif _FINGERPRINT_RE.match(fingerprint) is None:
            findings.append("FINGERPRINT_INVALID_FORMAT")

        # Step E — Provider/model attribution for READY packages
        if package.package_status == "READY":
            if not package.t162_provider_name:
                findings.append("PROVIDER_NAME_MISSING")
            if not package.t162_model_name:
                findings.append("MODEL_NAME_MISSING")

        # Step F — Audit internal contradiction
        if audit.published_package_status != audit.expected_package_status:
            findings.append("PACKAGE_STATUS_CONTRADICTION")

        # Step G — Audit and consistency verdicts
        if audit.package_audit_status != "CONSISTENT":
            findings.append("AUDIT_NOT_CONSISTENT")
        if audit.findings:
            findings.append("AUDIT_HAS_FINDINGS")
        if consistency.consistency_status != "CONSISTENT":
            findings.append("CONSISTENCY_NOT_CONSISTENT")
        if consistency.findings:
            findings.append("CONSISTENCY_HAS_FINDINGS")

        # Step H — Package verdict
        if package.package_status == "BLOCKED":
            findings.append("PACKAGE_BLOCKED")
        elif package.package_status not in ("READY", "BLOCKED"):
            findings.append("PACKAGE_NOT_READY_OR_BLOCKED")
        if package.findings:
            findings.append("PACKAGE_HAS_FINDINGS")

        # Step I — Determine attestation status; BLOCKED takes precedence
        blocked = package.package_status == "BLOCKED"

        certified = (
            not findings
            and package.package_status == "READY"
            and audit.package_audit_status == "CONSISTENT"
            and consistency.consistency_status == "CONSISTENT"
            and package.session_id != ""
        )

        if blocked:
            attestation_status = "BLOCKED"
        elif certified:
            attestation_status = "CERTIFIED"
        else:
            attestation_status = "UNAVAILABLE"

        # Step J — Populate result dict with coherent boolean projections
        findings = sorted(set(findings))
        result: dict[str, Any] = {
            "session_id": package.session_id,
            "attestation_status": attestation_status,
            "certified": attestation_status == "CERTIFIED",
            "blocked": attestation_status == "BLOCKED",
            "available": attestation_status != "UNAVAILABLE",
            "package_status": package.package_status,
            "package_audit_status": audit.package_audit_status,
            "consistency_status": consistency.consistency_status,
            "finding_count": len(findings),
            "findings": findings,
            "attestation_source": (
                REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171
            ),
        }

        # Step K — Validate through schema, raise on contract error
        return ReasoningRunStage7FinalEvidenceAttestationService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the attestation result through the strict contract."""
        try:
            validated = ReasoningRunStage7FinalEvidenceAttestationRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7FinalEvidenceAttestationContractError(
                "FINAL_EVIDENCE_ATTESTATION_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

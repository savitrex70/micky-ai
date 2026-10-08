"""Task 166: independent Stage 7 evidence-bundle audit service.

Independent audit boundary over the already-published Task 165 evidence bundle.
The auditor independently derives the expected bundle state from the
published Task 162, Task 163, and Task 164 surfaces already present inside
the bundle, then compares the independently derived state against the
published Task 165 bundle status.

The auditor never calls Task 165, never calls Tasks 162-164 services, never
recomputes fingerprints, never invokes a provider, and never accesses a
database. It only reads the already-published evidence surfaces contained
in the validated Task 165 bundle.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation. The audit is a deterministic
verification of the Task 165 bundle's internal coherence.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
    _canonical_sources,
    _derive_expected_bundle_status,
    _present,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166",
    "ReasoningRunStage7EvidenceBundleAuditContractError",
    "ReasoningRunStage7EvidenceBundleAuditService",
]

# Canonical request fingerprint shape: SHA-256 hex digest, exactly
# 64 lowercase hexadecimal characters. Checked with fullmatch so no trailing
# newline slips through. Shape only -- never recomputed.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")


class ReasoningRunStage7EvidenceBundleAuditContractError(Exception):
    """Task 166: the evidence-bundle audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _canonical_fingerprint(value: str | None) -> bool:
    """Report whether a request fingerprint has the canonical shape.

    Shape-only check; the value is never recomputed, normalised, or
    repaired.
    """
    return (
        isinstance(value, str) and _REQUEST_FINGERPRINT_RE.fullmatch(value) is not None
    )


class ReasoningRunStage7EvidenceBundleAuditService:
    """Deterministic read-only audit of one Stage 7 evidence bundle."""

    @staticmethod
    def audit(*, bundle: ReasoningRunStage7EvidenceBundleRead) -> dict[str, Any]:
        """Independently audit one already-published, already-validated bundle.

        The audit derives the expected bundle status from the published
        Task 162, Task 163, and Task 164 evidence surfaces already present
        inside the bundle, then compares the independently derived state
        against the published Task 165 bundle status.

        ``CONSISTENT`` when the independently derived expected state matches
        the published Task 165 bundle. ``INCONSISTENT`` when the published
        evidence contradicts the independently derived result. ``UNAVAILABLE``
        for missing or malformed Task 165 input.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        findings: list[str] = []

        # Step A — Validate bundle source
        task_165_source = REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165
        if bundle.bundle_source != task_165_source:
            findings.append("TASK_165_SOURCE_MISMATCH")

        # Step B — Validate session identity (only for READY bundles)
        if bundle.bundle_status == "READY" and not _present(bundle.session_id):
            findings.append("SESSION_ID_MISMATCH")

        # Step C — Validate child sources
        canonical_sources = _canonical_sources()
        if bundle.t162_audit_source != canonical_sources["t162_audit_source"]:
            findings.append("T162_SOURCE_MISMATCH")
        if bundle.certification_source != canonical_sources["certification_source"]:
            findings.append("T163_SOURCE_MISMATCH")
        if bundle.audit_source != canonical_sources["audit_source"]:
            findings.append("T164_SOURCE_MISMATCH")

        # Step D — Validate fingerprint shape (no recomputation, only for READY)
        if bundle.bundle_status == "READY" and not _canonical_fingerprint(
            bundle.request_fingerprint
        ):
            findings.append("FINGERPRINT_MISMATCH")

        # Step E — Validate provider/model attribution (only for READY bundles)
        if bundle.bundle_status == "READY":
            if not _present(bundle.provider_name) or not _present(bundle.model_name):
                findings.append(
                    "PROVIDER_NAME_MISMATCH"
                    if not _present(bundle.provider_name)
                    else "MODEL_NAME_MISMATCH"
                )

        # Step F — Validate Task 163 evidence coherence
        if bundle.slice_status not in ("READY", "BLOCKED", "UNAVAILABLE"):
            findings.append("SLICE_STATUS_MISMATCH")
        if bundle.admission_status not in ("ADMITTED", "BLOCKED", "UNAVAILABLE", None):
            findings.append("ADMISSION_STATUS_MISMATCH")
        if bundle.diagnostics_status not in (
            "HEALTHY",
            "DEGRADED",
            "UNHEALTHY",
            "NO_MATERIAL",
            None,
        ):
            findings.append("DIAGNOSTICS_STATUS_MISMATCH")

        # Step G — Validate Task 164 evidence coherence
        valid_audit_statuses = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")
        if bundle.slice_audit_status not in valid_audit_statuses:
            findings.append("REQUEST_AUDIT_STATUS_MISMATCH")
        if bundle.audit_available != (bundle.slice_audit_status != "UNAVAILABLE"):
            findings.append("AUDIT_AVAILABLE_MISMATCH")
        if bundle.audit_consistent != (bundle.slice_audit_status == "CONSISTENT"):
            findings.append("AUDIT_CONSISTENT_MISMATCH")

        # Step H — Validate Task 162 attribution coherence
        if bundle.request_audit_status not in (
            "CONSISTENT",
            "INCONSISTENT",
            "UNAVAILABLE",
            None,
        ):
            findings.append("REQUEST_AUDIT_STATUS_MISMATCH")
        if bundle.proposal_audit_status not in (
            "CONSISTENT",
            "INCONSISTENT",
            "UNAVAILABLE",
            None,
        ):
            findings.append("PROPOSAL_AUDIT_STATUS_MISMATCH")

        # Step I — Validate findings coherence
        if bundle.finding_count != len(bundle.findings):
            findings.append("FINDINGS_MISMATCH")
        if len(set(bundle.findings)) != len(bundle.findings):
            findings.append("FINDINGS_MISMATCH")
        if bundle.findings != sorted(bundle.findings):
            findings.append("FINDINGS_MISMATCH")

        if bundle.audit_finding_count != len(bundle.audit_findings):
            findings.append("AUDIT_FINDINGS_MISMATCH")
        if len(set(bundle.audit_findings)) != len(bundle.audit_findings):
            findings.append("AUDIT_FINDINGS_MISMATCH")
        if bundle.audit_findings != sorted(bundle.audit_findings):
            findings.append("AUDIT_FINDINGS_MISMATCH")

        if bundle.bundle_finding_count != len(bundle.bundle_findings):
            findings.append("BUNDLE_FINDING_MISMATCH")
        if len(set(bundle.bundle_findings)) != len(bundle.bundle_findings):
            findings.append("BUNDLE_FINDING_MISMATCH")
        if bundle.bundle_findings != sorted(bundle.bundle_findings):
            findings.append("BUNDLE_FINDING_MISMATCH")

        # Step J — Derive expected bundle status independently
        bundle_dict = {
            name: getattr(bundle, name) for name in type(bundle).model_fields
        }
        expected_status = _derive_expected_bundle_status(bundle_dict)

        # Step K — Compare expected vs published status
        if expected_status != bundle.bundle_status:
            findings.append("BUNDLE_STATUS_MISMATCH")

        # Step L — Populate result dict
        findings = sorted(set(findings))
        bundle_audit_status = "UNAVAILABLE"
        if findings:
            bundle_audit_status = "INCONSISTENT"
        else:
            bundle_audit_status = "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": bundle.session_id,
            "bundle_audit_status": bundle_audit_status,
            "available": bundle_audit_status != "UNAVAILABLE",
            "consistent": bundle_audit_status == "CONSISTENT",
            "published_bundle_status": bundle.bundle_status,
            "expected_bundle_status": expected_status,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
        }

        # Step M — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidenceBundleAuditService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidenceBundleAuditRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7EvidenceBundleAuditContractError(
                "EVIDENCE_BUNDLE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

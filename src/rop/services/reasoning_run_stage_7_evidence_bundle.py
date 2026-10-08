"""Task 165: canonical Stage 7 vertical-slice evidence bundle service.

Evidence aggregation boundary over the already-published Task 162 audit
package, Task 163 vertical-slice verdict, and Task 164 vertical-slice
consistency audit. The assembler answers: what is the canonical compact
evidence showing what Task 163 concluded, whether Task 164 independently
confirmed it, and what Stage 7 currently has evidence for?

The assembler receives three already-validated Pydantic objects. It does
not call any child service, does not invoke Task 162, Task 163, or Task
164, does not write to a database, does not invoke any provider, and
does not recompute any fingerprint. It is a pure aggregation of
already-published material.

Neither fingerprint reconstruction nor child-service invocation can
sneak in: the assembler reads typed fields from validated objects, never
raw mappings. The request fingerprint from Task 162 is shape-validated
only (64 lowercase hexadecimal characters, fullmatch) and preserved
verbatim -- never recomputed.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation. Raw provider text, raw
provider response objects, raw request payloads, and raw proposal
objects can never appear in the returned bundle.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
    stage_7_bundle_blocking_condition_holds,
    stage_7_bundle_ready_conditions_hold,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
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
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165",
    "ReasoningRunStage7EvidenceBundleContractError",
    "ReasoningRunStage7EvidenceBundleService",
]

# Canonical Task 155 request fingerprint shape: SHA-256 hex digest, exactly
# 64 lowercase hexadecimal characters. Checked with fullmatch so no trailing
# newline slips through. Shape only -- never recomputed.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")


class ReasoningRunStage7EvidenceBundleContractError(Exception):
    """Task 165: the evidence bundle cannot be projected."""

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


def _published_status(
    slice_value: str | None,
    package_value: str | None,
    *,
    favorable: str,
    blocking: str,
) -> str | None:
    """Pick the status the bundle publishes for a field both children carry.

    The bundle shows the Task 163 value verbatim. Only when the Task 162
    package disagrees in the unfavorable direction does the package value
    surface instead: a blocking package value always, and any non-favorable
    package value over a favorable Task 163 value. The bundle therefore
    never presents READY-level evidence the package contradicts, and never
    claims a blocking state its published fields do not show. Nothing is
    recomputed; both inputs are already-validated published values.
    """
    if package_value == blocking:
        return package_value
    if slice_value == favorable and package_value != favorable:
        return package_value
    return slice_value


class ReasoningRunStage7EvidenceBundleService:
    """Deterministic read-only assembly of one Stage 7 evidence bundle."""

    @staticmethod
    def assemble(
        *,
        pkg162: ReasoningRunStage7AuditPackageRead,
        slice163: ReasoningRunStage7VerticalSliceRead,
        audit164: ReasoningRunStage7VerticalSliceAuditRead,
    ) -> dict[str, Any]:
        """Aggregate three already-published, already-validated pieces of material.

        ``READY`` only when all three inputs fully agree on every READY
        condition. ``BLOCKED`` when the validated evidence carries an
        approved blocking state. ``UNAVAILABLE`` for everything else,
        including session mismatches, missing sources, missing
        fingerprints, missing attribution, and any Task 164
        ``INCONSISTENT`` or ``UNAVAILABLE`` status. No child service is
        invoked, no fingerprint is recomputed, and no database is
        written.
        """
        bundle_findings: list[str] = []

        # Step A — Session binding
        ids = {pkg162.session_id, slice163.session_id, audit164.session_id}
        if len(ids) == 1 and pkg162.session_id != "":
            session_id = pkg162.session_id
        else:
            # Either a mismatch or an empty/blank session identity
            bundle_findings.append("STAGE_7_SESSION_MISMATCH")
            session_id = ""

        # Step B — Source validation
        if pkg162.audit_source != REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162:
            bundle_findings.append("T162_AUDIT_SOURCE_NOT_CANONICAL")
        if (
            slice163.certification_source
            != REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
        ):
            bundle_findings.append("T163_CERTIFICATION_SOURCE_NOT_CANONICAL")
        if (
            audit164.audit_source
            != REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
        ):
            bundle_findings.append("T164_AUDIT_SOURCE_NOT_CANONICAL")

        # Step C — Fingerprint validation (shape only, never recomputed)
        if not _canonical_fingerprint(pkg162.request_fingerprint):
            bundle_findings.append("REQUEST_FINGERPRINT_MISSING_OR_MALFORMED")

        # Step D — Attribution validation
        if not pkg162.provider_name or not pkg162.model_name:
            bundle_findings.append("PROVIDER_ATTRIBUTION_MISSING")

        # Step E — Published evidence (what the bundle will actually show)
        admission_status = _published_status(
            slice163.admission_status,
            pkg162.admission_status,
            favorable="ADMITTED",
            blocking="BLOCKED",
        )
        diagnostics_status = _published_status(
            slice163.diagnostics_status,
            pkg162.diagnostics_status,
            favorable="HEALTHY",
            blocking="UNHEALTHY",
        )
        # A malformed request fingerprint is withheld, never published,
        # repaired, or recomputed; REQUEST_FINGERPRINT_MISSING_OR_MALFORMED
        # records why.
        request_fingerprint = (
            pkg162.request_fingerprint
            if _canonical_fingerprint(pkg162.request_fingerprint)
            else None
        )

        # Step G — Populate result dict (bundle_status filled in below)
        bundle_findings = sorted(set(bundle_findings))
        result: dict[str, Any] = {
            # Identity
            "session_id": session_id,
            # Task 163 surface (verbatim from validated slice163)
            "slice_status": slice163.slice_status,
            "admission_status": admission_status,
            "diagnostics_status": diagnostics_status,
            "provider_name": slice163.provider_name,
            "model_name": slice163.model_name,
            "finding_count": slice163.finding_count,
            "findings": list(slice163.findings),
            "certification_source": slice163.certification_source,
            # Task 164 surface (verbatim from validated audit164)
            "slice_audit_status": audit164.slice_audit_status,
            "audit_available": audit164.available,
            "audit_consistent": audit164.consistent,
            "published_slice_status": audit164.published_slice_status,
            "expected_slice_status": audit164.expected_slice_status,
            "audit_finding_count": audit164.finding_count,
            "audit_findings": list(audit164.findings),
            "audit_source": audit164.audit_source,
            # Task 162 attribution surface (verbatim from validated pkg162)
            "request_fingerprint": request_fingerprint,
            "request_audit_status": pkg162.request_audit_status,
            "proposal_audit_status": pkg162.proposal_audit_status,
            "t162_audit_source": pkg162.audit_source,
            # Aggregate
            "bundle_status": "UNAVAILABLE",
            "bundle_finding_count": len(bundle_findings),
            "bundle_findings": bundle_findings,
            "bundle_source": REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
        }

        # READY conditions: ALL must hold; any failure → UNAVAILABLE. The
        # shared schema predicate guarantees the verdict never claims more
        # (or less) than the published evidence supports.
        ready = (
            not bundle_findings
            and stage_7_bundle_ready_conditions_hold(result)
            and slice163.slice_status == "READY"
            and audit164.slice_audit_status == "CONSISTENT"
            and audit164.available is True
            and audit164.consistent is True
            and audit164.published_slice_status == "READY"
            and audit164.expected_slice_status == "READY"
            and pkg162.admission_status == "ADMITTED"
            and pkg162.diagnostics_status == "HEALTHY"
            and pkg162.request_audit_status == "CONSISTENT"
            and pkg162.proposal_audit_status == "CONSISTENT"
            and slice163.admission_status == "ADMITTED"
            and slice163.diagnostics_status == "HEALTHY"
            and slice163.findings == []
            and audit164.findings == []
            and pkg162.audit_source
            == REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
            and slice163.certification_source
            == REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
            and audit164.audit_source
            == REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
            and session_id != ""
            and _canonical_fingerprint(pkg162.request_fingerprint)
            and bool(pkg162.provider_name and pkg162.provider_name.strip())
            and bool(pkg162.model_name and pkg162.model_name.strip())
        )

        # BLOCKED conditions: the blocking evidence the bundle itself publishes
        # (same shared predicate the schema enforces)
        blocked = stage_7_bundle_blocking_condition_holds(result)

        # Priority: BLOCKED first, then READY, then UNAVAILABLE
        if blocked:
            result["bundle_status"] = "BLOCKED"
        elif ready:
            result["bundle_status"] = "READY"

        # Step H — _project: validate through schema, raise on contract error
        return ReasoningRunStage7EvidenceBundleService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the assembled bundle through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidenceBundleRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7EvidenceBundleContractError(
                "EVIDENCE_BUNDLE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

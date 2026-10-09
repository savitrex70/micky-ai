"""Task 168: canonical Stage 7 evidence package service.

Aggregation boundary over already-published and already-validated Stage 7
evidence: Task 162 Audit Package, Task 163 Vertical-Slice Verdict, Task
164 Vertical-Slice Audit, Task 165 Evidence Bundle, Task 166 Evidence-
Bundle Audit, and Task 167 Evidence-Bundle Audit Consistency.

The assembler preserves exact session identity only when all inputs agree,
preserves canonical sources, preserves all evidence verbatim, and maintains
sorted/deduplicated findings. The assembler adds an aggregate package status
(READY/BLOCKED/UNAVAILABLE) with BLOCKED precedence over READY and
UNAVAILABLE.

The assembler never calls any child service, never writes to a database,
never invokes a provider, and never recomputes a fingerprint.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
    ReasoningRunStage7EvidenceBundleSnapshot,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
    _bundle_status_is_valid,
    _expected_task167,
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
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168",
    "ReasoningRunStage7EvidencePackageContractError",
    "ReasoningRunStage7EvidencePackageService",
]


class ReasoningRunStage7EvidencePackageContractError(Exception):
    """Task 168: the evidence package cannot be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _exactly_equal(left: Any, right: Any) -> bool:
    """Compare published values without Python's bool/int equality overlap."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _exactly_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _exactly_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


class ReasoningRunStage7EvidencePackageService:
    """Deterministic read-only assembly of one Stage 7 evidence package."""

    @staticmethod
    def assemble(
        *,
        pkg162: ReasoningRunStage7AuditPackageRead,
        slice163: ReasoningRunStage7VerticalSliceRead,
        audit164: ReasoningRunStage7VerticalSliceAuditRead,
        bundle165: ReasoningRunStage7EvidenceBundleRead,
        audit166: ReasoningRunStage7EvidenceBundleAuditRead,
        consistency167: ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
    ) -> dict[str, Any]:
        """Aggregate six already-published, already-validated pieces of material.

        ``READY`` only when all six inputs fully agree on every READY
        condition, including canonical upstream provenance and the exact
        Task 165/166 evidence binding the Task 167 verdict was computed
        over. ``BLOCKED`` when the validated evidence carries an
        approved blocking state. ``UNAVAILABLE`` for everything else,
        including session mismatches, non-canonical sources, missing
        evidence, unbound audits, and any INCONSISTENT or UNAVAILABLE
        status.

        Provenance fields are preserved verbatim in the output; a forged
        value is never repaired or replaced, only reported. No child
        service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        try:
            # Step A — Session binding
            ids = (
                pkg162.session_id,
                slice163.session_id,
                audit164.session_id,
                bundle165.session_id,
                audit166.session_id,
                consistency167.session_id,
            )
            if not all(isinstance(session_id, str) for session_id in ids):
                raise ReasoningRunStage7EvidencePackageContractError(
                    "EVIDENCE_PACKAGE_UNREADABLE",
                    "published session identities must be strings",
                )
            session_bound = len(set(ids)) == 1 and pkg162.session_id != ""
            problems: set[str] = set()
            if not session_bound:
                problems.add("STAGE_7_SESSION_MISMATCH")
                session_id = ""
            else:
                session_id = pkg162.session_id

            # Step B — Canonical upstream provenance. Every source is
            # checked, because a previously validated input whose source
            # was subsequently altered must never contribute to READY.
            if (
                pkg162.audit_source
                != REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
            ):
                problems.add("T162_SOURCE_MISMATCH")
            if (
                slice163.certification_source
                != REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
            ):
                problems.add("T163_SOURCE_MISMATCH")
            if (
                audit164.audit_source
                != REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
            ):
                problems.add("T164_SOURCE_MISMATCH")
            if (
                bundle165.bundle_source
                != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165
            ):
                problems.add("T165_SOURCE_MISMATCH")
            if (
                bundle165.t162_audit_source
                != REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
            ):
                problems.add("T162_SOURCE_MISMATCH")
            if (
                bundle165.certification_source
                != REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
            ):
                problems.add("T163_SOURCE_MISMATCH")
            if (
                bundle165.audit_source
                != REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
            ):
                problems.add("T164_SOURCE_MISMATCH")
            if (
                audit166.audit_source
                != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
            ):
                problems.add("T166_SOURCE_MISMATCH")
            if consistency167.consistency_source != (
                REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
            ):
                problems.add("T167_SOURCE_MISMATCH")

            # Step C — Bind the complete Task 165 surface to its sources.
            bundle_values = bundle165.model_dump()
            for field_name in (
                "bundle_status",
                "slice_status",
                "admission_status",
                "diagnostics_status",
                "slice_audit_status",
                "published_slice_status",
                "expected_slice_status",
                "request_audit_status",
                "proposal_audit_status",
            ):
                if not _bundle_status_is_valid(field_name, bundle_values[field_name]):
                    problems.add("T165_STATUS_INVALID")

            if bundle165.session_id != pkg162.session_id:
                problems.add("T165_SESSION_MISMATCH")
            if any(
                not _exactly_equal(getattr(bundle165, field), getattr(pkg162, source))
                for field, source in (
                    ("request_fingerprint", "request_fingerprint"),
                    ("request_audit_status", "request_audit_status"),
                    ("proposal_audit_status", "proposal_audit_status"),
                    ("t162_audit_source", "audit_source"),
                )
            ):
                problems.add("T165_T162_EVIDENCE_MISMATCH")

            if any(
                not _exactly_equal(getattr(bundle165, field), getattr(slice163, source))
                for field, source in (
                    ("slice_status", "slice_status"),
                    ("admission_status", "admission_status"),
                    ("diagnostics_status", "diagnostics_status"),
                    ("provider_name", "provider_name"),
                    ("model_name", "model_name"),
                    ("finding_count", "finding_count"),
                    ("findings", "findings"),
                    ("certification_source", "certification_source"),
                )
            ):
                problems.add("T165_T163_EVIDENCE_MISMATCH")
            if (
                pkg162.provider_name != slice163.provider_name
                or pkg162.model_name != slice163.model_name
            ):
                problems.add("T162_T163_ATTRIBUTION_MISMATCH")

            if any(
                not _exactly_equal(
                    getattr(bundle165, bundle_field),
                    getattr(audit164, audit_field),
                )
                for bundle_field, audit_field in (
                    ("slice_audit_status", "slice_audit_status"),
                    ("audit_available", "available"),
                    ("audit_consistent", "consistent"),
                    ("published_slice_status", "published_slice_status"),
                    ("expected_slice_status", "expected_slice_status"),
                    ("audit_finding_count", "finding_count"),
                    ("audit_findings", "findings"),
                    ("audit_source", "audit_source"),
                )
            ):
                problems.add("T165_T164_EVIDENCE_MISMATCH")
            if audit164.published_slice_status != slice163.slice_status:
                problems.add("T164_PUBLISHED_STATUS_MISMATCH")
            if audit164.expected_slice_status != slice163.slice_status:
                problems.add("T164_EXPECTED_STATUS_MISMATCH")
            if audit164.slice_audit_status == "CONSISTENT" and (
                audit164.published_slice_status != audit164.expected_slice_status
                or audit164.available is not True
                or audit164.consistent is not True
                or audit164.findings
            ):
                problems.add("T164_CONSISTENCY_INVALID")

            # Step D — Task 166's audit and snapshot are bound to the exact
            # Task 166 verdict is only evidence about the Task 165
            # bundle it actually compared: its published status must
            # agree with the supplied bundle whenever it names one, its
            # expected status must agree with its published status
            # wherever it claims consistency, and its recorded snapshot
            # must equal the supplied bundle field for field. A Task
            # 167 verdict computed over a different pair is not proof
            # about this pair, so the binding is re-verified here with
            # exact equality over already-published evidence.
            if (
                audit166.published_bundle_status is not None
                and audit166.published_bundle_status != bundle165.bundle_status
            ):
                problems.add("T166_PUBLISHED_STATUS_MISMATCH")
            if (
                audit166.bundle_audit_status == "CONSISTENT"
                and audit166.expected_bundle_status != audit166.published_bundle_status
            ):
                problems.add("T166_EXPECTED_STATUS_MISMATCH")
            snapshot = audit166.audited_bundle
            if audit166.bundle_audit_status != "UNAVAILABLE":
                if not isinstance(snapshot, ReasoningRunStage7EvidenceBundleSnapshot):
                    problems.add("T166_SNAPSHOT_MISSING")
                else:
                    snapshot_fields = snapshot.model_dump()
                    if not _exactly_equal(snapshot_fields, bundle_values):
                        problems.add("T166_SNAPSHOT_MISMATCH")
            if (
                consistency167.consistency_status == "CONSISTENT"
                and audit166.bundle_audit_status != "CONSISTENT"
            ):
                problems.add("T167_BINDING_MISMATCH")
            expected_t167_status, expected_t167_findings = _expected_task167(
                ReasoningRunStage7EvidenceBundleSnapshot.model_validate(bundle_values),
                (
                    snapshot
                    if isinstance(snapshot, ReasoningRunStage7EvidenceBundleSnapshot)
                    else None
                ),
                audit166.session_id,
                audit166.bundle_audit_status,
                audit166.available,
                audit166.consistent,
                audit166.published_bundle_status,
                audit166.expected_bundle_status,
                audit166.finding_count,
                audit166.findings,
                audit166.audit_source,
            )
            if (
                consistency167.consistency_status != expected_t167_status
                or consistency167.findings != expected_t167_findings
            ):
                problems.add("T167_RESULT_MISMATCH")

            # Step E — Aggregate findings from all inputs. Any problem
            # found above joins them; the aggregate is the sorted,
            # deduplicated union the package reports verbatim.
            all_findings = (
                pkg162.findings
                + slice163.findings
                + audit164.findings
                + bundle165.bundle_findings
                + audit166.findings
                + consistency167.findings
            )
            findings = sorted(set(all_findings) | problems)
        except (AttributeError, TypeError, ValidationError) as exc:
            raise ReasoningRunStage7EvidencePackageContractError(
                "EVIDENCE_PACKAGE_UNREADABLE",
                "published evidence has an unreadable shape",
            ) from exc

        # Step F — Determine package status
        # BLOCKED takes precedence; it requires a genuine published
        # blocking state, so a bare contradiction (forged source,
        # detached binding) without one yields UNAVAILABLE instead.
        blocked = (
            pkg162.admission_status == "BLOCKED"
            or pkg162.diagnostics_status == "UNHEALTHY"
            or slice163.slice_status == "BLOCKED"
            or slice163.admission_status == "BLOCKED"
            or slice163.diagnostics_status == "UNHEALTHY"
            or bundle165.bundle_status == "BLOCKED"
        )

        # READY requires all inputs to be READY/CONSISTENT, canonically
        # sourced, exactly bound, internally coherent, and finding-free.
        ready = (
            not findings
            and pkg162.admission_status == "ADMITTED"
            and pkg162.diagnostics_status == "HEALTHY"
            and pkg162.request_audit_status == "CONSISTENT"
            and pkg162.proposal_audit_status == "CONSISTENT"
            and slice163.slice_status == "READY"
            and slice163.admission_status == "ADMITTED"
            and slice163.diagnostics_status == "HEALTHY"
            and audit164.slice_audit_status == "CONSISTENT"
            and audit164.available is True
            and audit164.consistent is True
            and bundle165.bundle_status == "READY"
            and audit166.bundle_audit_status == "CONSISTENT"
            and audit166.available is True
            and audit166.consistent is True
            and consistency167.consistency_status == "CONSISTENT"
            and consistency167.available is True
            and consistency167.consistent is True
            and session_id != ""
        )

        # Priority: BLOCKED first, then READY, then UNAVAILABLE
        if blocked:
            package_status = "BLOCKED"
        elif ready:
            package_status = "READY"
        else:
            package_status = "UNAVAILABLE"

        # Step D — Populate result dict
        result: dict[str, Any] = {
            # Identity
            "session_id": session_id,
            # Task 162 evidence (verbatim)
            "t162_session_id": pkg162.session_id,
            "t162_admission_status": pkg162.admission_status,
            "t162_diagnostics_status": pkg162.diagnostics_status,
            "t162_request_fingerprint": pkg162.request_fingerprint,
            "t162_request_audit_status": pkg162.request_audit_status,
            "t162_proposal_audit_status": pkg162.proposal_audit_status,
            "t162_provider_name": pkg162.provider_name,
            "t162_model_name": pkg162.model_name,
            "t162_finding_count": pkg162.finding_count,
            "t162_findings": list(pkg162.findings),
            "t162_audit_source": pkg162.audit_source,
            # Task 163 evidence (verbatim)
            "t163_session_id": slice163.session_id,
            "t163_slice_status": slice163.slice_status,
            "t163_admission_status": slice163.admission_status,
            "t163_diagnostics_status": slice163.diagnostics_status,
            "t163_provider_name": slice163.provider_name,
            "t163_model_name": slice163.model_name,
            "t163_finding_count": slice163.finding_count,
            "t163_findings": list(slice163.findings),
            "t163_certification_source": slice163.certification_source,
            # Task 164 evidence (verbatim)
            "t164_session_id": audit164.session_id,
            "t164_slice_audit_status": audit164.slice_audit_status,
            "t164_available": audit164.available,
            "t164_consistent": audit164.consistent,
            "t164_published_slice_status": audit164.published_slice_status,
            "t164_expected_slice_status": audit164.expected_slice_status,
            "t164_finding_count": audit164.finding_count,
            "t164_findings": list(audit164.findings),
            "t164_audit_source": audit164.audit_source,
            # Task 165 evidence (verbatim)
            "t165_session_id": bundle165.session_id,
            "t165_bundle_status": bundle165.bundle_status,
            "t165_bundle_finding_count": bundle165.bundle_finding_count,
            "t165_bundle_findings": list(bundle165.bundle_findings),
            "t165_bundle_source": bundle165.bundle_source,
            "t165_bundle_evidence": bundle165.model_dump(),
            # Task 166 evidence (verbatim)
            "t166_session_id": audit166.session_id,
            "t166_bundle_audit_status": audit166.bundle_audit_status,
            "t166_available": audit166.available,
            "t166_consistent": audit166.consistent,
            "t166_published_bundle_status": audit166.published_bundle_status,
            "t166_expected_bundle_status": audit166.expected_bundle_status,
            "t166_finding_count": audit166.finding_count,
            "t166_findings": list(audit166.findings),
            "t166_audit_source": audit166.audit_source,
            "t166_audited_bundle": (
                snapshot.model_dump()
                if isinstance(snapshot, ReasoningRunStage7EvidenceBundleSnapshot)
                else None
            ),
            # Task 167 evidence (verbatim)
            "t167_session_id": consistency167.session_id,
            "t167_consistency_status": consistency167.consistency_status,
            "t167_available": consistency167.available,
            "t167_consistent": consistency167.consistent,
            "t167_finding_count": consistency167.finding_count,
            "t167_findings": list(consistency167.findings),
            "t167_consistency_source": consistency167.consistency_source,
            # Aggregate
            "package_status": package_status,
            "finding_count": len(findings),
            "findings": findings,
            "package_source": REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
        }

        # Step E — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidencePackageService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the assembled package through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidencePackageRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7EvidencePackageContractError(
                "EVIDENCE_PACKAGE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

"""Task 177: Stage 7 release-readiness evidence bundle service.

Deterministic aggregation boundary over the already-published Task 174
release-readiness projection, Task 175 release-readiness audit, and Task 176
release-readiness audit-consistency verdict. The assembler answers: what
readiness did Task 174 project, did Task 175 independently confirm its
expected status, and did Task 176 bind the audit to the exact projection?

The assembler receives three already-validated Pydantic objects. It does
not call any child service, does not invoke Task 174, Task 175, or Task
176, does not write to a database, does not invoke any provider, and does
not re-derive any readiness status. It is a pure aggregation of
already-published material, and it never mutates caller inputs.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit_consistency import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
)

_ChildT = TypeVar("_ChildT")

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177",
    "ReasoningRunStage7ReleaseReadinessEvidenceBundleContractError",
    "ReasoningRunStage7ReleaseReadinessEvidenceBundleService",
]


class ReasoningRunStage7ReleaseReadinessEvidenceBundleContractError(Exception):
    """Task 177: the release-readiness evidence bundle cannot be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ReleaseReadinessEvidenceBundleService:
    """Deterministic read-only assembly of one release-readiness bundle."""

    @staticmethod
    def assemble(
        *,
        projection174: ReasoningRunStage7ReleaseReadinessProjectionRead,
        audit175: ReasoningRunStage7ReleaseReadinessAuditRead,
        consistency176: ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
    ) -> dict[str, Any]:
        """Aggregate three already-published, already-validated pieces of material.

        ``READY`` only when the Task 174 projection publishes READY, the
        Task 175 audit is CONSISTENT over that same READY status, and the
        Task 176 consistency verdict is CONSISTENT over that same binding.
        ``BLOCKED`` when the bundle's published fields carry an approved
        blocking state. ``UNAVAILABLE`` for everything else, including
        session mismatches, missing statuses, and any Task 175 or Task 176
        ``UNAVAILABLE`` status. ``bundle_findings`` contains only Task 177
        structural finding codes, never copies of child findings.

        No child service is invoked, no readiness is re-derived, and no
        database is written. Inputs are never mutated.
        """
        # Task 177 validates each child input independently so one invalid
        # input never misrepresents the provenance of the other two.
        # ``None`` marks an input that is missing, has the wrong model type,
        # or fails its own contract (including post-construction mutation).
        service = ReasoningRunStage7ReleaseReadinessEvidenceBundleService
        projection_valid = service._validated_child(
            projection174, ReasoningRunStage7ReleaseReadinessProjectionRead
        )
        audit_valid = service._validated_child(
            audit175, ReasoningRunStage7ReleaseReadinessAuditRead
        )
        consistency_valid = service._validated_child(
            consistency176, ReasoningRunStage7ReleaseReadinessAuditConsistencyRead
        )
        all_inputs_valid = (
            projection_valid is not None
            and audit_valid is not None
            and consistency_valid is not None
        )

        bundle_findings: list[str] = []
        if not all_inputs_valid:
            bundle_findings.append("EVIDENCE_INPUT_INVALID")

        # Step A — Session binding. A shared bundle session is claimed only
        # when all three inputs are valid and agree; child session ids are
        # never rewritten. With an invalid input no three-way binding
        # exists, so the bundle session stays empty, and a mismatch is
        # reported only when the valid children genuinely disagree.
        valid_sessions = [
            child.session_id
            for child in (projection_valid, audit_valid, consistency_valid)
            if child is not None
        ]
        session_id = ""
        if len(valid_sessions) >= 2:
            distinct = set(valid_sessions)
            if len(distinct) == 1 and valid_sessions[0] != "":
                if all_inputs_valid:
                    session_id = valid_sessions[0]
            else:
                bundle_findings.append("STAGE_7_SESSION_MISMATCH")

        # Step D — Populate result dict (bundle_status filled in below).
        # A valid child keeps its genuine, validated evidence verbatim; an
        # invalid child carries only the canonical unavailable placeholder.
        bundle_findings = sorted(set(bundle_findings))
        result: dict[str, Any] = {
            "session_id": session_id,
            **service._projection_surface(projection_valid),
            **service._audit_surface(audit_valid),
            **service._consistency_surface(consistency_valid),
            # Aggregate
            "bundle_status": "UNAVAILABLE",
            "bundle_finding_count": len(bundle_findings),
            "bundle_findings": bundle_findings,
            "bundle_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
            ),
            # Each flag is true exactly when that child passed its own
            # contract and its surface above is its genuine evidence.
            "projection_evidence_valid": projection_valid is not None,
            "audit_evidence_valid": audit_valid is not None,
            "consistency_evidence_valid": consistency_valid is not None,
        }

        # Invalid or incomplete evidence never produces READY or BLOCKED:
        # the bundle stays UNAVAILABLE, with the valid children's genuine
        # evidence still visible on their own surfaces.
        if projection_valid is None or audit_valid is None or consistency_valid is None:
            return service._project(result)

        # READY conditions: ALL must hold; any failure → UNAVAILABLE.
        ready = (
            not bundle_findings
            and session_id != ""
            and projection_valid.readiness_status == "READY"
            and projection_valid.attestation_status == "CERTIFIED"
            and projection_valid.attestation_audit_status == "CONSISTENT"
            and projection_valid.consistency_status == "CONSISTENT"
            and projection_valid.finding_count == 0
            and projection_valid.findings == []
            and audit_valid.readiness_audit_status == "CONSISTENT"
            and audit_valid.published_readiness_status == "READY"
            and audit_valid.expected_readiness_status == "READY"
            and audit_valid.finding_count == 0
            and audit_valid.findings == []
            and consistency_valid.consistency_status == "CONSISTENT"
            and consistency_valid.finding_count == 0
            and consistency_valid.findings == []
        )

        # BLOCKED conditions: the blocking evidence the bundle itself
        # publishes (same shared predicate the schema enforces).
        blocked = (
            result["readiness_status"] == "BLOCKED"
            or result["readiness_audit_status"] == "INCONSISTENT"
            or result["audit_consistency_status"] == "INCONSISTENT"
        )

        # Priority: BLOCKED first, then READY, then UNAVAILABLE
        if blocked:
            result["bundle_status"] = "BLOCKED"
        elif ready:
            result["bundle_status"] = "READY"

        # Step E — Validate through schema, raise on contract error
        return service._project(result)

    @staticmethod
    def _validated_child(value: Any, model_type: type[_ChildT]) -> _ChildT | None:
        """Return a freshly revalidated child, or ``None`` if it is invalid.

        Enforces the strict model type, then revalidates the dumped state so
        post-construction mutation is detected. The caller's object is never
        mutated or repaired.
        """
        if not isinstance(value, model_type):
            return None
        try:
            return model_type.model_validate(value.model_dump())
        except (AttributeError, TypeError, ValidationError):
            return None

    @staticmethod
    def _projection_surface(
        projection: ReasoningRunStage7ReleaseReadinessProjectionRead | None,
    ) -> dict[str, Any]:
        """Task 174 surface: genuine evidence, or the canonical placeholder."""
        if projection is None:
            return {
                "readiness_status": "UNAVAILABLE",
                "attestation_status": "UNAVAILABLE",
                "attestation_audit_status": "UNAVAILABLE",
                "consistency_status": "UNAVAILABLE",
                "finding_count": 0,
                "findings": [],
                "projection_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
                ),
            }
        return {
            "readiness_status": projection.readiness_status,
            "attestation_status": projection.attestation_status,
            "attestation_audit_status": projection.attestation_audit_status,
            "consistency_status": projection.consistency_status,
            "finding_count": projection.finding_count,
            "findings": list(projection.findings),
            "projection_source": projection.projection_source,
        }

    @staticmethod
    def _audit_surface(
        audit: ReasoningRunStage7ReleaseReadinessAuditRead | None,
    ) -> dict[str, Any]:
        """Task 175 surface: genuine evidence, or the canonical placeholder."""
        if audit is None:
            return {
                "readiness_audit_status": "UNAVAILABLE",
                "audit_available": False,
                "audit_consistent": False,
                "published_readiness_status": "UNAVAILABLE",
                "expected_readiness_status": "UNAVAILABLE",
                "audit_finding_count": 0,
                "audit_findings": [],
                "audit_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
                ),
            }
        return {
            "readiness_audit_status": audit.readiness_audit_status,
            "audit_available": audit.available,
            "audit_consistent": audit.consistent,
            "published_readiness_status": audit.published_readiness_status,
            "expected_readiness_status": audit.expected_readiness_status,
            "audit_finding_count": audit.finding_count,
            "audit_findings": list(audit.findings),
            "audit_source": audit.audit_source,
        }

    @staticmethod
    def _consistency_surface(
        consistency: ReasoningRunStage7ReleaseReadinessAuditConsistencyRead | None,
    ) -> dict[str, Any]:
        """Task 176 surface: genuine evidence, or the canonical placeholder.

        An invalid child has no verdict and therefore no findings: the empty
        list is the honest placeholder, never a fabricated Task 176 finding.
        """
        if consistency is None:
            return {
                "audit_consistency_status": "UNAVAILABLE",
                "consistency_available": False,
                "consistency_consistent": False,
                "consistency_finding_count": 0,
                "consistency_findings": [],
                "consistency_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
                ),
            }
        return {
            "audit_consistency_status": consistency.consistency_status,
            "consistency_available": consistency.available,
            "consistency_consistent": consistency.consistent,
            "consistency_finding_count": consistency.finding_count,
            "consistency_findings": list(consistency.findings),
            "consistency_source": consistency.consistency_source,
        }

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the assembled bundle through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
                    result
                )
            )
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseReadinessEvidenceBundleContractError(
                "RELEASE_READINESS_EVIDENCE_BUNDLE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

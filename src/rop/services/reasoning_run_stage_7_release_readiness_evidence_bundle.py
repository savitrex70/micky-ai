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

from typing import Any

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
        try:
            if not isinstance(
                projection174, ReasoningRunStage7ReleaseReadinessProjectionRead
            ):
                raise TypeError("projection174 has an unexpected model type")
            if not isinstance(audit175, ReasoningRunStage7ReleaseReadinessAuditRead):
                raise TypeError("audit175 has an unexpected model type")
            if not isinstance(
                consistency176,
                ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
            ):
                raise TypeError("consistency176 has an unexpected model type")
            # Revalidate to detect post-construction mutation; malformed
            # model state is rejected rather than silently accepted.
            projection174 = (
                ReasoningRunStage7ReleaseReadinessProjectionRead.model_validate(
                    projection174.model_dump()
                )
            )
            audit175 = ReasoningRunStage7ReleaseReadinessAuditRead.model_validate(
                audit175.model_dump()
            )
            consistency176 = (
                ReasoningRunStage7ReleaseReadinessAuditConsistencyRead.model_validate(
                    consistency176.model_dump()
                )
            )
        except (AttributeError, TypeError, ValidationError):
            return ReasoningRunStage7ReleaseReadinessEvidenceBundleService._project(
                {
                    "session_id": "",
                    "readiness_status": "UNAVAILABLE",
                    "attestation_status": "UNAVAILABLE",
                    "attestation_audit_status": "UNAVAILABLE",
                    "consistency_status": "UNAVAILABLE",
                    "finding_count": 0,
                    "findings": [],
                    "projection_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
                    ),
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
                    "audit_consistency_status": "UNAVAILABLE",
                    "consistency_available": False,
                    "consistency_consistent": False,
                    # No child verdict existed, so no child findings exist
                    # either: an empty list here is the honest
                    # representation of unavailable child evidence, never
                    # a fabricated Task 176 finding.
                    "consistency_finding_count": 0,
                    "consistency_findings": [],
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
                    ),
                    "bundle_status": "UNAVAILABLE",
                    "bundle_finding_count": 1,
                    "bundle_findings": ["EVIDENCE_INPUT_INVALID"],
                    "bundle_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
                    ),
                    # No child evidence could be validated, so every child
                    # surface is explicitly marked unavailable.
                    "projection_evidence_valid": False,
                    "audit_evidence_valid": False,
                    "consistency_evidence_valid": False,
                }
            )

        bundle_findings: list[str] = []

        # Step A — Session binding across the three inputs
        sessions = {
            projection174.session_id,
            audit175.session_id,
            consistency176.session_id,
        }
        if len(sessions) == 1 and projection174.session_id != "":
            session_id = projection174.session_id
        else:
            bundle_findings.append("STAGE_7_SESSION_MISMATCH")
            session_id = ""

        # Step D — Populate result dict (bundle_status filled in below)
        bundle_findings = sorted(set(bundle_findings))
        result: dict[str, Any] = {
            # Identity
            "session_id": session_id,
            # Task 174 surface (verbatim from validated projection174)
            "readiness_status": projection174.readiness_status,
            "attestation_status": projection174.attestation_status,
            "attestation_audit_status": projection174.attestation_audit_status,
            "consistency_status": projection174.consistency_status,
            "finding_count": projection174.finding_count,
            "findings": list(projection174.findings),
            "projection_source": projection174.projection_source,
            # Task 175 surface (verbatim from validated audit175)
            "readiness_audit_status": audit175.readiness_audit_status,
            "audit_available": audit175.available,
            "audit_consistent": audit175.consistent,
            "published_readiness_status": audit175.published_readiness_status,
            "expected_readiness_status": audit175.expected_readiness_status,
            "audit_finding_count": audit175.finding_count,
            "audit_findings": list(audit175.findings),
            "audit_source": audit175.audit_source,
            # Task 176 surface (verbatim from validated consistency176)
            "audit_consistency_status": consistency176.consistency_status,
            "consistency_available": consistency176.available,
            "consistency_consistent": consistency176.consistent,
            "consistency_finding_count": consistency176.finding_count,
            "consistency_findings": list(consistency176.findings),
            "consistency_source": consistency176.consistency_source,
            # Aggregate
            "bundle_status": "UNAVAILABLE",
            "bundle_finding_count": len(bundle_findings),
            "bundle_findings": bundle_findings,
            "bundle_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
            ),
            # All three inputs passed their own contracts to reach this
            # path, so every child surface is explicitly valid here.
            "projection_evidence_valid": True,
            "audit_evidence_valid": True,
            "consistency_evidence_valid": True,
        }

        # READY conditions: ALL must hold; any failure → UNAVAILABLE.
        ready = (
            not bundle_findings
            and session_id != ""
            and projection174.readiness_status == "READY"
            and projection174.attestation_status == "CERTIFIED"
            and projection174.attestation_audit_status == "CONSISTENT"
            and projection174.consistency_status == "CONSISTENT"
            and projection174.finding_count == 0
            and projection174.findings == []
            and audit175.readiness_audit_status == "CONSISTENT"
            and audit175.published_readiness_status == "READY"
            and audit175.expected_readiness_status == "READY"
            and audit175.finding_count == 0
            and audit175.findings == []
            and consistency176.consistency_status == "CONSISTENT"
            and consistency176.finding_count == 0
            and consistency176.findings == []
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
        return ReasoningRunStage7ReleaseReadinessEvidenceBundleService._project(result)

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

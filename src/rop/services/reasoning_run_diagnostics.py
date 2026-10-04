"""Task 143: Stage 6 operational diagnostics boundary service.

Read-only presentation over the existing Task 142 unified inspection
bundle (which reuses Tasks 137-141). Reports coarse deterministic
diagnostics statuses without reimplementing receipt, fingerprint,
snapshot, provenance-binding, replay, consistency, or
inspection-status logic. No reasoning execution, no replay engine
invocation, no persistence, no provider/model calls. The Task 140
``original_result`` is request material, never persisted, so it is
never reconstructed here; its ``NOT_PERSISTED`` provenance is not an
issue code and never drives any diagnostics status.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_diagnostics import ReasoningRunDiagnosticsRead
from rop.services.reasoning_run_inspection import (
    ReasoningRunInspectionContractError,
    ReasoningRunInspectionService,
)

REASONING_RUN_DIAGNOSTICS_SOURCE_TASK_143 = "REASONING_RUN_DIAGNOSTICS_TASK_143"

DIAGNOSTICS_NO_MATERIAL = "NO_MATERIAL"
DIAGNOSTICS_CONSISTENT = "CONSISTENT"
DIAGNOSTICS_INCONSISTENT = "INCONSISTENT"
DIAGNOSTICS_UNVERIFIABLE = "UNVERIFIABLE"

# Presentation mapping only: a Task 139 finding whose issues are exactly
# this evidence-limitation set means binding evidence was never
# persisted -- unverifiable, never tampering. Mirrors the Task 142
# evidence-limitation rule over already computed audit output; no
# validation logic lives here.
_PROVENANCE_EVIDENCE_GAP_ISSUES = frozenset({"FINGERPRINT_PROVENANCE_NOT_PERSISTED"})


class ReasoningRunDiagnosticsContractError(Exception):
    """Task 143: the diagnostics result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunDiagnosticsService:
    """Deterministic read-only diagnostics over persisted inspection state."""

    def __init__(
        self,
        inspection_service: ReasoningRunInspectionService | None = None,
    ) -> None:
        self.inspection_service = inspection_service or ReasoningRunInspectionService()

    def diagnose(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Report the operational diagnostics for one exact session.

        Delegates to the existing Task 142 bundle and maps its already
        computed results to coarse diagnostics statuses. Read-only: no
        writes, no execution, no replay, no provider/model calls.
        """
        try:
            bundle = self.inspection_service.inspect(db, session_id)
        except ReasoningRunInspectionContractError as exc:
            raise ReasoningRunDiagnosticsContractError(
                "INSPECTION_UNREADABLE",
                "persisted inspection material cannot be projected onto "
                "the canonical inspection schema",
            ) from exc

        completed = len(bundle["receipt_history"]["receipts"])
        if completed == 0:
            inspection_status = "NO_MATERIAL"
            provenance_status = DIAGNOSTICS_NO_MATERIAL
            replay_status = DIAGNOSTICS_NO_MATERIAL
            findings: list[str] = []
        else:
            inspection_status = bundle["overall_status"]
            provenance_status = self._provenance_status(bundle["provenance_audit"])
            replay_status = self._replay_status(bundle["replay_consistency_audit"])
            findings = list(bundle["findings"])

        diagnostics = {
            "requested_session_id": str(session_id),
            "session_exists": True,
            "completed_receipts": completed,
            "inspection_status": inspection_status,
            "provenance_status": provenance_status,
            "replay_consistency_status": replay_status,
            "finding_count": len(findings),
            "findings": findings,
            "diagnostics_source": REASONING_RUN_DIAGNOSTICS_SOURCE_TASK_143,
        }
        try:
            validated = ReasoningRunDiagnosticsRead.model_validate(diagnostics)
        except ValidationError as exc:
            raise ReasoningRunDiagnosticsContractError(
                "DIAGNOSTICS_UNPROJECTABLE",
                "diagnostics result cannot be projected onto the canonical "
                "diagnostics schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _provenance_status(provenance_audit: dict[str, Any]) -> str:
        """Map the Task 139 audit output to a coarse diagnostics status."""
        if provenance_audit.get("completed_receipts_examined", 0) == 0:
            return DIAGNOSTICS_NO_MATERIAL
        if provenance_audit.get("audit_consistent", False):
            return DIAGNOSTICS_CONSISTENT
        for finding in provenance_audit.get("findings", []):
            issues = set(finding.get("provenance_issues", []))
            if issues and not issues <= _PROVENANCE_EVIDENCE_GAP_ISSUES:
                return DIAGNOSTICS_INCONSISTENT
        return DIAGNOSTICS_UNVERIFIABLE

    @staticmethod
    def _replay_status(replay_audit: dict[str, Any]) -> str:
        """Map the Task 141 audit output to a coarse diagnostics status."""
        state = replay_audit.get("replay_state", DIAGNOSTICS_NO_MATERIAL)
        if state == "NO_MATERIAL":
            return DIAGNOSTICS_NO_MATERIAL
        if state == "SATISFIED":
            return DIAGNOSTICS_CONSISTENT
        if state == "INCONSISTENT":
            return DIAGNOSTICS_INCONSISTENT
        return DIAGNOSTICS_UNVERIFIABLE

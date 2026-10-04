"""Task 144: Stage 6 pre-LLM deterministic core completion gate service.

Read-only decision surface over the existing Task 142 unified
inspection bundle and Task 143 operational diagnostics. Orchestrates
and classifies already computed deterministic results; creates no
second implementation of fingerprint, snapshot, receipt, provenance,
replay, consistency, inspection-status, or diagnostics logic. No
reasoning execution, no replay engine invocation, no persistence, no
provider/model calls. The Task 140 ``original_result`` is request
material, never persisted, so it is never reconstructed here; its
``NOT_PERSISTED`` provenance is not an issue code and never blocks the
gate on its own. This gate does not start Stage 7.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_gate import ReasoningRunStage6GateRead
from rop.services.reasoning_run_diagnostics import (
    ReasoningRunDiagnosticsContractError,
    ReasoningRunDiagnosticsService,
)
from rop.services.reasoning_run_inspection import (
    ReasoningRunInspectionContractError,
    ReasoningRunInspectionService,
)

REASONING_RUN_STAGE_6_GATE_SOURCE_TASK_144 = "REASONING_RUN_STAGE_6_GATE_TASK_144"

GATE_STATUS_READY = "READY"
GATE_STATUS_BLOCKED = "BLOCKED"
GATE_STATUS_UNVERIFIABLE = "UNVERIFIABLE"
GATE_STATUS_NO_MATERIAL = "NO_MATERIAL"


class ReasoningRunStage6GateContractError(Exception):
    """Task 144: the gate result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6GateService:
    """Deterministic read-only Stage 6 completion gate for one session."""

    def __init__(
        self,
        inspection_service: ReasoningRunInspectionService | None = None,
        diagnostics_service: ReasoningRunDiagnosticsService | None = None,
    ) -> None:
        self.inspection_service = inspection_service or ReasoningRunInspectionService()
        self.diagnostics_service = (
            diagnostics_service or ReasoningRunDiagnosticsService()
        )

    def evaluate(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Evaluate the Stage 6 completion gate for one exact session.

        Delegates to the existing Task 142/143 services and classifies
        their results. Read-only: no writes, no execution, no replay,
        no provider/model calls.
        """
        try:
            bundle = self.inspection_service.inspect(db, session_id)
        except ReasoningRunInspectionContractError as exc:
            raise ReasoningRunStage6GateContractError(
                "INSPECTION_UNREADABLE",
                "persisted inspection material cannot be projected onto "
                "the canonical inspection schema",
            ) from exc
        try:
            diagnostics = self.diagnostics_service.diagnose(db, session_id)
        except ReasoningRunDiagnosticsContractError as exc:
            raise ReasoningRunStage6GateContractError(
                "DIAGNOSTICS_UNREADABLE",
                "persisted diagnostics material cannot be projected onto "
                "the canonical diagnostics schema",
            ) from exc

        completed = diagnostics["completed_receipts"]
        receipt_status = self._receipt_status(bundle, completed)
        history_status = self._history_status(bundle, completed)
        provenance_status = diagnostics["provenance_status"]
        replay_status = diagnostics["replay_consistency_status"]
        inspection_status = diagnostics["inspection_status"]
        diagnostics_status = self._diagnostics_status(
            completed, provenance_status, replay_status
        )

        findings = list(diagnostics["findings"])
        if receipt_status == "INCOMPLETE":
            findings.append("RECEIPT_INSPECTION_INCOMPLETE")
        if history_status == "MISMATCH":
            findings.append("RECEIPT_HISTORY_COUNT_MISMATCH")
        findings = sorted(set(findings))

        gate_status = self._gate_status(
            completed,
            receipt_status,
            history_status,
            inspection_status,
            diagnostics_status,
        )

        gate = {
            "requested_session_id": str(session_id),
            "gate_status": gate_status,
            "ready": gate_status == GATE_STATUS_READY,
            "receipt_status": receipt_status,
            "history_status": history_status,
            "provenance_status": provenance_status,
            "replay_status": replay_status,
            "inspection_status": inspection_status,
            "diagnostics_status": diagnostics_status,
            "finding_count": len(findings),
            "findings": findings,
            "gate_source": REASONING_RUN_STAGE_6_GATE_SOURCE_TASK_144,
        }
        try:
            validated = ReasoningRunStage6GateRead.model_validate(gate)
        except ValidationError as exc:
            raise ReasoningRunStage6GateContractError(
                "GATE_UNPROJECTABLE",
                "gate result cannot be projected onto the canonical gate " "schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _receipt_status(bundle: dict[str, Any], completed: int) -> str:
        """Every persisted receipt must carry its exact Task 137 inspection."""
        if completed == 0:
            return "NO_MATERIAL"
        inspections = bundle.get("receipt_inspections", [])
        if len(inspections) == completed and all(
            item.get("found", False) for item in inspections
        ):
            return "VERIFIED"
        return "INCOMPLETE"

    @staticmethod
    def _history_status(bundle: dict[str, Any], completed: int) -> str:
        """History and audit evidence counts must agree exactly."""
        if completed == 0:
            return "NO_MATERIAL"
        examined = {
            bundle.get("provenance_audit", {}).get("completed_receipts_examined", -1),
            bundle.get("replay_consistency_audit", {}).get(
                "completed_receipts_examined", -2
            ),
        }
        if examined == {completed}:
            return "CONSISTENT"
        return "MISMATCH"

    @staticmethod
    def _diagnostics_status(
        completed: int, provenance_status: str, replay_status: str
    ) -> str:
        """Coarse diagnostics health over the Task 143 component statuses."""
        if completed == 0:
            return "NO_MATERIAL"
        if provenance_status == "INCONSISTENT" or replay_status == "INCONSISTENT":
            return "UNHEALTHY"
        if provenance_status == "UNVERIFIABLE" or replay_status == "UNVERIFIABLE":
            return "DEGRADED"
        return "HEALTHY"

    @staticmethod
    def _gate_status(
        completed: int,
        receipt_status: str,
        history_status: str,
        inspection_status: str,
        diagnostics_status: str,
    ) -> str:
        """Classify the already computed component statuses into a verdict.

        Contradiction outranks missing evidence: any detected
        inconsistency blocks, while a pure evidence gap (with nothing
        contradictory) leaves the gate unverifiable rather than
        blocked. The architectural ``original_result`` gap never
        appears here because it is not an issue code anywhere
        upstream.
        """
        if completed == 0:
            return GATE_STATUS_NO_MATERIAL
        if (
            inspection_status == "INCONSISTENT"
            or diagnostics_status == "UNHEALTHY"
            or receipt_status == "INCOMPLETE"
            or history_status == "MISMATCH"
        ):
            return GATE_STATUS_BLOCKED
        if inspection_status == "UNVERIFIABLE" or diagnostics_status == "DEGRADED":
            return GATE_STATUS_UNVERIFIABLE
        if inspection_status == "VERIFIABLE" and diagnostics_status == "HEALTHY":
            return GATE_STATUS_READY
        return GATE_STATUS_BLOCKED

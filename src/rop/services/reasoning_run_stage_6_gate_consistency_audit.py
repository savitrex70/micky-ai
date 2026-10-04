"""Task 145: Stage 6 completion gate consistency audit service.

Read-only audit of the Task 144 gate result against the deterministic
evidence from Tasks 142 and 143. Compares the published gate verdict
with an independent expectation mapped from the Task 143 diagnostics
component statuses. Reuses the existing gate and diagnostics services;
reimplements no receipt, provenance, replay, inspection, diagnostics,
or gate-classification validation logic. No reasoning execution, no
replay engine invocation, no persistence, no provider/model calls. The
Task 140 ``original_result`` is request material, never persisted, so
it is never reconstructed here; its ``NOT_PERSISTED`` provenance is
not an issue code and never drives this audit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditRead,
)
from rop.services.reasoning_run_diagnostics import (
    ReasoningRunDiagnosticsContractError,
    ReasoningRunDiagnosticsService,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateContractError,
    ReasoningRunStage6GateService,
)

REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_SOURCE_TASK_145 = (
    "REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145"
)


class ReasoningRunStage6GateConsistencyAuditContractError(Exception):
    """Task 145: the gate consistency audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6GateConsistencyAuditService:
    """Deterministic read-only audit of the Task 144 gate verdict."""

    def __init__(
        self,
        gate_service: ReasoningRunStage6GateService | None = None,
        diagnostics_service: ReasoningRunDiagnosticsService | None = None,
    ) -> None:
        self.gate_service = gate_service or ReasoningRunStage6GateService()
        self.diagnostics_service = (
            diagnostics_service or ReasoningRunDiagnosticsService()
        )

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit the published gate status against persisted evidence.

        Delegates to the existing Task 144 gate and Task 143
        diagnostics services. Read-only: no writes, no execution, no
        replay, no provider/model calls.
        """
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6GateConsistencyAuditContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            diagnostics = self.diagnostics_service.diagnose(db, session_id)
        except ReasoningRunDiagnosticsContractError as exc:
            raise ReasoningRunStage6GateConsistencyAuditContractError(
                "DIAGNOSTICS_UNREADABLE",
                "persisted diagnostics material cannot be projected onto "
                "the canonical diagnostics schema",
            ) from exc

        actual = gate["gate_status"]
        expected = self._expected_status(diagnostics)
        consistent = expected == actual

        findings = list(gate["findings"])
        if not consistent:
            findings.append(f"GATE_STATUS_MISMATCH:expected={expected},actual={actual}")
        findings = sorted(set(findings))

        audit = {
            "requested_session_id": str(session_id),
            "available": True,
            "gate_status": actual,
            "gate_consistent": consistent,
            "expected_gate_status": expected,
            "actual_gate_status": actual,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_SOURCE_TASK_145
            ),
        }
        try:
            validated = ReasoningRunStage6GateConsistencyAuditRead.model_validate(audit)
        except ValidationError as exc:
            raise ReasoningRunStage6GateConsistencyAuditContractError(
                "AUDIT_UNPROJECTABLE",
                "gate consistency audit cannot be projected onto the "
                "canonical audit schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _expected_status(diagnostics: dict[str, Any]) -> str:
        """Map Task 143 diagnostics outputs to the expected gate verdict.

        Independent expectation over already computed component
        statuses: contradiction outranks missing evidence, and the
        architectural ``original_result`` gap never appears here
        because it is not an issue code anywhere upstream. An unknown
        combination never silently passes as READY.
        """
        if diagnostics.get("completed_receipts", 0) == 0:
            return "NO_MATERIAL"
        inspection = diagnostics.get("inspection_status", "NO_MATERIAL")
        provenance = diagnostics.get("provenance_status", "NO_MATERIAL")
        replay = diagnostics.get("replay_consistency_status", "NO_MATERIAL")
        if (
            inspection == "INCONSISTENT"
            or provenance == "INCONSISTENT"
            or replay == "INCONSISTENT"
        ):
            return "BLOCKED"
        if (
            inspection == "UNVERIFIABLE"
            or provenance == "UNVERIFIABLE"
            or replay == "UNVERIFIABLE"
        ):
            return "UNVERIFIABLE"
        if (
            inspection == "VERIFIABLE"
            and provenance == "CONSISTENT"
            and replay == "CONSISTENT"
        ):
            return "READY"
        return "BLOCKED"

"""Task 145: Stage 6 completion gate consistency audit service.

Read-only audit of the complete Task 144 gate contract against
independent deterministic evidence: the Task 143 diagnostics, Task 142
inspection bundle, Task 139 provenance audit, and Task 141 replay
consistency audit outputs. Verifies every decision-relevant gate
field -- ``gate_status``, ``ready``, ``receipt_status``,
``history_status``, ``provenance_status``, ``replay_status``,
``inspection_status``, ``diagnostics_status`` -- including status /
boolean coherence. Reuses the existing services; reimplements no
receipt, provenance, replay, inspection, diagnostics, or
gate-classification validation logic (the diagnostics-health rule is
reused verbatim from Task 144). No reasoning execution, no replay
engine invocation, no persistence, no provider/model calls. The Task
140 ``original_result`` is request material, never persisted, so it is
never reconstructed here; its ``NOT_PERSISTED`` provenance is not an
issue code and never drives this audit.
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
from rop.services.reasoning_run_inspection import (
    ReasoningRunInspectionContractError,
    ReasoningRunInspectionService,
)
from rop.services.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditContractError,
    ReasoningRunReceiptProvenanceAuditService,
)
from rop.services.reasoning_run_replay_consistency_audit import (
    ReasoningRunReplayConsistencyAuditContractError,
    ReasoningRunReplayConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateContractError,
    ReasoningRunStage6GateService,
    derive_diagnostics_health,
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
    """Deterministic read-only audit of the Task 144 gate contract."""

    def __init__(
        self,
        gate_service: ReasoningRunStage6GateService | None = None,
        diagnostics_service: ReasoningRunDiagnosticsService | None = None,
        inspection_service: ReasoningRunInspectionService | None = None,
        provenance_audit_service: (
            ReasoningRunReceiptProvenanceAuditService | None
        ) = None,
        replay_audit_service: ReasoningRunReplayConsistencyAuditService | None = None,
    ) -> None:
        self.gate_service = gate_service or ReasoningRunStage6GateService()
        self.diagnostics_service = (
            diagnostics_service or ReasoningRunDiagnosticsService()
        )
        self.inspection_service = inspection_service or ReasoningRunInspectionService()
        self.provenance_audit_service = (
            provenance_audit_service or ReasoningRunReceiptProvenanceAuditService()
        )
        self.replay_audit_service = (
            replay_audit_service or ReasoningRunReplayConsistencyAuditService()
        )

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit the published gate contract against persisted evidence.

        Delegates to the existing Task 144/143/142/139/141 services.
        Read-only: no writes, no execution, no replay, no
        provider/model calls.
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
        try:
            inspection = self.inspection_service.inspect(db, session_id)
        except ReasoningRunInspectionContractError as exc:
            raise ReasoningRunStage6GateConsistencyAuditContractError(
                "INSPECTION_UNREADABLE",
                "persisted inspection material cannot be projected onto "
                "the canonical inspection schema",
            ) from exc
        try:
            provenance_audit = self.provenance_audit_service.audit(db, session_id)
        except ReasoningRunReceiptProvenanceAuditContractError as exc:
            raise ReasoningRunStage6GateConsistencyAuditContractError(
                "PROVENANCE_AUDIT_UNREADABLE",
                "persisted provenance audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc
        try:
            replay_audit = self.replay_audit_service.audit(db, session_id)
        except ReasoningRunReplayConsistencyAuditContractError as exc:
            raise ReasoningRunStage6GateConsistencyAuditContractError(
                "REPLAY_AUDIT_UNREADABLE",
                "persisted replay audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc

        expected = self._expected_gate(
            diagnostics, inspection, provenance_audit, replay_audit
        )
        actual = {
            "gate_status": gate["gate_status"],
            "ready": gate["ready"],
            "receipt_status": gate["receipt_status"],
            "history_status": gate["history_status"],
            "provenance_status": gate["provenance_status"],
            "replay_status": gate["replay_status"],
            "inspection_status": gate["inspection_status"],
            "diagnostics_status": gate["diagnostics_status"],
        }

        findings = list(gate["findings"])
        if expected["gate_status"] != actual["gate_status"]:
            findings.append(
                "GATE_STATUS_MISMATCH:"
                f"expected={expected['gate_status']},"
                f"actual={actual['gate_status']}"
            )
        if expected["ready"] != actual["ready"]:
            findings.append(
                "GATE_READY_MISMATCH:"
                f"expected={expected['ready']},actual={actual['ready']}"
            )
        if actual["ready"] != (actual["gate_status"] == "READY"):
            findings.append(
                "GATE_READY_INCOHERENT:"
                f"status={actual['gate_status']},ready={actual['ready']}"
            )
        for field in (
            "receipt_status",
            "history_status",
            "provenance_status",
            "replay_status",
            "inspection_status",
            "diagnostics_status",
        ):
            if expected[field] != actual[field]:
                findings.append(
                    f"GATE_{field.upper()}_MISMATCH:"
                    f"expected={expected[field]},actual={actual[field]}"
                )
        findings = sorted(set(findings))

        consistent = (
            expected["gate_status"] == actual["gate_status"]
            and expected["ready"] == actual["ready"]
            and actual["ready"] == (actual["gate_status"] == "READY")
            and all(
                expected[field] == actual[field]
                for field in (
                    "receipt_status",
                    "history_status",
                    "provenance_status",
                    "replay_status",
                    "inspection_status",
                    "diagnostics_status",
                )
            )
        )

        audit = {
            "requested_session_id": str(session_id),
            "available": True,
            "gate_status": actual["gate_status"],
            "gate_consistent": consistent,
            "expected_gate_status": expected["gate_status"],
            "actual_gate_status": actual["gate_status"],
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
    def _expected_gate(
        diagnostics: dict[str, Any],
        inspection: dict[str, Any],
        provenance_audit: dict[str, Any],
        replay_audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Derive the expected Task 144 contract from upstream evidence.

        Independent expectation over already computed outputs, using
        the canonical Task 144 semantics: completed material decides
        NO_MATERIAL; contradiction outranks missing evidence; the
        architectural ``original_result`` gap never appears here
        because it is not an issue code anywhere upstream. An unknown
        combination never silently passes as READY.
        """
        completed = diagnostics["completed_receipts"]
        inspection_status = diagnostics["inspection_status"]
        provenance_status = diagnostics["provenance_status"]
        replay_status = diagnostics["replay_consistency_status"]
        diagnostics_status = derive_diagnostics_health(
            completed, provenance_status, replay_status
        )

        receipts = inspection["receipt_history"]["receipts"]
        if completed == 0:
            receipt_status = "NO_MATERIAL"
            history_status = "NO_MATERIAL"
        else:
            inspections = inspection["receipt_inspections"]
            if len(inspections) == completed and all(
                item.get("found", False) for item in inspections
            ):
                receipt_status = "VERIFIED"
            else:
                receipt_status = "INCOMPLETE"
            examined = {
                provenance_audit.get("completed_receipts_examined", -1),
                replay_audit.get("completed_receipts_examined", -2),
            }
            if examined == {completed} == {len(receipts)}:
                history_status = "CONSISTENT"
            else:
                history_status = "MISMATCH"

        if completed == 0:
            gate_status = "NO_MATERIAL"
        elif (
            inspection_status == "INCONSISTENT"
            or diagnostics_status == "UNHEALTHY"
            or receipt_status == "INCOMPLETE"
            or history_status == "MISMATCH"
        ):
            gate_status = "BLOCKED"
        elif inspection_status == "UNVERIFIABLE" or diagnostics_status == "DEGRADED":
            gate_status = "UNVERIFIABLE"
        elif inspection_status == "VERIFIABLE" and diagnostics_status == "HEALTHY":
            gate_status = "READY"
        else:
            gate_status = "BLOCKED"

        return {
            "gate_status": gate_status,
            "ready": gate_status == "READY",
            "receipt_status": receipt_status,
            "history_status": history_status,
            "provenance_status": provenance_status,
            "replay_status": replay_status,
            "inspection_status": inspection_status,
            "diagnostics_status": diagnostics_status,
        }

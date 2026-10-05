"""Task 146: canonical Stage 6 release readiness report service.

Read-only reporting boundary over the existing Task 144 gate verdict
and Task 145 gate consistency audit (which themselves embed the Task
142 inspection and Task 143 diagnostics evidence). Aggregates canonical
evidence into one readiness verdict; reimplements no
receipt, provenance, replay, inspection, diagnostics, gate, or audit
validation logic. No reasoning execution, no replay engine
invocation, no persistence, no provider/model calls. The Task 140
``original_result`` is request material, never persisted, so it is
never reconstructed here; its ``NOT_PERSISTED`` provenance is not an
issue code and never blocks readiness on its own. READY additionally
requires the gate ``ready`` flag to be true and diagnostics to be
healthy. Precedence is mandatory: a genuine Task 145 gate
inconsistency (``gate_consistent == False``) is always BLOCKED and
outranks every other verdict, including ``NO_MATERIAL``, so a
consistency contradiction can never be hidden by the empty-session
convenience classification; only a genuinely coherent NO_MATERIAL
result may report NO_MATERIAL.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessRead,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateContractError,
    ReasoningRunStage6GateService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditContractError,
    ReasoningRunStage6GateConsistencyAuditService,
)

REASONING_RUN_STAGE_6_READINESS_SOURCE_TASK_146 = (
    "REASONING_RUN_STAGE_6_READINESS_TASK_146"
)


class ReasoningRunStage6ReadinessContractError(Exception):
    """Task 146: the readiness report cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6ReadinessService:
    """Deterministic read-only Stage 6 release readiness report."""

    def __init__(
        self,
        gate_service: ReasoningRunStage6GateService | None = None,
        gate_audit_service: ReasoningRunStage6GateConsistencyAuditService | None = None,
    ) -> None:
        self.gate_service = gate_service or ReasoningRunStage6GateService()
        self.gate_audit_service = (
            gate_audit_service or ReasoningRunStage6GateConsistencyAuditService()
        )

    def report(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Report release readiness for one exact session.

        Delegates to the existing Task 144 gate and Task 145 gate
        consistency audit. Read-only: no writes, no execution, no
        replay, no provider/model calls.
        READY requires the gate to be READY with its ``ready`` flag
        true, the gate audit to agree, healthy diagnostics, and no
        blocking deterministic contradiction. Verdict precedence is
        mandatory: ``gate_consistent == False`` is always BLOCKED and
        outranks every other verdict, including ``NO_MATERIAL`` -- a
        Task 145 contradiction is never hidden by the empty-session
        classification, and only a genuinely coherent NO_MATERIAL
        result reports NO_MATERIAL. UNHEALTHY diagnostics and an
        incoherent gate ``ready`` flag fall through to BLOCKED.
        ``release_ready`` is true exactly when ``readiness_status`` is
        READY, by construction from the same verdict.
        """
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6ReadinessContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ReadinessContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc

        gate_status = gate["gate_status"]
        gate_ready = gate["ready"]
        gate_consistent = gate_audit["gate_consistent"]
        diagnostics_status = gate["diagnostics_status"]
        gate_ready_coherent = gate_ready == (gate_status == "READY")

        # Mandatory precedence: a genuine Task 145 gate inconsistency
        # outranks every other verdict, including NO_MATERIAL. Task 145
        # is explicitly saying the canonical gate result contradicts
        # itself, so that contradiction must never be hidden by the
        # empty-session convenience classification.
        if not gate_consistent:
            readiness_status = "BLOCKED"
        elif gate_status == "NO_MATERIAL":
            readiness_status = "NO_MATERIAL"
        elif gate_status == "BLOCKED":
            readiness_status = "BLOCKED"
        elif gate_status == "UNVERIFIABLE":
            readiness_status = "UNVERIFIABLE"
        elif diagnostics_status == "DEGRADED":
            readiness_status = "UNVERIFIABLE"
        elif gate_status == "READY" and gate_ready and diagnostics_status == "HEALTHY":
            readiness_status = "READY"
        else:
            readiness_status = "BLOCKED"

        findings = sorted(set(gate["findings"]) | set(gate_audit["findings"]))
        if gate_status != "NO_MATERIAL" and not gate_ready_coherent:
            findings = sorted(
                set(findings)
                | {"GATE_READY_INCOHERENT:" f"status={gate_status},ready={gate_ready}"}
            )

        report = {
            "requested_session_id": str(session_id),
            "readiness_status": readiness_status,
            "release_ready": readiness_status == "READY",
            "gate_status": gate_status,
            "gate_consistent": gate_consistent,
            "diagnostics_status": diagnostics_status,
            "finding_count": len(findings),
            "findings": findings,
            "readiness_source": (REASONING_RUN_STAGE_6_READINESS_SOURCE_TASK_146),
        }
        try:
            validated = ReasoningRunStage6ReadinessRead.model_validate(report)
        except ValidationError as exc:
            raise ReasoningRunStage6ReadinessContractError(
                "READINESS_UNPROJECTABLE",
                "readiness report cannot be projected onto the canonical "
                "readiness schema",
            ) from exc
        return validated.model_dump()

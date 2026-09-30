"""Task 132: canonical deterministic reasoning-run orchestration.

One application-level boundary over the existing deterministic
services: validate the session, establish the canonical input snapshot
and fingerprint, execute the established stages in their defined order,
run the independent chain audit, and produce one strongly validated
audited result. No stage logic is duplicated here; no medical decision
is made beyond the already-defined deterministic policy contracts; no
model, network, or external system is involved.

When a required stage fails, the failure stage is explicit and no
further orchestration proceeds past the failed execution: the chain
audit still reports read-only over the partial state, but the
orchestration is marked inconsistent.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_orchestration import ReasoningRunOrchestrationRead
from rop.services.reasoning_chain_audit import ReasoningChainAuditService
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    ReasoningRunInputSnapshotService,
)
from rop.services.reasoning_session import ReasoningSessionService

REASONING_RUN_ORCHESTRATION_SOURCE_TASK_132 = "REASONING_RUN_ORCHESTRATION_TASK_132"


class ReasoningRunOrchestrationContractError(Exception):
    """Task 132: orchestration could not be established."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunOrchestrationService:
    """Single orchestration boundary over deterministic ROP services."""

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        snapshot_service: ReasoningRunInputSnapshotService | None = None,
        execution_service: ReasoningRunExecutionService | None = None,
        chain_audit_service: ReasoningChainAuditService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.snapshot_service = snapshot_service or ReasoningRunInputSnapshotService()
        self.execution_service = execution_service or ReasoningRunExecutionService()
        self.chain_audit_service = chain_audit_service or ReasoningChainAuditService()

    def orchestrate(self, db: Session, session_id: UUID) -> dict[str, Any]:
        """Run the full deterministic workflow and audit the outcome."""
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningRunOrchestrationContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )
        try:
            snapshot = self.snapshot_service.build_snapshot(db, session_id)
            input_fingerprint = compute_snapshot_fingerprint(snapshot)
        except Exception as exc:
            raise ReasoningRunOrchestrationContractError(
                "INPUT_SNAPSHOT_FAILED",
                "orchestration input could not be established: " + type(exc).__name__,
            ) from exc

        execution = self.execution_service.execute_for_session(db, session_id)
        failure_stage = self._first_failed_stage(execution)

        chain_audit: dict[str, Any] | None = None
        try:
            chain_audit = self.chain_audit_service.audit_session(db, session_id)
        except Exception:
            chain_audit = None

        orchestration_consistent = (
            failure_stage is None
            and execution.get("outcome") == "COMPLETED"
            and execution.get("execution_consistent") is True
            and isinstance(chain_audit, dict)
            and chain_audit.get("chain_consistent") is True
        )
        result = {
            "available": failure_stage is None,
            "orchestration_consistent": bool(orchestration_consistent),
            "session_id": str(session_id),
            "input_fingerprint": input_fingerprint,
            "failure_stage": failure_stage,
            "execution": execution,
            "chain_audit": chain_audit,
            "orchestration_source": REASONING_RUN_ORCHESTRATION_SOURCE_TASK_132,
        }
        return ReasoningRunOrchestrationRead.model_validate(result).model_dump()

    @staticmethod
    def _first_failed_stage(execution: dict[str, Any]) -> str | None:
        stages = execution.get("stages")
        if not isinstance(stages, list):
            return "STAGES_MISSING"
        for stage in stages:
            if isinstance(stage, dict) and stage.get("status") == "FAILED":
                return str(stage.get("stage_id"))
        if execution.get("outcome") != "COMPLETED":
            return "OUTCOME_NOT_COMPLETED"
        return None

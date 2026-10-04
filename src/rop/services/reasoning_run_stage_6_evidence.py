"""Task 148: canonical Stage 6 release evidence bundle service.

Read-only evidence aggregation over the existing Task 144 gate, Task
145 gate consistency audit, Task 146 readiness report, and Task 147
readiness consistency audit (which themselves embed the Task 142
inspection and Task 143 diagnostics evidence). Collects the minimal
canonical evidence supporting the release-readiness decision and
verifies the canonical statuses agree. Reimplements no receipt,
provenance, replay, inspection, diagnostics, gate, audit, or
readiness validation logic. No reasoning execution, no replay engine
invocation, no persistence, no provider/model calls. The Task 140
``original_result`` is request material, never persisted, so it is
never reconstructed here; its ``NOT_PERSISTED`` provenance is not an
issue code and never drives this bundle.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceRead,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateContractError,
    ReasoningRunStage6GateService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditContractError,
    ReasoningRunStage6GateConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessContractError,
    ReasoningRunStage6ReadinessService,
)
from rop.services.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditContractError,
    ReasoningRunStage6ReadinessConsistencyAuditService,
)

REASONING_RUN_STAGE_6_EVIDENCE_SOURCE_TASK_148 = (
    "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148"
)


class ReasoningRunStage6EvidenceContractError(Exception):
    """Task 148: the evidence bundle cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6EvidenceService:
    """Deterministic read-only Stage 6 release evidence bundle."""

    def __init__(
        self,
        gate_service: ReasoningRunStage6GateService | None = None,
        gate_audit_service: ReasoningRunStage6GateConsistencyAuditService | None = None,
        readiness_service: ReasoningRunStage6ReadinessService | None = None,
        readiness_audit_service: (
            ReasoningRunStage6ReadinessConsistencyAuditService | None
        ) = None,
    ) -> None:
        self.gate_service = gate_service or ReasoningRunStage6GateService()
        self.gate_audit_service = (
            gate_audit_service or ReasoningRunStage6GateConsistencyAuditService()
        )
        self.readiness_service = (
            readiness_service or ReasoningRunStage6ReadinessService()
        )
        self.readiness_audit_service = (
            readiness_audit_service
            or ReasoningRunStage6ReadinessConsistencyAuditService()
        )

    def bundle(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Bundle the canonical release evidence for one exact session.

        Delegates to the existing Task 144/145/146/147 services.
        Read-only: no writes, no execution, no replay, no
        provider/model calls. Release readiness is reported only when
        the gate is READY, readiness is READY, and both consistency
        audits agree.
        """
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6EvidenceContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6EvidenceContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc
        try:
            readiness = self.readiness_service.report(db, session_id)
        except ReasoningRunStage6ReadinessContractError as exc:
            raise ReasoningRunStage6EvidenceContractError(
                "READINESS_UNREADABLE",
                "persisted readiness material cannot be projected onto "
                "the canonical readiness schema",
            ) from exc
        try:
            readiness_audit = self.readiness_audit_service.audit(db, session_id)
        except ReasoningRunStage6ReadinessConsistencyAuditContractError as exc:
            raise ReasoningRunStage6EvidenceContractError(
                "READINESS_AUDIT_UNREADABLE",
                "persisted readiness audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc

        gate_status = gate["gate_status"]
        gate_consistent = gate_audit["gate_consistent"]
        readiness_status = readiness["readiness_status"]
        readiness_consistent = readiness_audit["readiness_consistent"]

        if gate_status == "NO_MATERIAL":
            stage_6_status = "NO_MATERIAL"
        elif (
            gate_status == "BLOCKED"
            or readiness_status == "BLOCKED"
            or not gate_consistent
            or not readiness_consistent
        ):
            stage_6_status = "BLOCKED"
        elif gate_status == "UNVERIFIABLE" or readiness_status == "UNVERIFIABLE":
            stage_6_status = "UNVERIFIABLE"
        elif (
            gate_status == "READY"
            and readiness_status == "READY"
            and gate_consistent
            and readiness_consistent
        ):
            stage_6_status = "READY"
        else:
            stage_6_status = "BLOCKED"

        findings = sorted(
            set(gate["findings"])
            | set(gate_audit["findings"])
            | set(readiness["findings"])
            | set(readiness_audit["findings"])
        )

        bundle = {
            "requested_session_id": str(session_id),
            "evidence_available": stage_6_status != "NO_MATERIAL",
            "stage_6_status": stage_6_status,
            "release_ready": stage_6_status == "READY",
            "gate_status": gate_status,
            "gate_consistent": gate_consistent,
            "readiness_status": readiness_status,
            "readiness_consistent": readiness_consistent,
            "finding_count": len(findings),
            "findings": findings,
            "evidence_source": (REASONING_RUN_STAGE_6_EVIDENCE_SOURCE_TASK_148),
        }
        try:
            validated = ReasoningRunStage6EvidenceRead.model_validate(bundle)
        except ValidationError as exc:
            raise ReasoningRunStage6EvidenceContractError(
                "EVIDENCE_UNPROJECTABLE",
                "evidence bundle cannot be projected onto the canonical "
                "evidence schema",
            ) from exc
        return validated.model_dump()

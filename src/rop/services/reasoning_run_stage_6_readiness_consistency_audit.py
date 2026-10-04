"""Task 147: Stage 6 release readiness consistency audit service.

Read-only audit of the Task 146 readiness report against the
deterministic evidence from Tasks 144 and 145. Compares the published
readiness state with an independent expectation mapped from the gate
verdict, gate consistency, and diagnostics health already computed
upstream. Reuses the existing readiness, gate, and gate-audit
services; reimplements no receipt, provenance, replay, inspection,
diagnostics, gate, or readiness validation logic. No reasoning
execution, no replay engine invocation, no persistence, no
provider/model calls. The Task 140 ``original_result`` is request
material, never persisted, so it is never reconstructed here; its
``NOT_PERSISTED`` provenance is not an issue code and never drives
this audit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditRead,
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

REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_SOURCE_TASK_147 = (
    "REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147"
)


class ReasoningRunStage6ReadinessConsistencyAuditContractError(Exception):
    """Task 147: the readiness consistency audit cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6ReadinessConsistencyAuditService:
    """Deterministic read-only audit of the Task 146 readiness report."""

    def __init__(
        self,
        readiness_service: ReasoningRunStage6ReadinessService | None = None,
        gate_service: ReasoningRunStage6GateService | None = None,
        gate_audit_service: ReasoningRunStage6GateConsistencyAuditService | None = None,
    ) -> None:
        self.readiness_service = (
            readiness_service or ReasoningRunStage6ReadinessService()
        )
        self.gate_service = gate_service or ReasoningRunStage6GateService()
        self.gate_audit_service = (
            gate_audit_service or ReasoningRunStage6GateConsistencyAuditService()
        )

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit the published readiness contract against evidence.

        Delegates to the existing Task 146/144/145 services. Verifies
        the complete Task 146 contract -- ``readiness_status``,
        ``release_ready``, ``gate_status``, ``gate_consistent``, and
        ``diagnostics_status`` -- against the canonical Task 144/145
        evidence. Read-only: no writes, no execution, no replay, no
        provider/model calls.
        """
        try:
            readiness = self.readiness_service.report(db, session_id)
        except ReasoningRunStage6ReadinessContractError as exc:
            raise ReasoningRunStage6ReadinessConsistencyAuditContractError(
                "READINESS_UNREADABLE",
                "persisted readiness material cannot be projected onto "
                "the canonical readiness schema",
            ) from exc
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6ReadinessConsistencyAuditContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ReadinessConsistencyAuditContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc

        actual = readiness["readiness_status"]
        expected = self._expected_status(gate, gate_audit)
        expected_release_ready = expected == "READY"
        release_ready_ok = readiness["release_ready"] == expected_release_ready

        echo_checks = (
            (
                "READINESS_GATE_STATUS_MISMATCH",
                readiness["gate_status"],
                gate["gate_status"],
            ),
            (
                "READINESS_GATE_CONSISTENT_MISMATCH",
                readiness["gate_consistent"],
                gate_audit["gate_consistent"],
            ),
            (
                "READINESS_DIAGNOSTICS_STATUS_MISMATCH",
                readiness["diagnostics_status"],
                gate["diagnostics_status"],
            ),
        )
        echo_ok = all(published == canonical for _, published, canonical in echo_checks)
        consistent = expected == actual and release_ready_ok and echo_ok

        findings = list(readiness["findings"])
        if expected != actual:
            findings.append(
                "READINESS_STATUS_MISMATCH:" f"expected={expected},actual={actual}"
            )
        if not release_ready_ok:
            findings.append(
                "READINESS_RELEASE_READY_MISMATCH:"
                f"expected={expected_release_ready},"
                f"actual={readiness['release_ready']}"
            )
        if readiness["release_ready"] != (actual == "READY"):
            findings.append(
                "READINESS_RELEASE_READY_INCOHERENT:"
                f"status={actual},"
                f"release_ready={readiness['release_ready']}"
            )
        for name, published, canonical in echo_checks:
            if published != canonical:
                findings.append(f"{name}:expected={canonical},actual={published}")
        findings = sorted(set(findings))

        audit = {
            "requested_session_id": str(session_id),
            "available": True,
            "readiness_status": actual,
            "expected_readiness_status": expected,
            "actual_readiness_status": actual,
            "readiness_consistent": consistent,
            "release_ready": readiness["release_ready"],
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_SOURCE_TASK_147
            ),
        }
        try:
            validated = ReasoningRunStage6ReadinessConsistencyAuditRead.model_validate(
                audit
            )
        except ValidationError as exc:
            raise ReasoningRunStage6ReadinessConsistencyAuditContractError(
                "AUDIT_UNPROJECTABLE",
                "readiness consistency audit cannot be projected onto the "
                "canonical audit schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _expected_status(gate: dict[str, Any], gate_audit: dict[str, Any]) -> str:
        """Map Task 144/145 outputs to the expected readiness state.

        Independent expectation over already computed verdicts, using
        the same readiness rule the Task 146 report applies:
        contradiction (or a disagreeing gate audit) blocks, a pure
        evidence gap leaves readiness unverifiable, and only a READY
        gate with a consistent audit and healthy diagnostics is ready.
        The architectural ``original_result`` gap never appears here
        because it is not an issue code anywhere upstream. An unknown
        combination never silently passes as READY.
        """
        gate_status = gate.get("gate_status", "NO_MATERIAL")
        gate_consistent = gate_audit.get("gate_consistent", False)
        diagnostics_health = gate.get("diagnostics_status", "NO_MATERIAL")
        if gate_status == "NO_MATERIAL":
            return "NO_MATERIAL"
        if (
            gate_status == "BLOCKED"
            or not gate_consistent
            or diagnostics_health == "UNHEALTHY"
        ):
            return "BLOCKED"
        if gate_status == "UNVERIFIABLE" or diagnostics_health == "DEGRADED":
            return "UNVERIFIABLE"
        if (
            gate_status == "READY"
            and gate_consistent
            and diagnostics_health == "HEALTHY"
        ):
            return "READY"
        return "BLOCKED"

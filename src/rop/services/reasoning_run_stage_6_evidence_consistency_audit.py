"""Task 149: Stage 6 release evidence consistency audit service.

Read-only audit of the Task 148 evidence bundle against the canonical
evidence chain: Task 144 gate, Task 145 gate consistency, Task 146
readiness, and Task 147 readiness consistency (which themselves embed
the Task 142 inspection and Task 143 diagnostics evidence).
Determines whether the final bundle faithfully represents that chain.
Reuses the existing evidence, gate, gate-audit, readiness, and
readiness-audit services; reimplements no receipt, fingerprint,
provenance, replay, inspection, diagnostics, gate, or readiness
validation logic. No reasoning execution, no replay engine invocation,
no persistence, no provider/model calls. The Task 140
``original_result`` is request material, never persisted, so it is
never reconstructed here; its ``NOT_PERSISTED`` provenance is not an
issue code and never drives this audit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_evidence_consistency_audit import (
    ReasoningRunStage6EvidenceConsistencyAuditRead,
)
from rop.services.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceContractError,
    ReasoningRunStage6EvidenceService,
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

REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_SOURCE_TASK_149 = (
    "REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149"
)


class ReasoningRunStage6EvidenceConsistencyAuditContractError(Exception):
    """Task 149: the evidence consistency audit cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6EvidenceConsistencyAuditService:
    """Deterministic read-only audit of the Task 148 evidence bundle."""

    def __init__(
        self,
        evidence_service: ReasoningRunStage6EvidenceService | None = None,
        gate_service: ReasoningRunStage6GateService | None = None,
        gate_audit_service: ReasoningRunStage6GateConsistencyAuditService | None = None,
        readiness_service: ReasoningRunStage6ReadinessService | None = None,
        readiness_audit_service: (
            ReasoningRunStage6ReadinessConsistencyAuditService | None
        ) = None,
    ) -> None:
        self.evidence_service = evidence_service or ReasoningRunStage6EvidenceService()
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

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit the published evidence bundle against upstream evidence.

        Delegates to the existing Task 148/144/145/146/147 services.
        Read-only: no writes, no execution, no replay, no
        provider/model calls.
        """
        try:
            evidence = self.evidence_service.bundle(db, session_id)
        except ReasoningRunStage6EvidenceContractError as exc:
            raise ReasoningRunStage6EvidenceConsistencyAuditContractError(
                "EVIDENCE_UNREADABLE",
                "persisted evidence material cannot be projected onto "
                "the canonical evidence schema",
            ) from exc
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6EvidenceConsistencyAuditContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6EvidenceConsistencyAuditContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc
        try:
            readiness = self.readiness_service.report(db, session_id)
        except ReasoningRunStage6ReadinessContractError as exc:
            raise ReasoningRunStage6EvidenceConsistencyAuditContractError(
                "READINESS_UNREADABLE",
                "persisted readiness material cannot be projected onto "
                "the canonical readiness schema",
            ) from exc
        try:
            readiness_audit = self.readiness_audit_service.audit(db, session_id)
        except ReasoningRunStage6ReadinessConsistencyAuditContractError as exc:
            raise ReasoningRunStage6EvidenceConsistencyAuditContractError(
                "READINESS_AUDIT_UNREADABLE",
                "persisted readiness audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc

        actual = evidence["stage_6_status"]
        expected = self._expected_status(gate, gate_audit, readiness, readiness_audit)
        expected_release_ready = expected == "READY"
        release_ready_ok = evidence["release_ready"] == expected_release_ready
        expected_available = expected != "NO_MATERIAL"
        available_ok = evidence["evidence_available"] == expected_available

        echo_checks = (
            (
                "EVIDENCE_GATE_STATUS_MISMATCH",
                evidence["gate_status"],
                gate["gate_status"],
            ),
            (
                "EVIDENCE_GATE_CONSISTENT_MISMATCH",
                evidence["gate_consistent"],
                gate_audit["gate_consistent"],
            ),
            (
                "EVIDENCE_READINESS_STATUS_MISMATCH",
                evidence["readiness_status"],
                readiness["readiness_status"],
            ),
            (
                "EVIDENCE_READINESS_CONSISTENT_MISMATCH",
                evidence["readiness_consistent"],
                readiness_audit["readiness_consistent"],
            ),
        )
        echo_ok = all(published == canonical for _, published, canonical in echo_checks)
        consistent = (
            expected == actual and release_ready_ok and available_ok and echo_ok
        )

        findings = list(evidence["findings"])
        if expected != actual:
            findings.append(
                "EVIDENCE_STATUS_MISMATCH:" f"expected={expected},actual={actual}"
            )
        if not release_ready_ok:
            findings.append(
                "EVIDENCE_RELEASE_READY_MISMATCH:"
                f"expected={expected_release_ready},"
                f"actual={evidence['release_ready']}"
            )
        if not available_ok:
            findings.append(
                "EVIDENCE_AVAILABLE_MISMATCH:"
                f"expected={expected_available},"
                f"actual={evidence['evidence_available']}"
            )
        if evidence["release_ready"] != (actual == "READY"):
            findings.append(
                "EVIDENCE_RELEASE_READY_INCOHERENT:"
                f"status={actual},"
                f"release_ready={evidence['release_ready']}"
            )
        for name, published, canonical in echo_checks:
            if published != canonical:
                findings.append(f"{name}:expected={canonical},actual={published}")
        findings = sorted(set(findings))

        audit = {
            "requested_session_id": str(session_id),
            "available": True,
            "evidence_status": actual,
            "expected_evidence_status": expected,
            "actual_evidence_status": actual,
            "evidence_consistent": consistent,
            "release_ready": evidence["release_ready"],
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_SOURCE_TASK_149
            ),
        }
        try:
            validated = ReasoningRunStage6EvidenceConsistencyAuditRead.model_validate(
                audit
            )
        except ValidationError as exc:
            raise ReasoningRunStage6EvidenceConsistencyAuditContractError(
                "AUDIT_UNPROJECTABLE",
                "evidence consistency audit cannot be projected onto the "
                "canonical audit schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _expected_status(
        gate: dict[str, Any],
        gate_audit: dict[str, Any],
        readiness: dict[str, Any],
        readiness_audit: dict[str, Any],
    ) -> str:
        """Map Task 144-147 outputs to the expected evidence state.

        Independent expectation over already computed verdicts: a real
        contradiction or a disagreeing consistency audit blocks, a pure
        evidence gap leaves the bundle unverifiable, and only a READY
        gate with a READY readiness and two agreeing audits is READY.
        The architectural ``original_result`` gap never appears here
        because it is not an issue code anywhere upstream. An unknown
        combination never silently passes as READY.
        """
        gate_status = gate.get("gate_status", "NO_MATERIAL")
        gate_consistent = gate_audit.get("gate_consistent", False)
        readiness_status = readiness.get("readiness_status", "NO_MATERIAL")
        readiness_consistent = readiness_audit.get("readiness_consistent", False)
        if gate_status == "NO_MATERIAL":
            return "NO_MATERIAL"
        if (
            gate_status == "BLOCKED"
            or readiness_status == "BLOCKED"
            or not gate_consistent
            or not readiness_consistent
        ):
            return "BLOCKED"
        if gate_status == "UNVERIFIABLE" or readiness_status == "UNVERIFIABLE":
            return "UNVERIFIABLE"
        if (
            gate_status == "READY"
            and readiness_status == "READY"
            and gate_consistent
            and readiness_consistent
        ):
            return "READY"
        return "BLOCKED"

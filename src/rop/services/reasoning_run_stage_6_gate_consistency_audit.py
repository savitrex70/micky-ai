"""Task 145: Stage 6 completion gate consistency audit service.

Read-only audit of the complete Task 144 gate contract against
independent deterministic evidence: the Task 142 inspection bundle,
Task 139 provenance audit, and Task 141 replay consistency audit
outputs. Verifies every decision-relevant gate field --
``gate_status``, ``ready``, ``receipt_status``, ``history_status``,
``provenance_status``, ``replay_status``, ``inspection_status``,
``diagnostics_status`` -- including status / boolean coherence. The
expected provenance and replay states are derived from the owning
Task 139/141 audits, never from the Task 143 presentation mapping;
Task 143 diagnostics is consumed only as a cross-check surface, and a
disagreement between canonical evidence and the diagnostics
presentation is reported explicitly. Reuses the existing services;
reimplements no receipt, provenance, replay, inspection, diagnostics,
or gate-classification validation logic (the diagnostics-health rule
is reused verbatim from Task 144). No reasoning execution, no replay
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

# Structural malformation per Task 141's canonical contract: material
# carrying any of these issues is structurally unverifiable, so it can
# never reach the weaker tamper verdict. Cited from Task 141 rather
# than re-derived, so the per-finding classification below reconstructs
# Task 141's own verdicts instead of inventing new ones.
_REPLAY_MALFORMING_ISSUES = frozenset(
    {
        "REPLAY_MALFORMED_FINGERPRINT",
        "REPLAY_OUTCOME_NOT_COMPLETED",
        "REPLAY_EXOGENOUS_SNAPSHOT_MALFORMED",
        "REPLAY_RECEIPT_UNREADABLE",
        "REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED",
        "REPLAY_INPUT_SNAPSHOT_MALFORMED",
    }
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

        expected, coherence_findings = self._expected_gate(
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
        mismatch_findings: list[str] = []
        mismatch_findings.extend(coherence_findings)
        if expected["gate_status"] != actual["gate_status"]:
            mismatch_findings.append(
                "GATE_STATUS_MISMATCH:"
                f"expected={expected['gate_status']},"
                f"actual={actual['gate_status']}"
            )
        if expected["ready"] != actual["ready"]:
            mismatch_findings.append(
                "GATE_READY_MISMATCH:"
                f"expected={expected['ready']},actual={actual['ready']}"
            )
        if actual["ready"] != (actual["gate_status"] == "READY"):
            mismatch_findings.append(
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
                mismatch_findings.append(
                    f"GATE_{field.upper()}_MISMATCH:"
                    f"expected={expected[field]},actual={actual[field]}"
                )
        findings.extend(mismatch_findings)
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
            and not mismatch_findings
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

    @classmethod
    def _canonical_provenance_status(
        cls,
        provenance_audit: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """Derive provenance state from the owning Task 139 audit output.

        The verdict comes from the audit's own per-receipt evidence,
        never from its summary boolean alone: every finding's
        ``receipt_consistent`` flag must agree with its
        ``provenance_issues``, the session ``audit_consistent`` flag
        must agree with the findings, and the examined count must agree
        with the findings length. Any internal disagreement is an
        incoherent audit and yields INCONSISTENT with an explicit
        finding. Otherwise: no examined material is NO_MATERIAL; empty
        issues everywhere is CONSISTENT; a pure
        missing-binding-evidence gap
        (``FINGERPRINT_PROVENANCE_NOT_PERSISTED`` only) is
        UNVERIFIABLE, never tampering; any genuine contradiction is
        INCONSISTENT.
        """
        incoherent: list[str] = []
        examined = provenance_audit.get("completed_receipts_examined", 0)
        findings = provenance_audit.get("findings", [])
        if examined == 0:
            if findings or not provenance_audit.get("audit_consistent", True):
                incoherent.append("GATE_PROVENANCE_AUDIT_INCOHERENT")
                return "INCONSISTENT", incoherent
            return "NO_MATERIAL", incoherent
        if len(findings) != examined:
            incoherent.append("GATE_PROVENANCE_AUDIT_INCOHERENT")
        for finding in findings:
            issues = set(finding.get("provenance_issues", []))
            if finding.get("receipt_consistent", False) == bool(issues):
                incoherent.append(
                    "GATE_PROVENANCE_FINDING_INCOHERENT:"
                    f"{finding.get('receipt_id', '')}"
                )
        if provenance_audit.get("audit_consistent", False) == any(
            finding.get("provenance_issues", []) for finding in findings
        ):
            incoherent.append("GATE_PROVENANCE_AUDIT_INCOHERENT")
        if incoherent:
            return "INCONSISTENT", sorted(set(incoherent))
        for finding in findings:
            issues = set(finding.get("provenance_issues", []))
            if issues and not issues <= {"FINGERPRINT_PROVENANCE_NOT_PERSISTED"}:
                return "INCONSISTENT", []
        if any(finding.get("provenance_issues", []) for finding in findings):
            return "UNVERIFIABLE", []
        return "CONSISTENT", []

    @staticmethod
    def _finding_classification(issues: set[str]) -> tuple[str, str]:
        """Reconstruct Task 141's per-finding verdict from its issues.

        Mirrors Task 141's own classification exactly: clean material
        is SATISFIED, structurally malformed material is MALFORMED
        (UNVERIFIABLE when the only gap is never-persisted binding
        evidence, RECORD_INVALID otherwise), and readable but
        contract-violating material is INCONSISTENT (RECORD_TAMPERED).
        """
        if not issues:
            return ("SATISFIED", "PERSISTED_MATERIAL_VERIFIABLE")
        if issues & _REPLAY_MALFORMING_ISSUES:
            if issues == {"REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED"}:
                return ("MALFORMED", "UNVERIFIABLE")
            return ("MALFORMED", "RECORD_INVALID")
        return ("INCONSISTENT", "RECORD_TAMPERED")

    @classmethod
    def _canonical_replay_status(
        cls,
        replay_audit: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """Derive replay state from the owning Task 141 audit output.

        Coherence first: every finding's ``replay_state`` and
        ``replay_contract_finding`` must match Task 141's own
        classification reconstructed from its ``replay_issues``, and
        ``original_result_provenance`` must carry the architectural
        ``NOT_PERSISTED`` marker. Any internal disagreement is an
        incoherent audit and yields INCONSISTENT -- a ``SATISFIED``
        verdict over tampered issues is refused, never trusted.
        Once coherence holds, the verdict follows Task 141's own
        classification (``SATISFIED`` clean, ``INCONSISTENT``
        contract-violating, ``MALFORMED`` structurally unverifiable
        including missing binding evidence), so a genuine
        malformed-but-flagged record agrees with the gate instead of
        manufacturing a second verdict. The ``NOT_PERSISTED``
        original-result gap is not an issue code and can never surface
        here as INCONSISTENT.
        """
        incoherent: list[str] = []
        examined = replay_audit.get("completed_receipts_examined", 0)
        findings = replay_audit.get("findings", [])
        if replay_audit.get("original_result_provenance") != "NOT_PERSISTED":
            incoherent.append(
                "GATE_REPLAY_ORIGINAL_PROVENANCE_UNEXPECTED:"
                f"{replay_audit.get('original_result_provenance')}"
            )
        if examined == 0:
            if (
                findings
                or not replay_audit.get("audit_consistent", True)
                or replay_audit.get("replay_state", "NO_MATERIAL") != "NO_MATERIAL"
            ):
                incoherent.append("GATE_REPLAY_AUDIT_INCOHERENT")
                return "INCONSISTENT", sorted(set(incoherent))
            return "NO_MATERIAL", sorted(set(incoherent))
        if len(findings) != examined:
            incoherent.append("GATE_REPLAY_AUDIT_INCOHERENT")
        for finding in findings:
            issues = set(finding.get("replay_issues", []))
            if finding.get("replay_consistent", False) == bool(issues):
                incoherent.append(
                    "GATE_REPLAY_FINDING_INCOHERENT:" f"{finding.get('receipt_id', '')}"
                )
            expected_state, expected_contract = cls._finding_classification(issues)
            if (
                finding.get("replay_state", "") != expected_state
                or finding.get("replay_contract_finding", "") != expected_contract
            ):
                incoherent.append(
                    "GATE_REPLAY_FINDING_INCOHERENT:" f"{finding.get('receipt_id', '')}"
                )
        if replay_audit.get("audit_consistent", False) == any(
            finding.get("replay_issues", []) for finding in findings
        ):
            incoherent.append("GATE_REPLAY_AUDIT_INCOHERENT")
        session_state = replay_audit.get("replay_state", "")
        has_issues = any(finding.get("replay_issues", []) for finding in findings)
        if session_state == "NO_MATERIAL" or (session_state == "SATISFIED") == (
            has_issues
        ):
            incoherent.append("GATE_REPLAY_AUDIT_INCOHERENT")
        # Task 141's canonical session aggregation, reconstructed from
        # the per-receipt findings with its exact precedence: a
        # MALFORMED finding outranks INCONSISTENT, which outranks
        # SATISFIED. Any published session state disagreeing with that
        # reconstruction is an incoherent audit.
        finding_states = {finding.get("replay_state", "") for finding in findings}
        if "MALFORMED" in finding_states:
            expected_session_state: str | None = "MALFORMED"
        elif "INCONSISTENT" in finding_states:
            expected_session_state = "INCONSISTENT"
        elif finding_states == {"SATISFIED"}:
            expected_session_state = "SATISFIED"
        else:
            expected_session_state = None
        if (
            expected_session_state is not None
            and session_state != expected_session_state
        ):
            incoherent.append("GATE_REPLAY_AUDIT_INCOHERENT")
        if incoherent:
            return "INCONSISTENT", sorted(set(incoherent))
        if session_state == "SATISFIED":
            return "CONSISTENT", []
        if session_state == "INCONSISTENT":
            return "INCONSISTENT", []
        return "UNVERIFIABLE", []

    @classmethod
    def _expected_gate(
        cls,
        diagnostics: dict[str, Any],
        inspection: dict[str, Any],
        provenance_audit: dict[str, Any],
        replay_audit: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """Derive the expected Task 144 contract from canonical evidence.

        Provenance, replay, and inspection states come from their
        owning Task 139/141/142 outputs; diagnostics health uses the
        shared Task 144 helper over those canonical states. Task 143
        diagnostics is compared as a cross-check surface only: a
        disagreement between canonical evidence and the diagnostics
        presentation yields explicit presentation findings and fails
        consistency, but the expected gate itself never follows a
        forged presentation. An unknown combination never silently
        passes as READY.
        """
        completed = len(inspection["receipt_history"]["receipts"])
        inspection_status = inspection["overall_status"]
        provenance_status, provenance_incoherent = cls._canonical_provenance_status(
            provenance_audit
        )
        replay_status, replay_incoherent = cls._canonical_replay_status(replay_audit)
        diagnostics_status = derive_diagnostics_health(
            completed, provenance_status, replay_status
        )

        presentation_findings: list[str] = []
        presentation_findings.extend(provenance_incoherent)
        presentation_findings.extend(replay_incoherent)
        if diagnostics.get("provenance_status") != provenance_status:
            presentation_findings.append(
                "GATE_PROVENANCE_PRESENTATION_MISMATCH:"
                f"expected={provenance_status},"
                f"actual={diagnostics.get('provenance_status')}"
            )
        if diagnostics.get("replay_consistency_status") != replay_status:
            presentation_findings.append(
                "GATE_REPLAY_PRESENTATION_MISMATCH:"
                f"expected={replay_status},"
                f"actual={diagnostics.get('replay_consistency_status')}"
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

        return (
            {
                "gate_status": gate_status,
                "ready": gate_status == "READY",
                "receipt_status": receipt_status,
                "history_status": history_status,
                "provenance_status": provenance_status,
                "replay_status": replay_status,
                "inspection_status": inspection_status,
                "diagnostics_status": diagnostics_status,
            },
            presentation_findings,
        )

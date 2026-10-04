"""Task 142: unified deterministic reasoning-run inspection bundle service.

Read-only orchestration over already persisted inspection material. The
bundle validates/identifies the requested session's material by
delegating to the existing deterministic services -- Task 137 receipt
inspection, Task 138 receipt history, Task 139 provenance audit, and
Task 141 replay consistency audit -- then assembles their results and
derives one deterministic overall status. No reasoning execution, no
replay engine invocation, no persistence, no provider/model logic. The
underlying validation algorithms are never copied here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
from rop.schemas.reasoning_run_inspection import ReasoningRunInspectionRead
from rop.services.reasoning_run_receipt import (
    ReasoningRunReceiptContractError,
    ReasoningRunReceiptService,
)
from rop.services.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditContractError,
    ReasoningRunReceiptProvenanceAuditService,
)
from rop.services.reasoning_run_replay_consistency_audit import (
    ReasoningRunReplayConsistencyAuditContractError,
    ReasoningRunReplayConsistencyAuditService,
)

REASONING_RUN_INSPECTION_SOURCE_TASK_142 = "REASONING_RUN_INSPECTION_TASK_142"

INSPECTION_STATUS_NO_MATERIAL = "NO_MATERIAL"
INSPECTION_STATUS_VERIFIABLE = "VERIFIABLE"
INSPECTION_STATUS_INCONSISTENT = "INCONSISTENT"
INSPECTION_STATUS_UNVERIFIABLE = "UNVERIFIABLE"

# A finding whose only issue is missing historical binding evidence is
# an evidence limitation, not a contradiction: it can never drive the
# bundle to INCONSISTENT.
_PROVENANCE_GAP_ONLY_ISSUES = frozenset({"FINGERPRINT_PROVENANCE_NOT_PERSISTED"})
_REPLAY_GAP_ONLY_ISSUES = frozenset({"REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED"})


class ReasoningRunInspectionContractError(Exception):
    """Task 142: the inspection bundle result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunInspectionService:
    """Deterministic read-only bundle of one session's inspection material."""

    def __init__(
        self,
        receipt_repository: ReasoningRunReceiptRepository | None = None,
        receipt_service: ReasoningRunReceiptService | None = None,
        provenance_audit_service: (
            ReasoningRunReceiptProvenanceAuditService | None
        ) = None,
        replay_consistency_audit_service: (
            ReasoningRunReplayConsistencyAuditService | None
        ) = None,
    ) -> None:
        self.receipt_repository = receipt_repository or ReasoningRunReceiptRepository()
        self.receipt_service = receipt_service or ReasoningRunReceiptService()
        self.provenance_audit_service = (
            provenance_audit_service or ReasoningRunReceiptProvenanceAuditService()
        )
        self.replay_consistency_audit_service = (
            replay_consistency_audit_service
            or ReasoningRunReplayConsistencyAuditService()
        )

    def inspect(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Assemble the unified inspection bundle for one exact session.

        Delegates to the existing read-only Task 137/138/139/141
        services and derives the deterministic overall status. Read-only:
        no writes, no execution, no replay, no recomputation of stored
        material, no provider/model calls. The Task 140
        ``original_result`` is request material, never persisted, so it
        is never reconstructed, never replayed for, and never persisted
        here; its ``NOT_PERSISTED`` provenance (reported inside the
        Task 141 audit) never drives the overall status.
        """
        try:
            history = self.receipt_service.history(db, session_id)
        except ReasoningRunReceiptContractError as exc:
            raise ReasoningRunInspectionContractError(
                "RECEIPT_HISTORY_UNREADABLE",
                "persisted receipt history cannot be projected onto the "
                "canonical read schema",
            ) from exc

        receipts = history.get("receipts", [])
        receipt_inspections: list[dict[str, Any]] = []
        for receipt in receipts:
            try:
                inspection = self.receipt_service.inspect(
                    db, session_id, receipt["input_fingerprint"]
                )
            except ReasoningRunReceiptContractError as exc:
                raise ReasoningRunInspectionContractError(
                    "RECEIPT_INSPECTION_UNREADABLE",
                    "persisted receipt cannot be projected onto the "
                    "canonical read schema",
                ) from exc
            receipt_inspections.append(inspection)

        try:
            provenance_audit = self.provenance_audit_service.audit(db, session_id)
        except ReasoningRunReceiptProvenanceAuditContractError as exc:
            raise ReasoningRunInspectionContractError(
                "PROVENANCE_AUDIT_UNPROJECTABLE",
                "provenance audit result cannot be projected onto the "
                "canonical audit schema",
            ) from exc

        try:
            replay_consistency_audit = self.replay_consistency_audit_service.audit(
                db, session_id
            )
        except ReasoningRunReplayConsistencyAuditContractError as exc:
            raise ReasoningRunInspectionContractError(
                "REPLAY_CONSISTENCY_AUDIT_UNPROJECTABLE",
                "replay consistency audit result cannot be projected onto "
                "the canonical audit schema",
            ) from exc

        overall_status, findings = self._derive_status(
            receipts, provenance_audit, replay_consistency_audit
        )

        bundle = {
            "requested_session_id": str(session_id),
            "receipt_inspections": receipt_inspections,
            "receipt_history": history,
            "provenance_audit": provenance_audit,
            "replay_consistency_audit": replay_consistency_audit,
            "overall_status": overall_status,
            "findings": findings,
            "inspection_source": REASONING_RUN_INSPECTION_SOURCE_TASK_142,
        }
        try:
            validated = ReasoningRunInspectionRead.model_validate(bundle)
        except ValidationError as exc:
            raise ReasoningRunInspectionContractError(
                "INSPECTION_UNPROJECTABLE",
                "inspection bundle cannot be projected onto the canonical "
                "inspection schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _derive_status(
        receipts: list[dict[str, Any]],
        provenance_audit: dict[str, Any],
        replay_consistency_audit: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """Derive the deterministic overall status and findings.

        ``NO_MATERIAL`` is decided by persisted material alone. Any
        invalid finding beyond a pure missing-evidence gap is a detected
        contradiction and yields ``INCONSISTENT``. A pure missing-evidence
        gap (with nothing contradictory) yields ``UNVERIFIABLE``. The
        architectural ``original_result_provenance`` gap is never an
        issue code, so it can never drive this verdict.
        """
        if len(receipts) == 0:
            return INSPECTION_STATUS_NO_MATERIAL, []

        raw_findings: list[str] = []
        for finding in provenance_audit.get("findings", []):
            raw_findings.extend(finding.get("provenance_issues", []))
        for finding in replay_consistency_audit.get("findings", []):
            raw_findings.extend(finding.get("replay_issues", []))
        findings = sorted(set(raw_findings))

        inconsistent = False
        unverifiable_gap = False
        for finding in provenance_audit.get("findings", []):
            issues = set(finding.get("provenance_issues", []))
            if not issues:
                continue
            if issues <= _PROVENANCE_GAP_ONLY_ISSUES:
                unverifiable_gap = True
            else:
                inconsistent = True
        for finding in replay_consistency_audit.get("findings", []):
            issues = set(finding.get("replay_issues", []))
            if not issues:
                continue
            if issues <= _REPLAY_GAP_ONLY_ISSUES:
                unverifiable_gap = True
            else:
                inconsistent = True

        if inconsistent:
            return INSPECTION_STATUS_INCONSISTENT, findings
        if unverifiable_gap:
            return INSPECTION_STATUS_UNVERIFIABLE, findings
        return INSPECTION_STATUS_VERIFIABLE, findings

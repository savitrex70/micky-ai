"""Task 142: unified deterministic reasoning-run inspection bundle service.

A small, strictly read-only orchestration layer that assembles the
already-existing Task 137 receipt-inspection, Task 138 receipt-history,
Task 139 provenance-consistency-audit, and Task 141 replay-consistency-
audit results for one exact session into a single canonical inspection
bundle, then derives a deterministic overall ``inspection_status`` from
those assembled results.

This service is an aggregation/presentation contract only. It does NOT
duplicate any owning service's validation logic: every nested section
is the exact canonical output of its owner, embedded untouched. It does
not execute a reasoning run, does not invoke the Task 140 replay
engine, does not reconstruct the Task 140 ``original_result`` (request
material that is not historically persisted), does not mutate
persistence, and never calls provider/model infrastructure.

Deterministic overall status (mutually exclusive, priority order):

* ``NO_MATERIAL`` -- no persisted COMPLETED receipt exists for the
  session; nothing was inspected. A legitimate result, never reported
  as inconsistent.
* ``MALFORMED`` -- material exists but is structurally unverifiable
  per the Task 141 verdict (the canonical contract could not be
  evaluated); nothing is claimed about it cryptographically.
* ``INCONSISTENT`` -- readable material contradicts the canonical
  contract (tamper/identity/binding violations detected by the Task
  139/141 audits).
* ``UNVERIFIABLE`` -- material exists but required historical binding
  evidence cannot be independently verified (the Task 141
  ``REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED`` verdict: receipts written
  before binding evidence existed). Distinct from tampering and from
  structural corruption. The Task 139 counterpart token
  ``FINGERPRINT_PROVENANCE_NOT_PERSISTED`` is deliberately NOT an
  UNVERIFIABLE driver on its own: it also appears for genuinely
  malformed material (a missing snapshot additionally fails the
  Task 137 projectability check with ``RECEIPT_UNREADABLE``), so
  status uses the precise Task 141 verdict for that distinction,
  while both tokens remain visible verbatim in the findings.
* ``VERIFIABLE`` -- all persisted material is internally consistent
  and verifiable across every assembled audit.

The architectural Task 141 ``original_result_provenance =
NOT_PERSISTED`` gap alone NEVER changes the overall status: missing
historical original-result evidence is preserved verbatim in the
embedded Task 141 section and surfaced through one explicit bundle
finding, but it is never treated as tampering and never downgrades an
otherwise clean bundle. Findings are ordered deterministically:
section order is fixed (Task 137, Task 138, Task 139, Task 141), each
owning audit's per-receipt findings already follow the durable
Task 138 history ordering (creation time, then receipt id), issue
tokens within one receipt are sorted lexicographically, and each
issue token is reused verbatim from its owning contract -- never a
new vocabulary. No timestamps generated during inspection, no random
identifiers, no mutable runtime information.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_inspection_bundle import (
    ReasoningRunInspectionBundleRead,
)
from rop.services.reasoning_run_receipt import ReasoningRunReceiptService
from rop.services.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditService,
)
from rop.services.reasoning_run_replay_consistency_audit import (
    REPLAY_STATE_INCONSISTENT,
    REPLAY_STATE_MALFORMED,
    REPLAY_STATE_SATISFIED,
    ReasoningRunReplayConsistencyAuditService,
)

REASONING_RUN_INSPECTION_BUNDLE_SOURCE_TASK_142 = (
    "REASONING_RUN_INSPECTION_BUNDLE_TASK_142"
)

# Deterministic overall inspection statuses (see module docstring).
INSPECTION_STATUS_NO_MATERIAL = "NO_MATERIAL"
INSPECTION_STATUS_VERIFIABLE = "VERIFIABLE"
INSPECTION_STATUS_INCONSISTENT = "INCONSISTENT"
INSPECTION_STATUS_UNVERIFIABLE = "UNVERIFIABLE"
INSPECTION_STATUS_MALFORMED = "MALFORMED"

#: Fixed finding-section order: bundle-level Task 138 identity check,
#: then the Task 137 latest-receipt probe, then Task 139, then Task 141.
_FINDING_SECTION_ORDER = (
    "TASK_138",
    "TASK_137",
    "TASK_139",
    "TASK_141",
)

class ReasoningRunInspectionBundleContractError(Exception):
    """Task 142: the inspection bundle cannot be projected.

    Raised only for genuine contract-level failures -- an assembled
    bundle that cannot be validated against the strict canonical read
    schema despite every nested section being the exact canonical
    output of its owner. Never a client-input or medical error, and
    never a fabricated successful inspection.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunInspectionBundleService:
    """Read-only orchestration over the existing Task 137-141 audits."""

    def __init__(
        self,
        receipt_service: ReasoningRunReceiptService | None = None,
        provenance_audit_service: ReasoningRunReceiptProvenanceAuditService
        | None = None,
        replay_consistency_audit_service: ReasoningRunReplayConsistencyAuditService
        | None = None,
    ) -> None:
        # Reuse the owning services unchanged; this bundle adds no
        # validation of its own beyond status derivation.
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

        Purely read-only: delegates to the Task 138 history query, the
        Task 137 exact-identity inspection, the Task 139 provenance
        audit, and the Task 141 replay-consistency audit. No writes,
        no execution, no replay, no snapshot builds, no reads of
        mutable current session state, no provider/model calls. The
        requested session identity is always echoed.
        """
        history = self.receipt_service.history(db, session_id)
        receipts = history["receipts"]
        examined = len(receipts)

        if examined == 0:
            # No completed reasoning-run material: still inspect the
            # canonical identity so the Task 137 section is genuinely
            # absent (found=False), never fabricated.
            receipt_inspection = self.receipt_service.inspect(
                db, session_id, self._absent_identity()
            )
        else:
            # Deterministic "latest" is the LAST item of the durable
            # Task 138 history ordering (created_at asc, id asc) --
            # never database row order alone, never runtime recency.
            latest = receipts[-1]
            receipt_inspection = self.receipt_service.inspect(
                db, session_id, latest["input_fingerprint"]
            )

        provenance_audit = self.provenance_audit_service.audit(db, session_id)
        replay_audit = self.replay_consistency_audit_service.audit(db, session_id)

        findings = self._collect_findings(
            session_id=session_id,
            history=history,
            receipt_inspection=receipt_inspection,
            provenance_audit=provenance_audit,
            replay_audit=replay_audit,
        )
        status = self._derive_status(
            examined=examined,
            provenance_audit=provenance_audit,
            replay_audit=replay_audit,
        )

        bundle: dict[str, Any] = {
            "available": True,
            "requested_session_id": str(session_id),
            "inspection_status": status,
            "completed_receipts_examined": examined,
            "receipt_inspection": receipt_inspection,
            "history": history,
            "provenance_audit": provenance_audit,
            "replay_consistency_audit": replay_audit,
            "findings": findings,
            "bundle_source": REASONING_RUN_INSPECTION_BUNDLE_SOURCE_TASK_142,
        }
        try:
            validated = ReasoningRunInspectionBundleRead.model_validate(bundle)
        except ValidationError as exc:
            raise ReasoningRunInspectionBundleContractError(
                "BUNDLE_UNPROJECTABLE",
                "assembled inspection bundle cannot be projected onto the "
                "canonical bundle schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _absent_identity() -> str:
        """Canonical fingerprint shape that can never match a receipt.

        Used only so the Task 137 section reports an explicit
        ``found=False`` for a session with no completed material --
        the identity is well-formed (never normalized or repaired)
        and the lookup stays exact; no receipt is ever fabricated.
        """
        return "0" * 64

    @staticmethod
    def _derive_status(
        *,
        examined: int,
        provenance_audit: dict[str, Any],
        replay_audit: dict[str, Any],
    ) -> str:
        """Derive the deterministic overall status from owned verdicts.

        Decides purely from the assembled Task 139/141 results -- no
        re-validation, no new evidence. The architectural Task 141
        ``original_result_provenance = NOT_PERSISTED`` value is
        deliberately ignored here: it is an evidence limitation
        reported verbatim in the embedded section, never a status
        driver and never tampering.
        """
        if examined == 0:
            return INSPECTION_STATUS_NO_MATERIAL

        replay_state = replay_audit["replay_state"]
        replay_issues: set[str] = set()
        for finding in replay_audit["findings"]:
            replay_issues |= set(finding["replay_issues"])

        # 1. Readable material that contradicts the canonical
        # contract: the Task 141 INCONSISTENT state or an explicit
        # tamper verdict detected by the owning audit.
        if replay_state == REPLAY_STATE_INCONSISTENT:
            return INSPECTION_STATUS_INCONSISTENT
        if "REPLAY_RECORD_TAMPERED" in replay_issues:
            return INSPECTION_STATUS_INCONSISTENT

        # 2. Any other Task 139 invalid receipt is a detected
        # contradiction over persisted material.
        if not provenance_audit["audit_consistent"]:
            return INSPECTION_STATUS_INCONSISTENT

        # 3. Material exists but its required historical binding
        # evidence was never persisted (legacy receipts): the ONLY
        # Task 141 issue is REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED.
        # Unverifiable -- explicitly NOT tampering and NOT structural
        # corruption, and never claimed cryptographically wrong.
        if replay_state == REPLAY_STATE_MALFORMED:
            if replay_issues == {"REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED"}:
                return INSPECTION_STATUS_UNVERIFIABLE
            # 4. Structural malformation makes the canonical contract
            # unevaluable; nothing is claimed about it.
            return INSPECTION_STATUS_MALFORMED

        # 5. Fully clean persisted material.
        if replay_state == REPLAY_STATE_SATISFIED:
            return INSPECTION_STATUS_VERIFIABLE
        return INSPECTION_STATUS_UNVERIFIABLE

    @staticmethod
    def _collect_findings(
        *,
        session_id: UUID,
        history: dict[str, Any],
        receipt_inspection: dict[str, Any],
        provenance_audit: dict[str, Any],
        replay_audit: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Assemble the deterministic flat finding list.

        Reuses each owning contract's own findings and issue tokens
        verbatim; adds no new issue vocabulary. Section order is
        fixed, per-receipt order follows the durable Task 138 history
        ordering, and issue tokens within one receipt are sorted
        lexicographically -- identical inputs always yield an
        identical list.
        """
        findings: list[dict[str, Any]] = []

        # Task 138 section: the history must belong to the exact
        # requested session (echoed identity check, not re-validation).
        if str(history["session_id"]) != str(session_id):
            findings.append(
                {
                    "source_task": "TASK_138",
                    "receipt_id": "",
                    "input_fingerprint": "",
                    "issue": "HISTORY_SESSION_MISMATCH",
                }
            )

        # Task 137 section: surface the owning contract's own
        # invariant token when the latest persisted receipt identity
        # cannot be canonically inspected/projected.
        if not receipt_inspection["found"] and history["receipts"]:
            findings.append(
                {
                    "source_task": "TASK_137",
                    "receipt_id": "",
                    "input_fingerprint": receipt_inspection[
                        "requested_input_fingerprint"
                    ],
                    "issue": "RECEIPT_UNREADABLE",
                }
            )

        # Task 139 section: one finding per issue token, per receipt,
        # in durable history order, tokens sorted.
        for finding in provenance_audit["findings"]:
            for issue in sorted(set(finding["provenance_issues"])):
                findings.append(
                    {
                        "source_task": "TASK_139",
                        "receipt_id": finding["receipt_id"],
                        "input_fingerprint": finding["input_fingerprint"],
                        "issue": issue,
                    }
                )

        # Task 141 section: per-receipt issue tokens plus the explicit
        # architectural original-result provenance statement. The
        # NOT_PERSISTED note is an evidence limitation, never a
        # tampering claim, and never affects the derived status.
        for finding in replay_audit["findings"]:
            for issue in sorted(set(finding["replay_issues"])):
                findings.append(
                    {
                        "source_task": "TASK_141",
                        "receipt_id": finding["receipt_id"],
                        "input_fingerprint": finding["input_fingerprint"],
                        "issue": issue,
                    }
                )
        findings.append(
            {
                "source_task": "TASK_141",
                "receipt_id": "",
                "input_fingerprint": "",
                "issue": (
                    "ORIGINAL_RESULT_"
                    + replay_audit["original_result_provenance"]
                ),
            }
        )

        # Stable section grouping without disturbing intra-section
        # deterministic order (Python's sort is stable).
        rank = {task: index for index, task in enumerate(_FINDING_SECTION_ORDER)}
        return sorted(findings, key=lambda item: rank[item["source_task"]])

"""Task 142: unified deterministic reasoning-run inspection bundle contract.

The strict read-only inspection response for one exact session's already
persisted reasoning-run inspection material. Aggregates the existing
deterministic Task 137 (receipt inspection), Task 138 (receipt history),
Task 139 (provenance audit), and Task 141 (replay consistency audit)
results into a single presentation contract. No reasoning execution, no
replay, no writes, no provider/model logic live here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_run_receipt import (
    ReasoningRunReceiptHistoryRead,
    ReasoningRunReceiptInspectionRead,
)
from rop.schemas.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditRead,
)
from rop.schemas.reasoning_run_replay_consistency_audit import (
    ReasoningRunReplayConsistencyAuditRead,
)


class ReasoningRunInspectionRead(BaseModel):
    """Strict unified inspection bundle for one session's reasoning run.

    ``receipt_inspections`` holds one exact-identity Task 137 inspection
    per persisted COMPLETED receipt (in deterministic history order), so
    no fingerprint is invented and no "latest receipt" substitution
    applies. ``receipt_history`` is the Task 138 history,
    ``provenance_audit`` the Task 139 audit, and
    ``replay_consistency_audit`` the Task 141 audit, each reused
    unchanged.

    ``overall_status`` is derived deterministically from those results:

    * ``NO_MATERIAL`` -- no completed reasoning-run material exists;
    * ``VERIFIABLE`` -- persisted material is internally consistent and
      verifiable;
    * ``INCONSISTENT`` -- persisted material contains a detected
      contradiction/tampering/inconsistency;
    * ``UNVERIFIABLE`` -- material exists but some required historical
      evidence cannot be independently verified.

    The architectural Task 140 ``original_result`` gap (reported by the
    Task 141 audit as ``original_result_provenance == NOT_PERSISTED``)
    is preserved as an evidence limitation inside
    ``replay_consistency_audit`` and never drives ``overall_status``:
    it is neither tampering nor verification.

    ``findings`` is the deterministic sorted set of issue codes reported
    by the underlying audits. ``inspection_source`` is the canonical
    identifier of this inspection contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    receipt_inspections: list[ReasoningRunReceiptInspectionRead]
    receipt_history: ReasoningRunReceiptHistoryRead
    provenance_audit: ReasoningRunReceiptProvenanceAuditRead
    replay_consistency_audit: ReasoningRunReplayConsistencyAuditRead
    overall_status: Literal["NO_MATERIAL", "VERIFIABLE", "INCONSISTENT", "UNVERIFIABLE"]
    findings: list[str]
    inspection_source: str

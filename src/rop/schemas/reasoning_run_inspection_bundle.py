"""Task 142: unified deterministic reasoning-run inspection bundle contract.

The strict read-only response for inspecting one session's persisted
reasoning-run evidence through a single canonical endpoint. The bundle
is a pure composition contract: the nested Task 137 receipt-inspection
result, Task 138 history result, Task 139 provenance audit result, and
Task 141 replay-consistency audit result are the exact canonical
outputs of their owning services, embedded untouched -- never
re-derived, re-validated with weaker rules, or duplicated here.

``inspection_status`` is the deterministic overall verdict over the
assembled results: ``NO_MATERIAL`` (no completed reasoning-run
inspection material exists), ``VERIFIABLE`` (persisted material is
internally consistent and verifiable), ``INCONSISTENT`` (persisted
material contains a detected contradiction/tampering/inconsistency),
``UNVERIFIABLE`` (material exists but some required historical
evidence cannot be independently verified), and ``MALFORMED``
(material exists but is structurally unverifiable, so nothing is
claimed about it).

The Task 140 ``original_result`` is request material and is not
historically persisted. The bundle preserves that boundary exactly as
Task 141 established it: ``replay_consistency_audit.
original_result_provenance`` carries the Task 141 verdict verbatim
(always ``NOT_PERSISTED`` under the current architecture), no original
replay result is ever reconstructed, and an architectural
``NOT_PERSISTED`` gap alone never drives the bundle status to
``INCONSISTENT`` -- missing historical evidence is never reported as
tampering.

No ORM internals, no database details, no provider/model information,
no timestamps generated during inspection. ``bundle_source`` is a
fixed structural identifier.
"""

from __future__ import annotations

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


class ReasoningRunInspectionFindingRead(BaseModel):
    """One deterministic finding explaining why an inspection is not clean.

    ``source_task`` names the owning Task 137/138/139/141 contract the
    finding came from; ``issue`` is that contract's own issue token,
    reused verbatim (never a new vocabulary); ``receipt_id`` and
    ``input_fingerprint`` identify the audited persisted material when
    the finding is per-receipt, and are empty strings when the finding
    is bundle-level. Findings are ordered deterministically by the
    bundle service, never by runtime dict iteration or database row
    order alone.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    source_task: str
    receipt_id: str
    input_fingerprint: str
    issue: str


class ReasoningRunInspectionBundleRead(BaseModel):
    """Task 142: unified read-only inspection bundle for one session.

    Every section is the exact canonical output of its owner:

    * ``receipt_inspection`` -- Task 137 inspection of the session's
      latest persisted COMPLETED receipt identity (all ``None``
      fields when the session has no completed receipt at all --
      never a fabricated receipt);
    * ``history`` -- Task 138 deterministic completed-receipt history;
    * ``provenance_audit`` -- Task 139 provenance consistency audit;
    * ``replay_consistency_audit`` -- Task 141 replay-material
      consistency audit, whose ``original_result_provenance``
      semantics (``NOT_PERSISTED`` = architectural evidence gap, not
      tampering) are preserved untouched.

    ``inspection_status`` is the deterministic overall verdict and
    ``findings`` carries the deterministic finding list sufficient to
    understand why the overall inspection is not fully satisfactory.
    ``completed_receipts_examined`` is the deterministic count of
    persisted COMPLETED receipts the bundle was assembled from (zero
    yields ``NO_MATERIAL``). Extra fields are forbidden at every
    level; SQLAlchemy objects, ORM internals, and database metadata
    are not exposed.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    requested_session_id: str
    inspection_status: str
    completed_receipts_examined: int
    receipt_inspection: ReasoningRunReceiptInspectionRead | None
    history: ReasoningRunReceiptHistoryRead
    provenance_audit: ReasoningRunReceiptProvenanceAuditRead
    replay_consistency_audit: ReasoningRunReplayConsistencyAuditRead
    findings: list[ReasoningRunInspectionFindingRead]
    bundle_source: str

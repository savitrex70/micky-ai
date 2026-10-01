"""Task 137: canonical deterministic reasoning-run receipt inspection contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunReceiptRead(BaseModel):
    """Strict read view of one canonical completed reasoning-run receipt.

    Exposes only the approved durable receipt fields persisted by the
    existing append-only ``ReasoningRunReceipt`` model (Tasks 126/127):
    the receipt identifier, the canonical ``(session_id,
    input_fingerprint)`` identity, the stored engine-external
    continuity projection, the persisted outcome, and the created
    timestamp.

    Provenance semantics are fixed by the durable contract:
    ``input_fingerprint`` is the fingerprint of the exact canonical
    Task 124 snapshot used by the completed execution -- never a
    fingerprint of current state; ``exogenous_snapshot`` is the stored
    engine-external continuity projection captured at completion. A
    receipt is immutable historical evidence: this schema never
    reinterprets, recomputes, or repairs it. SQLAlchemy objects,
    ORM internals, and database metadata are not exposed.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    session_id: str
    input_fingerprint: str
    exogenous_snapshot: dict
    outcome: str
    created_at: str


class ReasoningRunReceiptInspectionRead(BaseModel):
    """Task 137: result of inspecting one canonical receipt identity.

    ``found`` distinguishes exactly the two deterministic outcomes: a
    matching completed receipt exists (``receipt`` carries the strict
    ``ReasoningRunReceiptRead`` projection) or no matching completed
    receipt exists (``receipt`` is ``None``) -- never a fabricated,
    recomputed, or substituted receipt. The requested canonical
    identity ``(requested_session_id, requested_input_fingerprint)``
    is always echoed so a caller can verify the lookup was exact.
    ``receipt_source`` is a fixed structural identifier.
    """

    model_config = ConfigDict(extra="forbid")

    found: bool
    available: bool
    requested_session_id: str
    requested_input_fingerprint: str
    receipt: ReasoningRunReceiptRead | None
    receipt_source: str

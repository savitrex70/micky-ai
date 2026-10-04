"""Task 144: Stage 6 pre-LLM deterministic core completion gate contract.

The strict read-only gate response for one exact session's Stage 6
deterministic reasoning core. A decision surface only: it classifies
already computed Task 142 inspection and Task 143 diagnostics results
into READY / BLOCKED / UNVERIFIABLE / NO_MATERIAL without
reimplementing any validation logic. This gate does not start Stage 7:
no LLM runtime, no model execution, no provider integration, no
replay, no writes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6GateRead(BaseModel):
    """Strict Stage 6 completion gate for one session's reasoning core.

    ``gate_status`` is the canonical verdict:

    * ``READY`` -- Stage 6 deterministic core satisfies the completion
      conditions (persisted material verifies end to end);
    * ``BLOCKED`` -- a deterministic correctness/integrity requirement
      is not satisfied (contradiction, tampering, or structural
      anomaly in persisted material);
    * ``UNVERIFIABLE`` -- required evidence is insufficient to
      establish readiness (missing historical binding evidence);
    * ``NO_MATERIAL`` -- no completed reasoning-run material exists
      from which readiness can be established.

    ``ready`` is true exactly when ``gate_status`` is ``READY``. The
    component statuses reuse the Task 142/143 vocabularies verbatim;
    ``Task 144`` adds no new inspection implementation. The
    architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never blocks the gate
    on its own. ``findings`` deterministically explains every
    non-READY state. ``gate_source`` is the canonical identifier of
    this gate contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    ready: bool
    receipt_status: Literal["NO_MATERIAL", "VERIFIED", "INCOMPLETE"]
    history_status: Literal["NO_MATERIAL", "CONSISTENT", "MISMATCH"]
    provenance_status: Literal[
        "NO_MATERIAL", "CONSISTENT", "INCONSISTENT", "UNVERIFIABLE"
    ]
    replay_status: Literal["NO_MATERIAL", "CONSISTENT", "INCONSISTENT", "UNVERIFIABLE"]
    inspection_status: Literal[
        "NO_MATERIAL", "VERIFIABLE", "INCONSISTENT", "UNVERIFIABLE"
    ]
    diagnostics_status: Literal["NO_MATERIAL", "HEALTHY", "DEGRADED", "UNHEALTHY"]
    finding_count: int
    findings: list[str]
    gate_source: str

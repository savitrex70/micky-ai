"""Task 143: Stage 6 operational diagnostics boundary contract.

The strict read-only diagnostics response for one exact session's
persisted Stage 6 reasoning-run inspection state. A presentation
boundary only: it reports coarse deterministic statuses derived from
the existing Task 142 unified inspection bundle (which itself reuses
Tasks 137-141) without reimplementing any validation logic. No
reasoning execution, no replay, no writes, no provider/model logic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunDiagnosticsRead(BaseModel):
    """Strict operational diagnostics for one session's reasoning run.

    ``completed_receipts`` counts persisted COMPLETED receipts.
    ``inspection_status`` is the Task 142 overall status verbatim.
    ``provenance_status`` and ``replay_consistency_status`` are coarse
    presentation mappings over the already computed Task 139/141 audit
    outputs: ``NO_MATERIAL`` (nothing persisted), ``CONSISTENT``
    (persisted material verifies), ``INCONSISTENT`` (persisted material
    contradicts its own evidence), ``UNVERIFIABLE`` (material exists
    but required historical evidence was never persisted). An evidence
    limitation is never reported as tampering: the architectural Task
    140 ``original_result`` gap (``NOT_PERSISTED``) is not an issue code
    and never drives any status here.

    ``findings`` is the deterministic sorted issue set inherited from
    the Task 142 bundle; ``finding_count`` is its length.
    ``diagnostics_source`` is the canonical identifier of this
    diagnostics contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    session_exists: bool
    completed_receipts: int
    inspection_status: Literal[
        "NO_MATERIAL", "VERIFIABLE", "INCONSISTENT", "UNVERIFIABLE"
    ]
    provenance_status: Literal[
        "NO_MATERIAL", "CONSISTENT", "INCONSISTENT", "UNVERIFIABLE"
    ]
    replay_consistency_status: Literal[
        "NO_MATERIAL", "CONSISTENT", "INCONSISTENT", "UNVERIFIABLE"
    ]
    finding_count: int
    findings: list[str]
    diagnostics_source: str

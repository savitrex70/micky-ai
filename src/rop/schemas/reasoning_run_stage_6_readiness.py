"""Task 146: canonical Stage 6 release readiness report contract.

The strict read-only readiness response for one exact session's Stage
6 deterministic core. A reporting/orchestration boundary over the
existing Task 144 gate, Task 145 gate consistency audit, and Task 143
diagnostics: READY requires the gate to be READY, the gate audit to
agree, and no blocking deterministic contradiction. No reasoning
behavior is introduced here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6ReadinessRead(BaseModel):
    """Strict Stage 6 release readiness report for one session.

    ``readiness_status`` is the canonical verdict: ``NO_MATERIAL``
    (no completed material to evaluate), ``READY`` (gate READY, gate
    audit consistent, no blocking contradiction),
    ``BLOCKED`` (real contradiction, integrity violation, or
    inconsistent gate state), ``UNVERIFIABLE`` (insufficient evidence
    without a direct contradiction -- never collapsed into BLOCKED).
    ``release_ready`` is true exactly when ``readiness_status`` is
    ``READY``, so readiness is never reported when Task 145 finds the
    gate inconsistent. ``gate_status``, ``gate_consistent``, and
    ``diagnostics_status`` reuse the Task 144/145/143 vocabularies
    verbatim. The architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never blocks readiness
    on its own. ``readiness_source`` is the canonical identifier of
    this report contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    readiness_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    release_ready: bool
    gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    gate_consistent: bool
    diagnostics_status: Literal["NO_MATERIAL", "HEALTHY", "DEGRADED", "UNHEALTHY"]
    finding_count: int
    findings: list[str]
    readiness_source: str

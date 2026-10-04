"""Task 148: canonical Stage 6 release evidence bundle contract.

The strict read-only evidence response collecting the minimal
canonical evidence supporting the Stage 6 release-readiness decision.
A compact evidence index over the existing Task 144 gate, Task 145
gate consistency audit, Task 146 readiness report, and Task 147
readiness consistency audit -- never the full Task 142-147 payloads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6EvidenceRead(BaseModel):
    """Strict Stage 6 release evidence bundle for one session.

    ``stage_6_status`` is the canonical decision state (``NO_MATERIAL``
    / ``READY`` / ``BLOCKED`` / ``UNVERIFIABLE``) with the established
    meanings. ``evidence_available`` reports whether sufficient
    deterministic persisted evidence exists to support the decision --
    never claimed when the canonical services report it unavailable.
    ``release_ready`` is true exactly when ``stage_6_status`` is
    ``READY`` with both consistency audits agreeing, so release
    readiness can never be reported when gate or readiness consistency
    fails. ``gate_status``, ``gate_consistent``, ``readiness_status``,
    and ``readiness_consistent`` reuse the Task 144-147 vocabularies
    verbatim. The architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never drives this
    bundle. ``evidence_source`` is the canonical identifier of this
    evidence contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    evidence_available: bool
    stage_6_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    release_ready: bool
    gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    gate_consistent: bool
    readiness_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    readiness_consistent: bool
    finding_count: int
    findings: list[str]
    evidence_source: str

"""Task 152: final Stage 6 deterministic release certification contract.

The strict read-only certification response for the Stage 6 pre-LLM
core. The last Stage 6 boundary: one canonical answer to whether the
deterministic core satisfies all release-readiness and consistency
requirements over the existing canonical evidence chain (Tasks
144-151). Certification confirms the deterministic core only; it does
not execute, configure, select, or integrate any LLM/provider.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6CertificationRead(BaseModel):
    """Strict Stage 6 release certification for one session.

    ``certification_status`` is the canonical verdict:
    ``NO_MATERIAL`` (no completed material to certify),
    ``CERTIFIED`` (every invariant holds: READY gate, consistent gate
    audit, READY readiness, consistent readiness audit,
    available/consistent evidence, valid complete manifest, consistent
    manifest audit, and no blocking contradiction or unverifiable
    surface anywhere), ``BLOCKED`` (real contradiction, integrity
    problem, or consistency failure), ``UNVERIFIABLE`` (insufficient
    evidence without a direct contradiction -- never collapsed into
    BLOCKED). ``certified`` and ``release_ready`` are true exactly
    when ``certification_status`` is ``CERTIFIED``, so certification
    can never override a lower-level inconsistency. The component
    fields reuse the Task 144-151 vocabularies verbatim. The
    architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never blocks
    certification on its own. ``certification_source`` is the canonical
    identifier of this certification contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    certification_status: Literal["CERTIFIED", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    certified: bool
    release_ready: bool
    gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    gate_consistent: bool
    readiness_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    readiness_consistent: bool
    evidence_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    evidence_consistent: bool
    manifest_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    manifest_consistent: bool
    finding_count: int
    findings: list[str]
    certification_source: str

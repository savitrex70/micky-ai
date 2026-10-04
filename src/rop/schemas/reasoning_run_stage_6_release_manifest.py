"""Task 150: canonical Stage 6 release package manifest contract.

The strict read-only manifest response indexing the canonical Stage 6
evidence surfaces and their current readiness/consistency state. A
metadata/index boundary only: compact machine-readable entries over
already computed Task 142-149 results, never their complete responses
and never another validation or readiness algorithm.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6ReleaseManifestComponentRead(BaseModel):
    """Strict entry for one canonical Stage 6 evidence surface.

    ``component_id`` is the canonical source identifier already
    established by the owning task (e.g.
    ``REASONING_RUN_STAGE_6_GATE_TASK_144``); ``component_kind`` names
    the surface role; ``status`` is the surface's own deterministic
    verdict; ``consistent`` reports whether an audit surface agrees
    with its evidence (always true for pure report surfaces, whose own
    coherence is guaranteed by their strict schemas);
    ``available`` reports whether the surface evaluated successfully.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    component_id: str
    component_kind: str
    status: str
    consistent: bool
    available: bool


class ReasoningRunStage6ReleaseManifestRead(BaseModel):
    """Strict Stage 6 release package manifest for one session.

    ``components`` lists the eight required canonical surfaces in
    stable order: Task 142 inspection, Task 143 diagnostics, Task 144
    gate, Task 145 gate consistency audit, Task 146 readiness, Task 147
    readiness consistency audit, Task 148 evidence, Task 149 evidence
    consistency audit. ``manifest_status`` is the package verdict
    (``NO_MATERIAL`` / ``READY`` / ``BLOCKED`` / ``UNVERIFIABLE``);
    ``release_ready`` is true exactly when ``manifest_status`` is
    ``READY``, which entails every required invariant (READY gate,
    consistent audits, READY readiness, available consistent
    evidence). The manifest never overrides a lower-level canonical
    inconsistency. The architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never drives this
    manifest. ``manifest_source`` is the canonical identifier of this
    manifest contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    manifest_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    release_ready: bool
    finding_count: int
    findings: list[str]
    components: list[ReasoningRunStage6ReleaseManifestComponentRead]
    manifest_source: str

"""Task 174: Stage 7 release-readiness projection contract.

Strict read-only projection that answers whether the fully audited Stage 7
evidence is eligible to be considered release-ready. The projection never
releases, persists, executes, or invokes anything - it only projects
evidence.

Statuses: READY (eligible for release), BLOCKED (not eligible due to
blocking evidence), UNAVAILABLE (insufficient evidence but no blocking
state).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174 = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174"
)


class ReasoningRunStage7ReleaseReadinessProjectionRead(BaseModel):
    """Strict read model for one Stage 7 release-readiness projection.

    ``readiness_status`` is the single projected verdict: ``READY`` when
    the fully audited Stage 7 evidence is eligible to be considered
    release-ready, ``BLOCKED`` when not eligible due to blocking evidence,
    and ``UNAVAILABLE`` when evidence is insufficient but no blocking
    state exists. ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    readiness_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    attestation_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    projection_source: str

    @model_validator(mode="after")
    def _coherent_projection(self) -> ReasoningRunStage7ReleaseReadinessProjectionRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        # READY requires all conditions
        if self.readiness_status == "READY":
            if self.attestation_status != "CERTIFIED":
                raise ValueError("READY requires CERTIFIED attestation")
            if self.attestation_audit_status != "CONSISTENT":
                raise ValueError("READY requires CONSISTENT attestation audit")
            if self.consistency_status != "CONSISTENT":
                raise ValueError("READY requires CONSISTENT consistency")
            if self.finding_count != 0:
                raise ValueError("READY requires a finding-free projection")
        # BLOCKED requires genuine blocking evidence
        if self.readiness_status == "BLOCKED":
            blocking = (
                self.attestation_status == "BLOCKED"
                or self.attestation_audit_status == "INCONSISTENT"
                or self.consistency_status == "INCONSISTENT"
                or self.finding_count > 0
            )
            if not blocking:
                raise ValueError("BLOCKED requires published blocking evidence")
        return self

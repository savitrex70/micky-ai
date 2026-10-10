"""Task 183: Stage 7 final release-gate projection contract.

The projection deterministically summarizes the published Task 180
attestation, Task 181 independent audit, and Task 182 consistency verdict.
It does not authorize or execute a release.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183 = (
    "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_TASK_183"
)


class ReasoningRunStage7FinalReleaseGateProjectionRead(BaseModel):
    """Strict read model for one final release-gate projection."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    attestation_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    projection_source: str

    @model_validator(mode="after")
    def _coherent_projection(self) -> ReasoningRunStage7FinalReleaseGateProjectionRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.projection_source != (
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
        ):
            raise ValueError("projection_source must be the canonical Task 183 source")
        if self.gate_status == "READY":
            if not self.session_id:
                raise ValueError("READY requires a valid session_id")
            if self.attestation_status != "CERTIFIED":
                raise ValueError("READY requires CERTIFIED attestation")
            if self.attestation_audit_status != "CONSISTENT":
                raise ValueError("READY requires a CONSISTENT attestation audit")
            if self.consistency_status != "CONSISTENT":
                raise ValueError("READY requires CONSISTENT consistency")
            if self.findings:
                raise ValueError("READY requires a finding-free projection")
        elif self.gate_status == "BLOCKED":
            blocking = (
                self.attestation_status == "BLOCKED"
                or self.attestation_audit_status == "INCONSISTENT"
                or self.consistency_status == "INCONSISTENT"
            )
            if not blocking:
                raise ValueError("BLOCKED requires published blocking evidence")
        else:
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            blocking = (
                self.attestation_status == "BLOCKED"
                or self.attestation_audit_status == "INCONSISTENT"
                or self.consistency_status == "INCONSISTENT"
            )
            if blocking:
                raise ValueError("UNAVAILABLE must not hide readable blocking evidence")
        return self

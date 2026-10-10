"""Task 185: consistency contract for the final release-gate audit."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185 = (
    "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_TASK_185"
)


class ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(BaseModel):
    """Strict read model for one Task 185 gate-audit consistency verdict."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    gate_consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    consistency_source: str

    @model_validator(mode="after")
    def _coherent_consistency(
        self,
    ) -> ReasoningRunStage7FinalReleaseGateAuditConsistencyRead:
        if self.available != (self.gate_consistency_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (gate_consistency_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.gate_consistency_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (gate_consistency_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.consistency_source != (
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
        ):
            raise ValueError("consistency_source must be the canonical Task 185 source")
        if self.published_gate_status is None:
            if self.gate_consistency_status != "UNAVAILABLE":
                raise ValueError(
                    "unknown published gate status requires an UNAVAILABLE consistency"
                )
            if "PROJECTION_INVALID" not in self.findings:
                raise ValueError(
                    "unknown published gate status requires PROJECTION_INVALID"
                )
        if self.gate_consistency_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            return self
        if self.gate_consistency_status == "CONSISTENT":
            if not self.session_id:
                raise ValueError("CONSISTENT requires a session identity")
            if self.published_gate_status != self.expected_gate_status:
                raise ValueError(
                    "CONSISTENT requires published and expected gate statuses to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free consistency")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

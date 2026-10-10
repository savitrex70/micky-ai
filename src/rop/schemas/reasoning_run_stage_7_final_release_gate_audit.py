"""Task 184: independent Stage 7 final release-gate audit contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184 = (
    "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_TASK_184"
)


class ReasoningRunStage7FinalReleaseGateAuditRead(BaseModel):
    """Strict read model for one independent final release-gate audit."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    gate_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7FinalReleaseGateAuditRead:
        if self.available != (self.gate_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (gate_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.gate_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (gate_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.audit_source != (
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184
        ):
            raise ValueError("audit_source must be the canonical Task 184 source")
        if self.published_gate_status is None:
            if self.gate_audit_status != "UNAVAILABLE":
                raise ValueError(
                    "an unknown published gate status requires an UNAVAILABLE audit"
                )
            if "PROJECTION_INVALID" not in self.findings:
                raise ValueError(
                    "an unknown published gate status requires PROJECTION_INVALID"
                )
        if self.gate_audit_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            return self
        if self.gate_audit_status == "CONSISTENT":
            if not self.session_id:
                raise ValueError("CONSISTENT requires a session identity")
            if self.published_gate_status != self.expected_gate_status:
                raise ValueError(
                    "CONSISTENT requires published and expected gate status to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

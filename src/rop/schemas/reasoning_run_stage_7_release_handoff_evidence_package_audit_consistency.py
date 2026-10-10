"""Task 188: consistency contract for the Task 186 package and Task 187 audit."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188 = (  # noqa: E501
    "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_188"
)


class ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead(BaseModel):
    """Strict verdict for the binding between one handoff package and its audit."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    finding_count: int
    findings: list[str]
    consistency_source: str

    @model_validator(mode="after")
    def _coherent_consistency(
        self,
    ) -> ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead:
        if self.available != (self.consistency_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (consistency_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.consistency_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (consistency_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.consistency_status == "UNAVAILABLE":
            if self.session_id:
                raise ValueError("UNAVAILABLE must not claim a session identity")
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
        elif self.consistency_status == "CONSISTENT":
            if not self.session_id:
                raise ValueError("CONSISTENT requires a session identity")
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free consistency check")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        if (
            self.consistency_source
            != REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188  # noqa: E501
        ):
            raise ValueError("consistency_source must be the canonical Task 188 source")
        return self

"""Task 187: independent audit contract for the Task 186 handoff package."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187 = (
    "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_TASK_187"
)


class ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead(BaseModel):
    """Strict read model for one independent Task 186 package audit."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    package_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(
        self,
    ) -> ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead:
        if self.available != (self.package_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (package_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.package_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (package_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.audit_source != (
            REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187
        ):
            raise ValueError("audit_source must be the canonical Task 187 source")
        if self.published_package_status is None:
            if self.package_audit_status != "UNAVAILABLE":
                raise ValueError(
                    "an unknown published package status requires an UNAVAILABLE audit"
                )
            if "PACKAGE_INVALID" not in self.findings:
                raise ValueError(
                    "an unknown published package status requires PACKAGE_INVALID"
                )
        if self.package_audit_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if self.session_id:
                raise ValueError("UNAVAILABLE must not claim a session identity")
            return self
        if self.package_audit_status == "CONSISTENT":
            if not self.session_id:
                raise ValueError("CONSISTENT requires a session identity")
            if self.published_package_status != self.expected_package_status:
                raise ValueError(
                    "CONSISTENT requires published and expected package statuses "
                    "to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

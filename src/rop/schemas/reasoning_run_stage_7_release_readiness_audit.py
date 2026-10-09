"""Task 175: independent Stage 7 release-readiness audit contract.

Strict read-only audit verdict for one published Task 174 release-readiness
projection. The audit independently derives the expected readiness from the
published Task 171-173 evidence rather than trusting Task 174.

The audit is pure, provider-neutral, and independent: it never calls Task
174, never calls Tasks 171-173 services, never recomputes fingerprints,
never invokes a provider, and never accesses a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175 = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_TASK_175"
)


class ReasoningRunStage7ReleaseReadinessAuditRead(BaseModel):
    """Strict read model for one independent Stage 7 release-readiness audit.

    ``readiness_audit_status`` is the single audit verdict: ``CONSISTENT``
    when the independently derived expected state matches the published Task
    174 projection, ``INCONSISTENT`` when the published evidence contradicts
    the independently derived result, and ``UNAVAILABLE`` for missing or
    malformed Task 174 input. ``published_readiness_status`` is the status
    the Task 174 projection claims, and ``expected_readiness_status`` is the
    status independently derived from the published evidence surfaces.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    readiness_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_readiness_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    expected_readiness_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7ReleaseReadinessAuditRead:
        if self.available != (self.readiness_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (readiness_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.readiness_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (readiness_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.readiness_audit_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            return self
        if self.readiness_audit_status == "CONSISTENT":
            if self.published_readiness_status != self.expected_readiness_status:
                raise ValueError(
                    "CONSISTENT requires published and expected "
                    "readiness status to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

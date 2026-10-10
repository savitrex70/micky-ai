"""Task 176: Stage 7 release-readiness audit consistency contract.

Strict read-only consistency verdict for the binding between Task 174
Release-Readiness Projection and Task 175 Release-Readiness Audit. The
consistency check verifies that the audit actually belongs to the exact
Task 174 projection being represented.

The consistency boundary is independent: it never calls Task 174 or Task 175
services, never recomputes fingerprints, never invokes a provider, and never
accesses a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176 = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_TASK_176"
)


class ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(BaseModel):
    """Strict consistency verdict for projection-audit binding.

    ``consistency_status`` is the single canonical verdict: ``CONSISTENT``
    when the audit is canonically bound to the exact Task 174 projection
    represented, ``INCONSISTENT`` when the audit is detached or contradicts
    the projection, and ``UNAVAILABLE`` when either input is missing or
    fails its own contract. ``findings`` are deterministic, sorted, and
    deduplicated; ``finding_count`` always equals ``len(findings)``.

    A valid Task 174 projection whose ``readiness_status`` is ``UNAVAILABLE``
    can still have a ``CONSISTENT`` audit and consistency result if the
    published evidence is validly bound and correctly represented.
    """

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
    ) -> ReasoningRunStage7ReleaseReadinessAuditConsistencyRead:
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
        if self.consistency_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ):
            raise ValueError("consistency_source must be the canonical Task 176 source")
        if self.consistency_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            return self
        if self.consistency_status == "CONSISTENT":
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free consistency check")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

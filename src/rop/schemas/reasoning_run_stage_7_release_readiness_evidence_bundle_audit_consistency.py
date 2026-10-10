"""Task 179: Stage 7 release-readiness bundle-audit consistency contract.

Strict read-only consistency verdict for the binding between Task 177
Release-Readiness Evidence Bundle and Task 178 Release-Readiness Evidence
Bundle Audit. The consistency check verifies that the Task 178 audit
actually belongs to the exact Task 177 bundle being represented.

The consistency boundary is independent: it never calls Task 177 or Task 178
services, never recomputes fingerprints, never invokes a provider, and never
accesses a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179 = (  # noqa: E501
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE"
    "_AUDIT_CONSISTENCY_TASK_179"
)


class ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead(BaseModel):
    """Strict consistency verdict for bundle-audit binding.

    ``consistency_status`` is the single canonical verdict: ``CONSISTENT``
    when the Task 178 audit is canonically bound to the exact Task 177
    bundle represented, ``INCONSISTENT`` when the audit is detached from or
    contradicts the bundle, and ``UNAVAILABLE`` when either input is missing
    or fails its own contract and the binding cannot be established.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.

    A valid Task 177 bundle whose ``bundle_status`` is ``UNAVAILABLE`` can
    still have a ``CONSISTENT`` audit and consistency result if the
    published evidence is validly bound and correctly represented. A Task
    178 audit verdict of ``UNAVAILABLE`` means the binding cannot be proven
    and yields ``UNAVAILABLE`` unless separate readable evidence proves a
    contradiction.
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
    ) -> ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead:
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
        canonical = REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_179  # noqa: E501
        if self.consistency_source != canonical:
            raise ValueError("consistency_source must be the canonical Task 179 source")
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

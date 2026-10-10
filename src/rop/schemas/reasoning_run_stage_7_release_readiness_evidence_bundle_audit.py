"""Task 178: Stage 7 release-readiness evidence bundle audit contract.

Strict read-only audit verdict for one published Task 177 release-readiness
evidence bundle. The audit independently derives the expected bundle state
from the supplied Task 174 projection, Task 175 audit, and Task 176
consistency record rather than trusting the published bundle.

The audit is pure, provider-neutral, and independent: it never calls Task
177, never calls Tasks 174-176 services, never recomputes fingerprints,
never executes a release, never invokes a provider, and never accesses a
database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178 = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_TASK_178"
)


class ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(BaseModel):
    """Strict read model for one independent release-readiness bundle audit.

    ``bundle_audit_status`` is the single audit verdict: ``CONSISTENT``
    when the independently derived expected bundle status matches the
    published Task 177 bundle, ``INCONSISTENT`` when the readable published
    evidence contradicts the independently derived result, and
    ``UNAVAILABLE`` for missing or malformed Task 177 input or when
    unavailable upstream records leave the binding unprovable.
    ``published_bundle_status`` is the status the Task 177 bundle claims,
    and ``expected_bundle_status`` is the status independently derived from
    the published Task 174-176 evidence. ``findings`` are deterministic,
    sorted, and deduplicated; ``finding_count`` always equals
    ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    bundle_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    expected_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(
        self,
    ) -> ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead:
        if self.available != (self.bundle_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (bundle_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.bundle_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (bundle_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.audit_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
        ):
            raise ValueError("audit_source must be the canonical Task 178 source")
        if self.bundle_audit_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            return self
        if self.bundle_audit_status == "CONSISTENT":
            if not self.session_id:
                raise ValueError("CONSISTENT requires a session identity")
            if self.published_bundle_status != self.expected_bundle_status:
                raise ValueError(
                    "CONSISTENT requires published and expected "
                    "bundle status to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

"""Task 173: Stage 7 final attestation consistency contract.

Strict read-only consistency verdict for the binding between Task 171 Final
Evidence Attestation and Task 172 Final Attestation Audit. The consistency
check verifies that the audit actually belongs to the exact attestation
being represented.

The consistency boundary is independent: it never calls Task 171 or
Task 172 services, never recomputes fingerprints, never invokes a
provider, and never accesses a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173 = (
    "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_TASK_173"
)


class ReasoningRunStage7FinalAttestationConsistencyRead(BaseModel):
    """Strict consistency verdict for attestation-audit binding.

    ``consistency_status`` is the single canonical verdict: ``CONSISTENT``
    when the audit is canonically bound to the exact Task 171 attestation
    represented, ``INCONSISTENT`` when the audit is detached or contradicts
    the attestation, and ``UNAVAILABLE`` when either input is missing or
    fails its own contract. ``findings`` are deterministic, sorted, and
    deduplicated; ``finding_count`` always equals ``len(findings)``.
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
    ) -> ReasoningRunStage7FinalAttestationConsistencyRead:
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
            REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173
        ):
            raise ValueError("consistency_source must be the canonical Task 173 source")
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

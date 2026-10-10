"""Task 182: Stage 7 release-readiness final-attestation consistency contract.

Strict read-only consistency verdict for the binding between the published
Task 180 release-readiness final attestation and the Task 181 independent
final-attestation audit. The consistency check verifies that the published
Task 180 attestation truly reflects the values the Task 181 audit independently
derived from the published Task 177-179 evidence.

The consistency verdict is one of CONSISTENT, INCONSISTENT and UNAVAILABLE.
CONSISTENT means the published attestation agrees with the independently
derived expected state. INCONSISTENT means readable evidence proves a
contradiction. UNAVAILABLE means the published attestation or the upstream
audit cannot be read and therefore no binding can be proven.

The consistency check never calls the Task 180 or Task 181 services, never
recomputes fingerprints, never executes a release, never invokes a provider,
and never accesses a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182 = "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_TASK_182"  # noqa: E501


class ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead(BaseModel):
    """Strict read model for one final-attestation consistency verdict.

    ``attestation_consistency_status`` is the single consistency verdict:
    CONSISTENT when the published Task 180 attestation agrees with the state
    independently derived by the Task 181 audit, INCONSISTENT when readable
    evidence proves a contradiction, and UNAVAILABLE for missing, malformed,
    or unreadable Task 180 input or unreadable Task 181 audit output.
    ``published_attestation_status`` is the status the Task 180 attestation
    claims. It is None when no valid published status can be established, a
    distinction from a genuinely published UNAVAILABLE status. An unknown
    status is never presented as a published claim. ``expected_attestation_status``
    is the status independently derived from the published Task 177-179
    evidence. ``findings`` are deterministic, sorted, deduplicated and their
    count always equals ``finding_count``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    attestation_consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"] | None
    expected_attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    consistency_source: str

    @model_validator(mode="after")
    def _coherent_consistency(
        self,
    ) -> ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead:
        if self.available != (self.attestation_consistency_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (attestation_consistency_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.attestation_consistency_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (attestation_consistency_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.consistency_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_182
        ):
            raise ValueError("consistency_source must be the canonical Task 182 source")
        if self.published_attestation_status is None:
            if self.attestation_consistency_status != "UNAVAILABLE":
                raise ValueError(
                    "unknown published status requires an UNAVAILABLE consistency"
                )
            if "ATTESTATION_INVALID" not in self.findings:
                raise ValueError(
                    "unknown published status requires ATTESTATION_INVALID"
                )
        if self.attestation_consistency_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            return self
        if self.attestation_consistency_status == "CONSISTENT":
            if self.published_attestation_status != self.expected_attestation_status:
                raise ValueError(
                    "CONSISTENT requires published and expected statuses to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free consistency")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

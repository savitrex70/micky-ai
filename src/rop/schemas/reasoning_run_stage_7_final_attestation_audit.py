"""Task 172: independent Stage 7 final-attestation audit contract.

Strict read-only audit verdict for one published Task 171 final evidence
attestation. The audit independently derives the expected certification
state from the published Task 168-170 evidence rather than trusting Task 171.

The audit is pure, provider-neutral, and independent: it never calls Task
171, never calls Tasks 168-170 services, never recomputes fingerprints,
never invokes a provider, and never accesses a database.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172 = (
    "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_TASK_172"
)


class ReasoningRunStage7FinalAttestationAuditRead(BaseModel):
    """Strict read model for one independent Stage 7 final-attestation audit.

    ``attestation_audit_status`` is the single audit verdict: ``CONSISTENT``
    when the independently derived expected state matches the published Task
    171 attestation, ``INCONSISTENT`` when the published evidence contradicts
    the independently derived result, and ``UNAVAILABLE`` for missing or
    malformed Task 171 input. ``published_attestation_status`` is the status
    the Task 171 attestation claims, and ``expected_attestation_status`` is
    the status independently derived from the published evidence surfaces.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    attestation_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    expected_attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7FinalAttestationAuditRead:
        if self.available != (self.attestation_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (attestation_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.attestation_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (attestation_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.audit_source != (
            REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172
        ):
            raise ValueError("audit_source must be the canonical Task 172 source")
        if self.attestation_audit_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            return self
        if self.attestation_audit_status == "CONSISTENT":
            if self.published_attestation_status != self.expected_attestation_status:
                raise ValueError(
                    "CONSISTENT requires published and expected "
                    "attestation status to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self

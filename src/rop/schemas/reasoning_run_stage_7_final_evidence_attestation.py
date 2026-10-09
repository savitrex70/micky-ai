"""Task 171: Stage 7 final evidence attestation contract.

Strict read-only attestation over the fully audited Stage 7 evidence chain
through Task 170. The attestation answers only: "Does the published Stage 7
evidence package have complete, mutually consistent, canonically
attributable evidence?"

The attestation does NOT perform new reasoning. It only verifies that
Task 168 package is complete, Task 169 audit is valid, Task 170 consistency
is CONSISTENT, session binding is exact, sources are canonical, findings
are resolved, attribution is complete, fingerprint shape is valid, and no
evidence contradiction exists.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171 = (
    "REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_TASK_171"
)


class ReasoningRunStage7FinalEvidenceAttestationRead(BaseModel):
    """Strict read model for one Stage 7 final evidence attestation.

    ``attestation_status`` is the single canonical verdict: ``CERTIFIED``
    when the published Stage 7 evidence package has complete, mutually
    consistent, canonically attributable evidence; ``BLOCKED`` when genuine
    blocking evidence exists; and ``UNAVAILABLE`` when evidence is insufficient
    and there is no blocking state. ``certified``, ``blocked``, and
    ``available`` are coherent boolean projections of the status, while
    ``package_status``, ``package_audit_status``, and ``consistency_status``
    echo the upstream Task 168/169/170 verdicts the attestation was derived
    from. ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    certified: bool
    blocked: bool
    available: bool
    package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None = None
    package_audit_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    ) = None
    consistency_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    ) = None
    finding_count: int
    findings: list[str]
    attestation_source: str

    @model_validator(mode="after")
    def _coherent_attestation(self) -> ReasoningRunStage7FinalEvidenceAttestationRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        # CERTIFIED requires complete consistent evidence
        if self.attestation_status == "CERTIFIED":
            if self.finding_count != 0:
                raise ValueError("CERTIFIED requires a finding-free attestation")
            if not self.session_id:
                raise ValueError("CERTIFIED requires a valid session_id")
        # BLOCKED requires genuine blocking evidence
        if self.attestation_status == "BLOCKED":
            if self.finding_count == 0:
                raise ValueError("BLOCKED requires at least one finding")
        # UNAVAILABLE requires a diagnostic finding
        if self.attestation_status == "UNAVAILABLE":
            if self.finding_count == 0:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
        # Boolean projections must cohere with the status
        if self.certified != (self.attestation_status == "CERTIFIED"):
            raise ValueError("certified must equal (attestation_status == 'CERTIFIED')")
        if self.blocked != (self.attestation_status == "BLOCKED"):
            raise ValueError("blocked must equal (attestation_status == 'BLOCKED')")
        if self.available != (self.attestation_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (attestation_status != 'UNAVAILABLE')"
            )
        if self.attestation_source != (
            REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171
        ):
            raise ValueError("attestation_source must be the canonical Task 171 source")
        return self

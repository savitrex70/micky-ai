"""Task 159: Stage 7 proposal provenance and consistency audit contract.

The strict read-only audit verdict for one returned Task 158 proposal
result, audited against the canonical Task 055 context that produced
it. The verdict is a projection of the authoritative Task 103 proposal
audit: every dimension flag and every finding is Task 103 evidence,
never a second definition of proposal consistency.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

_DIMENSIONS = (
    "session_consistent",
    "fingerprint_consistent",
    "candidate_assessments_consistent",
    "evidence_references_consistent",
    "unresolved_info_consistent",
    "candidate_order_consistent",
    "provenance_consistent",
    "metadata_consistent",
)


class ReasoningRunStage7ProposalAuditRead(BaseModel):
    """Strict proposal audit verdict for one returned Stage 7 proposal.

    ``proposal_audit_status`` is the canonical verdict: ``CONSISTENT``
    (the Task 103 audit certified the returned proposal consistent),
    ``INCONSISTENT`` (the Task 103 audit ran and did not certify
    consistency), or ``UNAVAILABLE`` (the proposal material, the
    canonical context, or the audit itself is unreadable -- no
    dimension is certified, every flag is ``False``). ``available`` is
    always exactly
    ``proposal_audit_status != "UNAVAILABLE"``. ``proposal_consistent``
    and every dimension flag carry the Task 103 result verbatim.
    ``findings`` are deterministic, sorted, and deduplicated.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    proposal_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    proposal_consistent: bool
    session_consistent: bool
    fingerprint_consistent: bool
    candidate_assessments_consistent: bool
    evidence_references_consistent: bool
    unresolved_info_consistent: bool
    candidate_order_consistent: bool
    provenance_consistent: bool
    metadata_consistent: bool
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7ProposalAuditRead:
        if self.available != (self.proposal_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (proposal_audit_status != 'UNAVAILABLE')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        dimensions = [getattr(self, name) for name in _DIMENSIONS]
        if self.proposal_audit_status == "CONSISTENT":
            if not self.proposal_consistent or not all(dimensions):
                raise ValueError(
                    "CONSISTENT requires proposal_consistent and all dimensions"
                )
        elif self.proposal_audit_status == "INCONSISTENT":
            if self.proposal_consistent and all(dimensions):
                raise ValueError("INCONSISTENT requires a failed Task 103 dimension")
        elif self.proposal_consistent or any(dimensions):
            raise ValueError("UNAVAILABLE requires every flag to be False")
        return self

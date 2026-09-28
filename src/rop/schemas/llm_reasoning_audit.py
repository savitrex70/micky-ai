"""Task 103: LLM reasoning audit contracts.

The public Task 103 result schema, ``LLMReasoningAuditRead``, which
captures the deterministic audit of a Task 057 LLMReasoningProposalRead.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LLMReasoningAuditRead(BaseModel):
    """Task 103: the deterministic result of the LLM reasoning audit.

    Performs an independent consistency audit of a Task 057 proposal.
    All checks are structural and type-based; no external context is
    required. The audit never calls a provider, touches a database, or
    makes HTTP requests.

    ``available`` and ``proposal_consistent`` reflect the proposal's own
    state. The remaining flags report on specific structural invariants.
    ``consistency_issues`` is a deterministically ordered, deduplicated
    list of any violations found. ``audit_source`` is a fixed structural
    identifier.

    Task 117: strict boundary. Unexpected output fields are rejected
    (``extra="forbid"``); the service validates every audit result
    through this schema before returning it.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

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
    consistency_issues: list[str] = Field(default_factory=list)
    audit_source: str

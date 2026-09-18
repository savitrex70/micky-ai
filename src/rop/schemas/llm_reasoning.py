"""Task 057: LLM reasoning boundary contracts.

Two layers live here:

1. A parse-only wrapper for the raw model output. This exists solely
   so Pydantic can reject malformed JSON shapes with a single clear
   error before any ROP-specific validation runs.

2. The public Task 057 result schema, ``LLMReasoningProposalRead``,
   which combines ROP-computed provenance (session, fingerprint,
   provider, model, availability, consistency) with the model's
   validated candidate assessments.

Nothing here selects, ranks, scores, or decides. The model's output
is strictly a reasoning proposal; deterministic ROP state is
unaffected.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Assessment = Literal["SUPPORTS", "WEAKENS", "UNCLEAR"]


class ReasoningCandidateAssessmentRead(BaseModel):
    """One candidate's reasoning assessment, produced by the model.

    ``explanation`` is a short structured justification. It is NOT
    hidden chain-of-thought and MUST NOT contain private deliberation.
    Every ID referenced here is validated against the canonical Task
    055 context by the service before this object is exposed.
    """

    model_config = ConfigDict(from_attributes=True)

    candidate_id: UUID
    assessment: Assessment
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)
    unresolved_information_ids: list[UUID] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    uncertainty_flags: list[str] = Field(default_factory=list)


class _RawCandidateAssessment(BaseModel):
    """Parse-only wrapper for one entry in the raw model output."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    assessment: Assessment
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)
    unresolved_information_ids: list[UUID] = Field(default_factory=list)
    explanation: str
    uncertainty_flags: list[str] = Field(default_factory=list)


class _RawLLMReasoningProposal(BaseModel):
    """Parse-only wrapper for the raw model output.

    The model must return exactly one top-level key,
    ``candidate_assessments``. Any additional key is rejected, so a
    model that smuggles in a "winner" or "recommendation" field fails
    schema validation immediately.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_assessments: list[_RawCandidateAssessment]


class LLMReasoningProposalRead(BaseModel):
    """Task 057: the deterministic result of the LLM reasoning boundary.

    Combines ROP-computed provenance with the model's validated
    proposal. ``available`` is False when the boundary declined to
    call the model (input unavailable or inconsistent); in that case
    ``candidate_assessments`` is empty.

    ``proposal_consistent`` is True when the boundary produced a
    coherent, fully validated proposal from a valid model call. It is
    False for the "input inconsistent" soft state, and is never set
    for the hard failure states (MODEL_UNAVAILABLE,
    MODEL_OUTPUT_INVALID, MODEL_OUTPUT_INCONSISTENT), which raise.

    ``llm_reasoning_source`` is a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    context_fingerprint: str
    provider: str
    model: str
    candidate_assessments: list[ReasoningCandidateAssessmentRead]
    available: bool
    proposal_consistent: bool
    llm_reasoning_source: str

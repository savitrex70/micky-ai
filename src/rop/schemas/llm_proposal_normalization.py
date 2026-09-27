"""Task 106: normalized LLM reasoning proposal schema.

Matches the output of normalize_proposal from llm_proposal_normalization.py.
All fields are JSON-safe (UUIDs as strings, no complex types).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Assessment = Literal["SUPPORTS", "WEAKENS", "UNCLEAR"]


class NormalizedCandidateAssessmentRead(BaseModel):
    """One candidate's normalized reasoning assessment."""

    model_config = ConfigDict(from_attributes=True)

    candidate_id: str | None = Field(default=None)
    assessment: Assessment
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    unresolved_information_ids: list[str] = Field(default_factory=list)
    explanation: str
    uncertainty_flags: list[str] = Field(default_factory=list)


class NormalizedLLMReasoningProposalRead(BaseModel):
    """Task 106: normalized deterministic form of an LLM reasoning proposal.

    Matches the output of normalize_proposal(). All values are JSON-safe:
    - session_id is string (UUID converted)
    - All evidence/information IDs are strings
    - candidate_assessments order is preserved from input (matches context order)
    - uncertainty_flags are sorted alphabetically within each assessment
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: str | None = Field(default=None)
    context_fingerprint: str
    provider: str
    model: str
    candidate_assessments: list[NormalizedCandidateAssessmentRead]
    available: bool
    proposal_consistent: bool
    llm_reasoning_source: str

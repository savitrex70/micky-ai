"""Task 109: read-only inspection read model for a validated LLM proposal.

Mirrors the dict returned by the Task 109 inspection service. All IDs
are strings, all derived reference lists are flat sorted string
lists, and provenance is carried by ``inspection_source`` plus the
recomputed ``proposal_fingerprint``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rop.schemas.llm_proposal_normalization import (
    NormalizedCandidateAssessmentRead,
)


class LLMProposalInspectionRead(BaseModel):
    """Task 109: deterministic read-only view over a validated proposal."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    context_fingerprint: str
    provider: str
    model: str
    available: bool
    proposal_consistent: bool
    candidate_assessments: list[NormalizedCandidateAssessmentRead] = Field(
        default_factory=list
    )
    evidence_references: list[str] = Field(default_factory=list)
    unresolved_information_references: list[str] = Field(default_factory=list)
    uncertainty_flags: list[str] = Field(default_factory=list)
    inspection_source: str
    proposal_fingerprint: str


__all__ = ["LLMProposalInspectionRead"]

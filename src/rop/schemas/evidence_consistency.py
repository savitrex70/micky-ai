from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvidenceConsistencyRead(BaseModel):
    """Task 022: evidence consistency/quality analysis for one candidate.

    A derived view over the same already-persisted ``EvaluatedEvidence``
    records ``EvidenceSummaryRead`` (Task 021) summarizes, adding a
    structural consistency signal (support-only, contradiction-only, mixed,
    neutral-only, or no evidence) plus ratios. Does not evaluate evidence
    or write anything.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    total_evidence_items: int
    supporting_evidence_count: int
    strongly_supporting_evidence_count: int
    contradicting_evidence_count: int
    strongly_contradicting_evidence_count: int
    neutral_or_unknown_count: int
    total_support_contribution: float
    total_contradiction_contribution: float
    net_contribution: float
    has_evidence: bool
    has_supporting_evidence: bool
    has_contradicting_evidence: bool
    has_mixed_evidence: bool
    support_evidence_ratio: float
    contradiction_evidence_ratio: float
    neutral_or_unknown_evidence_ratio: float
    evidence_consistency: str

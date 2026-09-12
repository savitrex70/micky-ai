from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvidenceSummaryRead(BaseModel):
    """Deterministic evidence summary for one candidate hypothesis.

    A derived view over a hypothesis's already-persisted ``EvaluatedEvidence``
    records (Task 020) — counts and contribution totals only. Does not
    evaluate evidence, rank hypotheses, or produce a diagnosis; it exists so
    a later hypothesis-scoring engine can consume one summary per hypothesis
    instead of raw evidence rows.
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

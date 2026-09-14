from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HypothesisScoreRead(BaseModel):
    """Task 023: deterministic hypothesis score for one candidate.

    A derived view over Task 022's evidence consistency/quality analysis
    (which itself derives from Task 021's evidence summary over Task
    020's persisted ``EvaluatedEvidence`` records). ``hypothesis_score``
    is currently ``net_contribution`` unchanged — a transparent,
    reproducible number, not a probability, percentage, or diagnostic
    confidence. This is a scoring foundation, not a ranked differential:
    candidates are not compared or ordered against one another here.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    hypothesis_score: float
    score_source: str
    evidence_consistency: str
    total_evidence_items: int
    total_support_contribution: float
    total_contradiction_contribution: float
    net_contribution: float
    has_evidence: bool
    has_mixed_evidence: bool

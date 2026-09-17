from pydantic import BaseModel, ConfigDict

from rop.schemas.decision_candidate_assessment import (
    DecisionCandidateAssessmentSetRead,
)
from rop.schemas.decision_candidate_set import DecisionCandidateSetRead


class DecisionInputBundleRead(BaseModel):
    """Task 037: final audited input bundle before the future decision layer.

    Packages the Task 035 candidate set and the Task 036 assessment set
    as one cross-validated structure. Guarantees that both refer to the
    same candidate sequence, in the same order, with matching identity
    and metadata, and that neither upstream structure has been
    silently repaired. There is no winner, best candidate, diagnosis,
    recommendation, probability, confidence, utility, or decision
    anywhere in this contract. ``input_source`` is a fixed
    structural-contract identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    candidate_set: DecisionCandidateSetRead
    assessment_set: DecisionCandidateAssessmentSetRead
    candidate_count: int
    candidate_order_preserved: bool
    candidate_assessment_alignment_complete: bool
    input_structure_consistent: bool
    input_source: str

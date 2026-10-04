from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionEvaluationCriterionResultRead(BaseModel):
    """Task 032: the result of evaluating one candidate against one criterion.

    ``satisfied`` and ``required`` are independent: an unsatisfied
    optional criterion is not a failure, and this schema carries no
    weight, score, or ranking of its own. ``reason`` is a deterministic,
    factual explanation derived directly from the Task 031
    ``DecisionContext`` — never free-form or LLM-generated text.
    """

    model_config = ConfigDict(from_attributes=True)

    criterion_id: str
    criterion_name: str
    satisfied: bool
    required: bool
    reason: str


class DecisionCandidateEvaluationRead(BaseModel):
    """Task 032: the complete deterministic evaluation of one candidate.

    Answers "how does this candidate perform against the defined
    decision criteria?" — never "is this candidate the answer?". There
    is no winner, selected candidate, decision, diagnosis, probability,
    confidence, or weighted/utility score anywhere in this schema.

    ``evaluation_complete`` is true only when every declared criterion
    was evaluated deterministically for this candidate; it says nothing
    about whether those criteria were satisfied.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    criteria: list[DecisionEvaluationCriterionResultRead]
    criterion_count: int
    criteria_satisfied: int
    criteria_unsatisfied: int
    required_criteria_satisfied: int
    required_criteria_unsatisfied: int
    evaluation_complete: bool
    evaluation_source: str

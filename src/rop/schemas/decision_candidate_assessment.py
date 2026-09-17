from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionCriterionAssessmentRead(BaseModel):
    """Task 036: one candidate's result against one decision criterion.

    A verbatim projection of the corresponding entry in the Task 032
    evaluation's ``criteria`` list. ``satisfied`` and ``required`` are
    independent; ``reason`` is the deterministic factual explanation
    produced by Task 032. No weight, score, or ranking is added here.
    """

    model_config = ConfigDict(from_attributes=True)

    criterion_id: str
    criterion_name: str
    satisfied: bool
    required: bool
    reason: str


class DecisionCandidateAssessmentRead(BaseModel):
    """Task 036: one candidate's full assessment package.

    Combines the candidate identity and ranking facts carried by Task
    035 (verbatim) with the candidate's Task 032 evaluation results
    (verbatim). No winner, score aggregation, probability, confidence,
    or recommendation appears anywhere in this schema.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    rank: int
    score: float
    is_tied: bool
    tie_group_size: int
    score_gap_to_next_higher: float | None
    score_gap_to_next_lower: float | None
    criteria: list[DecisionCriterionAssessmentRead]
    criterion_count: int
    criteria_satisfied: int
    criteria_unsatisfied: int
    required_criteria_satisfied: int
    required_criteria_unsatisfied: int
    evaluation_complete: bool
    assessment_source: str


class DecisionCandidateAssessmentSetRead(BaseModel):
    """Task 036: the assessment package for the full candidate set.

    Deterministic join of Task 035's candidate set with Task 032's
    per-candidate evaluations, gated by Task 033's structural
    consistency verdict. When the input is fully usable, every Task
    035 candidate appears exactly once with its Task 032 evaluation
    attached; otherwise the assessment set is empty and ``available``
    is ``False``. ``assessment_source`` is a fixed structural-contract
    identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    candidate_count: int
    assessments: list[DecisionCandidateAssessmentRead]
    candidate_order_preserved: bool
    evaluation_coverage_complete: bool
    assessment_structure_consistent: bool
    assessment_source: str

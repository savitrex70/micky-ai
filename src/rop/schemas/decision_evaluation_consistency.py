from pydantic import BaseModel, ConfigDict


class DecisionEvaluationConsistencyRead(BaseModel):
    """Task 033: structural consistency/coverage over Task 032's evaluations.

    Answers "are the candidate evaluations complete, structurally
    consistent, and fully comparable across the current decision
    context?" -- never "which candidate should be chosen?". There is
    no winner, score, probability, confidence, or recommendation
    anywhere in this schema; every field here is either a count or a
    boolean structural verdict.
    """

    model_config = ConfigDict(from_attributes=True)

    consistent: bool
    evaluation_count: int
    expected_candidate_count: int
    candidate_count_matches: bool
    criterion_sets_match: bool
    criterion_count_matches: bool
    criterion_definitions_match: bool
    required_flags_match: bool
    evaluation_completeness_matches: bool
    candidate_ids_unique: bool
    criterion_ids_unique_per_candidate: bool
    all_candidates_evaluated: bool
    all_criteria_evaluated: bool
    has_missing_candidate_evaluation: bool
    has_incomplete_evaluation: bool
    has_structural_mismatch: bool
    consistency_source: str

from pydantic import BaseModel, ConfigDict


class DecisionInputEligibilityRead(BaseModel):
    """Task 034: the final gate before the future decision engine.

    Answers "is the current decision input structurally valid and
    sufficiently prepared to enter the future decision engine?" --
    never "which candidate should be chosen?". It combines the
    already-approved Task 030 readiness result (via Task 031),
    Task 031 decision context, and Task 033 evaluation consistency
    (which itself is built over Task 032's candidate evaluations)
    into a single deterministic eligibility verdict.

    There is no winner, best candidate, diagnosis, recommendation,
    action, probability, confidence, utility, weighted score,
    expected outcome, or treatment anywhere in this schema.

    ``eligible`` is an explicit conjunction of the other boolean
    fields here -- never a hidden threshold on any upstream score,
    ranking position, tie presence, or evidence direction.
    ``blocking_conditions`` is a deterministically ordered list of
    fixed, machine-readable identifiers explaining exactly why
    ``eligible`` is ``False``; it is empty if and only if ``eligible``
    is ``True``. ``eligibility_source`` is a fixed structural-contract
    identifier, never a score, probability, confidence, or
    recommendation.
    """

    model_config = ConfigDict(from_attributes=True)

    eligible: bool
    decision_ready: bool
    context_available: bool
    evaluation_consistent: bool
    has_candidates: bool
    evaluations_available: bool
    all_candidates_evaluated: bool
    all_criteria_evaluated: bool
    candidate_count_matches: bool
    evaluation_structure_consistent: bool
    blocking_conditions: list[str]
    eligibility_source: str

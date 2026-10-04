from pydantic import BaseModel, ConfigDict

from rop.schemas.differential_decision_readiness import (
    DifferentialDecisionReadinessRead,
)
from rop.schemas.differential_rank import DifferentialRankRead
from rop.schemas.differential_ranking_consistency import (
    DifferentialRankingConsistencyRead,
)
from rop.schemas.differential_ranking_summary import DifferentialRankingSummaryRead


class DecisionContextRead(BaseModel):
    """Task 031: the first stable input contract for a future decision engine.

    A deterministic, read-only package of Tasks 027-030's already-
    validated outputs: the Task 027 ranked differential, the Task 028
    structural summary, the Task 029 consistency result, and the Task
    030 readiness result. Every nested component is preserved exactly
    and remains fully typed — this contract is packaging, not
    reinterpretation, and duplicates no scoring or ranking logic.

    ``context_available`` means a complete, internally consistent
    decision-context package has been assembled. It does not mean a
    decision exists, a diagnosis is known, or a winner exists.
    ``decision_ready`` and ``consistency_verified`` are exact mirrors
    of ``decision_readiness.ready`` and
    ``differential_consistency.consistent`` respectively — Task 031
    never redefines either. ``context_source`` is a fixed structural-
    contract identifier, never a score, probability, confidence, or
    recommendation.

    An empty differential is a valid upstream state: ``candidate_count
    = 0``, ``decision_ready = False`` (per Task 030), and therefore
    ``context_available = False`` — because there is nothing yet for a
    decision engine to consume, not because anything is corrupted.

    This is the intended hand-off point: a future decision engine
    should consume one ``DecisionContextRead`` instead of reaching
    backward into evidence, observations, entities, hypothesis scores,
    or the differential ranking directly. It contains no
    ``is_winner``, ``selected_hypothesis``, diagnosis, probability,
    confidence, recommendation, or treatment field.
    """

    model_config = ConfigDict(from_attributes=True)

    context_available: bool
    decision_ready: bool
    consistency_verified: bool
    candidate_count: int
    differential: list[DifferentialRankRead]
    differential_summary: DifferentialRankingSummaryRead
    differential_consistency: DifferentialRankingConsistencyRead
    decision_readiness: DifferentialDecisionReadinessRead
    context_source: str

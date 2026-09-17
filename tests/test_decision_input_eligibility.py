"""Tests for the Task 034 decision-input eligibility gate.

Task 034 is the final gate between decision preparation and the
future decision engine. It combines the Task 030 readiness result
(via Task 031), the Task 031 decision context, and the Task 033
evaluation-consistency result (built over Task 032's candidate
evaluations) into a single deterministic eligibility verdict. It
never selects a winner, never diagnoses, never computes a
probability, confidence, or score, and never persists anything.

Regression note: running this file alone is not a substitute for the
full suite. Tasks 020-033 must be re-run alongside this file before
Task 034 is considered done (Definition of Done #11).
"""

from __future__ import annotations

import copy
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.decision_candidate_evaluation import (
    DecisionCandidateEvaluationService,
)
from rop.services.decision_context import DecisionContextService
from rop.services.decision_evaluation_consistency import (
    DecisionEvaluationConsistencyService,
)
from rop.services.decision_input_eligibility import (
    BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE,
    BLOCKING_CONTEXT_UNAVAILABLE,
    BLOCKING_CRITERIA_INCOMPLETE,
    BLOCKING_DECISION_NOT_READY,
    BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT,
    BLOCKING_NO_CANDIDATES,
    BLOCKING_NO_EVALUATIONS,
    ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
    DecisionInputEligibilityContractError,
    DecisionInputEligibilityService,
)
from rop.services.differential_decision_readiness import (
    DifferentialDecisionReadinessService,
)
from rop.services.differential_ranking import DifferentialRankingService
from rop.services.differential_ranking_consistency import (
    DifferentialRankingConsistencyService,
)
from rop.services.differential_ranking_summary import (
    DifferentialRankingSummaryService,
)
from rop.services.evidence_aggregation import (
    CONSISTENCY_SUPPORT_ONLY,
    EvidenceAggregationService,
)
from rop.services.hypothesis_scoring import (
    SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
    HypothesisScoringService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


ELIGIBILITY_RESULT_FIELDS = (
    "eligible",
    "decision_ready",
    "context_available",
    "evaluation_consistent",
    "has_candidates",
    "evaluations_available",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "candidate_count_matches",
    "evaluation_structure_consistent",
    "blocking_conditions",
    "eligibility_source",
)

_ALL_BLOCKING_CONDITIONS = frozenset(
    {
        BLOCKING_DECISION_NOT_READY,
        BLOCKING_CONTEXT_UNAVAILABLE,
        BLOCKING_NO_CANDIDATES,
        BLOCKING_NO_EVALUATIONS,
        BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE,
        BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT,
        BLOCKING_CRITERIA_INCOMPLETE,
    }
)


# ---------------------------------------------------------------------------
# Helpers -- build a genuine Tasks 027-033 chain from hand-crafted score
# results, exactly like the Task 031/032/033 test suites do, so every
# "well formed" context/consistency pair used here is a real upstream
# output, not a guess at its shape.
# ---------------------------------------------------------------------------


def _ranking_service() -> DifferentialRankingService:
    return DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )


def _readiness_service() -> DifferentialDecisionReadinessService:
    return DifferentialDecisionReadinessService(
        DifferentialRankingConsistencyService(
            DifferentialRankingSummaryService(_ranking_service())
        )
    )


def _context_service() -> DecisionContextService:
    return DecisionContextService(_readiness_service())


def _candidate_evaluation_service() -> DecisionCandidateEvaluationService:
    return DecisionCandidateEvaluationService(_context_service())


def _consistency_service() -> DecisionEvaluationConsistencyService:
    return DecisionEvaluationConsistencyService(_candidate_evaluation_service())


def _eligibility_service() -> DecisionInputEligibilityService:
    return DecisionInputEligibilityService(_consistency_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    evidence_consistency: str = CONSISTENCY_SUPPORT_ONLY,
    total_support_contribution: float = 0.0,
    total_contradiction_contribution: float = 0.0,
    evidence_coverage_ratio: float | None = None,
) -> dict[str, Any]:
    has_evidence = True
    if evidence_coverage_ratio is None:
        evidence_coverage_ratio = 1.0 if has_evidence else 0.0

    if hypothesis_score > 0:
        score_direction = "POSITIVE"
    elif hypothesis_score < 0:
        score_direction = "NEGATIVE"
    else:
        score_direction = "ZERO"

    return {
        "hypothesis_id": uuid4(),
        "hypothesis_name": hypothesis_name,
        "hypothesis_score": hypothesis_score,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": evidence_consistency,
        "total_evidence_items": 1,
        "total_support_contribution": total_support_contribution,
        "total_contradiction_contribution": total_contradiction_contribution,
        "net_contribution": (
            total_support_contribution - total_contradiction_contribution
        ),
        "has_evidence": has_evidence,
        "has_mixed_evidence": False,
        "score_direction": score_direction,
        "evidence_coverage_ratio": evidence_coverage_ratio,
        "informative_evidence_ratio": evidence_coverage_ratio,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING",
    }


def _build(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    consistency_service = DifferentialRankingConsistencyService(summary_service)
    readiness_service = DifferentialDecisionReadinessService(consistency_service)

    ranked = ranking_service.rank_score_results(entries)
    summary = summary_service.summarize_ranked(ranked)
    consistency = consistency_service.check_consistency(ranked, summary)
    readiness = readiness_service.evaluate(ranked, summary, consistency)
    return ranked, summary, consistency, readiness


def _make_context(entries: list[dict[str, Any]]) -> dict[str, Any]:
    ranked, summary, consistency, readiness = _build(entries)
    return _context_service().build(ranked, summary, consistency, readiness)


def _make_context_and_consistency(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the real Task 031 -> 032 -> 033 chain, building the Task 031
    context exactly once, mirroring what
    ``DecisionInputEligibilityService.build_for_session`` now does.
    """
    context = _make_context(entries)
    evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    consistency_result = _consistency_service().check(evaluations, expected_ids)
    return context, consistency_result


def _ready_context_and_consistency() -> tuple[dict[str, Any], dict[str, Any]]:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    return _make_context_and_consistency(entries)


# ---------------------------------------------------------------------------
# Valid / eligible cases
# ---------------------------------------------------------------------------


def test_one_valid_candidate_is_eligible() -> None:
    context, consistency_result = _make_context_and_consistency(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )

    result = _eligibility_service().build(context, consistency_result)

    assert set(result) == set(ELIGIBILITY_RESULT_FIELDS)
    assert result["eligible"] is True
    assert result["blocking_conditions"] == []


def test_multiple_valid_candidates_are_eligible() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["eligible"] is True
    assert result["blocking_conditions"] == []


def test_eligible_when_all_upstream_gates_valid() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["decision_ready"] is True
    assert result["context_available"] is True
    assert result["has_candidates"] is True
    assert result["evaluations_available"] is True
    assert result["all_candidates_evaluated"] is True
    assert result["all_criteria_evaluated"] is True
    assert result["candidate_count_matches"] is True
    assert result["evaluation_structure_consistent"] is True


def test_deterministic_repeated_call() -> None:
    context, consistency_result = _ready_context_and_consistency()
    service = _eligibility_service()

    first = service.build(context, consistency_result)
    second = service.build(context, consistency_result)

    assert first == second


def test_blocking_conditions_empty_when_eligible() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["eligible"] is True
    assert result["blocking_conditions"] == []


def test_no_decision_fields_are_introduced() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert set(result) == set(ELIGIBILITY_RESULT_FIELDS)
    for forbidden in (
        "winner",
        "selected_candidate",
        "diagnosis",
        "recommendation",
        "action",
        "probability",
        "confidence",
        "utility",
        "utility_score",
        "weighted_score",
        "expected_outcome",
        "treatment",
        "is_winner",
        "score",
        "ranking",
    ):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# Decision readiness cases
# ---------------------------------------------------------------------------


def test_not_ready_context_blocks_eligibility() -> None:
    # Force the not-ready state directly on a hand-built context,
    # exactly like the Task 031/032/033 suites do for contract-level
    # tests, rather than trying to coax an un-ready differential out
    # of the scoring pipeline itself.
    context, consistency_result = _ready_context_and_consistency()
    not_ready_context = copy.deepcopy(context)
    not_ready_context["decision_ready"] = False
    not_ready_context["context_available"] = False

    result = _eligibility_service().build(not_ready_context, consistency_result)

    assert result["decision_ready"] is False
    assert result["eligible"] is False
    assert BLOCKING_DECISION_NOT_READY in result["blocking_conditions"]


def test_decision_ready_true_is_not_itself_blocking() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert BLOCKING_DECISION_NOT_READY not in result["blocking_conditions"]


# ---------------------------------------------------------------------------
# Context cases
# ---------------------------------------------------------------------------


def test_context_unavailable_blocks_eligibility() -> None:
    context, consistency_result = _ready_context_and_consistency()
    unavailable_context = copy.deepcopy(context)
    unavailable_context["context_available"] = False

    result = _eligibility_service().build(unavailable_context, consistency_result)

    assert result["context_available"] is False
    assert result["eligible"] is False
    assert BLOCKING_CONTEXT_UNAVAILABLE in result["blocking_conditions"]


def test_context_available_true_is_not_itself_blocking() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert BLOCKING_CONTEXT_UNAVAILABLE not in result["blocking_conditions"]


# ---------------------------------------------------------------------------
# Candidate cases
# ---------------------------------------------------------------------------


def test_zero_candidates_is_not_eligible() -> None:
    context, consistency_result = _make_context_and_consistency([])

    result = _eligibility_service().build(context, consistency_result)

    assert result["has_candidates"] is False
    assert result["eligible"] is False
    # Task 034 Section 7 adds each blocking condition
    # independently. An empty context is simultaneously not
    # decision-ready, unavailable, and candidate-free, so all
    # three appear -- in the fixed order from Section 4.
    assert result["blocking_conditions"] == [
        BLOCKING_DECISION_NOT_READY,
        BLOCKING_CONTEXT_UNAVAILABLE,
        BLOCKING_NO_CANDIDATES,
    ]


def test_zero_candidates_does_not_also_report_no_evaluations() -> None:
    # Section 8: an empty candidate set is not treated as an
    # evaluation-consistency failure merely because the evaluation
    # list is empty -- only NO_CANDIDATES should appear.
    context, consistency_result = _make_context_and_consistency([])

    result = _eligibility_service().build(context, consistency_result)

    assert BLOCKING_NO_EVALUATIONS not in result["blocking_conditions"]
    assert BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE not in result["blocking_conditions"]
    assert (
        BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT not in result["blocking_conditions"]
    )
    assert BLOCKING_CRITERIA_INCOMPLETE not in result["blocking_conditions"]


def test_candidates_present_is_a_prerequisite_for_eligibility() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["has_candidates"] is True
    assert BLOCKING_NO_CANDIDATES not in result["blocking_conditions"]


def test_candidates_but_no_evaluations() -> None:
    context, _ = _ready_context_and_consistency()
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    empty_evaluations_consistency = _consistency_service().check([], expected_ids)

    result = _eligibility_service().build(context, empty_evaluations_consistency)

    assert result["has_candidates"] is True
    assert result["evaluations_available"] is False
    assert result["eligible"] is False
    assert BLOCKING_NO_EVALUATIONS in result["blocking_conditions"]


# ---------------------------------------------------------------------------
# Evaluation coverage
# ---------------------------------------------------------------------------


def test_all_candidates_evaluated_is_not_blocking() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["all_candidates_evaluated"] is True
    assert BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE not in result["blocking_conditions"]


def test_missing_candidate_evaluation_blocks_eligibility() -> None:
    context, _ = _ready_context_and_consistency()
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    all_evaluations = _candidate_evaluation_service().evaluate(context)
    trimmed = all_evaluations[:1]
    trimmed_consistency = _consistency_service().check(trimmed, expected_ids)

    result = _eligibility_service().build(context, trimmed_consistency)

    assert result["all_candidates_evaluated"] is False
    assert result["eligible"] is False
    assert BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE in result["blocking_conditions"]


def test_candidate_count_mismatch_blocks_eligibility() -> None:
    context, _ = _ready_context_and_consistency()
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    trimmed_expected = expected_ids[:1]
    all_evaluations = _candidate_evaluation_service().evaluate(context)
    mismatched_consistency = _consistency_service().check(
        all_evaluations, trimmed_expected
    )

    result = _eligibility_service().build(context, mismatched_consistency)

    assert result["candidate_count_matches"] is False
    assert result["eligible"] is False
    assert BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE in result["blocking_conditions"]


def test_all_criteria_evaluated_true_case() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["all_criteria_evaluated"] is True
    assert BLOCKING_CRITERIA_INCOMPLETE not in result["blocking_conditions"]


def test_incomplete_criteria_blocks_eligibility() -> None:
    context, _ = _ready_context_and_consistency()
    all_evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    mutated = copy.deepcopy(all_evaluations)
    mutated[0]["criteria"] = mutated[0]["criteria"][:-1]
    criteria = mutated[0]["criteria"]
    satisfied = sum(1 for c in criteria if c["satisfied"] is True)
    required = [c for c in criteria if c["required"] is True]
    required_satisfied = sum(1 for c in required if c["satisfied"] is True)
    mutated[0]["criterion_count"] = len(criteria)
    mutated[0]["criteria_satisfied"] = satisfied
    mutated[0]["criteria_unsatisfied"] = len(criteria) - satisfied
    mutated[0]["required_criteria_satisfied"] = required_satisfied
    mutated[0]["required_criteria_unsatisfied"] = len(required) - required_satisfied
    mutated[0]["evaluation_complete"] = False
    incomplete_consistency = _consistency_service().check(mutated, expected_ids)

    result = _eligibility_service().build(context, incomplete_consistency)

    assert result["all_criteria_evaluated"] is False
    assert result["eligible"] is False
    assert BLOCKING_CRITERIA_INCOMPLETE in result["blocking_conditions"]


# ---------------------------------------------------------------------------
# Structural consistency
# ---------------------------------------------------------------------------


def test_task_033_consistent_is_not_blocking() -> None:
    context, consistency_result = _ready_context_and_consistency()

    assert consistency_result["has_structural_mismatch"] is False
    result = _eligibility_service().build(context, consistency_result)

    assert result["evaluation_structure_consistent"] is True
    assert (
        BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT
        not in result["blocking_conditions"]
    )


def test_task_033_inconsistent_blocks_eligibility() -> None:
    context, _ = _ready_context_and_consistency()
    all_evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    mutated = copy.deepcopy(all_evaluations)
    mutated[0]["criteria"].append(copy.deepcopy(mutated[0]["criteria"][0]))
    duplicate_id_consistency = _consistency_service().check(mutated, expected_ids)

    assert duplicate_id_consistency["has_structural_mismatch"] is True
    result = _eligibility_service().build(context, duplicate_id_consistency)

    assert result["evaluation_structure_consistent"] is False
    assert result["eligible"] is False
    assert (
        BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT in result["blocking_conditions"]
    )


def test_evaluation_consistent_matches_upstream_consistent() -> None:
    """Section 3 requires ``evaluation_consistent``, taken verbatim
    from Task 033's ``consistent`` verdict. Task 034 must expose that
    value, not recompute it or derive it from the sub-flags.
    """
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["evaluation_consistent"] == consistency_result["consistent"]
    assert result["evaluation_consistent"] is True


def test_evaluation_consistent_reflects_upstream_inconsistency() -> None:
    """When Task 033 reports ``consistent=False``, Task 034 must reflect
    that verbatim in ``evaluation_consistent`` -- without inventing a
    new blocking condition for it (Section 7 lists none).
    """
    context, _ = _ready_context_and_consistency()
    all_evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    mutated = copy.deepcopy(all_evaluations)
    mutated[0]["criteria"].append(copy.deepcopy(mutated[0]["criteria"][0]))
    inconsistent = _consistency_service().check(mutated, expected_ids)

    assert inconsistent["consistent"] is False
    result = _eligibility_service().build(context, inconsistent)

    assert result["evaluation_consistent"] is False
    assert result["eligible"] is False
    assert (
        BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT in result["blocking_conditions"]
    )


# ---------------------------------------------------------------------------
# Blocking-condition contract
# ---------------------------------------------------------------------------


def test_exact_blocking_condition_set_for_zero_candidates() -> None:
    context, consistency_result = _make_context_and_consistency([])

    result = _eligibility_service().build(context, consistency_result)

    # Zero candidates is the primary failure, but Section 7 adds
    # every applicable condition independently, so the empty
    # context also reports the readiness and context failures.
    assert set(result["blocking_conditions"]) == {
        BLOCKING_DECISION_NOT_READY,
        BLOCKING_CONTEXT_UNAVAILABLE,
        BLOCKING_NO_CANDIDATES,
    }


def test_blocking_condition_deterministic_ordering() -> None:
    context, consistency_result = _ready_context_and_consistency()
    broken_context = copy.deepcopy(context)
    broken_context["decision_ready"] = False
    broken_context["context_available"] = False

    all_evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    trimmed_consistency = _consistency_service().check(
        all_evaluations[:1], expected_ids
    )

    result = _eligibility_service().build(broken_context, trimmed_consistency)

    # DECISION_NOT_READY, CONTEXT_UNAVAILABLE, then coverage -- never
    # any other relative order, regardless of the order the underlying
    # booleans were computed in.
    assert result["blocking_conditions"] == [
        BLOCKING_DECISION_NOT_READY,
        BLOCKING_CONTEXT_UNAVAILABLE,
        BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE,
    ]


def test_blocking_conditions_have_no_duplicates() -> None:
    context, consistency_result = _make_context_and_consistency([])

    result = _eligibility_service().build(context, consistency_result)

    assert len(result["blocking_conditions"]) == len(
        set(result["blocking_conditions"])
    )


def test_invalid_blocking_condition_identifier_rejected() -> None:
    context, consistency_result = _ready_context_and_consistency()
    result = _eligibility_service().build(context, consistency_result)
    corrupted = copy.deepcopy(result)
    corrupted["eligible"] = False
    corrupted["blocking_conditions"] = ["NOT_A_REAL_CONDITION"]

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        DecisionInputEligibilityService._validate_result(corrupted)
    assert exc_info.value.invariant == "INVALID_BLOCKING_CONDITION"


def test_condition_present_while_eligible_true_rejected() -> None:
    context, consistency_result = _make_context_and_consistency([])
    result = _eligibility_service().build(context, consistency_result)
    corrupted = copy.deepcopy(result)
    corrupted["eligible"] = True

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        DecisionInputEligibilityService._validate_result(corrupted)
    assert exc_info.value.invariant == "ELIGIBLE_WITH_BLOCKING_CONDITIONS"


def test_eligible_false_with_empty_blocking_conditions_rejected() -> None:
    context, consistency_result = _ready_context_and_consistency()
    result = _eligibility_service().build(context, consistency_result)
    corrupted = copy.deepcopy(result)
    corrupted["eligible"] = False

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        DecisionInputEligibilityService._validate_result(corrupted)
    assert exc_info.value.invariant == "INELIGIBLE_WITHOUT_BLOCKING_CONDITIONS"


def test_irrelevant_blocking_conditions_are_not_generated() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert result["blocking_conditions"] == []
    for condition in _ALL_BLOCKING_CONDITIONS:
        assert condition not in result["blocking_conditions"]


def test_blocking_conditions_out_of_order_rejected() -> None:
    context, consistency_result = _make_context_and_consistency([])
    result = _eligibility_service().build(context, consistency_result)
    corrupted = copy.deepcopy(result)
    corrupted["blocking_conditions"] = [
        BLOCKING_NO_CANDIDATES,
        BLOCKING_DECISION_NOT_READY,
    ]
    corrupted["decision_ready"] = False

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        DecisionInputEligibilityService._validate_result(corrupted)
    assert exc_info.value.invariant == "BLOCKING_CONDITIONS_ORDER"


# ---------------------------------------------------------------------------
# Type/contract tests -- malformed upstream input
# ---------------------------------------------------------------------------


def test_rejects_none_context() -> None:
    _, consistency_result = _ready_context_and_consistency()
    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(None, consistency_result)
    assert exc_info.value.invariant == "MISSING_CONTEXT"


def test_rejects_none_consistency_result() -> None:
    context, _ = _ready_context_and_consistency()
    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(context, None)
    assert exc_info.value.invariant == "MISSING_CONSISTENCY_RESULT"


def test_rejects_non_mapping_context() -> None:
    _, consistency_result = _ready_context_and_consistency()
    with pytest.raises(DecisionInputEligibilityContractError):
        _eligibility_service().build(  # type: ignore[arg-type]
            "not-a-mapping", consistency_result
        )


def test_rejects_non_mapping_consistency_result() -> None:
    context, _ = _ready_context_and_consistency()
    with pytest.raises(DecisionInputEligibilityContractError):
        _eligibility_service().build(context, "not-a-mapping")  # type: ignore[arg-type]


def test_rejects_context_missing_required_field() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    del malformed["decision_ready"]

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "MISSING_CONTEXT_FIELD"


def test_rejects_non_boolean_decision_ready() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    malformed["decision_ready"] = "true"

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "DECISION_READY_TYPE"


def test_rejects_non_boolean_context_available() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    malformed["context_available"] = 1

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "CONTEXT_AVAILABLE_TYPE"


def test_rejects_negative_candidate_count() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    malformed["candidate_count"] = -1

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "CANDIDATE_COUNT_NEGATIVE"


def test_rejects_candidate_count_mismatch_with_differential() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    malformed["candidate_count"] = malformed["candidate_count"] + 1

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "CANDIDATE_COUNT_MISMATCH"


def test_rejects_invalid_context_source() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    malformed["context_source"] = "SOMETHING_ELSE"

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "INVALID_CONTEXT_SOURCE"


def test_rejects_consistency_result_missing_required_field() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(consistency_result)
    del malformed["all_candidates_evaluated"]

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(context, malformed)
    assert exc_info.value.invariant == "MISSING_CONSISTENCY_FIELD"


def test_rejects_negative_evaluation_count() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(consistency_result)
    malformed["evaluation_count"] = -1

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(context, malformed)
    assert exc_info.value.invariant == "EVALUATION_COUNT_NEGATIVE"


def test_rejects_non_boolean_has_structural_mismatch() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(consistency_result)
    malformed["has_structural_mismatch"] = "no"

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(context, malformed)
    assert exc_info.value.invariant == "HAS_STRUCTURAL_MISMATCH_TYPE"


def test_rejects_invalid_consistency_source() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(consistency_result)
    malformed["consistency_source"] = "SOMETHING_ELSE"

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(context, malformed)
    assert exc_info.value.invariant == "INVALID_CONSISTENCY_SOURCE"


def test_rejects_malformed_differential_type() -> None:
    context, consistency_result = _ready_context_and_consistency()
    malformed = copy.deepcopy(context)
    malformed["differential"] = "not-a-list"

    with pytest.raises(DecisionInputEligibilityContractError) as exc_info:
        _eligibility_service().build(malformed, consistency_result)
    assert exc_info.value.invariant == "DIFFERENTIAL_TYPE"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_build_does_not_mutate_context() -> None:
    context, consistency_result = _ready_context_and_consistency()
    context_before = copy.deepcopy(context)

    _eligibility_service().build(context, consistency_result)

    assert context == context_before


def test_build_does_not_mutate_consistency_result() -> None:
    context, consistency_result = _ready_context_and_consistency()
    consistency_before = copy.deepcopy(consistency_result)

    _eligibility_service().build(context, consistency_result)

    assert consistency_result == consistency_before


def test_eligibility_source_is_fixed() -> None:
    context, consistency_result = _ready_context_and_consistency()

    result = _eligibility_service().build(context, consistency_result)

    assert (
        result["eligibility_source"]
        == ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034
    )


# ---------------------------------------------------------------------------
# Regression lock for the single-context-build pattern established at the
# Task 032/033 boundary: the Task 031 decision context must be built
# exactly once per build_for_session call.
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "decision-input-eligibility-test"},
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _seed_session(user_input: str) -> str:
    session_id = _create_session(user_input)

    obs_response = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert obs_response.status_code == 201

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201
    assert len(generate_response.json()) > 0

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    return session_id


def test_build_for_session_builds_decision_context_exactly_once(monkeypatch) -> None:
    session_id = UUID(_seed_session("Task 034 single-build regression test"))
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_id, offset=0, limit=100
        )

        context_service = _context_service()
        call_count = {"n": 0}
        original_build_for_session = context_service.build_for_session

        def _counting_build_for_session(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            return original_build_for_session(*args, **kwargs)

        monkeypatch.setattr(
            context_service, "build_for_session", _counting_build_for_session
        )

        candidate_evaluation_service = DecisionCandidateEvaluationService(
            context_service
        )
        consistency_service = DecisionEvaluationConsistencyService(
            candidate_evaluation_service
        )
        eligibility_service = DecisionInputEligibilityService(consistency_service)

        result = eligibility_service.build_for_session(db, session_id, candidates)

        assert call_count["n"] == 1
        assert result["eligible"] is True
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


def test_api_decision_input_eligibility_endpoint() -> None:
    session_id = _seed_session("Task 034 eligibility endpoint test")

    response = client.get(f"/sessions/{session_id}/decision-input-eligibility")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(ELIGIBILITY_RESULT_FIELDS)
    assert (
        payload["eligibility_source"]
        == ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034
    )
    assert payload["eligible"] is True
    for forbidden in (
        "winner",
        "selected_candidate",
        "decision",
        "diagnosis",
        "recommendation",
        "probability",
        "confidence",
        "utility_score",
        "weighted_score",
        "is_winner",
        "score",
        "ranking",
    ):
        assert forbidden not in payload


def test_api_decision_input_eligibility_empty_session() -> None:
    session_id = _create_session("Task 034 empty eligibility test")

    response = client.get(f"/sessions/{session_id}/decision-input-eligibility")
    assert response.status_code == 200
    payload = response.json()

    assert payload["has_candidates"] is False
    assert payload["eligible"] is False
    # All three conditions are independently false for an empty
    # session, so all three appear -- in Section 4 order.
    assert payload["blocking_conditions"] == [
        BLOCKING_DECISION_NOT_READY,
        BLOCKING_CONTEXT_UNAVAILABLE,
        BLOCKING_NO_CANDIDATES,
    ]


def test_api_decision_input_eligibility_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/decision-input-eligibility")
    assert response.status_code == 404


def test_api_decision_input_eligibility_is_read_only() -> None:
    session_id = _seed_session("Task 034 read-only test")

    context_before = client.get(f"/sessions/{session_id}/decision-context").json()
    consistency_before = client.get(
        f"/sessions/{session_id}/decision-evaluation-consistency"
    ).json()

    response = client.get(f"/sessions/{session_id}/decision-input-eligibility")
    assert response.status_code == 200

    assert (
        client.get(f"/sessions/{session_id}/decision-context").json() == context_before
    )
    assert (
        client.get(f"/sessions/{session_id}/decision-evaluation-consistency").json()
        == consistency_before
    )


def test_api_decision_input_eligibility_is_deterministic() -> None:
    session_id = _seed_session("Task 034 determinism test")

    first = client.get(f"/sessions/{session_id}/decision-input-eligibility").json()
    second = client.get(f"/sessions/{session_id}/decision-input-eligibility").json()

    assert first == second


def test_api_response_matches_service_output() -> None:
    session_id = _seed_session("Task 034 service-agreement test")

    api_result = client.get(
        f"/sessions/{session_id}/decision-input-eligibility"
    ).json()

    # Use whichever db dependency is actually wired into `client` right now
    # rather than this module's own engine directly: when the full suite
    # runs, test-module import order decides which override "wins" on the
    # shared `app` object, and it need not be this module's.
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _eligibility_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == service_result

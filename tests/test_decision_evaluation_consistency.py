"""Tests for the Task 033 decision-evaluation consistency/coverage layer.

Task 033 consumes only the Task 032 candidate evaluations and answers
"are the candidate evaluations complete, structurally consistent, and
fully comparable across the current decision context?" It never
selects a winner, never diagnoses, never computes a probability or
score, and never persists anything.

Regression note: running this file alone is not a substitute for the
full suite. Tasks 020-032 must be re-run alongside this file before
Task 033 is considered done (Definition of Done #11).
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
    DEFAULT_CRITERIA,
    DecisionCandidateEvaluationService,
)
from rop.services.decision_context import DecisionContextService
from rop.services.decision_evaluation_consistency import (
    CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033,
    DecisionEvaluationConsistencyContractError,
    DecisionEvaluationConsistencyService,
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
    CONSISTENCY_MIXED,
    CONSISTENCY_NO_EVIDENCE,
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


CONSISTENCY_RESULT_FIELDS = (
    "consistent",
    "evaluation_count",
    "expected_candidate_count",
    "candidate_count_matches",
    "criterion_sets_match",
    "criterion_count_matches",
    "criterion_definitions_match",
    "required_flags_match",
    "evaluation_completeness_matches",
    "candidate_ids_unique",
    "criterion_ids_unique_per_candidate",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "has_missing_candidate_evaluation",
    "has_incomplete_evaluation",
    "has_structural_mismatch",
    "consistency_source",
)

_DECLARED_CRITERION_IDS = frozenset(c.criterion_id for c in DEFAULT_CRITERIA)


# ---------------------------------------------------------------------------
# Helpers -- build a genuine Tasks 027-032 chain from hand-crafted score
# results, exactly like the Task 031/032 test suites do, so every "well
# formed" evaluation used here is a real Task 032 output, not a guess at
# its shape.
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


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    evidence_consistency: str = CONSISTENCY_SUPPORT_ONLY,
    total_support_contribution: float = 0.0,
    total_contradiction_contribution: float = 0.0,
    evidence_coverage_ratio: float | None = None,
) -> dict[str, Any]:
    has_evidence = evidence_consistency != CONSISTENCY_NO_EVIDENCE
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
        "total_evidence_items": 1 if has_evidence else 0,
        "total_support_contribution": total_support_contribution,
        "total_contradiction_contribution": total_contradiction_contribution,
        "net_contribution": (
            total_support_contribution - total_contradiction_contribution
        ),
        "has_evidence": has_evidence,
        "has_mixed_evidence": evidence_consistency == CONSISTENCY_MIXED,
        "score_direction": score_direction,
        "evidence_coverage_ratio": evidence_coverage_ratio,
        "informative_evidence_ratio": evidence_coverage_ratio,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING" if has_evidence else "UNSUPPORTED",
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


def _make_evaluations_and_expected_ids(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Run the real Task 031 -> Task 032 chain and return both outputs.

    ``expected_ids`` comes from the same built context's
    ``differential``, mirroring exactly what
    ``DecisionEvaluationConsistencyService.check_session`` now does
    with a single context build (fix for the duplicate-construction
    issue) rather than a second, independent pipeline.
    """
    context = _make_context(entries)
    evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    return evaluations, expected_ids


def _recompute_counts(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Recompute an evaluation's derived count/completeness fields
    from its (possibly hand-mutated) ``criteria`` list, so a criterion-
    structure test can isolate exactly one Task 033 flag without also
    tripping the independent count-consistency checks as a side
    effect.
    """
    evaluation = copy.deepcopy(evaluation)
    criteria = evaluation["criteria"]
    satisfied = sum(1 for c in criteria if c["satisfied"] is True)
    required = [c for c in criteria if c["required"] is True]
    required_satisfied = sum(1 for c in required if c["satisfied"] is True)

    evaluation["criterion_count"] = len(criteria)
    evaluation["criteria_satisfied"] = satisfied
    evaluation["criteria_unsatisfied"] = len(criteria) - satisfied
    evaluation["required_criteria_satisfied"] = required_satisfied
    evaluation["required_criteria_unsatisfied"] = len(required) - required_satisfied
    evaluation["evaluation_complete"] = (
        len(criteria) == len(DEFAULT_CRITERIA)
        and {c["criterion_id"] for c in criteria} == _DECLARED_CRITERION_IDS
    )
    return evaluation


def _one_well_formed_evaluation() -> tuple[dict[str, Any], list[Any]]:
    evaluations, expected_ids = _make_evaluations_and_expected_ids(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    return evaluations[0], expected_ids


# ---------------------------------------------------------------------------
# Normal cases
# ---------------------------------------------------------------------------


def test_multiple_valid_candidates_are_consistent() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        _score_result(hypothesis_name="H3", hypothesis_score=1.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)

    result = _consistency_service().check(evaluations, expected_ids)

    assert set(result) == set(CONSISTENCY_RESULT_FIELDS)
    assert result["consistent"] is True
    assert result["evaluation_count"] == 3
    assert result["expected_candidate_count"] == 3


def test_single_valid_candidate_is_consistent() -> None:
    evaluations, expected_ids = _make_evaluations_and_expected_ids(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["consistent"] is True
    assert result["evaluation_count"] == 1
    assert result["expected_candidate_count"] == 1


def test_empty_candidate_set_is_structurally_valid() -> None:
    evaluations, expected_ids = _make_evaluations_and_expected_ids([])

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["consistent"] is True
    assert result["evaluation_count"] == 0
    assert result["expected_candidate_count"] == 0
    assert result["has_missing_candidate_evaluation"] is False
    assert result["has_incomplete_evaluation"] is False
    assert result["candidate_count_matches"] is True
    assert result["all_candidates_evaluated"] is True


def test_all_candidates_fully_complete() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["evaluation_completeness_matches"] is True
    assert result["all_criteria_evaluated"] is True
    assert result["has_incomplete_evaluation"] is False


def test_identical_criterion_sets_across_candidates() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        _score_result(hypothesis_name="H3", hypothesis_score=1.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["criterion_sets_match"] is True
    assert result["criterion_count_matches"] is True


def test_identical_required_optional_flags_across_candidates() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["required_flags_match"] is True
    assert result["criterion_definitions_match"] is True


def test_deterministic_repeated_evaluation() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)
    service = _consistency_service()

    first = service.check(evaluations, expected_ids)
    second = service.check(evaluations, expected_ids)

    assert first == second


def test_no_decision_fields_are_introduced() -> None:
    evaluations, expected_ids = _make_evaluations_and_expected_ids(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    result = _consistency_service().check(evaluations, expected_ids)

    assert set(result) == set(CONSISTENCY_RESULT_FIELDS)
    for forbidden in (
        "winner",
        "selected_candidate",
        "decision",
        "diagnosis",
        "probability",
        "confidence",
        "utility_score",
        "weighted_score",
        "is_winner",
        "score",
        "ranking",
    ):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# Candidate coverage
# ---------------------------------------------------------------------------


def test_missing_candidate_detected() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)
    trimmed = evaluations[:1]

    result = _consistency_service().check(trimmed, expected_ids)

    assert result["has_missing_candidate_evaluation"] is True
    assert result["candidate_count_matches"] is False
    assert result["all_candidates_evaluated"] is False
    assert result["consistent"] is False


def test_duplicate_candidate_detected() -> None:
    evaluations, expected_ids = _make_evaluations_and_expected_ids(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    duplicated = evaluations + [copy.deepcopy(evaluations[0])]

    result = _consistency_service().check(duplicated, expected_ids)

    assert result["candidate_ids_unique"] is False
    assert result["all_candidates_evaluated"] is False
    assert result["consistent"] is False


def test_unexpected_candidate_detected() -> None:
    evaluations, expected_ids = _make_evaluations_and_expected_ids(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    extra = copy.deepcopy(evaluations[0])
    extra["hypothesis_id"] = uuid4()
    combined = evaluations + [extra]

    result = _consistency_service().check(combined, expected_ids)

    assert result["has_missing_candidate_evaluation"] is False
    assert result["candidate_count_matches"] is False
    assert result["all_candidates_evaluated"] is False
    assert result["consistent"] is False


def test_expected_candidate_count_mismatch() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)
    trimmed_expected = expected_ids[:1]

    result = _consistency_service().check(evaluations, trimmed_expected)

    assert result["candidate_count_matches"] is False
    assert result["all_candidates_evaluated"] is False
    assert result["consistent"] is False


def test_zero_evaluations_with_expected_candidates() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    _, expected_ids = _make_evaluations_and_expected_ids(entries)

    result = _consistency_service().check([], expected_ids)

    assert result["evaluation_count"] == 0
    assert result["expected_candidate_count"] == 2
    assert result["has_missing_candidate_evaluation"] is True
    assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Criterion structure
# ---------------------------------------------------------------------------


def test_missing_criterion_detected() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    mutated = copy.deepcopy(evaluation)
    mutated["criteria"] = mutated["criteria"][:-1]
    mutated = _recompute_counts(mutated)

    result = _consistency_service().check([mutated], expected_ids)

    assert result["criterion_sets_match"] is False
    assert result["all_criteria_evaluated"] is False
    assert result["consistent"] is False


def test_unexpected_criterion_detected() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    mutated = copy.deepcopy(evaluation)
    mutated["criteria"].append(
        {
            "criterion_id": "extra_undeclared_criterion",
            "criterion_name": "Not a real criterion",
            "satisfied": True,
            "required": False,
            "reason": "manually injected for test coverage",
        }
    )
    mutated = _recompute_counts(mutated)

    result = _consistency_service().check([mutated], expected_ids)

    assert result["criterion_sets_match"] is False
    assert result["criterion_definitions_match"] is False
    assert result["required_flags_match"] is False
    assert result["consistent"] is False


def test_duplicate_criterion_id_detected() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    mutated = copy.deepcopy(evaluation)
    mutated["criteria"].append(copy.deepcopy(mutated["criteria"][0]))
    mutated = _recompute_counts(mutated)

    result = _consistency_service().check([mutated], expected_ids)

    assert result["criterion_ids_unique_per_candidate"] is False
    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


def test_different_criterion_name_detected() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    mutated = copy.deepcopy(evaluation)
    mutated["criteria"][0]["criterion_name"] = "A completely different name"

    result = _consistency_service().check([mutated], expected_ids)

    assert result["criterion_definitions_match"] is False
    assert result["consistent"] is False


def test_different_required_flag_detected() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    mutated = copy.deepcopy(evaluation)
    mutated["criteria"][0]["required"] = not mutated["criteria"][0]["required"]
    mutated = _recompute_counts(mutated)

    result = _consistency_service().check([mutated], expected_ids)

    assert result["required_flags_match"] is False
    assert result["consistent"] is False


def test_different_criterion_count_detected() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    mutated = copy.deepcopy(evaluation)
    mutated["criterion_count"] = mutated["criterion_count"] + 1

    result = _consistency_service().check([mutated], expected_ids)

    assert result["criterion_count_matches"] is False
    assert result["consistent"] is False


def test_different_criterion_definitions_between_candidates() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)
    evaluations = [copy.deepcopy(e) for e in evaluations]
    evaluations[0]["criteria"][0]["criterion_name"] = "Only candidate 0 differs"

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["criterion_definitions_match"] is False
    assert result["consistent"] is False


def test_all_expected_criteria_present_for_every_candidate() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)

    result = _consistency_service().check(evaluations, expected_ids)

    assert result["all_criteria_evaluated"] is True
    assert result["criterion_sets_match"] is True


# ---------------------------------------------------------------------------
# Independent validation -- Task 033 must recompute these itself rather
# than trusting Task 032's own summary fields.
# ---------------------------------------------------------------------------


def test_detects_corrupted_criterion_count_independently() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criterion_count"] = corrupted["criterion_count"] + 1

    result = _consistency_service().check([corrupted], expected_ids)

    assert result["criterion_count_matches"] is False
    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


def test_detects_corrupted_criteria_satisfied_independently() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria_satisfied"] = corrupted["criteria_satisfied"] + 1

    result = _consistency_service().check([corrupted], expected_ids)

    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


def test_detects_corrupted_criteria_unsatisfied_independently() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria_unsatisfied"] = corrupted["criteria_unsatisfied"] + 1

    result = _consistency_service().check([corrupted], expected_ids)

    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


def test_detects_corrupted_required_criteria_satisfied_independently() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["required_criteria_satisfied"] = (
        corrupted["required_criteria_satisfied"] + 1
    )

    result = _consistency_service().check([corrupted], expected_ids)

    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


def test_detects_corrupted_required_criteria_unsatisfied_independently() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["required_criteria_unsatisfied"] = (
        corrupted["required_criteria_unsatisfied"] + 1
    )

    result = _consistency_service().check([corrupted], expected_ids)

    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


def test_detects_corrupted_evaluation_complete_independently() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["evaluation_complete"] = not corrupted["evaluation_complete"]

    result = _consistency_service().check([corrupted], expected_ids)

    assert result["evaluation_completeness_matches"] is False
    assert result["has_structural_mismatch"] is True
    assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Contract tests -- malformed/mistyped input to check()
# ---------------------------------------------------------------------------


def test_rejects_none_evaluations() -> None:
    _, expected_ids = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check(None, expected_ids)


def test_rejects_evaluations_not_a_list() -> None:
    _, expected_ids = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check("not-a-list", expected_ids)  # type: ignore[arg-type]


def test_rejects_evaluations_given_as_tuple() -> None:
    # Task 032's contract declares evaluations as a list. A tuple is
    # a Sequence too, but it is not the declared container type, so
    # it must be rejected on its own rather than quietly tolerated
    # because it happens to be sequence-like.
    evaluation, expected_ids = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check((evaluation,), expected_ids)  # type: ignore[arg-type]


def test_rejects_malformed_candidate_evaluation() -> None:
    _, expected_ids = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check(["not-a-mapping"], expected_ids)  # type: ignore[list-item]


def test_rejects_evaluation_missing_required_field() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    del corrupted["evaluation_complete"]

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_missing_candidate_id() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["hypothesis_id"] = None

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "MISSING_CANDIDATE_ID"


def test_rejects_unhashable_candidate_id() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["hypothesis_id"] = ["not", "hashable"]

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "INVALID_CANDIDATE_ID_TYPE"


def test_rejects_string_masquerading_as_candidate_id() -> None:
    # Task 032 declares hypothesis_id as a UUID. A hashable string is
    # not a type error at the set-operation level, but it is still
    # not the declared type, so this must be rejected on its own --
    # not merely tolerated because it happens to be hashable.
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["hypothesis_id"] = "abc123"

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "INVALID_CANDIDATE_ID_TYPE"


def test_rejects_criteria_not_a_list() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"] = "not-a-list"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_criteria_given_as_tuple() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"] = tuple(corrupted["criteria"])

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_malformed_criterion_result() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"][0] = "not-a-mapping"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_criterion_missing_required_field() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    del corrupted["criteria"][0]["required"]

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_invalid_criterion_id() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"][0]["criterion_id"] = ""

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_evaluation_missing_hypothesis_name() -> None:
    # Task 032's own contract requires hypothesis_name on every
    # candidate evaluation even though Task 033's structural
    # calculations never read it. A Task 032 evaluation missing it is
    # malformed per the 032 contract, so Task 033 must reject it too
    # rather than silently accepting a partial 032 shape.
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    del corrupted["hypothesis_name"]

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "MISSING_EVALUATION_FIELD"


def test_rejects_non_string_hypothesis_name() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["hypothesis_name"] = 123

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "HYPOTHESIS_NAME_TYPE"


def test_rejects_evaluation_missing_evaluation_source() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    del corrupted["evaluation_source"]

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "MISSING_EVALUATION_FIELD"


def test_rejects_non_string_evaluation_source() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["evaluation_source"] = 123

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "EVALUATION_SOURCE_TYPE"


def test_rejects_wrong_evaluation_source_value() -> None:
    # A well-typed string is not enough -- Task 032's evaluation_source
    # is a fixed identifier, so a syntactically valid but wrong value
    # (e.g. from a different or forged source) is just as malformed
    # per the 032 contract as a missing or non-string one, and must
    # not be tolerated merely because it happens to be a string.
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["evaluation_source"] = "SOME_RANDOM_SOURCE"

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "INVALID_EVALUATION_SOURCE"


def test_rejects_criterion_missing_reason() -> None:
    # Likewise, each Task 032 criterion result carries a reason field.
    # A criterion missing it is malformed per the 032 contract even
    # though Task 033's structural calculations never read it.
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    del corrupted["criteria"][0]["reason"]

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "MISSING_CRITERION_FIELD"


def test_rejects_non_string_criterion_reason() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"][0]["reason"] = 123

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "CRITERION_REASON_TYPE"


def test_rejects_non_string_criterion_name() -> None:
    # The field-presence check alone would let criterion_name = 123
    # through silently (it would only fail the later definition
    # comparison against the declared criterion, not be flagged as
    # malformed input). Task 032's schema declares this as a string,
    # so Task 033 must independently enforce that type too.
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"][0]["criterion_name"] = 123

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == "CRITERION_NAME_TYPE"


def test_rejects_invalid_satisfied_boolean() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"][0]["satisfied"] = "yes"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_invalid_required_boolean() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criteria"][0]["required"] = "no"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_invalid_integer_field() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criterion_count"] = "6"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_boolean_in_integer_field() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["criterion_count"] = True

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


@pytest.mark.parametrize(
    "field",
    [
        "criterion_count",
        "criteria_satisfied",
        "criteria_unsatisfied",
        "required_criteria_satisfied",
        "required_criteria_unsatisfied",
    ],
)
def test_rejects_negative_incoming_count(field: str) -> None:
    # An impossible (negative) count in Task 032's own reported
    # fields is malformed input per the 032 contract -- not merely a
    # structural mismatch to be recalculated and reported through the
    # boolean flags. It must raise, not silently feed the independent
    # count-consistency check.
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted[field] = -1

    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([corrupted], expected_ids)
    assert exc_info.value.invariant == f"{field.upper()}_NEGATIVE"


def test_rejects_invalid_evaluation_complete_type() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    corrupted = copy.deepcopy(evaluation)
    corrupted["evaluation_complete"] = "true"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([corrupted], expected_ids)


def test_rejects_none_expected_candidate_ids() -> None:
    evaluation, _ = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([evaluation], None)


def test_rejects_expected_candidate_ids_not_a_list() -> None:
    evaluation, _ = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([evaluation], "not-a-list")  # type: ignore[arg-type]


def test_rejects_expected_candidate_ids_given_as_tuple() -> None:
    evaluation, expected_ids = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError):
        _consistency_service().check([evaluation], tuple(expected_ids))  # type: ignore[arg-type]


def test_rejects_null_expected_candidate_id() -> None:
    evaluation, _ = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([evaluation], [None])
    assert exc_info.value.invariant == "INVALID_EXPECTED_CANDIDATE_ID"


def test_rejects_unhashable_expected_candidate_id() -> None:
    evaluation, _ = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([evaluation], [["not", "hashable"]])
    assert exc_info.value.invariant == "INVALID_EXPECTED_CANDIDATE_ID_TYPE"


def test_rejects_string_masquerading_as_expected_candidate_id() -> None:
    evaluation, _ = _one_well_formed_evaluation()
    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([evaluation], ["abc123"])
    assert exc_info.value.invariant == "INVALID_EXPECTED_CANDIDATE_ID_TYPE"


def test_rejects_duplicate_expected_candidate_id() -> None:
    evaluation, _ = _one_well_formed_evaluation()
    candidate_id = evaluation["hypothesis_id"]
    with pytest.raises(DecisionEvaluationConsistencyContractError) as exc_info:
        _consistency_service().check([evaluation], [candidate_id, candidate_id])
    assert exc_info.value.invariant == "DUPLICATE_EXPECTED_CANDIDATE_ID"


# ---------------------------------------------------------------------------
# Contract tests -- the output validator, exercised directly
# ---------------------------------------------------------------------------


def _well_formed_result() -> dict[str, Any]:
    evaluation, expected_ids = _one_well_formed_evaluation()
    return _consistency_service().check([evaluation], expected_ids)


def test_validate_result_accepts_well_formed_result() -> None:
    result = _well_formed_result()
    DecisionEvaluationConsistencyService._validate_result(result)


def test_validate_result_rejects_non_boolean_field() -> None:
    corrupted = copy.deepcopy(_well_formed_result())
    corrupted["consistent"] = "yes"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        DecisionEvaluationConsistencyService._validate_result(corrupted)


def test_validate_result_rejects_negative_evaluation_count() -> None:
    corrupted = copy.deepcopy(_well_formed_result())
    corrupted["evaluation_count"] = -1

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        DecisionEvaluationConsistencyService._validate_result(corrupted)


def test_validate_result_rejects_negative_expected_candidate_count() -> None:
    corrupted = copy.deepcopy(_well_formed_result())
    corrupted["expected_candidate_count"] = -1

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        DecisionEvaluationConsistencyService._validate_result(corrupted)


def test_validate_result_rejects_invalid_consistency_source() -> None:
    corrupted = copy.deepcopy(_well_formed_result())
    corrupted["consistency_source"] = "SOMETHING_ELSE"

    with pytest.raises(DecisionEvaluationConsistencyContractError):
        DecisionEvaluationConsistencyService._validate_result(corrupted)


# ---------------------------------------------------------------------------
# Integrity: no mutation, determinism
# ---------------------------------------------------------------------------


def test_check_does_not_mutate_its_inputs() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    evaluations, expected_ids = _make_evaluations_and_expected_ids(entries)
    evaluations_before = copy.deepcopy(evaluations)
    expected_ids_before = copy.deepcopy(expected_ids)

    _consistency_service().check(evaluations, expected_ids)

    assert evaluations == evaluations_before
    assert expected_ids == expected_ids_before


# ---------------------------------------------------------------------------
# Regression lock for the duplicate-context-construction fix (#4): the
# Task 031 decision context must be built exactly once per
# check_session call, not once inside evaluate_session and again
# independently.
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "decision-evaluation-consistency-test"},
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


def test_check_session_builds_decision_context_exactly_once(monkeypatch) -> None:
    session_id = UUID(_seed_session("Task 033 single-build regression test"))
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

        result = consistency_service.check_session(db, session_id, candidates)

        assert call_count["n"] == 1
        assert result["consistent"] is True
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


def test_api_decision_evaluation_consistency_endpoint() -> None:
    session_id = _seed_session("Task 033 consistency endpoint test")

    response = client.get(f"/sessions/{session_id}/decision-evaluation-consistency")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(CONSISTENCY_RESULT_FIELDS)
    assert (
        payload["consistency_source"]
        == CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033
    )
    assert payload["consistent"] is True
    for forbidden in (
        "winner",
        "selected_candidate",
        "decision",
        "diagnosis",
        "probability",
        "confidence",
        "utility_score",
        "weighted_score",
        "is_winner",
        "score",
        "ranking",
    ):
        assert forbidden not in payload


def test_api_decision_evaluation_consistency_empty_session() -> None:
    session_id = _create_session("Task 033 empty consistency test")

    response = client.get(f"/sessions/{session_id}/decision-evaluation-consistency")
    assert response.status_code == 200
    payload = response.json()

    assert payload["evaluation_count"] == 0
    assert payload["expected_candidate_count"] == 0
    assert payload["consistent"] is True


def test_api_decision_evaluation_consistency_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/decision-evaluation-consistency")
    assert response.status_code == 404


def test_api_decision_evaluation_consistency_is_read_only() -> None:
    session_id = _seed_session("Task 033 read-only test")

    context_before = client.get(f"/sessions/{session_id}/decision-context").json()
    evaluations_before = client.get(
        f"/sessions/{session_id}/decision-candidate-evaluations"
    ).json()

    response = client.get(f"/sessions/{session_id}/decision-evaluation-consistency")
    assert response.status_code == 200

    assert (
        client.get(f"/sessions/{session_id}/decision-context").json() == context_before
    )
    assert (
        client.get(f"/sessions/{session_id}/decision-candidate-evaluations").json()
        == evaluations_before
    )


def test_api_decision_evaluation_consistency_is_deterministic() -> None:
    session_id = _seed_session("Task 033 determinism test")

    first = client.get(f"/sessions/{session_id}/decision-evaluation-consistency").json()
    second = client.get(
        f"/sessions/{session_id}/decision-evaluation-consistency"
    ).json()

    assert first == second


def test_api_response_matches_service_output() -> None:
    session_id = _seed_session("Task 033 service-agreement test")

    api_result = client.get(
        f"/sessions/{session_id}/decision-evaluation-consistency"
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
        service_result = _consistency_service().check_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == service_result

"""Tests for Task 039 decision policy execution contract.

Task 039 is the first boundary permitted to select a candidate. It
executes the Task 038 default policy against the Task 037 bundle:
required-criteria eligibility, then the existing upstream rank, then a
unique highest rank wins. Ties return UNRESOLVED; no hidden tie-breaker.
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
from rop.services.decision_execution import (
    DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039,
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_INPUT_UNAVAILABLE,
    OUTCOME_NO_ELIGIBLE_CANDIDATE,
    OUTCOME_SELECTED,
    OUTCOME_UNRESOLVED,
    DecisionExecutionContractError,
    DecisionExecutionService,
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

RESULT_FIELDS = (
    "available",
    "outcome",
    "selected_candidate",
    "eligible_candidate_count",
    "eligible_candidate_ids",
    "policy_id",
    "policy_version",
    "decision_execution_source",
)

SELECTED_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "rank",
    "score",
)


def _service() -> DecisionExecutionService:
    return DecisionExecutionService()


def _default_policy() -> dict[str, Any]:
    return {
        "policy_id": "DECISION_POLICY_DEFAULT",
        "policy_version": "1.0.0",
        "policy_name": "Default Decision Policy",
        "required_candidate_count": 1,
        "allowed_selection_mode": "SINGLE_CANDIDATE",
        "required_criteria_behavior": "MUST_ALL_BE_SATISFIED",
        "tie_behavior": "MUST_RETURN_UNRESOLVED",
        "insufficient_input_behavior": "MUST_RETURN_UNAVAILABLE",
        "incomplete_input_behavior": "MUST_RETURN_INCONSISTENT",
        "policy_source": "DECISION_POLICY_TASK_038",
    }


def _criterion(cid: str, required: bool, satisfied: bool) -> dict[str, Any]:
    return {
        "criterion_id": cid,
        "criterion_name": f"Criterion {cid}",
        "satisfied": satisfied,
        "required": required,
        "reason": "test reason",
    }


def _assessment(
    hid: UUID,
    name: str,
    rank: int,
    score: float,
    criteria_specs: list[tuple[str, bool, bool]],
) -> dict[str, Any]:
    criteria = [_criterion(cid, req, sat) for cid, req, sat in criteria_specs]
    sat = sum(1 for c in criteria if c["satisfied"])
    unsat = len(criteria) - sat
    req_sat = sum(1 for c in criteria if c["required"] and c["satisfied"])
    req_unsat = sum(1 for c in criteria if c["required"] and not c["satisfied"])
    return {
        "hypothesis_id": hid,
        "hypothesis_name": name,
        "rank": rank,
        "score": score,
        "is_tied": False,
        "tie_group_size": 1,
        "score_gap_to_next_higher": None,
        "score_gap_to_next_lower": None,
        "criteria": criteria,
        "criterion_count": len(criteria),
        "criteria_satisfied": sat,
        "criteria_unsatisfied": unsat,
        "required_criteria_satisfied": req_sat,
        "required_criteria_unsatisfied": req_unsat,
        "evaluation_complete": True,
        "assessment_source": "DECISION_CANDIDATE_ASSESSMENT_TASK_036",
    }


def _bundle(
    assessments: list[dict[str, Any]],
    *,
    available: bool = True,
    consistent: bool = True,
) -> dict[str, Any]:
    return {
        "available": available,
        "candidate_set": {
            "available": available,
            "candidate_count": len(assessments),
            "candidates": [
                {
                    "hypothesis_id": a["hypothesis_id"],
                    "hypothesis_name": a["hypothesis_name"],
                    "rank": a["rank"],
                    "score": a["score"],
                    "is_tied": False,
                    "tie_group_size": 1,
                    "score_gap_to_next_higher": None,
                    "score_gap_to_next_lower": None,
                }
                for a in assessments
            ],
            "candidate_order_preserved": True,
            "candidate_set_complete": available,
            "candidate_set_source": "DECISION_CANDIDATE_SET_TASK_035",
        },
        "assessment_set": {
            "available": available,
            "candidate_count": len(assessments),
            "assessments": assessments,
            "candidate_order_preserved": True,
            "evaluation_coverage_complete": available,
            "assessment_structure_consistent": available,
            "assessment_source": "DECISION_CANDIDATE_ASSESSMENT_TASK_036",
        },
        "candidate_count": len(assessments) if available else 0,
        "candidate_order_preserved": True,
        "candidate_assessment_alignment_complete": available,
        "input_structure_consistent": consistent,
        "input_source": "DECISION_INPUT_BUNDLE_TASK_037",
    }


def _all_required_satisfied():
    return [("c1", True, True), ("c2", True, True)]


# ---------------------------------------------------------------------------
# Valid selection
# ---------------------------------------------------------------------------


def test_single_eligible_selected() -> None:
    hid = uuid4()
    a = _assessment(hid, "H1", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a]), _default_policy())

    assert set(result) == set(RESULT_FIELDS)
    assert result["outcome"] == OUTCOME_SELECTED
    assert result["available"] is True
    assert result["selected_candidate"]["hypothesis_id"] == hid


def test_unique_highest_among_multiple_selected() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2]), _default_policy())

    assert result["outcome"] == OUTCOME_SELECTED
    assert result["selected_candidate"]["hypothesis_id"] == h1


def test_selected_metadata_preserved() -> None:
    hid = uuid4()
    a = _assessment(hid, "Alpha", 3, 7.5, _all_required_satisfied())
    result = _service().build(_bundle([a]), _default_policy())

    sc = result["selected_candidate"]
    assert set(sc) == set(SELECTED_FIELDS)
    assert sc["hypothesis_id"] == hid
    assert sc["hypothesis_name"] == "Alpha"
    assert sc["rank"] == 3
    assert sc["score"] == 7.5


def test_eligible_ids_contain_all_eligible() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2]), _default_policy())

    assert result["eligible_candidate_count"] == 2
    assert result["eligible_candidate_ids"] == [h1, h2]


# ---------------------------------------------------------------------------
# No eligible candidate
# ---------------------------------------------------------------------------


def test_no_eligible_when_all_fail_required() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, [("c1", True, False)])
    a2 = _assessment(uuid4(), "H2", 2, 5.0, [("c1", True, False)])
    result = _service().build(_bundle([a1, a2]), _default_policy())

    assert result["outcome"] == OUTCOME_NO_ELIGIBLE_CANDIDATE
    assert result["available"] is True
    assert result["selected_candidate"] is None
    assert result["eligible_candidate_count"] == 0
    assert result["eligible_candidate_ids"] == []


def test_no_eligible_when_no_assessments() -> None:
    result = _service().build(_bundle([]), _default_policy())
    assert result["outcome"] == OUTCOME_NO_ELIGIBLE_CANDIDATE


# ---------------------------------------------------------------------------
# Tie at highest eligible rank
# ---------------------------------------------------------------------------


def test_unresolved_two_tied_at_highest() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2]), _default_policy())

    assert result["outcome"] == OUTCOME_UNRESOLVED
    assert result["available"] is True
    assert result["selected_candidate"] is None
    assert result["eligible_candidate_count"] == 2


def test_unresolved_three_tied_at_highest() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 1, 10.0, _all_required_satisfied())
    a3 = _assessment(uuid4(), "H3", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2, a3]), _default_policy())

    assert result["outcome"] == OUTCOME_UNRESOLVED
    assert result["eligible_candidate_count"] == 3


def test_unique_highest_wins_despite_lower_tie() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 2, 5.0, _all_required_satisfied())
    a3 = _assessment(uuid4(), "H3", 2, 5.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2, a3]), _default_policy())

    assert result["outcome"] == OUTCOME_SELECTED
    assert result["selected_candidate"]["hypothesis_id"] == h1


# ---------------------------------------------------------------------------
# Required / optional criteria
# ---------------------------------------------------------------------------


def test_optional_failure_does_not_exclude() -> None:
    hid = uuid4()
    a = _assessment(
        hid, "H1", 1, 10.0,
        [("req", True, True), ("opt", False, False)],
    )
    result = _service().build(_bundle([a]), _default_policy())
    assert result["outcome"] == OUTCOME_SELECTED


def test_required_failure_excludes() -> None:
    a = _assessment(
        uuid4(), "H1", 1, 10.0,
        [("req", True, False), ("opt", False, True)],
    )
    result = _service().build(_bundle([a]), _default_policy())
    assert result["outcome"] == OUTCOME_NO_ELIGIBLE_CANDIDATE


def test_mixed_required_and_optional() -> None:
    h1 = uuid4()
    a1 = _assessment(
        h1, "H1", 1, 10.0,
        [("r1", True, True), ("o1", False, False)],
    )
    a2 = _assessment(
        uuid4(), "H2", 2, 5.0,
        [("r1", True, False), ("o1", False, True)],
    )
    result = _service().build(_bundle([a1, a2]), _default_policy())
    assert result["outcome"] == OUTCOME_SELECTED
    assert result["selected_candidate"]["hypothesis_id"] == h1
    assert result["eligible_candidate_ids"] == [h1]


def test_zero_required_criteria_is_vacuously_eligible() -> None:
    hid = uuid4()
    a = _assessment(hid, "H1", 1, 10.0, [("opt", False, False)])
    result = _service().build(_bundle([a]), _default_policy())
    assert result["outcome"] == OUTCOME_SELECTED
    assert result["selected_candidate"]["hypothesis_id"] == hid


# ---------------------------------------------------------------------------
# Input states
# ---------------------------------------------------------------------------


def test_unavailable_bundle_returns_input_unavailable() -> None:
    result = _service().build(
        _bundle([], available=False), _default_policy()
    )
    assert result["outcome"] == OUTCOME_INPUT_UNAVAILABLE
    assert result["available"] is False
    assert result["selected_candidate"] is None
    assert result["eligible_candidate_count"] == 0
    assert result["eligible_candidate_ids"] == []


def test_inconsistent_bundle_returns_input_inconsistent() -> None:
    # Task 037 folds input_structure_consistent into available, so the
    # only validly-shaped bundle with structure=False also has
    # available=False. Task 039 must classify it as INPUT_INCONSISTENT
    # (not INPUT_UNAVAILABLE) by checking structure first.
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    result = _service().build(
        _bundle([a], available=False, consistent=False), _default_policy()
    )
    assert result["outcome"] == OUTCOME_INPUT_INCONSISTENT
    assert result["available"] is False
    assert result["selected_candidate"] is None


def test_policy_id_and_version_preserved() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    policy = _default_policy()
    policy["policy_id"] = "CUSTOM_ID"
    policy["policy_version"] = "9.9.9"
    result = _service().build(_bundle([a]), policy)
    assert result["policy_id"] == "CUSTOM_ID"
    assert result["policy_version"] == "9.9.9"


def test_execution_source_is_fixed() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a]), _default_policy())
    assert (
        result["decision_execution_source"]
        == DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_eligible_ids_preserve_upstream_order() -> None:
    h1, h2, h3 = uuid4(), uuid4(), uuid4()
    a1 = _assessment(h1, "A", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "B", 2, 5.0, _all_required_satisfied())
    a3 = _assessment(h3, "C", 3, 1.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2, a3]), _default_policy())
    assert result["eligible_candidate_ids"] == [h1, h2, h3]


def test_no_implicit_tie_breaking_by_name() -> None:
    """Two tied at highest rank must be UNRESOLVED, even if names differ."""
    a1 = _assessment(uuid4(), "zzz", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "aaa", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2]), _default_policy())
    assert result["outcome"] == OUTCOME_UNRESOLVED


def test_no_implicit_tie_breaking_by_uuid() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a1, a2]), _default_policy())
    assert result["outcome"] == OUTCOME_UNRESOLVED


# ---------------------------------------------------------------------------
# Validator: input contract failures
# ---------------------------------------------------------------------------


def test_rejects_none_bundle() -> None:
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(None, _default_policy())
    assert ei.value.invariant == "MISSING_BUNDLE"


def test_rejects_non_mapping_bundle() -> None:
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build("nope", _default_policy())  # type: ignore[arg-type]
    assert ei.value.invariant == "BUNDLE_TYPE"


def test_rejects_missing_bundle_field() -> None:
    b = _bundle([])
    del b["available"]
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "MISSING_BUNDLE_FIELD"


def test_rejects_invalid_bundle_source() -> None:
    b = _bundle([])
    b["input_source"] = "WRONG"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_SOURCE"


def test_rejects_none_policy() -> None:
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([]), None)
    assert ei.value.invariant == "MISSING_POLICY"


def test_rejects_missing_policy_field() -> None:
    p = _default_policy()
    del p["tie_behavior"]
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([]), p)
    assert ei.value.invariant == "MISSING_POLICY_FIELD"


def test_rejects_invalid_policy_source() -> None:
    p = _default_policy()
    p["policy_source"] = "WRONG"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([]), p)
    assert ei.value.invariant == "INVALID_POLICY_SOURCE"


def test_rejects_unsupported_selection_mode() -> None:
    p = _default_policy()
    p["allowed_selection_mode"] = "MULTIPLE_CANDIDATES"
    p["required_candidate_count"] = None
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([]), p)
    assert ei.value.invariant == "UNSUPPORTED_POLICY_VALUES"


def test_rejects_unsupported_tie_behavior() -> None:
    p = _default_policy()
    p["tie_behavior"] = "MUST_APPLY_EXPLICIT_TIEBREAKER"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([]), p)
    assert ei.value.invariant == "UNSUPPORTED_POLICY_VALUES"


def test_rejects_unsupported_required_criteria_behavior() -> None:
    p = _default_policy()
    p["required_criteria_behavior"] = "MUST_BE_CONSIDERED"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([]), p)
    assert ei.value.invariant == "UNSUPPORTED_POLICY_VALUES"


def test_rejects_malformed_assessment() -> None:
    # Task 037's own validator catches a non-mapping assessment before
    # Task 039's eligibility computation runs; the Task 039 layer wraps
    # that as INVALID_BUNDLE_STRUCTURE.
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a])
    b["assessment_set"]["assessments"][0] = "not-a-mapping"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_missing_criteria() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    del a["criteria"]
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([a]), _default_policy())
    assert ei.value.invariant == "MISSING_ASSESSMENT_CRITERIA"


def test_rejects_malformed_criterion() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a["criteria"][0] = "not-a-mapping"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([a]), _default_policy())
    assert ei.value.invariant == "MALFORMED_CRITERION"


def test_rejects_missing_criterion_field() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    del a["criteria"][0]["required"]
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([a]), _default_policy())
    assert ei.value.invariant == "MISSING_CRITERION_FIELD"


def test_rejects_non_bool_criterion_field() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a["criteria"][0]["satisfied"] = "yes"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(_bundle([a]), _default_policy())
    assert ei.value.invariant == "CRITERION_FIELD_TYPE"


# ---------------------------------------------------------------------------
# Determinism / no mutation
# ---------------------------------------------------------------------------


def test_does_not_mutate_bundle() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a])
    before = copy.deepcopy(b)
    _service().build(b, _default_policy())
    assert b == before


def test_does_not_mutate_policy() -> None:
    p = _default_policy()
    before = copy.deepcopy(p)
    _service().build(_bundle([]), p)
    assert p == before


def test_deterministic() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a])
    p = _default_policy()
    s = _service()
    assert s.build(b, p) == s.build(b, p)


# ---------------------------------------------------------------------------
# No-decision-field regression
# ---------------------------------------------------------------------------


def test_no_forbidden_fields_in_result() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    result = _service().build(_bundle([a]), _default_policy())
    forbidden = (
        "probability",
        "confidence",
        "utility",
        "utility_score",
        "expected_outcome",
        "recommendation",
        "diagnosis",
        "treatment",
        "action",
        "score_breakdown",
        "weighted_score",
        "confidence_score",
    )
    assert set(result) == set(RESULT_FIELDS)
    for f in forbidden:
        assert f not in result
    sc = result["selected_candidate"]
    assert sc is None or set(sc) == set(SELECTED_FIELDS)
    for f in forbidden:
        assert sc is None or f not in sc


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "decision-execution-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_session(user_input: str) -> str:
    sid = _create_session(user_input)
    obs = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert obs.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    assert len(g.json()) > 0
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def test_api_endpoint() -> None:
    sid = _seed_session("Task 039 API test")
    r = client.get(f"/sessions/{sid}/decision-execution")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert (
        payload["decision_execution_source"]
        == DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
    )


def test_api_empty_session() -> None:
    sid = _create_session("Task 039 empty session")
    r = client.get(f"/sessions/{sid}/decision-execution")
    assert r.status_code == 200
    payload = r.json()
    assert payload["outcome"] == OUTCOME_INPUT_UNAVAILABLE
    assert payload["available"] is False


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/decision-execution")
    assert r.status_code == 404


def test_api_is_deterministic() -> None:
    sid = _seed_session("Task 039 deterministic")
    first = client.get(f"/sessions/{sid}/decision-execution").json()
    second = client.get(f"/sessions/{sid}/decision-execution").json()
    assert first == second


def test_api_is_read_only() -> None:
    sid = _seed_session("Task 039 read-only")
    before = client.get(f"/sessions/{sid}/decision-input-bundle").json()
    r = client.get(f"/sessions/{sid}/decision-execution")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/decision-input-bundle").json()
    assert after == before


def test_api_matches_service_output() -> None:
    sid = _seed_session("Task 039 agreement")
    api_result = client.get(f"/sessions/{sid}/decision-execution").json()

    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == _json_safe(service_result)


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    sc = result["selected_candidate"]
    return {
        **result,
        "selected_candidate": (
            {**sc, "hypothesis_id": str(sc["hypothesis_id"])}
            if sc is not None
            else None
        ),
        "eligible_candidate_ids": [
            str(hid) for hid in result["eligible_candidate_ids"]
        ],
    }


# ---------------------------------------------------------------------------
# Reviewer round 2: Task 037 input validation boundary
# ---------------------------------------------------------------------------


def _one_valid_bundle() -> dict[str, Any]:
    h1 = uuid4()
    a = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    return _bundle([a])


def test_rejects_candidate_assessment_id_mismatch() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["assessments"][0]["hypothesis_id"] = uuid4()
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_name_mismatch() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["assessments"][0]["hypothesis_name"] = "WRONG"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_rank_mismatch() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["assessments"][0]["rank"] = 99
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_score_mismatch() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["assessments"][0]["score"] = 999.0
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_is_tied_mismatch() -> None:
    b = _one_valid_bundle()
    b["candidate_set"]["candidates"][0]["is_tied"] = True
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_tie_group_size_mismatch() -> None:
    b = _one_valid_bundle()
    b["candidate_set"]["candidates"][0]["tie_group_size"] = 5
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_gap_higher_mismatch() -> None:
    b = _one_valid_bundle()
    b["candidate_set"]["candidates"][0]["score_gap_to_next_higher"] = 1.0
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_candidate_assessment_gap_lower_mismatch() -> None:
    b = _one_valid_bundle()
    b["candidate_set"]["candidates"][0]["score_gap_to_next_lower"] = 1.0
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_wrong_nested_candidate_set_source() -> None:
    b = _one_valid_bundle()
    b["candidate_set"]["candidate_set_source"] = "WRONG"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_wrong_nested_assessment_set_source() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["assessment_source"] = "WRONG"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_reordered_assessments() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "A", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "B", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    b["assessment_set"]["assessments"] = [a2, a1]
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_nested_assessment_available_with_inconsistent_flags() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["assessment_structure_consistent"] = False
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_rejects_nested_assessment_available_with_incomplete_coverage() -> None:
    b = _one_valid_bundle()
    b["assessment_set"]["evaluation_coverage_complete"] = False
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


def test_cannot_select_from_candidate_assessment_mismatch() -> None:
    """Regression: the exact case from the reviewer -- candidate H1 in
    the candidate set but assessment H2 in the assessment set. Task 039
    must reject the bundle rather than select H2."""
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    # Swap the assessment's identity so it no longer matches its
    # corresponding candidate. Without the Task 037 validation boundary
    # this would silently reach the selection stage.
    b["assessment_set"]["assessments"][0]["hypothesis_id"] = h2
    b["assessment_set"]["assessments"][0]["hypothesis_name"] = "H2"
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"


# ---------------------------------------------------------------------------
# Reviewer round 3: precedence and final Task 037 boundary
# ---------------------------------------------------------------------------


def test_inconsistent_takes_precedence_over_unavailable() -> None:
    """A validly-shaped Task 037 bundle with available=False AND
    input_structure_consistent=False must produce INPUT_INCONSISTENT,
    not INPUT_UNAVAILABLE. Task 039 must preserve the semantic
    distinction."""
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a], available=False, consistent=False)
    result = _service().build(b, _default_policy())
    assert result["outcome"] == OUTCOME_INPUT_INCONSISTENT
    assert result["available"] is False


def test_rejects_bundle_with_top_level_contradiction() -> None:
    """Task 037's final _validate_result is now delegated to, so a
    bundle whose top-level `available` contradicts its nested
    availability flags is rejected as INVALID_BUNDLE_STRUCTURE."""
    a = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a])
    # Force an internally contradictory top-level flag while leaving
    # the nested contracts valid: available=True but structure=False.
    b["input_structure_consistent"] = False
    with pytest.raises(DecisionExecutionContractError) as ei:
        _service().build(b, _default_policy())
    assert ei.value.invariant == "INVALID_BUNDLE_STRUCTURE"

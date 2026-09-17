"""Tests for Task 040 decision execution consistency contract.

Task 040 is an independent audit of a Task 039 execution result: it
re-derives the expected eligible set and expected outcome from the
Task 037 bundle and Task 038 policy, then checks the Task 039 result
against them field by field. It never selects, reranks, rescores, or
mutates any input.
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
)
from rop.services.decision_execution_consistency import (
    DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040,
    DecisionExecutionConsistencyContractError,
    DecisionExecutionConsistencyService,
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
    "execution_consistent",
    "outcome_consistent",
    "eligibility_consistent",
    "selection_consistent",
    "metadata_consistent",
    "source_consistent",
    "consistency_issues",
    "execution_source",
)


def _service() -> DecisionExecutionConsistencyService:
    return DecisionExecutionConsistencyService()


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
    req_unsat = sum(
        1 for c in criteria if c["required"] and not c["satisfied"]
    )
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


def _exec_selected(
    winner: dict[str, Any],
    eligible: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "available": True,
        "outcome": "SELECTED",
        "selected_candidate": {
            "hypothesis_id": winner["hypothesis_id"],
            "hypothesis_name": winner["hypothesis_name"],
            "rank": winner["rank"],
            "score": winner["score"],
        },
        "eligible_candidate_count": len(eligible),
        "eligible_candidate_ids": [a["hypothesis_id"] for a in eligible],
        "policy_id": "DECISION_POLICY_DEFAULT",
        "policy_version": "1.0.0",
        "decision_execution_source": (
            DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
        ),
    }


def _exec_no_eligible() -> dict[str, Any]:
    return {
        "available": True,
        "outcome": "NO_ELIGIBLE_CANDIDATE",
        "selected_candidate": None,
        "eligible_candidate_count": 0,
        "eligible_candidate_ids": [],
        "policy_id": "DECISION_POLICY_DEFAULT",
        "policy_version": "1.0.0",
        "decision_execution_source": (
            DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
        ),
    }


def _exec_unresolved(eligible: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "available": True,
        "outcome": "UNRESOLVED",
        "selected_candidate": None,
        "eligible_candidate_count": len(eligible),
        "eligible_candidate_ids": [a["hypothesis_id"] for a in eligible],
        "policy_id": "DECISION_POLICY_DEFAULT",
        "policy_version": "1.0.0",
        "decision_execution_source": (
            DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
        ),
    }


def _exec_unavailable() -> dict[str, Any]:
    return {
        "available": False,
        "outcome": "INPUT_UNAVAILABLE",
        "selected_candidate": None,
        "eligible_candidate_count": 0,
        "eligible_candidate_ids": [],
        "policy_id": "DECISION_POLICY_DEFAULT",
        "policy_version": "1.0.0",
        "decision_execution_source": (
            DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
        ),
    }


def _exec_inconsistent() -> dict[str, Any]:
    return {
        "available": False,
        "outcome": "INPUT_INCONSISTENT",
        "selected_candidate": None,
        "eligible_candidate_count": 0,
        "eligible_candidate_ids": [],
        "policy_id": "DECISION_POLICY_DEFAULT",
        "policy_version": "1.0.0",
        "decision_execution_source": (
            DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
        ),
    }


# ---------------------------------------------------------------------------
# Valid SELECTED
# ---------------------------------------------------------------------------


def test_consistent_selected_audit() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    r = _service().build(b, _default_policy(), _exec_selected(a1, [a1]))

    assert set(r) == set(RESULT_FIELDS)
    assert r["available"] is True
    assert r["execution_consistent"] is True
    assert r["outcome_consistent"] is True
    assert r["eligibility_consistent"] is True
    assert r["selection_consistent"] is True
    assert r["metadata_consistent"] is True
    assert r["source_consistent"] is True
    assert r["consistency_issues"] == []


def test_selected_metadata_preserved_audit() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "Alpha", 3, 7.5, _all_required_satisfied())
    b = _bundle([a1])
    r = _service().build(b, _default_policy(), _exec_selected(a1, [a1]))
    assert r["execution_consistent"] is True


def test_unique_highest_among_many_audit() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    r = _service().build(b, _default_policy(), _exec_selected(a1, [a1, a2]))
    assert r["execution_consistent"] is True


# ---------------------------------------------------------------------------
# Valid NO_ELIGIBLE_CANDIDATE
# ---------------------------------------------------------------------------


def test_consistent_no_eligible_audit() -> None:
    a = _assessment(uuid4(), "H1", 1, 10.0, [("c", True, False)])
    b = _bundle([a])
    r = _service().build(b, _default_policy(), _exec_no_eligible())
    assert r["execution_consistent"] is True
    assert r["consistency_issues"] == []


# ---------------------------------------------------------------------------
# Valid UNRESOLVED
# ---------------------------------------------------------------------------


def test_consistent_unresolved_audit() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    r = _service().build(b, _default_policy(), _exec_unresolved([a1, a2]))
    assert r["execution_consistent"] is True
    assert r["outcome_consistent"] is True
    assert r["selection_consistent"] is True


# ---------------------------------------------------------------------------
# Valid INPUT_UNAVAILABLE / INPUT_INCONSISTENT
# ---------------------------------------------------------------------------


def test_consistent_input_unavailable_audit() -> None:
    b = _bundle([], available=False, consistent=True)
    r = _service().build(b, _default_policy(), _exec_unavailable())
    assert r["available"] is True
    assert r["execution_consistent"] is True
    assert r["consistency_issues"] == []


def test_consistent_input_inconsistent_audit() -> None:
    b = _bundle([], available=False, consistent=False)
    r = _service().build(b, _default_policy(), _exec_inconsistent())
    assert r["available"] is True
    assert r["execution_consistent"] is True
    assert r["outcome_consistent"] is True


# ---------------------------------------------------------------------------
# Eligibility mismatch
# ---------------------------------------------------------------------------


def test_eligibility_ids_mismatch_flagged() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    e = _exec_selected(a1, [a1, a2])
    e["eligible_candidate_ids"] = [a1["hypothesis_id"]]
    e["eligible_candidate_count"] = 1
    r = _service().build(b, _default_policy(), e)
    assert r["eligibility_consistent"] is False
    assert "ELIGIBLE_IDS_MISMATCH" in r["consistency_issues"]
    assert r["execution_consistent"] is False


def test_eligibility_count_mismatch_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["eligible_candidate_count"] = 5
    r = _service().build(b, _default_policy(), e)
    assert "ELIGIBLE_COUNT_MISMATCH" in r["consistency_issues"]


def test_eligibility_ids_reordered_flagged() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    e = _exec_selected(a1, [a1, a2])
    e["eligible_candidate_ids"] = [h2, h1]
    r = _service().build(b, _default_policy(), e)
    assert "ELIGIBLE_IDS_MISMATCH" in r["consistency_issues"]


def test_duplicate_eligible_id_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["eligible_candidate_ids"] = [h1, h1]
    e["eligible_candidate_count"] = 2
    r = _service().build(b, _default_policy(), e)
    assert "DUPLICATE_ELIGIBLE_ID" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# Outcome mismatch
# ---------------------------------------------------------------------------


def test_selected_vs_expected_unresolved_flagged() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    # Executor claims SELECTED despite a tie.
    e = _exec_selected(a1, [a1, a2])
    r = _service().build(b, _default_policy(), e)
    assert r["outcome_consistent"] is False
    assert "OUTCOME_MISMATCH" in r["consistency_issues"]


def test_selected_vs_expected_no_eligible_flagged() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, [("c", True, False)])
    b = _bundle([a1])
    e = _exec_selected(a1, [])
    r = _service().build(b, _default_policy(), e)
    assert r["outcome_consistent"] is False
    assert "OUTCOME_MISMATCH" in r["consistency_issues"]


def test_unavailable_vs_expected_inconsistent_flagged() -> None:
    b = _bundle([], available=False, consistent=False)
    # Executor said unavailable when structure was actually inconsistent.
    r = _service().build(b, _default_policy(), _exec_unavailable())
    assert r["outcome_consistent"] is False
    assert "OUTCOME_MISMATCH" in r["consistency_issues"]


def test_inconsistent_vs_expected_unavailable_flagged() -> None:
    b = _bundle([], available=False, consistent=True)
    # Executor said inconsistent when structure was actually fine.
    r = _service().build(b, _default_policy(), _exec_inconsistent())
    assert r["outcome_consistent"] is False
    assert "OUTCOME_MISMATCH" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# Selection mismatch
# ---------------------------------------------------------------------------


def test_selected_not_eligible_flagged() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    e = _exec_selected(a2, [a1])  # a2 not in eligible set
    r = _service().build(b, _default_policy(), e)
    assert r["selection_consistent"] is False
    assert "SELECTED_NOT_ELIGIBLE" in r["consistency_issues"]


def test_selected_not_highest_flagged() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    # Select lower-ranked a2, and include it in eligible IDs.
    e = _exec_selected(a2, [a1, a2])
    r = _service().build(b, _default_policy(), e)
    assert r["selection_consistent"] is False
    assert "SELECTED_NOT_HIGHEST" in r["consistency_issues"]


def test_selected_metadata_mismatch_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["selected_candidate"]["score"] = 999.0
    r = _service().build(b, _default_policy(), e)
    assert "SELECTED_METADATA_MISMATCH" in r["consistency_issues"]


def test_selected_forbidden_when_unresolved_flagged() -> None:
    a1 = _assessment(uuid4(), "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(uuid4(), "H2", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    e = _exec_unresolved([a1, a2])
    e["selected_candidate"] = {
        "hypothesis_id": a1["hypothesis_id"],
        "hypothesis_name": a1["hypothesis_name"],
        "rank": a1["rank"],
        "score": a1["score"],
    }
    r = _service().build(b, _default_policy(), e)
    assert r["selection_consistent"] is False
    assert "SELECTED_FORBIDDEN" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# Tie mismatch
# ---------------------------------------------------------------------------


def test_unresolved_not_tied_flagged() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    # Executor claims UNRESOLVED but ranks are unique.
    r = _service().build(b, _default_policy(), _exec_unresolved([a1, a2]))
    assert "UNRESOLVED_NOT_TIED" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# No-eligible mismatch
# ---------------------------------------------------------------------------


def test_no_eligible_with_nonzero_ids_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, [("c", True, False)])
    b = _bundle([a1])
    e = _exec_no_eligible()
    e["eligible_candidate_ids"] = [h1]
    e["eligible_candidate_count"] = 1
    r = _service().build(b, _default_policy(), e)
    assert "NO_ELIGIBLE_MISMATCH" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# Metadata mismatch
# ---------------------------------------------------------------------------


def test_policy_id_mismatch_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["policy_id"] = "OTHER_ID"
    r = _service().build(b, _default_policy(), e)
    assert r["metadata_consistent"] is False
    assert "POLICY_ID_MISMATCH" in r["consistency_issues"]


def test_policy_version_mismatch_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["policy_version"] = "9.9.9"
    r = _service().build(b, _default_policy(), e)
    assert r["metadata_consistent"] is False
    assert "POLICY_VERSION_MISMATCH" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# Source mismatch
# ---------------------------------------------------------------------------


def test_invalid_execution_source_flagged() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["decision_execution_source"] = "WRONG"
    r = _service().build(b, _default_policy(), e)
    assert r["source_consistent"] is False
    assert "INVALID_EXECUTION_SOURCE" in r["consistency_issues"]


# ---------------------------------------------------------------------------
# Deterministic issue ordering
# ---------------------------------------------------------------------------


def test_issues_ordered_deterministically() -> None:
    h1, h2 = uuid4(), uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    a2 = _assessment(h2, "H2", 2, 5.0, _all_required_satisfied())
    b = _bundle([a1, a2])
    e = _exec_selected(a2, [a1, a2])
    e["policy_id"] = "OTHER"
    e["policy_version"] = "9.9"
    e["decision_execution_source"] = "WRONG"
    r = _service().build(b, _default_policy(), e)
    # Expected order per _ISSUE_ORDER. SELECTED_METADATA_MISMATCH also
    # fires because the selected candidate (a2) is compared against the
    # expected winner (a1) and their rank/score differ.
    expected_order = [
        "INVALID_EXECUTION_SOURCE",
        "POLICY_ID_MISMATCH",
        "POLICY_VERSION_MISMATCH",
        "SELECTED_NOT_HIGHEST",
        "SELECTED_METADATA_MISMATCH",
    ]
    assert r["consistency_issues"] == expected_order


def test_duplicate_issue_deduplicated() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    e["policy_id"] = "X"
    r = _service().build(b, _default_policy(), e)
    assert r["consistency_issues"].count("POLICY_ID_MISMATCH") == 1


# ---------------------------------------------------------------------------
# Determinism / no mutation
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    p = _default_policy()
    e = _exec_selected(a1, [a1])
    s = _service()
    assert s.build(b, p, e) == s.build(b, p, e)


def test_does_not_mutate_bundle() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    before = copy.deepcopy(b)
    _service().build(b, _default_policy(), _exec_selected(a1, [a1]))
    assert b == before


def test_does_not_mutate_policy() -> None:
    p = _default_policy()
    before = copy.deepcopy(p)
    _service().build(_bundle([]), p, _exec_no_eligible())
    assert p == before


def test_does_not_mutate_execution() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    before = copy.deepcopy(e)
    _service().build(b, _default_policy(), e)
    assert e == before


# ---------------------------------------------------------------------------
# Input contract failures
# ---------------------------------------------------------------------------


def test_rejects_none_bundle() -> None:
    e = _exec_no_eligible()
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(None, _default_policy(), e)
    assert ei.value.invariant == "MISSING_BUNDLE"


def test_rejects_invalid_bundle_source() -> None:
    b = _bundle([])
    b["input_source"] = "WRONG"
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(b, _default_policy(), _exec_no_eligible())
    assert ei.value.invariant == "INVALID_BUNDLE_SOURCE"


def test_rejects_none_policy() -> None:
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), None, _exec_no_eligible())
    assert ei.value.invariant == "MISSING_POLICY"


def test_rejects_invalid_policy_source() -> None:
    # Task 038's validator now catches the wrong source before Task 040's
    # default-value check; Task 040 wraps that as INVALID_POLICY_STRUCTURE.
    p = _default_policy()
    p["policy_source"] = "WRONG"
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    assert ei.value.invariant == "INVALID_POLICY_STRUCTURE"


def test_rejects_none_execution() -> None:
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), _default_policy(), None)
    assert ei.value.invariant == "MISSING_EXECUTION"


def test_rejects_missing_execution_field() -> None:
    e = _exec_no_eligible()
    del e["outcome"]
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), _default_policy(), e)
    assert ei.value.invariant == "MISSING_EXECUTION_FIELD"


def test_rejects_invalid_outcome() -> None:
    e = _exec_no_eligible()
    e["outcome"] = "NONSENSE"
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), _default_policy(), e)
    assert ei.value.invariant == "INVALID_OUTCOME"


def test_rejects_negative_eligible_count() -> None:
    e = _exec_no_eligible()
    e["eligible_candidate_count"] = -1
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), _default_policy(), e)
    assert ei.value.invariant == "EXECUTION_COUNT_NEGATIVE"


def test_rejects_non_list_eligible_ids() -> None:
    e = _exec_no_eligible()
    e["eligible_candidate_ids"] = "nope"
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), _default_policy(), e)
    assert ei.value.invariant == "EXECUTION_IDS_TYPE"


def test_rejects_selected_missing_field() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    b = _bundle([a1])
    e = _exec_selected(a1, [a1])
    del e["selected_candidate"]["rank"]
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(b, _default_policy(), e)
    assert ei.value.invariant == "SELECTED_MISSING_FIELD"


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_forbidden_fields() -> None:
    h1 = uuid4()
    a1 = _assessment(h1, "H1", 1, 10.0, _all_required_satisfied())
    r = _service().build(
        _bundle([a1]), _default_policy(), _exec_selected(a1, [a1])
    )
    forbidden = (
        "winner",
        "recommendation",
        "diagnosis",
        "treatment",
        "action",
        "probability",
        "confidence",
        "utility",
        "expected_outcome",
        "selected_candidate",
    )
    assert set(r) == set(RESULT_FIELDS)
    for f in forbidden:
        assert f not in r


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
            "metadata": {"source": "decision-execution-consistency-test"},
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
    sid = _seed_session("Task 040 API test")
    r = client.get(f"/sessions/{sid}/decision-execution-consistency")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert (
        payload["execution_source"]
        == DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040
    )
    assert payload["available"] is True
    assert payload["execution_consistent"] is True
    assert payload["consistency_issues"] == []


def test_api_empty_session() -> None:
    sid = _create_session("Task 040 empty session")
    r = client.get(f"/sessions/{sid}/decision-execution-consistency")
    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is True
    assert payload["execution_consistent"] is True


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/decision-execution-consistency")
    assert r.status_code == 404


def test_api_is_deterministic() -> None:
    sid = _seed_session("Task 040 deterministic")
    first = client.get(
        f"/sessions/{sid}/decision-execution-consistency"
    ).json()
    second = client.get(
        f"/sessions/{sid}/decision-execution-consistency"
    ).json()
    assert first == second


def test_api_is_read_only() -> None:
    sid = _seed_session("Task 040 read-only")
    before = client.get(f"/sessions/{sid}/decision-execution").json()
    r = client.get(f"/sessions/{sid}/decision-execution-consistency")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/decision-execution").json()
    assert after == before


def test_api_matches_service_output() -> None:
    sid = _seed_session("Task 040 agreement")
    api_result = client.get(
        f"/sessions/{sid}/decision-execution-consistency"
    ).json()

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

    assert api_result == service_result


# ---------------------------------------------------------------------------
# Reviewer round 2: full Task 038 policy validation
# ---------------------------------------------------------------------------


def test_rejects_boolean_required_candidate_count() -> None:
    """True == 1 in Python, so a partial validator would accept this.
    Task 038's validator explicitly rejects booleans for this field."""
    p = _default_policy()
    p["required_candidate_count"] = True
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    assert ei.value.invariant == "INVALID_POLICY_STRUCTURE"


def test_rejects_non_string_policy_name() -> None:
    p = _default_policy()
    p["policy_name"] = 123
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    assert ei.value.invariant == "INVALID_POLICY_STRUCTURE"


def test_rejects_empty_policy_name() -> None:
    p = _default_policy()
    p["policy_name"] = ""
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    assert ei.value.invariant == "INVALID_POLICY_STRUCTURE"


def test_rejects_missing_policy_field_via_task038() -> None:
    p = _default_policy()
    del p["tie_behavior"]
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    assert ei.value.invariant == "INVALID_POLICY_STRUCTURE"


def test_rejects_non_bool_boolean_policy_field() -> None:
    """A non-bool value where Task 038 requires a bool."""
    p = _default_policy()
    p["policy_source"] = 1  # not a string
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    assert ei.value.invariant == "INVALID_POLICY_STRUCTURE"


def test_rejects_inconsistent_cross_field_policy() -> None:
    """Task 038 rejects SINGLE_CANDIDATE with a count other than 1.
    That cross-field invariant is inherited by Task 040's delegation."""
    p = _default_policy()
    p["allowed_selection_mode"] = "SINGLE_CANDIDATE"
    p["required_candidate_count"] = 0
    with pytest.raises(DecisionExecutionConsistencyContractError) as ei:
        _service().build(_bundle([]), p, _exec_no_eligible())
    # The cross-field check fires first inside Task 038, or the default
    # value check fires first inside Task 040 -- either way it is a
    # rejection through the Task 038 boundary.
    assert ei.value.invariant in (
        "INVALID_POLICY_STRUCTURE",
        "UNSUPPORTED_POLICY_VALUES",
    )

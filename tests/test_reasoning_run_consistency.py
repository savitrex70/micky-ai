"""Tests for Task 043 full reasoning run consistency & audit contract.

Task 043 independently audits Task 042 against actual session state and
the nested Task 041 pipeline contract. Read-only.
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
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.entity import EntityService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.reasoning_run import ReasoningRunService
from rop.services.reasoning_run_consistency import (
    REASONING_RUN_CONSISTENCY_SOURCE_TASK_043,
    ReasoningRunConsistencyContractError,
    ReasoningRunConsistencyService,
)
from rop.services.template_match import TemplateMatchService

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
    "run_consistent",
    "session_consistent",
    "observations_consistent",
    "entities_consistent",
    "missing_information_consistent",
    "template_context_consistent",
    "candidate_state_consistent",
    "candidate_count_consistent",
    "candidate_generation_consistent",
    "pipeline_consistent",
    "stage_structure_consistent",
    "source_consistency",
    "metadata_consistency",
    "consistency_issues",
    "run_consistency_source",
)


def _service() -> ReasoningRunConsistencyService:
    return ReasoningRunConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "reasoning-run-consistency-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
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
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _build_audit(session_id: str) -> dict[str, Any]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return _service().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


def _get_run_and_state(
    session_id: str,
) -> tuple[
    dict[str, Any],
    list[Any],
    list[Any],
    list[Any],
    list[Any],
    list[Any],
    dict[str, Any],
    dict[str, Any],
]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        run, bundle, policy = (
            ReasoningRunService().build_for_session_with_inputs(
                db, session_uuid
            )
        )
        obs = ObservationService().list_by_session(
            db, session_uuid, offset=0, limit=1000
        )
        ent = EntityService().list_by_session(
            db, session_uuid, offset=0, limit=1000
        )
        mi = MissingInformationService().list_by_session(db, session_uuid)
        tm = TemplateMatchService().list_by_session(db, session_uuid)
        cands = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        return run, obs, ent, mi, tm, cands, bundle, policy
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Valid state
# ---------------------------------------------------------------------------


def test_valid_full_run_consistent() -> None:
    sid = _seed_full_session("Task 043 valid full run")
    result = _build_audit(sid)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["run_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_full_run_all_flags_true() -> None:
    sid = _seed_full_session("Task 043 all flags true")
    result = _build_audit(sid)
    for flag in (
        "session_consistent",
        "observations_consistent",
        "entities_consistent",
        "missing_information_consistent",
        "template_context_consistent",
        "candidate_state_consistent",
        "candidate_count_consistent",
        "candidate_generation_consistent",
        "pipeline_consistent",
        "stage_structure_consistent",
        "source_consistency",
        "metadata_consistency",
    ):
        assert result[flag] is True, flag


def test_valid_run_source_fixed() -> None:
    sid = _seed_full_session("Task 043 source")
    result = _build_audit(sid)
    assert (
        result["run_consistency_source"]
        == REASONING_RUN_CONSISTENCY_SOURCE_TASK_043
    )


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


def test_empty_session_audit_available() -> None:
    sid = _create_session("Task 043 empty")
    result = _build_audit(sid)
    assert result["available"] is True
    assert result["run_consistent"] is True
    assert result["consistency_issues"] == []


def test_empty_session_candidate_count_consistent() -> None:
    sid = _create_session("Task 043 empty count")
    result = _build_audit(sid)
    assert result["candidate_count_consistent"] is True


def test_empty_session_candidate_generation_stage_audited() -> None:
    sid = _create_session("Task 043 empty gen stage")
    result = _build_audit(sid)
    assert result["candidate_generation_consistent"] is True


def test_empty_session_input_unavailable_preserved() -> None:
    sid = _create_session("Task 043 empty input unavailable")
    r = client.get(f"/sessions/{sid}/reasoning-run").json()
    assert (
        r["reasoning_pipeline"]["final_execution"]["outcome"]
        == "INPUT_UNAVAILABLE"
    )
    # And the audit still succeeds.
    result = _build_audit(sid)
    assert result["available"] is True


# ---------------------------------------------------------------------------
# Candidate state
# ---------------------------------------------------------------------------


def test_candidate_count_mismatch_detected() -> None:
    sid = _seed_full_session("Task 043 candidate count mismatch")
    run, obs, ent, mi, tm, cands, bundle, policy = _get_run_and_state(sid)
    tampered = copy.deepcopy(run)
    tampered["candidate_count"] = 99
    tampered["candidate_generation_available"] = True
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "CANDIDATE_COUNT_MISMATCH" in result["consistency_issues"]
    assert result["candidate_count_consistent"] is False


def test_candidate_generation_availability_mismatch_detected() -> None:
    sid = _seed_full_session("Task 043 gen availability mismatch")
    run, obs, ent, mi, tm, cands, bundle, policy = _get_run_and_state(sid)
    tampered = copy.deepcopy(run)
    # Force zero candidates in state.
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=[],
        bundle=bundle,
        policy=policy,
    )
    assert (
        "CANDIDATE_GENERATION_AVAILABILITY_MISMATCH"
        in result["consistency_issues"]
    )


def test_candidate_generation_stage_mismatch_detected() -> None:
    sid = _seed_full_session("Task 043 gen stage mismatch")
    run, obs, ent, mi, tm, cands, bundle, policy = _get_run_and_state(sid)
    # Run says CANDIDATE_GENERATION available/complete; state says empty.
    result = _service().build(
        run=run,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=[],
        bundle=bundle,
        policy=policy,
    )
    assert "CANDIDATE_GENERATION_STAGE_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Template state
# ---------------------------------------------------------------------------


def test_template_present_stage_consistent() -> None:
    sid = _seed_full_session("Task 043 template present")
    client.post(f"/sessions/{sid}/match-template")
    result = _build_audit(sid)
    assert result["template_context_consistent"] is True


def test_template_absent_stage_consistent() -> None:
    sid = _seed_full_session("Task 043 template absent")
    result = _build_audit(sid)
    assert result["template_context_consistent"] is True


def test_template_stage_mismatch_detected() -> None:
    sid = _seed_full_session("Task 043 template mismatch")
    run, obs, ent, mi, tm, cands, bundle, policy = _get_run_and_state(sid)
    # Fabricate a non-empty template list while run reports none.
    fake_templates = [object()]
    result = _service().build(
        run=run,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=fake_templates,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "TEMPLATE_STAGE_MISMATCH" in result["consistency_issues"]
    assert result["template_context_consistent"] is False


# ---------------------------------------------------------------------------
# Downstream outcomes preserved
# ---------------------------------------------------------------------------


def test_downstream_selected_is_auditable() -> None:
    sid = _seed_full_session("Task 043 downstream selected")
    r = client.get(f"/sessions/{sid}/reasoning-run").json()
    outcome = r["reasoning_pipeline"]["final_execution"]["outcome"]
    assert outcome in (
        "SELECTED",
        "NO_ELIGIBLE_CANDIDATE",
        "UNRESOLVED",
    )
    result = _build_audit(sid)
    assert result["available"] is True
    assert result["run_consistent"] is True


def test_downstream_no_eligible_is_auditable() -> None:
    sid = _seed_full_session("Task 043 downstream no eligible")
    result = _build_audit(sid)
    assert result["available"] is True


def test_downstream_input_unavailable_is_auditable() -> None:
    sid = _create_session("Task 043 downstream input unavailable")
    result = _build_audit(sid)
    assert result["available"] is True
    assert result["run_consistent"] is True


# ---------------------------------------------------------------------------
# Stage structure tampering
# ---------------------------------------------------------------------------


def _valid_run_and_state() -> tuple[
    dict[str, Any],
    list[Any],
    list[Any],
    list[Any],
    list[Any],
    list[Any],
    dict[str, Any],
    dict[str, Any],
]:
    sid = _seed_full_session("Task 043 raw inputs")
    return _get_run_and_state(sid)


def test_tamper_run_source_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["run_source"] = "WRONG"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "RUN_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_tamper_stage_order_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["stages"][1]["stage_order"] = 99
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_ORDER_MISMATCH" in result["consistency_issues"]
    assert result["stage_structure_consistent"] is False


def test_tamper_duplicate_stage_id_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["stages"][1]["stage_id"] = tampered["stages"][0]["stage_id"]
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "DUPLICATE_STAGE_ID" in result["consistency_issues"]


def test_tamper_stage_source_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["stages"][0]["stage_source"] = "WRONG"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_SOURCE_MISMATCH" in result["consistency_issues"]


def test_tamper_stage_count_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["stage_count"] = 99
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_COUNT_MISMATCH" in result["consistency_issues"]


def test_tamper_missing_stage_field_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    del tampered["stages"][0]["available"]
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_FIELD_MISSING" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Pipeline tampering
# ---------------------------------------------------------------------------


def test_tamper_pipeline_source_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["reasoning_pipeline"]["pipeline_source"] = "WRONG"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "PIPELINE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["pipeline_consistent"] is False


def test_tamper_pipeline_structure_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["reasoning_pipeline"]["pipeline_consistent"] = "yes"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "PIPELINE_STRUCTURE_INCONSISTENT" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Run-level flag tampering
# ---------------------------------------------------------------------------


def test_tamper_run_complete_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["run_complete"] = not tampered["run_complete"]
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "RUN_COMPLETE_MISMATCH" in result["consistency_issues"]


def test_tamper_run_consistent_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["run_consistent"] = not tampered["run_consistent"]
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "RUN_CONSISTENCY_MISMATCH" in result["consistency_issues"]


def test_tamper_completed_stage_count_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["completed_stage_count"] = 0
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "COMPLETED_STAGE_COUNT_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Nested Task 042 malformed
# ---------------------------------------------------------------------------


def test_rejects_malformed_task042_run() -> None:
    with pytest.raises(ReasoningRunConsistencyContractError) as ei:
        _service().build(
            run={"available": True},
            observations=[],
            entities=[],
            missing_information=[],
            template_matches=[],
            candidates=[],
            bundle={},
            policy={},
        )
    assert ei.value.invariant == "INVALID_REASONING_RUN"


def test_rejects_none_run() -> None:
    with pytest.raises(ReasoningRunConsistencyContractError) as ei:
        _service().build(
            run=None,
            observations=[],
            entities=[],
            missing_information=[],
            template_matches=[],
            candidates=[],
            bundle={},
            policy={},
        )
    assert ei.value.invariant == "MISSING_RUN"


def test_rejects_missing_session() -> None:
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        with pytest.raises(ReasoningRunConsistencyContractError) as ei:
            _service().build_for_session(db, uuid4())
        assert ei.value.invariant == "MISSING_SESSION"
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Determinism / no mutation
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    sid = _seed_full_session("Task 043 deterministic")
    assert _build_audit(sid) == _build_audit(sid)


def test_does_not_mutate_inputs() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    run_before = copy.deepcopy(run)
    obs_before = list(obs)
    ent_before = list(ent)
    mi_before = list(mi)
    tm_before = list(tm)
    cands_before = list(cands)

    _service().build(
        run=run,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )

    assert run == run_before
    assert obs == obs_before
    assert ent == ent_before
    assert mi == mi_before
    assert tm == tm_before
    assert cands == cands_before


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_forbidden_fields() -> None:
    sid = _seed_full_session("Task 043 no forbidden")
    result = _build_audit(sid)
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
    )
    assert set(result) == set(RESULT_FIELDS)
    for f in forbidden:
        assert f not in result


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def test_get_does_not_regenerate_candidates() -> None:
    sid = _seed_full_session("Task 043 read-only")
    first = client.get(f"/sessions/{sid}/reasoning-run-consistency").json()
    for _ in range(3):
        r = client.get(f"/sessions/{sid}/reasoning-run-consistency")
        assert r.status_code == 200
        assert r.json() == first


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_valid() -> None:
    sid = _seed_full_session("Task 043 API valid")
    r = client.get(f"/sessions/{sid}/reasoning-run-consistency")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert payload["available"] is True
    assert (
        payload["run_consistency_source"]
        == REASONING_RUN_CONSISTENCY_SOURCE_TASK_043
    )


def test_api_empty_session() -> None:
    sid = _create_session("Task 043 API empty")
    r = client.get(f"/sessions/{sid}/reasoning-run-consistency")
    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is True
    assert payload["run_consistent"] is True


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/reasoning-run-consistency")
    assert r.status_code == 404


def test_api_is_deterministic() -> None:
    sid = _seed_full_session("Task 043 api deterministic")
    first = client.get(f"/sessions/{sid}/reasoning-run-consistency").json()
    second = client.get(f"/sessions/{sid}/reasoning-run-consistency").json()
    assert first == second


def test_api_is_read_only() -> None:
    sid = _seed_full_session("Task 043 api read-only")
    before = client.get(f"/sessions/{sid}/reasoning-run").json()
    r = client.get(f"/sessions/{sid}/reasoning-run-consistency")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/reasoning-run").json()
    assert after == before


def test_api_matches_service_output() -> None:
    sid = _seed_full_session("Task 043 api agreement")
    api_result = client.get(
        f"/sessions/{sid}/reasoning-run-consistency"
    ).json()
    service_result = _build_audit(sid)
    assert api_result == service_result


# ---------------------------------------------------------------------------
# Stage structure tampering
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Deep pipeline tamper (nested Task 041 contract)
# ---------------------------------------------------------------------------


def test_deep_pipeline_tamper_detected() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["reasoning_pipeline"]["final_execution"]["outcome"] = "GARBAGE"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "PIPELINE_STRUCTURE_INCONSISTENT" in result["consistency_issues"]
    assert result["pipeline_consistent"] is False
    assert result["run_consistent"] is False


def test_deep_pipeline_tamper_selected_missing() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["reasoning_pipeline"]["final_execution"]["outcome"] = "SELECTED"
    tampered["reasoning_pipeline"]["final_execution"]["selected_candidate"] = (
        None
    )
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "PIPELINE_STRUCTURE_INCONSISTENT" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Fixed-stage semantic triple tamper
# ---------------------------------------------------------------------------


def _stage_index(run: dict[str, Any], stage_id: str) -> int:
    for i, stage in enumerate(run["stages"]):
        if stage["stage_id"] == stage_id:
            return i
    raise AssertionError("stage not found: " + stage_id)


def test_tamper_observations_consistent() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "OBSERVATIONS")
    tampered["stages"][idx]["consistent"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_SEMANTIC_MISMATCH" in result["consistency_issues"]
    assert result["stage_structure_consistent"] is False
    assert result["run_consistent"] is False


def test_tamper_entities_complete() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "ENTITIES")
    tampered["stages"][idx]["complete"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_SEMANTIC_MISMATCH" in result["consistency_issues"]
    assert result["stage_structure_consistent"] is False


def test_tamper_missing_information_available() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "MISSING_INFORMATION")
    tampered["stages"][idx]["available"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_SEMANTIC_MISMATCH" in result["consistency_issues"]


def test_tamper_template_context_consistent() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "TEMPLATE_CONTEXT")
    tampered["stages"][idx]["consistent"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "TEMPLATE_STAGE_MISMATCH" in result["consistency_issues"]
    assert result["template_context_consistent"] is False


def test_tamper_template_context_complete() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "TEMPLATE_CONTEXT")
    tampered["stages"][idx]["complete"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "TEMPLATE_STAGE_MISMATCH" in result["consistency_issues"]
    assert result["template_context_consistent"] is False


def test_tamper_session_input_available() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "SESSION_INPUT")
    tampered["stages"][idx]["available"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_SEMANTIC_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# source_consistency covers all source groups
# ---------------------------------------------------------------------------


def test_tamper_stage_source_flips_source_consistency() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["stages"][0]["stage_source"] = "WRONG"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "STAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_tamper_pipeline_source_flips_source_consistency() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    tampered["reasoning_pipeline"]["pipeline_source"] = "WRONG"
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert "PIPELINE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# Per-stage flags reflect stage semantic triple
# ---------------------------------------------------------------------------


def test_observations_flag_reflects_semantic_mismatch() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "OBSERVATIONS")
    tampered["stages"][idx]["consistent"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert result["observations_consistent"] is False
    assert result["run_consistent"] is False


def test_entities_flag_reflects_semantic_mismatch() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "ENTITIES")
    tampered["stages"][idx]["complete"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert result["entities_consistent"] is False
    assert result["run_consistent"] is False


def test_missing_information_flag_reflects_semantic_mismatch() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "MISSING_INFORMATION")
    tampered["stages"][idx]["available"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert result["missing_information_consistent"] is False
    assert result["run_consistent"] is False


def test_session_flag_reflects_semantic_mismatch() -> None:
    run, obs, ent, mi, tm, cands, bundle, policy = _valid_run_and_state()
    tampered = copy.deepcopy(run)
    idx = _stage_index(tampered, "SESSION_INPUT")
    tampered["stages"][idx]["available"] = False
    result = _service().build(
        run=tampered,
        observations=obs,
        entities=ent,
        missing_information=mi,
        template_matches=tm,
        candidates=cands,
        bundle=bundle,
        policy=policy,
    )
    assert result["session_consistent"] is False
    assert result["run_consistent"] is False

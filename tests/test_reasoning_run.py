"""Tests for Task 042 full ROP reasoning-run composition contract.

Task 042 bridges session state into Task 041's reasoning pipeline. It
is read-only: candidate generation is never re-invoked from this
contract, so a GET never mutates session state.
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
from rop.services.reasoning_run import (
    REASONING_RUN_SOURCE_TASK_042,
    ReasoningRunContractError,
    ReasoningRunService,
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
    "run_consistent",
    "run_complete",
    "stage_count",
    "completed_stage_count",
    "stages",
    "candidate_count",
    "candidate_generation_available",
    "reasoning_pipeline",
    "run_source",
)

STAGE_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "available",
    "consistent",
    "complete",
)

EXPECTED_STAGE_IDS = [
    "SESSION_INPUT",
    "OBSERVATIONS",
    "ENTITIES",
    "MISSING_INFORMATION",
    "TEMPLATE_CONTEXT",
    "CANDIDATE_GENERATION",
    "REASONING_PIPELINE",
]


def _service() -> ReasoningRunService:
    return ReasoningRunService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "reasoning-run-test"},
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


def _build_for(session_id: str) -> dict[str, Any]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return _service().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Valid structure
# ---------------------------------------------------------------------------


def test_valid_run_shape() -> None:
    sid = _seed_full_session("Task 042 shape")
    result = _build_for(sid)
    assert set(result) == set(RESULT_FIELDS)


def test_run_source_fixed() -> None:
    sid = _seed_full_session("Task 042 source")
    result = _build_for(sid)
    assert result["run_source"] == REASONING_RUN_SOURCE_TASK_042


def test_stage_ids_and_order() -> None:
    sid = _seed_full_session("Task 042 stages")
    result = _build_for(sid)
    assert result["stage_count"] == 7
    ids = [s["stage_id"] for s in result["stages"]]
    assert ids == EXPECTED_STAGE_IDS
    for i, s in enumerate(result["stages"]):
        assert s["stage_order"] == i + 1
        assert set(s) == set(STAGE_FIELDS)


def test_stage_sources_preserved() -> None:
    sid = _seed_full_session("Task 042 sources")
    result = _build_for(sid)
    by_id = {s["stage_id"]: s["stage_source"] for s in result["stages"]}
    assert by_id["REASONING_PIPELINE"] == "REASONING_PIPELINE_TASK_041"
    # State stages carry Task 042-owned identifiers.
    for sid_key in (
        "SESSION_INPUT",
        "OBSERVATIONS",
        "ENTITIES",
        "MISSING_INFORMATION",
        "TEMPLATE_CONTEXT",
        "CANDIDATE_GENERATION",
    ):
        assert by_id[sid_key].endswith("_TASK_042")


def test_completed_stage_count_matches() -> None:
    sid = _seed_full_session("Task 042 completed")
    result = _build_for(sid)
    actual = sum(1 for s in result["stages"] if s["complete"])
    assert result["completed_stage_count"] == actual


def test_run_flags_derived_from_stages() -> None:
    sid = _seed_full_session("Task 042 flags")
    result = _build_for(sid)
    assert result["run_complete"] == all(
        s["complete"] for s in result["stages"]
    )
    assert result["run_consistent"] == all(
        s["consistent"] for s in result["stages"]
    )


def test_candidate_count_matches_collection() -> None:
    sid = _seed_full_session("Task 042 candidate count")
    result = _build_for(sid)
    assert result["candidate_count"] >= 1
    assert result["candidate_generation_available"] is True


def test_reasoning_pipeline_present() -> None:
    sid = _seed_full_session("Task 042 pipeline present")
    result = _build_for(sid)
    rp = result["reasoning_pipeline"]
    assert set(rp) == {
        "available",
        "pipeline_consistent",
        "pipeline_complete",
        "stage_count",
        "completed_stage_count",
        "stages",
        "final_execution",
        "final_execution_consistency",
        "pipeline_source",
    }
    assert rp["pipeline_source"] == "REASONING_PIPELINE_TASK_041"


# ---------------------------------------------------------------------------
# State handling
# ---------------------------------------------------------------------------


def test_empty_session_runs() -> None:
    sid = _create_session("Task 042 empty session")
    result = _build_for(sid)
    assert result["available"] is True
    assert result["candidate_count"] == 0
    assert result["candidate_generation_available"] is False
    assert (
        result["reasoning_pipeline"]["final_execution"]["outcome"]
        == "INPUT_UNAVAILABLE"
    )


def test_session_with_only_observations() -> None:
    sid = _create_session("Task 042 obs only")
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "chest pain",
            "type": "symptom",
            "confidence": 0.8,
            "source": "unit_test",
        },
    )
    result = _build_for(sid)
    assert result["available"] is True


def test_session_with_template_context() -> None:
    sid = _seed_full_session("Task 042 template context")
    client.post(f"/sessions/{sid}/match-template")
    result = _build_for(sid)
    by_id = {s["stage_id"]: s for s in result["stages"]}
    assert by_id["TEMPLATE_CONTEXT"]["available"] is True


# ---------------------------------------------------------------------------
# Downstream behavior
# ---------------------------------------------------------------------------


def test_reasoning_pipeline_output_preserved() -> None:
    sid = _seed_full_session("Task 042 preserve")
    run = _build_for(sid)
    # Re-query via API to compare. The service returns UUID objects in
    # the nested final_execution; the API returns JSON string UUIDs.
    # Normalize both sides to the JSON shape before comparing.
    api = client.get(f"/sessions/{sid}/reasoning-run").json()
    assert api["reasoning_pipeline"] == _json_safe(run)["reasoning_pipeline"]


def test_downstream_input_unavailable_visible() -> None:
    sid = _create_session("Task 042 input unavailable")
    run = _build_for(sid)
    assert (
        run["reasoning_pipeline"]["final_execution"]["outcome"]
        == "INPUT_UNAVAILABLE"
    )
    assert (
        run["reasoning_pipeline"]["final_execution_consistency"][
            "execution_consistent"
        ]
        is True
    )


# ---------------------------------------------------------------------------
# Contract failures / validator hardening
# ---------------------------------------------------------------------------


def _valid_result() -> dict[str, Any]:
    sid = _seed_full_session("Task 042 raw inputs")
    return _build_for(sid)


def test_rejects_missing_session() -> None:
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        with pytest.raises(ReasoningRunContractError) as ei:
            _service().build_for_session(db, uuid4())
        assert ei.value.invariant == "MISSING_SESSION"
    finally:
        db_gen.close()


def test_tamper_duplicate_stage_id_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["stages"][1]["stage_id"] = tampered["stages"][0]["stage_id"]
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "DUPLICATE_STAGE_ID"


def test_tamper_stage_order_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["stages"][1]["stage_order"] = 99
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "STAGE_ORDER_MISMATCH"


def test_tamper_stage_count_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["stage_count"] = 99
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "STAGE_COUNT_MISMATCH"


def test_tamper_completed_count_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["completed_stage_count"] = 0
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "COMPLETED_COUNT_MISMATCH"


def test_tamper_run_complete_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["run_complete"] = not tampered["run_complete"]
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "RUN_COMPLETE_MISMATCH"


def test_tamper_run_consistent_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["run_consistent"] = not tampered["run_consistent"]
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "RUN_CONSISTENT_MISMATCH"


def test_tamper_negative_candidate_count_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["candidate_count"] = -1
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "CANDIDATE_COUNT_NEGATIVE"


def test_tamper_run_source_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["run_source"] = "WRONG"
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "INVALID_RUN_SOURCE"


def test_tamper_pipeline_not_mapping_rejected() -> None:
    result = _valid_result()
    tampered = copy.deepcopy(result)
    tampered["reasoning_pipeline"] = "not-a-mapping"
    with pytest.raises(ReasoningRunContractError) as ei:
        ReasoningRunService._validate_result(tampered)
    assert ei.value.invariant == "PIPELINE_TYPE"


def test_rejects_malformed_nested_pipeline() -> None:
    """A structurally broken nested Task 041 result must be rejected via
    Task 041's own validator, wrapped as INVALID_REASONING_PIPELINE."""
    sid = _seed_full_session("Task 042 bad nested pipeline")
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.reasoning_pipeline import ReasoningPipelineService

        pipeline_service = ReasoningPipelineService()
        result, bundle, policy = (
            pipeline_service.build_for_session_with_inputs(
                db, session_uuid, []
            )
        )
        # Tamper the pipeline result so its own validator fails.
        result["pipeline_source"] = "WRONG"
        with pytest.raises(ReasoningRunContractError) as ei:
            _service().build(
                session=object(),
                observations=[],
                entities=[],
                missing_information=[],
                template_matches=[],
                candidates=[],
                pipeline_result=result,
                bundle=bundle,
                policy=policy,
            )
        assert ei.value.invariant == "INVALID_REASONING_PIPELINE"
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Determinism / no mutation
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    sid = _seed_full_session("Task 042 deterministic")
    first = _build_for(sid)
    second = _build_for(sid)
    assert first == second


def test_does_not_mutate_inputs() -> None:
    sid = _seed_full_session("Task 042 no mutation")
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.reasoning_pipeline import ReasoningPipelineService

        result, bundle, policy = (
            ReasoningPipelineService().build_for_session_with_inputs(
                db, session_uuid, []
            )
        )
        bundle_before = copy.deepcopy(bundle)
        policy_before = copy.deepcopy(policy)
        result_before = copy.deepcopy(result)

        _service().build(
            session=object(),
            observations=[],
            entities=[],
            missing_information=[],
            template_matches=[],
            candidates=[],
            pipeline_result=result,
            bundle=bundle,
            policy=policy,
        )

        assert bundle == bundle_before
        assert policy == policy_before
        assert result == result_before
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_forbidden_fields() -> None:
    sid = _seed_full_session("Task 042 no forbidden")
    result = _build_for(sid)
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
    for s in result["stages"]:
        assert set(s) == set(STAGE_FIELDS)
        for f in forbidden:
            assert f not in s


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def test_get_does_not_regenerate_candidates() -> None:
    """A GET must not mutate the session's candidate set -- the GET
    path must never invoke CandidateGenerationService.generate()."""
    sid = _seed_full_session("Task 042 read-only")
    # Snapshot the candidate set.
    initial = client.get(f"/sessions/{sid}/reasoning-run").json()
    initial_count = initial["candidate_count"]

    # Call the endpoint repeatedly.
    for _ in range(3):
        r = client.get(f"/sessions/{sid}/reasoning-run")
        assert r.status_code == 200
        assert r.json()["candidate_count"] == initial_count


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_endpoint() -> None:
    sid = _seed_full_session("Task 042 API")
    r = client.get(f"/sessions/{sid}/reasoning-run")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert payload["run_source"] == REASONING_RUN_SOURCE_TASK_042
    assert payload["stage_count"] == 7


def test_api_empty_session() -> None:
    sid = _create_session("Task 042 empty API")
    r = client.get(f"/sessions/{sid}/reasoning-run")
    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is True
    assert payload["candidate_count"] == 0
    assert payload["candidate_generation_available"] is False


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/reasoning-run")
    assert r.status_code == 404


def test_api_is_deterministic() -> None:
    sid = _seed_full_session("Task 042 api deterministic")
    first = client.get(f"/sessions/{sid}/reasoning-run").json()
    second = client.get(f"/sessions/{sid}/reasoning-run").json()
    assert first == second


def test_api_is_read_only() -> None:
    sid = _seed_full_session("Task 042 api read-only")
    before = client.get(f"/sessions/{sid}/reasoning-pipeline").json()
    r = client.get(f"/sessions/{sid}/reasoning-run")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/reasoning-pipeline").json()
    assert after == before


def test_api_matches_service_output() -> None:
    sid = _seed_full_session("Task 042 api agreement")
    api_result = client.get(f"/sessions/{sid}/reasoning-run").json()
    service_result = _build_for(sid)
    assert api_result == _json_safe(service_result)


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    pipeline = result["reasoning_pipeline"]
    fe = pipeline["final_execution"]
    safe_fe = {
        **fe,
        "selected_candidate": (
            {
                **fe["selected_candidate"],
                "hypothesis_id": str(fe["selected_candidate"]["hypothesis_id"]),
            }
            if fe["selected_candidate"] is not None
            else None
        ),
        "eligible_candidate_ids": [
            str(hid) for hid in fe["eligible_candidate_ids"]
        ],
    }
    return {
        **result,
        "reasoning_pipeline": {
            **pipeline,
            "final_execution": safe_fe,
        },
    }

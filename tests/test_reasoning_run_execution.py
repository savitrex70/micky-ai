"""Tests for Task 044 reasoning-run execution orchestrator.

Task 044 runs the deterministic reasoning workflow end-to-end by
delegating to the existing services. It owns ordering only.
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
from rop.services.evidence_evaluation import EvidenceEvaluationService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.observation_extraction import ObservationExtractionService
from rop.services.reasoning_run import ReasoningRunService
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
)
from rop.services.reasoning_run_execution import (
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_SESSION_NOT_FOUND,
    REASONING_RUN_EXECUTION_SOURCE_TASK_044,
    ReasoningRunExecutionContractError,
    ReasoningRunExecutionService,
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
    "outcome",
    "execution_consistent",
    "session_id",
    "completed_stage_count",
    "stage_count",
    "stages",
    "reasoning_run",
    "reasoning_run_consistency",
    "execution_source",
)

STAGE_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "status",
)

EXPECTED_STAGE_IDS = [
    "SESSION_VERIFIED",
    "OBSERVATION_EXTRACTION",
    "MISSING_INFORMATION",
    "TEMPLATE_MATCHING",
    "CANDIDATE_GENERATION",
    "EVIDENCE_EVALUATION",
    "REASONING_RUN",
    "REASONING_RUN_CONSISTENCY",
]


def _service() -> ReasoningRunExecutionService:
    return ReasoningRunExecutionService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "reasoning-run-execution-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_rich_session(user_input: str) -> str:
    return _create_session(user_input)


def _execute(session_id: str) -> dict[str, Any]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return _service().execute_for_session(db, session_uuid)
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Valid full execution
# ---------------------------------------------------------------------------


def test_valid_full_execution_shape() -> None:
    sid = _seed_rich_session("Patient reports chest pain and shortness of breath")
    result = _execute(sid)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["outcome"] == OUTCOME_COMPLETED


def test_execution_source_fixed() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert (
        result["execution_source"]
        == REASONING_RUN_EXECUTION_SOURCE_TASK_044
    )


def test_stage_ids_and_order() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["stage_count"] == 8
    ids = [s["stage_id"] for s in result["stages"]]
    assert ids == EXPECTED_STAGE_IDS
    for i, s in enumerate(result["stages"]):
        assert s["stage_order"] == i + 1
        assert set(s) == set(STAGE_FIELDS)
        assert s["status"] == "COMPLETED"


def test_completed_stage_count_matches() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    actual = sum(
        1 for s in result["stages"] if s["status"] == "COMPLETED"
    )
    assert result["completed_stage_count"] == actual
    assert result["completed_stage_count"] == result["stage_count"]


def test_reasoning_run_present() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert isinstance(result["reasoning_run"], dict)
    assert result["reasoning_run"]["run_source"] == "REASONING_RUN_TASK_042"
    assert result["reasoning_run"]["stage_count"] == 7


def test_reasoning_run_consistency_present() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert isinstance(result["reasoning_run_consistency"], dict)
    assert (
        result["reasoning_run_consistency"]["run_consistency_source"]
        == "REASONING_RUN_CONSISTENCY_TASK_043"
    )
    assert result["reasoning_run_consistency"]["available"] is True


def test_execution_consistent_reflects_audit() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["execution_consistent"] == (
        result["reasoning_run_consistency"]["run_consistent"]
    )


def test_empty_session_execution_succeeds() -> None:
    # user_input has min_length=1 on ReasoningSessionCreate, so use a
    # minimal placeholder rather than "" (which returns 422).
    sid = _seed_rich_session(".")
    result = _execute(sid)
    assert result["available"] is True
    assert result["outcome"] == OUTCOME_COMPLETED
    assert result["stage_count"] == 8
    assert result["completed_stage_count"] == 8


def test_session_id_preserved() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert str(result["session_id"]) == sid


# ---------------------------------------------------------------------------
# Session not found
# ---------------------------------------------------------------------------


def test_session_not_found() -> None:
    session_uuid = uuid4()
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        with pytest.raises(ReasoningRunExecutionContractError) as ei:
            _service().execute_for_session(db, session_uuid)
        assert ei.value.invariant == "SESSION_NOT_FOUND"
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Delegation to established services
# ---------------------------------------------------------------------------


def test_delegates_observation_extraction(monkeypatch) -> None:
    calls = {"n": 0}
    original = ObservationExtractionService.extract_and_store

    def spy(self, db, session_id, text):
        calls["n"] += 1
        return original(self, db, session_id, text)

    monkeypatch.setattr(
        ObservationExtractionService, "extract_and_store", spy
    )
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


def test_delegates_missing_information(monkeypatch) -> None:
    calls = {"n": 0}
    original = MissingInformationService.detect_and_store

    def spy(self, db, session_id, observations, profile_name=None):
        calls["n"] += 1
        return original(self, db, session_id, observations, profile_name)

    monkeypatch.setattr(
        MissingInformationService, "detect_and_store", spy
    )
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


def test_delegates_template_matching(monkeypatch) -> None:
    calls = {"n": 0}
    original = TemplateMatchService.match

    def spy(self, db, session_id, observations, entities):
        calls["n"] += 1
        return original(self, db, session_id, observations, entities)

    monkeypatch.setattr(TemplateMatchService, "match", spy)
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


def test_delegates_candidate_generation(monkeypatch) -> None:
    calls = {"n": 0}
    original = CandidateGenerationService.generate

    def spy(self, **kwargs):
        calls["n"] += 1
        return original(self, **kwargs)

    monkeypatch.setattr(CandidateGenerationService, "generate", spy)
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


def test_delegates_evidence_evaluation(monkeypatch) -> None:
    calls = {"n": 0}
    original = EvidenceEvaluationService.evaluate_session

    def spy(self, **kwargs):
        calls["n"] += 1
        return original(self, **kwargs)

    monkeypatch.setattr(
        EvidenceEvaluationService, "evaluate_session", spy
    )
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


def test_delegates_reasoning_run(monkeypatch) -> None:
    calls = {"n": 0}
    original = ReasoningRunService.build_for_session

    def spy(self, db, session_id):
        calls["n"] += 1
        return original(self, db, session_id)

    monkeypatch.setattr(ReasoningRunService, "build_for_session", spy)
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


def test_delegates_reasoning_run_consistency(monkeypatch) -> None:
    calls = {"n": 0}
    original = ReasoningRunConsistencyService.build_for_session

    def spy(self, db, session_id):
        calls["n"] += 1
        return original(self, db, session_id)

    monkeypatch.setattr(
        ReasoningRunConsistencyService, "build_for_session", spy
    )
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Failure propagation
# ---------------------------------------------------------------------------


def test_observation_extraction_failure_propagates(monkeypatch) -> None:
    def boom(self, db, session_id, text):
        raise RuntimeError("extraction blew up")

    monkeypatch.setattr(
        ObservationExtractionService, "extract_and_store", boom
    )
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == OUTCOME_FAILED
    assert result["available"] is False
    assert result["reasoning_run"] is None
    assert result["reasoning_run_consistency"] is None
    by_id = {st["stage_id"]: st for st in result["stages"]}
    assert by_id["OBSERVATION_EXTRACTION"]["status"] == "FAILED"
    assert by_id["MISSING_INFORMATION"]["status"] == "SKIPPED"
    assert by_id["REASONING_RUN"]["status"] == "SKIPPED"


def test_missing_information_failure_propagates(monkeypatch) -> None:
    def boom(self, db, session_id, observations, profile_name=None):
        raise RuntimeError("mi blew up")

    monkeypatch.setattr(
        MissingInformationService, "detect_and_store", boom
    )
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == OUTCOME_FAILED
    by_id = {st["stage_id"]: st for st in result["stages"]}
    assert by_id["OBSERVATION_EXTRACTION"]["status"] == "COMPLETED"
    assert by_id["MISSING_INFORMATION"]["status"] == "FAILED"
    assert by_id["TEMPLATE_MATCHING"]["status"] == "SKIPPED"


def test_template_matching_failure_propagates(monkeypatch) -> None:
    def boom(self, db, session_id, observations, entities):
        raise RuntimeError("template blew up")

    monkeypatch.setattr(TemplateMatchService, "match", boom)
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == OUTCOME_FAILED
    by_id = {st["stage_id"]: st for st in result["stages"]}
    assert by_id["TEMPLATE_MATCHING"]["status"] == "FAILED"
    assert by_id["CANDIDATE_GENERATION"]["status"] == "SKIPPED"


def test_candidate_generation_failure_propagates(monkeypatch) -> None:
    def boom(self, **kwargs):
        raise RuntimeError("cg blew up")

    monkeypatch.setattr(CandidateGenerationService, "generate", boom)
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == OUTCOME_FAILED
    by_id = {st["stage_id"]: st for st in result["stages"]}
    assert by_id["CANDIDATE_GENERATION"]["status"] == "FAILED"
    assert by_id["EVIDENCE_EVALUATION"]["status"] == "SKIPPED"


def test_evidence_evaluation_failure_propagates(monkeypatch) -> None:
    def boom(self, **kwargs):
        raise RuntimeError("ee blew up")

    monkeypatch.setattr(EvidenceEvaluationService, "evaluate_session", boom)
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == OUTCOME_FAILED
    by_id = {st["stage_id"]: st for st in result["stages"]}
    assert by_id["EVIDENCE_EVALUATION"]["status"] == "FAILED"
    assert by_id["REASONING_RUN"]["status"] == "SKIPPED"


def test_stage_failure_does_not_produce_fabricated_result(monkeypatch) -> None:
    def boom(self, db, session_id, text):
        raise RuntimeError("nope")

    monkeypatch.setattr(
        ObservationExtractionService, "extract_and_store", boom
    )
    sid = _seed_rich_session("Patient reports chest pain")
    result = _execute(sid)
    assert result["outcome"] == OUTCOME_FAILED
    assert result["available"] is False
    assert result["reasoning_run"] is None
    assert result["reasoning_run_consistency"] is None
    assert result["execution_consistent"] is False


# ---------------------------------------------------------------------------
# Idempotency / repeat execution
# ---------------------------------------------------------------------------


def test_repeat_execution_succeeds() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    first = _execute(sid)
    second = _execute(sid)
    assert first["outcome"] == OUTCOME_COMPLETED
    assert second["outcome"] == OUTCOME_COMPLETED


def test_repeat_execution_does_not_grow_observations() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    _execute(sid)
    first_count = len(
        client.get(f"/sessions/{sid}/observations").json()
    )
    _execute(sid)
    second_count = len(
        client.get(f"/sessions/{sid}/observations").json()
    )
    # Task 044 reuses existing observations on repeat execution rather
    # than re-invoking the append-only extractor.
    assert second_count == first_count


def test_repeat_execution_does_not_reduce_candidates() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    first = _execute(sid)
    second = _execute(sid)
    assert first["reasoning_run"]["candidate_count"] == (
        second["reasoning_run"]["candidate_count"]
    )
    assert first["reasoning_run"]["candidate_count"] >= 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_execute_endpoint() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert payload["outcome"] == OUTCOME_COMPLETED
    assert (
        payload["execution_source"]
        == REASONING_RUN_EXECUTION_SOURCE_TASK_044
    )


def test_api_execute_empty_session() -> None:
    sid = _create_session(".")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    assert r.status_code == 200
    assert r.json()["outcome"] == OUTCOME_COMPLETED


def test_api_execute_missing_session_returns_404() -> None:
    r = client.post(f"/sessions/{uuid4()}/reasoning-run/execute")
    assert r.status_code == 404


def test_api_execute_is_deterministic_on_empty_session() -> None:
    sid = _create_session(".")
    first = client.post(f"/sessions/{sid}/reasoning-run/execute").json()
    second = client.post(f"/sessions/{sid}/reasoning-run/execute").json()
    # The reasoning_run and audit bodies should match structurally.
    assert first["reasoning_run"]["stage_count"] == (
        second["reasoning_run"]["stage_count"]
    )
    assert first["stage_count"] == second["stage_count"]


def test_api_execute_matches_service_output() -> None:
    sid = _seed_rich_session("Patient reports chest pain")
    api_result = client.post(
        f"/sessions/{sid}/reasoning-run/execute"
    ).json()
    service_result = _execute(sid)
    # Candidate generation deletes and recreates candidates on each
    # call, so two separate executions produce different candidate
    # UUIDs. Compare structure with UUIDs replaced by a placeholder.
    assert _strip_uuids(api_result) == _strip_uuids(
        _json_safe(service_result)
    )


_UUID_RE = __import__("re").compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    __import__("re").I,
)


def _strip_uuids(obj):
    if isinstance(obj, str):
        return _UUID_RE.sub("UUID", obj)
    if isinstance(obj, list):
        return [_strip_uuids(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_uuids(v) for k, v in obj.items()}
    return obj


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "session_id": str(result["session_id"]),
        "reasoning_run": _json_safe_run(result["reasoning_run"]),
    }


def _json_safe_run(run: dict[str, Any]) -> dict[str, Any]:
    pipeline = run["reasoning_pipeline"]
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
        **run,
        "reasoning_pipeline": {
            **pipeline,
            "final_execution": safe_fe,
        },
    }


# ---------------------------------------------------------------------------
# Read-only GET endpoints stay read-only
# ---------------------------------------------------------------------------


def test_get_reasoning_run_remains_read_only() -> None:
    """The GET endpoint must not mutate candidate/observation state."""
    sid = _create_session("Patient reports chest pain")
    before_obs = client.get(f"/sessions/{sid}/observations").json()
    r1 = client.get(f"/sessions/{sid}/reasoning-run")
    assert r1.status_code == 200
    r2 = client.get(f"/sessions/{sid}/reasoning-run")
    assert r2.status_code == 200
    after_obs = client.get(f"/sessions/{sid}/observations").json()
    assert after_obs == before_obs
    assert r1.json() == r2.json()


def test_get_reasoning_run_consistency_remains_read_only() -> None:
    sid = _create_session("Patient reports chest pain")
    before_obs = client.get(f"/sessions/{sid}/observations").json()
    r1 = client.get(f"/sessions/{sid}/reasoning-run-consistency")
    assert r1.status_code == 200
    r2 = client.get(f"/sessions/{sid}/reasoning-run-consistency")
    assert r2.status_code == 200
    after_obs = client.get(f"/sessions/{sid}/observations").json()
    assert after_obs == before_obs
    assert r1.json() == r2.json()


# ---------------------------------------------------------------------------
# No duplication of business logic
# ---------------------------------------------------------------------------


def test_does_not_import_candidate_generator() -> None:
    """Task 044 must not import CandidateGenerator or duplicate
    candidate-generation logic."""
    import inspect

    from rop.services import reasoning_run_execution as mod

    src = inspect.getsource(mod)
    assert "CandidateGenerator" not in src
    assert "EvidenceEvaluator" not in src


def test_does_not_define_selection_logic() -> None:
    import inspect

    from rop.services import reasoning_run_execution as mod

    src = inspect.getsource(mod)
    # Selection/decision identifiers from Tasks 038-039 must not be
    # reinvented here.
    for forbidden in (
        "SELECTED",
        "NO_ELIGIBLE_CANDIDATE",
        "UNRESOLVED",
        "SINGLE_CANDIDATE",
        "MUST_RETURN_UNRESOLVED",
    ):
        assert forbidden not in src


def test_does_not_reimplement_policy() -> None:
    import inspect

    from rop.services import reasoning_run_execution as mod

    src = inspect.getsource(mod)
    assert "DecisionPolicy" not in src
    assert "required_candidate_count" not in src


# ---------------------------------------------------------------------------
# Validator: stage identity and source
# ---------------------------------------------------------------------------


def _valid_result_for_validation() -> dict[str, Any]:
    sid = _seed_rich_session("Patient reports chest pain")
    return _execute(sid)


def test_validator_rejects_wrong_stage_id() -> None:
    result = _valid_result_for_validation()
    tampered = copy.deepcopy(result)
    tampered["stages"][0]["stage_id"] = "WHATEVER"
    with pytest.raises(ReasoningRunExecutionContractError) as ei:
        ReasoningRunExecutionService._validate_result(tampered)
    assert ei.value.invariant == "STAGE_IDS_MISMATCH"


def test_validator_rejects_wrong_stage_source() -> None:
    result = _valid_result_for_validation()
    tampered = copy.deepcopy(result)
    tampered["stages"][0]["stage_source"] = "WRONG"
    with pytest.raises(ReasoningRunExecutionContractError) as ei:
        ReasoningRunExecutionService._validate_result(tampered)
    assert ei.value.invariant == "STAGE_SOURCE_MISMATCH"

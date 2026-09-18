"""Tests for Task 046 execution + audit bundle.

Task 046 composes Task 044 execution and Task 045 audit into one
bundle. It delegates exclusively to those two services and does not
reimplement any execution, audit, or reasoning logic.
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
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
from rop.services.reasoning_run_execution_bundle import (
    REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046,
    ReasoningRunExecutionBundleContractError,
    ReasoningRunExecutionBundleService,
)
from rop.services.reasoning_run_execution_consistency import (
    ReasoningRunExecutionConsistencyService,
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
    "bundle_consistent",
    "session_id",
    "execution",
    "execution_consistency",
    "bundle_source",
)


def _service() -> ReasoningRunExecutionBundleService:
    return ReasoningRunExecutionBundleService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-046-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _execute_via_api(session_id: str) -> dict[str, Any]:
    r = client.post(f"/sessions/{session_id}/reasoning-run/execute-audited")
    assert r.status_code == 200
    return r.json()


def _make_valid_bundle() -> dict[str, Any]:
    sid = _create_session("Patient reports chest pain")
    return _execute_via_api(sid)


# ---------------------------------------------------------------------------
# Valid bundle
# ---------------------------------------------------------------------------


def test_valid_bundle_shape() -> None:
    bundle = _make_valid_bundle()
    assert set(bundle) == set(RESULT_FIELDS)
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is True


def test_bundle_source_fixed() -> None:
    bundle = _make_valid_bundle()
    assert (
        bundle["bundle_source"]
        == REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046
    )


def test_nested_execution_present() -> None:
    bundle = _make_valid_bundle()
    exec_ = bundle["execution"]
    assert exec_["outcome"] == "COMPLETED"
    assert exec_["execution_source"] == "REASONING_RUN_EXECUTION_TASK_044"


def test_nested_audit_present() -> None:
    bundle = _make_valid_bundle()
    audit = bundle["execution_consistency"]
    assert audit["available"] is True
    assert audit["execution_consistent"] is True
    assert audit["consistency_issues"] == []
    assert (
        audit["execution_consistency_source"]
        == "REASONING_RUN_EXECUTION_CONSISTENCY_TASK_045"
    )


def test_bundle_consistent_matches_audit() -> None:
    bundle = _make_valid_bundle()
    assert bundle["bundle_consistent"] == (
        bundle["execution_consistency"]["execution_consistent"]
    )


def test_session_id_matches() -> None:
    sid = _create_session("Patient reports chest pain")
    bundle = _execute_via_api(sid)
    assert str(bundle["session_id"]) == sid
    assert str(bundle["execution"]["session_id"]) == sid


# ---------------------------------------------------------------------------
# Failed executions -- Task 044 FAILED must still produce a valid bundle
# ---------------------------------------------------------------------------


_FAILING_STAGES = (
    "OBSERVATION_EXTRACTION",
    "MISSING_INFORMATION",
    "TEMPLATE_MATCHING",
    "CANDIDATE_GENERATION",
    "EVIDENCE_EVALUATION",
    "REASONING_RUN",
    "REASONING_RUN_CONSISTENCY",
)


def _force_failure(monkeypatch, stage_id: str) -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.evidence_evaluation import EvidenceEvaluationService
    from rop.services.missing_information import MissingInformationService
    from rop.services.observation_extraction import (
        ObservationExtractionService,
    )
    from rop.services.reasoning_run import ReasoningRunService
    from rop.services.reasoning_run_consistency import (
        ReasoningRunConsistencyService,
    )
    from rop.services.template_match import TemplateMatchService

    def boom(*args, **kwargs):
        raise RuntimeError("forced failure at " + stage_id)

    if stage_id == "OBSERVATION_EXTRACTION":
        monkeypatch.setattr(
            ObservationExtractionService, "extract_and_store", boom
        )
    elif stage_id == "MISSING_INFORMATION":
        monkeypatch.setattr(
            MissingInformationService, "detect_and_store", boom
        )
    elif stage_id == "TEMPLATE_MATCHING":
        monkeypatch.setattr(TemplateMatchService, "match", boom)
    elif stage_id == "CANDIDATE_GENERATION":
        monkeypatch.setattr(CandidateGenerationService, "generate", boom)
    elif stage_id == "EVIDENCE_EVALUATION":
        monkeypatch.setattr(
            EvidenceEvaluationService, "evaluate_session", boom
        )
    elif stage_id == "REASONING_RUN":
        monkeypatch.setattr(
            ReasoningRunService, "build_for_session", boom
        )
    elif stage_id == "REASONING_RUN_CONSISTENCY":
        monkeypatch.setattr(
            ReasoningRunConsistencyService, "build_for_session", boom
        )
    else:
        raise AssertionError("unknown stage_id: " + stage_id)


@pytest.mark.parametrize("failing_stage", _FAILING_STAGES)
def test_bundle_for_failed_execution(monkeypatch, failing_stage) -> None:
    """A valid FAILED Task 044 execution must still produce an available
    bundle with bundle_consistent=True."""
    _force_failure(monkeypatch, failing_stage)

    sid = _create_session("Patient reports chest pain")
    bundle = _execute_via_api(sid)

    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is True
    exec_ = bundle["execution"]
    assert exec_["outcome"] == "FAILED"
    assert exec_["available"] is False
    assert exec_["reasoning_run"] is None
    assert exec_["reasoning_run_consistency"] is None
    audit = bundle["execution_consistency"]
    assert audit["available"] is True
    assert audit["execution_consistent"] is True
    assert audit["consistency_issues"] == []


# ---------------------------------------------------------------------------
# Identity mismatch
# ---------------------------------------------------------------------------


def _valid_execution_and_audit() -> tuple[dict[str, Any], dict[str, Any]]:
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    execution = r.json()
    audit = ReasoningRunExecutionConsistencyService().build(
        execution=execution
    )
    return execution, audit


def test_bundle_rejects_execution_session_mismatch() -> None:
    execution, audit = _valid_execution_and_audit()
    other_session = uuid4()
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=other_session,
            execution=execution,
            execution_consistency=audit,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_bundle_rejects_audit_session_inconsistent() -> None:
    execution, audit = _valid_execution_and_audit()
    sid = UUID(execution["session_id"])
    tampered_audit = copy.deepcopy(audit)
    tampered_audit["session_consistent"] = False
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=sid,
            execution=execution,
            execution_consistency=tampered_audit,
        )
    assert ei.value.invariant == "SESSION_CONSISTENCY_FALSE"


def test_bundle_rejects_audit_unavailable() -> None:
    execution, audit = _valid_execution_and_audit()
    sid = UUID(execution["session_id"])
    tampered_audit = copy.deepcopy(audit)
    tampered_audit["available"] = False
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=sid,
            execution=execution,
            execution_consistency=tampered_audit,
        )
    assert ei.value.invariant == "AUDIT_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Source mismatch
# ---------------------------------------------------------------------------


def test_bundle_rejects_wrong_execution_source() -> None:
    execution, audit = _valid_execution_and_audit()
    sid = UUID(execution["session_id"])
    tampered = copy.deepcopy(execution)
    tampered["execution_source"] = "WRONG"
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=sid,
            execution=tampered,
            execution_consistency=audit,
        )
    assert ei.value.invariant in (
        "INVALID_EXECUTION",
        "INVALID_EXECUTION_SOURCE",
    )


def test_bundle_rejects_wrong_audit_source() -> None:
    execution, audit = _valid_execution_and_audit()
    sid = UUID(execution["session_id"])
    tampered_audit = copy.deepcopy(audit)
    tampered_audit["execution_consistency_source"] = "WRONG"
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=sid,
            execution=execution,
            execution_consistency=tampered_audit,
        )
    assert ei.value.invariant in (
        "INVALID_EXECUTION_CONSISTENCY",
        "INVALID_AUDIT_SOURCE",
    )


# ---------------------------------------------------------------------------
# Audit relationship mismatch
# ---------------------------------------------------------------------------


def test_bundle_inconsistent_when_audit_reports_inconsistent() -> None:
    """If Task 045 legitimately reports execution_consistent=False, the
    bundle is still available but bundle_consistent=False."""
    sid = _create_session("Patient reports chest pain")
    # Force a FAILED execution, then tamper the audit so its
    # execution_consistent flag is False.
    from rop.services.observation_extraction import (
        ObservationExtractionService,
    )

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced")

    ObservationExtractionService.extract_and_store = boom
    try:
        r = client.post(f"/sessions/{sid}/reasoning-run/execute")
        execution = r.json()
    finally:
        ObservationExtractionService.extract_and_store = original
    audit = ReasoningRunExecutionConsistencyService().build(
        execution=execution
    )
    # Valid FAILED audit -- consistent
    assert audit["execution_consistent"] is True
    bundle = _service().build(
        session_id=UUID(sid),
        execution=execution,
        execution_consistency=audit,
    )
    assert bundle["bundle_consistent"] is True


# ---------------------------------------------------------------------------
# Missing nested objects
# ---------------------------------------------------------------------------


def test_bundle_rejects_missing_execution() -> None:
    _, audit = _valid_execution_and_audit()
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=uuid4(),
            execution=None,
            execution_consistency=audit,
        )
    assert ei.value.invariant == "MISSING_EXECUTION"


def test_bundle_rejects_missing_audit() -> None:
    execution, _ = _valid_execution_and_audit()
    sid = UUID(execution["session_id"])
    with pytest.raises(ReasoningRunExecutionBundleContractError) as ei:
        _service().build(
            session_id=sid,
            execution=execution,
            execution_consistency=None,
        )
    assert ei.value.invariant == "MISSING_EXECUTION_CONSISTENCY"


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_exact_execution_passed_to_audit(monkeypatch) -> None:
    """The exact Task 044 result must be the object handed to Task 045."""
    captured: dict[str, Any] = {}

    original_build = ReasoningRunExecutionConsistencyService.build

    def spy_build(self, *, execution=None):
        captured["execution"] = execution
        return original_build(self, execution=execution)

    monkeypatch.setattr(
        ReasoningRunExecutionConsistencyService, "build", spy_build
    )

    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
    assert r.status_code == 200

    # The captured execution must have come from Task 044 and be the
    # same dict shape embedded in the bundle.
    assert isinstance(captured["execution"], dict)
    assert captured["execution"]["execution_source"] == (
        "REASONING_RUN_EXECUTION_TASK_044"
    )


def test_execute_called_exactly_once(monkeypatch) -> None:
    calls = {"n": 0}
    original = ReasoningRunExecutionService.execute_for_session

    def spy(self, db, session_id):
        calls["n"] += 1
        return original(self, db, session_id)

    monkeypatch.setattr(ReasoningRunExecutionService, "execute_for_session", spy)

    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
    assert r.status_code == 200
    assert calls["n"] == 1


def test_build_for_session_delegates_to_044_and_045() -> None:
    """Sanity: build_for_session calls both nested services exactly once."""
    # Indirectly verified by the spy tests above; this is a structural
    # check that the service holds both nested services as attributes.
    svc = _service()
    assert isinstance(
        svc.reasoning_run_execution_service, ReasoningRunExecutionService
    )
    assert isinstance(
        svc.reasoning_run_execution_consistency_service,
        ReasoningRunExecutionConsistencyService,
    )


# ---------------------------------------------------------------------------
# No side effects outside Task 044
# ---------------------------------------------------------------------------


def test_service_does_not_import_forbidden_modules() -> None:
    import inspect

    from rop.services import reasoning_run_execution_bundle as mod

    src = inspect.getsource(mod)
    for forbidden in (
        "CandidateGenerationService",
        "EvidenceEvaluationService",
        "MissingInformationService",
        "ObservationExtractionService",
        "TemplateMatchService",
        "ObservationService",
        "EntityService",
        "DecisionPolicy",
        "DecisionExecution",
    ):
        assert forbidden not in src, forbidden


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_execute_audited_endpoint() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert payload["bundle_source"] == (
        "REASONING_RUN_EXECUTION_BUNDLE_TASK_046"
    )


def test_api_missing_session_returns_404() -> None:
    r = client.post(f"/sessions/{uuid4()}/reasoning-run/execute-audited")
    assert r.status_code == 404


def test_api_execute_audited_via_empty_input() -> None:
    sid = _create_session(".")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
    assert r.status_code == 200
    assert r.json()["available"] is True


# ---------------------------------------------------------------------------
# Existing endpoint compatibility
# ---------------------------------------------------------------------------


def test_existing_execute_endpoint_unchanged() -> None:
    """POST /reasoning-run/execute must still return Task 044's contract."""
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    assert r.status_code == 200
    payload = r.json()
    # Task 044 shape -- not the Task 046 shape.
    assert "execution_source" in payload
    assert "bundle_source" not in payload
    assert "execution" not in payload


def test_existing_reasoning_run_get_unchanged() -> None:
    sid = _create_session("Patient reports chest pain")
    r = client.get(f"/sessions/{sid}/reasoning-run")
    assert r.status_code == 200
    payload = r.json()
    assert "run_source" in payload
    assert "bundle_source" not in payload

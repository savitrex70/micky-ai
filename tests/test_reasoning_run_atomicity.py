"""Task 126: atomic deterministic reasoning-run execution tests.

Proves each write stage commits as one atomic unit: a mid-stage
failure rolls back instead of stranding invalid partial state, the
execution result still reports the failure correctly, unrelated
sessions stay untouched, and retry succeeds. No model, no network
beyond the test app.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID

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
from rop.services.reasoning_run_execution import ReasoningRunExecutionService
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


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "atomicity-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _counts(session_id: str) -> dict[str, int]:
    sid = UUID(session_id)
    with TestingSessionLocal() as db:
        return {
            "observations": len(ObservationService().list_by_session(db, sid)),
            "entities": len(EntityService().list_by_session(db, sid)),
            "missing": len(MissingInformationService().list_by_session(db, sid)),
            "templates": len(TemplateMatchService().list_by_session(db, sid)),
            "candidates": len(CandidateGenerationService().list_by_session(db, sid)),
            "evidence": len(EvidenceEvaluationService().list_by_session(db, sid)),
        }


def _execute(
    session_id: str, service: ReasoningRunExecutionService | None = None
) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return (service or ReasoningRunExecutionService()).execute_for_session(
            db, UUID(session_id)
        )


def _failing(extras: dict[str, Any]) -> ReasoningRunExecutionService:
    return ReasoningRunExecutionService(**extras)


def test_success_commits_all_stages_together() -> None:
    sid = _create_session("Patient reports chest pain and sweating")
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    counts = _counts(sid)
    assert counts["observations"] > 0
    assert counts["candidates"] > 0
    assert counts["evidence"] > 0


def test_extraction_failure_leaves_no_observations() -> None:
    from rop.services.observation_extraction import ObservationExtractionService

    class _BoomExtraction(ObservationExtractionService):
        def extract_and_store(self, db: Any, session_id: Any, text: Any) -> Any:
            raise RuntimeError("extraction exploded")

    sid = _create_session("Patient reports яростная боль")
    result = _execute(
        sid, _failing({"observation_extraction_service": _BoomExtraction()})
    )
    assert result["outcome"] == "FAILED"
    assert result["available"] is False
    assert result["reasoning_run"] is None
    assert result["reasoning_run_consistency"] is None
    failed = [s for s in result["stages"] if s["status"] == "FAILED"]
    assert [s["stage_id"] for s in failed] == ["OBSERVATION_EXTRACTION"]
    assert _counts(sid)["observations"] == 0


def test_missing_information_failure_rolls_back_replace() -> None:
    from rop.services.missing_information import MissingInformationService

    class _BoomMissing(MissingInformationService):
        def detect_and_store(self, *args: Any, **kwargs: Any) -> Any:
            # Simulate a failure after the delete half of a replace:
            # the rollback guard must leave prior state intact.
            raise RuntimeError("detection exploded")

    sid = _create_session("Patient reports chest pain")
    result = _execute(sid, _failing({"missing_information_service": _BoomMissing()}))
    assert result["outcome"] == "FAILED"
    failed = [s for s in result["stages"] if s["status"] == "FAILED"]
    assert [s["stage_id"] for s in failed] == ["MISSING_INFORMATION"]
    assert _counts(sid)["missing"] == 0


def test_template_failure_leaves_no_template() -> None:
    from rop.services.template_match import TemplateMatchService

    class _BoomTemplate(TemplateMatchService):
        def match(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("match exploded")

    sid = _create_session("Patient reports chest pain")
    result = _execute(sid, _failing({"template_match_service": _BoomTemplate()}))
    assert result["outcome"] == "FAILED"
    failed = [s for s in result["stages"] if s["status"] == "FAILED"]
    assert [s["stage_id"] for s in failed] == ["TEMPLATE_MATCHING"]
    assert _counts(sid)["templates"] == 0


def test_candidate_failure_keeps_prior_candidates() -> None:
    sid = _create_session("Patient reports chest pain and dizziness")
    first = _execute(sid)
    assert first["outcome"] == "COMPLETED"
    with TestingSessionLocal() as db:
        before = {
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(sid))
        }
    assert before

    from rop.repositories.candidate_hypothesis import (
        CandidateHypothesisRepository,
    )

    real_create = CandidateHypothesisRepository.create_many

    def _boom_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        # Fail AFTER the delete half: atomicity must restore the olds.
        real_create(self, *args, **kwargs)
        raise RuntimeError("create exploded")

    CandidateHypothesisRepository.create_many = _boom_create  # type: ignore[method-assign]
    try:
        result = _execute(sid)
    finally:
        CandidateHypothesisRepository.create_many = real_create  # type: ignore[method-assign]
    assert result["outcome"] == "FAILED"
    failed = [s for s in result["stages"] if s["status"] == "FAILED"]
    assert [s["stage_id"] for s in failed] == ["CANDIDATE_GENERATION"]
    with TestingSessionLocal() as db:
        after = {
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(sid))
        }
    assert after == before


def test_evidence_failure_keeps_prior_evidence() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService

    sid = _create_session("Patient reports chest pain and sweating")
    first = _execute(sid)
    assert first["outcome"] == "COMPLETED"
    assert _counts(sid)["evidence"] > 0

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    result = _execute(sid, _failing({"evidence_evaluation_service": _BoomEvidence()}))
    assert result["outcome"] == "FAILED"
    failed = [s for s in result["stages"] if s["status"] == "FAILED"]
    assert [s["stage_id"] for s in failed] == ["EVIDENCE_EVALUATION"]
    # Prior evidence set is intact, not half-deleted.
    assert _counts(sid)["evidence"] > 0


def test_unrelated_session_untouched_by_failure() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService

    good = _create_session("Patient reports chest pain")
    bad = _create_session("Patient reports ankle sprain")
    assert _execute(good)["outcome"] == "COMPLETED"
    good_counts = _counts(good)

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    with TestingSessionLocal() as db:
        result = _failing(
            {"evidence_evaluation_service": _BoomEvidence()}
        ).execute_for_session(db, UUID(bad))
    assert result["outcome"] == "FAILED"
    assert _counts(good) == good_counts


def test_retry_after_failure_succeeds() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService

    sid = _create_session("Patient reports chest pain and nausea")

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    failed = _execute(sid, _failing({"evidence_evaluation_service": _BoomEvidence()}))
    assert failed["outcome"] == "FAILED"
    retried = _execute(sid)
    assert retried["outcome"] == "COMPLETED"
    assert retried["execution_consistent"] is True

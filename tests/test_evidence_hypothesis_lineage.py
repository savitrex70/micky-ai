"""Task 130: deterministic evidence-hypothesis lineage tests.

Proves full positive traceability and negative violation reporting
without new scoring, ranking, probability, or winner logic. No model,
no network beyond the test app.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.evidence_hypothesis_lineage import EvidenceHypothesisLineageRead
from rop.services.evidence_hypothesis_lineage import (
    EVIDENCE_HYPOTHESIS_LINEAGE_SOURCE_TASK_130,
    EvidenceHypothesisLineageContractError,
    EvidenceHypothesisLineageService,
)
from rop.services.reasoning_run_execution import ReasoningRunExecutionService

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
            "metadata": {"source": "lineage-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(session_id: str, text: str) -> None:
    o = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": text,
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert o.status_code == 201


def _execute(session_id: str) -> dict[str, Any]:
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        return ReasoningRunExecutionService().execute_for_session(db, UUID(session_id))
    finally:
        gen.close()


def _lineage(session_id: str) -> dict[str, Any]:
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        return EvidenceHypothesisLineageService().build_for_session(
            db, UUID(session_id)
        )
    finally:
        gen.close()


def _seed_executed(user_input: str) -> str:
    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    return sid


def test_positive_lineage_fully_traced() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.differential_ranking import DifferentialRankingService
    from rop.services.hypothesis_scoring import HypothesisScoringService

    sid = _seed_executed("Patient reports chest pain and sweating")
    lineage = _lineage(sid)
    assert lineage["available"] is True
    assert lineage["lineage_consistent"] is True
    assert lineage["consistency_issues"] == []
    assert lineage["lineage_source"] == EVIDENCE_HYPOTHESIS_LINEAGE_SOURCE_TASK_130
    assert EvidenceHypothesisLineageRead.model_validate(lineage)

    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        scores = {
            str(s["hypothesis_id"]): s
            for s in HypothesisScoringService().score_session(db, UUID(sid), candidates)
        }
        ranks = {
            str(r["hypothesis_id"]): r
            for r in DifferentialRankingService().rank_session(
                db, UUID(sid), candidates
            )
        }
    assert {entry["hypothesis_id"] for entry in lineage["lineages"]} == {
        str(c.id) for c in candidates
    }
    for entry in lineage["lineages"]:
        hid = entry["hypothesis_id"]
        # Scores and ranks trace exactly to their source contracts.
        assert entry["hypothesis_score"] == scores[hid]["hypothesis_score"]
        assert entry["score_source"] == scores[hid]["score_source"]
        assert entry["rank"] == ranks[hid]["rank"]
        assert entry["is_tied"] == ranks[hid]["is_tied"]
        assert entry["lineage_complete"] is True
        assert entry["unresolved_information"] is not None
        # No decision-authority fields anywhere in the lineage.
        assert "winner" not in entry
        assert "recommendation" not in entry


def test_tie_behavior_preserved() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.differential_ranking import DifferentialRankingService

    sid = _seed_executed("Patient reports chest pain")
    lineage = _lineage(sid)
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        ranks = DifferentialRankingService().rank_session(db, UUID(sid), candidates)
    by_id = {entry["hypothesis_id"]: entry for entry in lineage["lineages"]}
    for row in ranks:
        hid = str(row["hypothesis_id"])
        assert by_id[hid]["rank"] == row["rank"]
        assert by_id[hid]["is_tied"] == row["is_tied"]


def test_dangling_observation_breaks_lineage() -> None:
    from rop.services.observation import ObservationService

    sid = _seed_executed("Patient reports chest pain")
    with TestingSessionLocal() as db:
        observations = ObservationService().list_by_session(db, UUID(sid))
        assert observations
        ObservationService().delete(db, observations[0].id)
    lineage = _lineage(sid)
    assert lineage["lineage_consistent"] is False
    assert any(
        issue.startswith("unknown_lineage_observation")
        for issue in lineage["consistency_issues"]
    )


def test_unknown_session_raises() -> None:
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        with pytest.raises(EvidenceHypothesisLineageContractError):
            EvidenceHypothesisLineageService().build_for_session(db, uuid4())
    finally:
        gen.close()


def test_lineage_schema_rejects_extra() -> None:
    sid = _seed_executed("Patient reports chest pain")
    lineage = _lineage(sid)
    lineage["winner"] = "candidate-x"
    with pytest.raises(ValidationError):
        EvidenceHypothesisLineageRead.model_validate(lineage)

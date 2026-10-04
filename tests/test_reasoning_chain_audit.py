"""Task 129: independent full deterministic reasoning-chain audit tests.

Proves clean-chain consistency, per-area corruption detection,
deterministic ordering, read-only auditing, and strict result shape.
No model, no network beyond the test app.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_chain_audit import ReasoningChainAuditRead
from rop.services.reasoning_chain_audit import (
    REASONING_CHAIN_AUDIT_SOURCE_TASK_129,
    ReasoningChainAuditContractError,
    ReasoningChainAuditService,
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
            "metadata": {"source": "chain-audit-test"},
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


def _audit(session_id: str) -> dict[str, Any]:
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        return ReasoningChainAuditService().audit_session(db, UUID(session_id))
    finally:
        gen.close()


def _seed_executed(user_input: str) -> str:
    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    result = _execute(sid)
    assert result["outcome"] == "COMPLETED"
    return sid


def test_clean_chain_fully_consistent() -> None:
    sid = _seed_executed("Patient reports chest pain and sweating")
    audit = _audit(sid)
    assert audit["available"] is True
    assert audit["chain_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["audit_source"] == REASONING_CHAIN_AUDIT_SOURCE_TASK_129
    assert len(audit["input_fingerprint"]) == 64
    assert ReasoningChainAuditRead.model_validate(audit)


def test_dangling_observation_reference_detected() -> None:
    from rop.services.observation import ObservationService

    sid = _seed_executed("Patient reports chest pain")
    with TestingSessionLocal() as db:
        observations = ObservationService().list_by_session(db, UUID(sid))
        assert observations
        ObservationService().delete(db, observations[0].id)
    audit = _audit(sid)
    assert audit["chain_consistent"] is False
    assert any(
        issue.startswith("unknown_candidate_observation")
        or issue.startswith("unknown_evidence_observation")
        or issue.startswith("unknown_template_observation")
        for issue in audit["consistency_issues"]
    )


def test_invalid_evidence_relationship_detected() -> None:
    from rop.models import EvaluatedEvidence

    sid = _seed_executed("Patient reports chest pain and nausea")
    with TestingSessionLocal() as db:
        rows = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(sid))
            .all()
        )
        assert rows
        rows[0].relationship = "bogus-relationship"
        db.commit()
    audit = _audit(sid)
    assert audit["chain_consistent"] is False
    assert any(
        issue.startswith("invalid_evidence_relationship")
        for issue in audit["consistency_issues"]
    )


def test_issues_deterministically_ordered() -> None:
    from rop.models import EvaluatedEvidence
    from rop.services.observation import ObservationService

    sid = _seed_executed("Patient reports chest pain")
    with TestingSessionLocal() as db:
        observations = ObservationService().list_by_session(db, UUID(sid))
        ObservationService().delete(db, observations[0].id)
        rows = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(sid))
            .all()
        )
        if rows:
            rows[0].relationship = "bogus-relationship"
            db.commit()
    first = _audit(sid)["consistency_issues"]
    second = _audit(sid)["consistency_issues"]
    assert first == second
    assert len(first) > 1
    from rop.services.reasoning_chain_audit import _issue_key

    assert first == sorted(set(first), key=_issue_key)


def test_audit_is_read_only() -> None:
    from rop.services.candidate_generation import CandidateGenerationService

    sid = _seed_executed("Patient reports steady chest pain")
    with TestingSessionLocal() as db:
        before = sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(sid))
        )
    _audit(sid)
    with TestingSessionLocal() as db:
        after = sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(sid))
        )
    assert after == before


def test_missing_session_raises() -> None:
    from uuid import uuid4

    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        with pytest.raises(ReasoningChainAuditContractError):
            ReasoningChainAuditService().audit_session(db, uuid4())
    finally:
        gen.close()


def test_audit_result_rejects_extra_fields() -> None:
    sid = _seed_executed("Patient reports chest pain")
    audit = _audit(sid)
    audit["smuggled"] = True
    with pytest.raises(ValidationError):
        ReasoningChainAuditRead.model_validate(audit)

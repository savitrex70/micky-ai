"""Task 057 opt-in smoke test against a live Ollama server.

Marked `ollama_smoke`. Excluded from the default suite because it
requires a running Ollama server and a model already pulled. Enable
explicitly with:

    pytest -m ollama_smoke

Requires ROP_OLLAMA_BASE_URL and ROP_OLLAMA_REASONING_MODEL to be
set to a reachable endpoint and an already-installed model.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.config import get_settings
from rop.database import Base, get_db
from rop.main import app
from rop.services.llm_reasoning import LLMReasoningService
from rop.services.ollama_reasoning_provider import OllamaReasoningProvider
from rop.services.reasoning_context import ReasoningContextService

pytestmark = pytest.mark.ollama_smoke

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


def _seed() -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "smoke test",
            "current_stage": "initial",
            "metadata": {"source": "task-057-smoke"},
        },
    )
    assert r.status_code == 201
    sid = str(r.json()["id"])
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    return sid


def test_live_ollama_reasoning_boundary() -> None:
    settings = get_settings()
    if not settings.ollama_reasoning_model:
        pytest.skip("ROP_OLLAMA_REASONING_MODEL is not configured")

    sid = _seed()
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        ctx = ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()

    provider = OllamaReasoningProvider()
    service = LLMReasoningService(provider=provider)
    result = service.build(context=ctx)

    assert result["available"] is True
    assert result["proposal_consistent"] is True
    assert result["provider"] == "ollama"
    assert len(result["candidate_assessments"]) == len(ctx["candidate_state"])
    for assessment in result["candidate_assessments"]:
        assert assessment["assessment"] in {
            "SUPPORTS",
            "WEAKENS",
            "UNCLEAR",
        }

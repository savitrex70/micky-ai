"""Tests for Task 057 LLM reasoning boundary.

All tests use an injected fake provider. The unit suite never needs a
running Ollama server. A separate opt-in smoke test (marked
`ollama_smoke`) exercises the concrete Ollama provider.
"""

from __future__ import annotations

import copy
import inspect
import json
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
from rop.services import llm_reasoning as mod
from rop.services.llm_reasoning import (
    LLM_REASONING_TASK_057,
    LLMReasoningContractError,
    LLMReasoningService,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_context_consistency import (
    ReasoningContextConsistencyService,
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


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeProvider:
    """Injectable provider used in every unit test.

    Records how many times it was called, and can be configured to
    either return a fixed text response or raise a chosen exception.
    """

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        response_text: str | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls = 0
        self.last_request: Any = None

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        self.calls += 1
        self.last_request = request
        if self.raise_error is not None:
            raise self.raise_error
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=self.response_text or "",
        )


# ---------------------------------------------------------------------------
# Session / context helpers
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-057-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _valid_context(user_input: str = "Task 057 valid") -> dict[str, Any]:
    sid = _seed_full_session(user_input)
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


def _valid_model_output(context: dict[str, Any]) -> str:
    """Build a schema-valid model output referencing every candidate."""
    assessments = []
    for candidate in context["candidate_state"]:
        assessments.append(
            {
                "candidate_id": str(candidate.id),
                "assessment": "UNCLEAR",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "insufficient evidence to decide",
                "uncertainty_flags": ["insufficient_evidence"],
            }
        )
    return json.dumps({"candidate_assessments": assessments})


def _service_with(provider: FakeProvider) -> LLMReasoningService:
    return LLMReasoningService(provider=provider)


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_context_and_valid_output() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    result = _service_with(provider).build(context=ctx)

    assert result["available"] is True
    assert result["proposal_consistent"] is True
    assert result["llm_reasoning_source"] == LLM_REASONING_TASK_057
    assert result["provider"] == "fake"
    assert result["model"] == "fake-model"
    assert len(result["candidate_assessments"]) == len(
        ctx["candidate_state"]
    )
    assert provider.calls == 1


def test_provider_receives_only_allowed_fields() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    _service_with(provider).build(context=ctx)

    assert provider.last_request is not None
    payload = provider.last_request.payload
    allowed = {
        "session_id",
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
        "reasoning_pipeline",
    }
    assert set(payload.keys()) == allowed
    # The fingerprint is attached alongside the payload, not inside it.
    assert "context_fingerprint" in provider.last_request.to_model_json()


def test_context_fingerprint_is_computed_and_preserved() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    result = _service_with(provider).build(context=ctx)
    fp = result["context_fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_determinism() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    service = _service_with(provider)
    first = service.build(context=ctx)
    second = service.build(context=ctx)
    assert first == second
    assert provider.calls == 2


# ---------------------------------------------------------------------------
# Input unavailable / inconsistent
# ---------------------------------------------------------------------------


def _unavailable_context() -> dict[str, Any]:
    return {
        "available": False,
        "context_consistent": False,
        "session_id": uuid4(),
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "candidate_state": [],
        "reasoning_pipeline": {},
        "reasoning_run_consistency": {},
        "context_source": "REASONING_CONTEXT_TASK_055",
    }


def test_unavailable_context_returns_soft_result() -> None:
    provider = FakeProvider(response_text="")
    result = _service_with(provider).build(
        context=_unavailable_context()
    )
    assert result["available"] is False
    assert result["proposal_consistent"] is False
    assert result["candidate_assessments"] == []
    assert provider.calls == 0


def test_provider_not_called_when_context_unavailable() -> None:
    provider = FakeProvider(response_text="anything")
    _service_with(provider).build(context=_unavailable_context())
    assert provider.calls == 0


def test_inconsistent_context_raises() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["context_source"] = "WRONG"
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=broken)
    assert ei.value.invariant == "INPUT_INCONSISTENT"
    assert provider.calls == 0


def test_audit_service_failure_raises() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))

    class BoomConsistency:
        def build(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("audit forced to fail")

    service = LLMReasoningService(
        reasoning_context_consistency_service=BoomConsistency(),  # type: ignore[arg-type]
        provider=provider,
    )
    with pytest.raises(LLMReasoningContractError) as ei:
        service.build(context=ctx)
    assert ei.value.invariant == "INPUT_INCONSISTENT"
    assert provider.calls == 0


def test_missing_context_raises() -> None:
    provider = FakeProvider(response_text="")
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=None)
    assert ei.value.invariant == "INPUT_UNAVAILABLE"
    assert provider.calls == 0


# ---------------------------------------------------------------------------
# Provider failures
# ---------------------------------------------------------------------------


def test_provider_unavailable_raises() -> None:
    ctx = _valid_context()
    provider = FakeProvider(
        raise_error=LLMReasoningProviderError("no connection")
    )
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_UNAVAILABLE"


def test_provider_unexpected_exception_raises() -> None:
    ctx = _valid_context()
    provider = FakeProvider(raise_error=RuntimeError("boom"))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_UNAVAILABLE"


def test_no_provider_configured_raises() -> None:
    ctx = _valid_context()
    service = LLMReasoningService()
    with pytest.raises(LLMReasoningContractError) as ei:
        service.build(context=ctx)
    assert ei.value.invariant == "MODEL_UNAVAILABLE"


def test_malformed_json_raises() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text="not-json-at-all")
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_json_that_is_not_an_object_raises() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text='["not", "an", "object"]')
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_missing_required_field_raises() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text='{"candidate_assessments": []}')
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_extra_top_level_field_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["winner"] = "candidate-x"
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_invalid_assessment_value_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["assessment"] = "DEFINITELY"
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# Candidate integrity
# ---------------------------------------------------------------------------


def test_unknown_candidate_id_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_missing_candidate_assessment_rejected() -> None:
    ctx = _valid_context()
    if len(ctx["candidate_state"]) < 2:
        pytest.skip("seed session produced only one candidate")
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"] = output["candidate_assessments"][:1]
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_duplicate_candidate_assessment_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"].append(
        copy.deepcopy(output["candidate_assessments"][0])
    )
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


# ---------------------------------------------------------------------------
# Evidence / missing-information integrity
# ---------------------------------------------------------------------------


def test_unknown_evidence_id_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["supporting_evidence_ids"] = [
        str(uuid4())
    ]
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_unknown_contradicting_evidence_id_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["contradicting_evidence_ids"] = [
        str(uuid4())
    ]
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_unknown_missing_information_id_rejected() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["unresolved_information_ids"] = [
        str(uuid4())
    ]
    provider = FakeProvider(response_text=json.dumps(output))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_valid_evidence_ids_accepted() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    if ctx["observations"]:
        output["candidate_assessments"][0]["supporting_evidence_ids"] = [
            str(ctx["observations"][0].id)
        ]
    provider = FakeProvider(response_text=json.dumps(output))
    result = _service_with(provider).build(context=ctx)
    assert result["available"] is True


# ---------------------------------------------------------------------------
# Safety boundary
# ---------------------------------------------------------------------------


def test_module_has_no_database_import() -> None:
    """The module may import Session for type annotations only; it
    must never construct a session, an engine, or execute a query."""
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        ".query(",
        ".execute(",
    ):
        assert forbidden not in src, forbidden


def test_module_has_no_http_import() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("httpx", "requests.", "fastapi"):
        assert forbidden not in src, forbidden


def test_module_does_not_reference_decision_services() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "DecisionPolicy",
        "DecisionExecution",
        "select_winner",
        "rank_candidates",
        "recommendation",
    ):
        assert forbidden not in src, forbidden


def test_module_does_not_write_provider_text_to_db() -> None:
    """The module may use Python set.add() for local bookkeeping, but
    it must never call an ORM commit or flush (the only two operations
    that would persist provider text)."""
    src = inspect.getsource(mod)
    assert ".commit(" not in src
    assert ".flush(" not in src


def test_tools_not_exposed_to_provider() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    _service_with(provider).build(context=ctx)
    payload = provider.last_request.payload
    for forbidden in ("tools", "tool", "functions", "function_call"):
        assert forbidden not in payload


# ---------------------------------------------------------------------------
# Mutation safety
# ---------------------------------------------------------------------------


def test_does_not_mutate_context() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    # Snapshot identity / shape of each nested collection.
    snaps = {}
    for name in (
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ):
        lst = ctx[name]
        snaps[name] = (id(lst), len(lst), [id(x) for x in lst])
    pipeline_keys = list(ctx["reasoning_pipeline"].keys())
    audit_keys = list(ctx["reasoning_run_consistency"].keys())

    _service_with(provider).build(context=ctx)

    for name, (lst_id, length, item_ids) in snaps.items():
        assert id(ctx[name]) == lst_id
        assert len(ctx[name]) == length
        assert [id(x) for x in ctx[name]] == item_ids
    assert list(ctx["reasoning_pipeline"].keys()) == pipeline_keys
    assert list(ctx["reasoning_run_consistency"].keys()) == audit_keys


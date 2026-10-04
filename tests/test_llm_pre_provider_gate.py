"""Tests for Task 111 pre-provider integration gate.

Final gate before a real provider is accepted: prove ROP keeps
control of the Task 057 boundary while using ONLY fake providers
defined in this file. No real provider module is ever imported.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import sys
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
from rop.services.llm_reasoning import (
    LLM_REASONING_TASK_057,
    LLMReasoningContractError,
    LLMReasoningService,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.llm_request_serialization import (
    ALLOWED_PAYLOAD_FIELDS,
    compute_fingerprint,
    serialize_context,
    validate_payload,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_context_consistency import (
    REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056,
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
# Fake providers only (implement the protocol; never a real provider)
# ---------------------------------------------------------------------------


class FakeGateProvider:
    """Capturing fake implementing the provider protocol."""

    provider_name = "fake-gate"
    model_name = "fake-gate-model"

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


class FakeSpoofedMetadataProvider(FakeGateProvider):
    """Fake whose provider/model labels differ from ROP metadata."""

    provider_name = "spoofed-provider"
    model_name = "spoofed-model"


# ---------------------------------------------------------------------------
# Seeded sessions + canonical context helpers (real services only)
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-111-test"},
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


def _open_db() -> Any:
    gen = app.dependency_overrides[get_db]()
    return gen, next(gen)


def _session_count() -> int:
    from rop.models.reasoning_session import ReasoningSession

    gen, db = _open_db()
    try:
        return int(db.query(ReasoningSession).count())
    finally:
        gen.close()


def _build_context(session_id: str) -> dict[str, Any]:
    gen, db = _open_db()
    try:
        ctx = ReasoningContextService().build_for_session(db, UUID(session_id))
        return dict(ctx)
    finally:
        gen.close()


def _seed_and_build(user_input: str) -> tuple[str, dict[str, Any]]:
    sid = _seed_full_session(user_input)
    return sid, _build_context(sid)


def _valid_model_output(context: dict[str, Any]) -> str:
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


def _audit(context: dict[str, Any]) -> dict[str, Any]:
    return dict(ReasoningContextConsistencyService().build(context=context))


# ---------------------------------------------------------------------------
# Gate 1: context valid + independently consistent before invocation
# ---------------------------------------------------------------------------


def test_context_valid_and_consistent_before_provider_call() -> None:
    sid, context = _seed_and_build("Task 111 gate context")
    assert isinstance(context["session_id"], UUID)
    assert str(context["session_id"]) == sid
    assert context["available"] is True
    assert context["context_consistent"] is True
    assert context["context_source"] == "REASONING_CONTEXT_TASK_055"

    audit = _audit(context)
    assert audit["available"] is True
    assert audit["context_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["audit_provenance_consistent"] is True
    assert (
        audit["context_consistency_source"]
        == REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
    )

    provider = FakeGateProvider(response_text=_valid_model_output(context))
    assert provider.calls == 0
    result = LLMReasoningService(provider=provider).build(context=context)
    assert provider.calls == 1
    assert result["available"] is True
    assert result["proposal_consistent"] is True
    assert str(result["session_id"]) == sid


# ---------------------------------------------------------------------------
# Gate 2: only the approved serialized payload crosses the boundary
# ---------------------------------------------------------------------------


def test_only_approved_serialized_payload_crosses() -> None:
    _, context = _seed_and_build("Task 111 payload gate")
    provider = FakeGateProvider(response_text=_valid_model_output(context))
    LLMReasoningService(provider=provider).build(context=context)

    assert provider.last_request is not None
    payload = provider.last_request.payload
    assert set(payload.keys()) == set(ALLOWED_PAYLOAD_FIELDS)
    assert len(ALLOWED_PAYLOAD_FIELDS) == 7
    assert payload == serialize_context(context)
    assert validate_payload(payload) == []
    assert "context_fingerprint" not in payload
    for forbidden in ("tools", "db", "engine", "session"):
        assert forbidden not in payload


# ---------------------------------------------------------------------------
# Gate 3: request carries the expected context fingerprint
# ---------------------------------------------------------------------------


def test_request_carries_expected_context_fingerprint() -> None:
    _, context = _seed_and_build("Task 111 fingerprint gate")
    provider = FakeGateProvider(response_text=_valid_model_output(context))
    result = LLMReasoningService(provider=provider).build(context=context)

    request = provider.last_request
    expected = compute_fingerprint(serialize_context(context))
    assert request.context_fingerprint == expected
    assert request.context_fingerprint == compute_fingerprint(request.payload)
    assert result["context_fingerprint"] == expected
    assert len(expected) == 64
    assert all(c in "0123456789abcdef" for c in expected)


# ---------------------------------------------------------------------------
# Gate 4: provider output strictly schema validated
# ---------------------------------------------------------------------------


def test_invalid_json_rejected_as_output_invalid() -> None:
    _, context = _seed_and_build("Task 111 invalid json")
    provider = FakeGateProvider(response_text="not-json-at-all")
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=provider).build(context=context)
    assert exc.value.invariant == "MODEL_OUTPUT_INVALID"
    assert exc.value.invariant != "MODEL_UNAVAILABLE"


def test_schema_violating_json_rejected_as_output_invalid() -> None:
    _, context = _seed_and_build("Task 111 schema violation")
    raw = json.loads(_valid_model_output(context))
    raw["winner"] = "candidate-x"
    provider = FakeGateProvider(response_text=json.dumps(raw))
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=provider).build(context=context)
    assert exc.value.invariant == "MODEL_OUTPUT_INVALID"


def test_invalid_enum_value_rejected_as_output_invalid() -> None:
    _, context = _seed_and_build("Task 111 bad enum")
    raw = json.loads(_valid_model_output(context))
    raw["candidate_assessments"][0]["assessment"] = "DEFINITELY"
    provider = FakeGateProvider(response_text=json.dumps(raw))
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=provider).build(context=context)
    assert exc.value.invariant == "MODEL_OUTPUT_INVALID"


def test_unknown_candidate_ids_rejected_as_inconsistent() -> None:
    _, context = _seed_and_build("Task 111 unknown candidate")
    raw = json.loads(_valid_model_output(context))
    raw["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    provider = FakeGateProvider(response_text=json.dumps(raw))
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=provider).build(context=context)
    assert exc.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


def test_all_reference_kinds_checked_against_exact_context() -> None:
    _, context = _seed_and_build("Task 111 reference integrity")
    candidate_ids = {str(c.id) for c in context["candidate_state"]}
    obs_ids = {str(o.id) for o in context["observations"]}
    ent_ids = {str(e.id) for e in context["entities"]}
    evidence_ids = obs_ids | ent_ids
    missing_ids = {str(m.id) for m in context["missing_information"]}

    provider = FakeGateProvider(response_text=_valid_model_output(context))
    result = LLMReasoningService(provider=provider).build(context=context)
    seen: set[str] = set()
    for item in result["candidate_assessments"]:
        cid = str(item["candidate_id"])
        assert cid in candidate_ids
        assert cid not in seen
        seen.add(cid)
        for eid in item["supporting_evidence_ids"]:
            assert str(eid) in evidence_ids
        for eid in item["contradicting_evidence_ids"]:
            assert str(eid) in evidence_ids
        for mid in item["unresolved_information_ids"]:
            assert str(mid) in missing_ids
    assert seen == candidate_ids

    for field, bad in (
        ("supporting_evidence_ids", [str(uuid4())]),
        ("contradicting_evidence_ids", [str(uuid4())]),
        ("unresolved_information_ids", [str(uuid4())]),
    ):
        raw = json.loads(_valid_model_output(context))
        raw["candidate_assessments"][0][field] = bad
        bad_provider = FakeGateProvider(response_text=json.dumps(raw))
        with pytest.raises(LLMReasoningContractError) as exc:
            LLMReasoningService(provider=bad_provider).build(context=context)
        assert exc.value.invariant == "MODEL_OUTPUT_INCONSISTENT"


# ---------------------------------------------------------------------------
# Gate 5: provider-controlled fields cannot overwrite ROP metadata
# ---------------------------------------------------------------------------


def test_provider_text_contributes_only_assessments() -> None:
    sid_a, context_a = _seed_and_build("Task 111 session A")
    _, context_b = _seed_and_build("Task 111 session B")

    foreign_text = _valid_model_output(context_b)
    foreign_provider = FakeGateProvider(response_text=foreign_text)
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=foreign_provider).build(context=context_a)
    assert exc.value.invariant == "MODEL_OUTPUT_INCONSISTENT"

    own_text = _valid_model_output(context_a)
    provider = FakeSpoofedMetadataProvider(response_text=own_text)
    result = LLMReasoningService(provider=provider).build(context=context_a)
    expected_fp = compute_fingerprint(serialize_context(context_a))
    assert str(result["session_id"]) == sid_a
    assert str(result["session_id"]) == str(context_a["session_id"])
    assert result["context_fingerprint"] == expected_fp
    assert result["llm_reasoning_source"] == LLM_REASONING_TASK_057
    assert LLM_REASONING_TASK_057 == "LLM_REASONING_TASK_057"
    assert result["provider"] == "spoofed-provider"
    assert result["model"] == "spoofed-model"

    parsed = json.loads(own_text)
    assert [str(a["candidate_id"]) for a in parsed["candidate_assessments"]] == [
        str(a["candidate_id"]) for a in result["candidate_assessments"]
    ]

    smuggled = json.loads(own_text)
    smuggled["session_id"] = str(uuid4())
    smuggled["context_fingerprint"] = "0" * 64
    smuggled["llm_reasoning_source"] = "SPOOFED"
    smuggle_provider = FakeGateProvider(response_text=json.dumps(smuggled))
    with pytest.raises(LLMReasoningContractError) as smuggled_exc:
        LLMReasoningService(provider=smuggle_provider).build(context=context_a)
    assert smuggled_exc.value.invariant == "MODEL_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# Gate 6: no raw model text escapes
# ---------------------------------------------------------------------------


def test_no_raw_model_text_escapes_result() -> None:
    _, context = _seed_and_build("Task 111 no raw text")
    provider_text = _valid_model_output(context)
    provider = FakeGateProvider(response_text=provider_text)
    result = LLMReasoningService(provider=provider).build(context=context)

    assert "text" not in result
    assert set(result.keys()) == {
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "candidate_assessments",
        "available",
        "proposal_consistent",
        "llm_reasoning_source",
    }
    dumped = json.dumps(result, sort_keys=True)
    assert provider_text not in dumped
    assert '{"candidate_assessments"' not in dumped
    flat_values: list[str] = []

    def _collect(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                _collect(v)
        elif isinstance(value, list):
            for v in value:
                _collect(v)
        elif isinstance(value, str):
            flat_values.append(value)

    _collect(result)
    assert provider_text not in flat_values
    for item in result["candidate_assessments"]:
        assert set(item.keys()) == {
            "candidate_id",
            "assessment",
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "unresolved_information_ids",
            "explanation",
            "uncertainty_flags",
        }


# ---------------------------------------------------------------------------
# Gate 7: no DB mutation + deterministic repeats
# ---------------------------------------------------------------------------


def test_no_db_mutation_from_gated_runs() -> None:
    _, context = _seed_and_build("Task 111 db static")
    before = _session_count()
    provider = FakeGateProvider(response_text=_valid_model_output(context))
    LLMReasoningService(provider=provider).build(context=context)
    assert _session_count() == before

    failing = FakeGateProvider(response_text="broken-json{{")
    with pytest.raises(LLMReasoningContractError):
        LLMReasoningService(provider=failing).build(context=context)
    assert _session_count() == before


def test_repeated_fake_provider_runs_deterministic() -> None:
    _, context = _seed_and_build("Task 111 deterministic")
    text = _valid_model_output(context)
    snapshot = copy.deepcopy(context)
    first = LLMReasoningService(provider=FakeGateProvider(response_text=text)).build(
        context=context
    )
    second = LLMReasoningService(provider=FakeGateProvider(response_text=text)).build(
        context=context
    )
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert serialize_context(context) == serialize_context(snapshot)


# ---------------------------------------------------------------------------
# Gate 8: provider failure explicit and bounded
# ---------------------------------------------------------------------------


def test_provider_error_maps_to_model_unavailable() -> None:
    _, context = _seed_and_build("Task 111 provider error")
    provider = FakeGateProvider(raise_error=LLMReasoningProviderError("no connection"))
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=provider).build(context=context)
    assert exc.value.invariant == "MODEL_UNAVAILABLE"


def test_provider_runtime_error_maps_to_model_unavailable() -> None:
    _, context = _seed_and_build("Task 111 runtime error")
    provider = FakeGateProvider(raise_error=RuntimeError("boom"))
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=provider).build(context=context)
    assert exc.value.invariant == "MODEL_UNAVAILABLE"


def test_none_provider_maps_to_model_unavailable() -> None:
    _, context = _seed_and_build("Task 111 none provider")
    with pytest.raises(LLMReasoningContractError) as exc:
        LLMReasoningService(provider=None).build(context=context)
    assert exc.value.invariant == "MODEL_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Gate 9: no real external provider required (fake-only)
# ---------------------------------------------------------------------------


def test_no_real_external_provider_required_fake_only() -> None:
    real_module = "olla" + "ma_reasoning_provider"
    assert real_module not in sys.modules
    assert FakeGateProvider.__module__ == __name__
    assert FakeSpoofedMetadataProvider.__module__ == __name__
    for cls in (FakeGateProvider, FakeSpoofedMetadataProvider):
        assert isinstance(cls.provider_name, str)
        assert isinstance(cls.model_name, str)
        assert callable(cls.generate_reasoning)

    import pathlib

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "olla" + "ma" not in alias.name
        if isinstance(node, ast.ImportFrom):
            assert "olla" + "ma" not in (node.module or "")

    import rop.services.llm_reasoning as service_mod

    service_src = inspect.getsource(service_mod)
    assert "OllamaReasoningProvider" not in service_src

    _, context = _seed_and_build("Task 111 fake only proves ready")
    provider = FakeGateProvider(response_text=_valid_model_output(context))
    result = LLMReasoningService(provider=provider).build(context=context)
    assert result["available"] is True

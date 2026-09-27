"""Live enforcement proofs for the corrected pre-LLM boundary.

Each test exercises the REAL Task 057 production path
(LLMReasoningService.build) to prove the Task 103-109 contracts are
enforced live -- not merely present as helpers. Covers: Task 104
payload enforcement before provider invocation, Task 105 output
validation mapping through the live path, Task 107 failure/metadata
delegation, ROP-controlled field integrity, and read-only/no-network
properties.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
from collections.abc import Generator, Mapping
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning import (
    LLM_REASONING_TASK_057,
    LLMReasoningContractError,
    LLMReasoningService,
)
from rop.services.llm_reasoning_audit import LLMReasoningAuditService
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
)
from rop.services.reasoning_context import ReasoningContextService

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


class FakeProvider:
    """Protocol-shaped fake capturing its request for boundary proofs."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        response_text: str | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls: list[Any] = []

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        self.calls.append(request)
        if self.raise_error is not None:
            raise self.raise_error
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=self.response_text or "",
        )


def _seed_full_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "live-enforcement"},
        },
    )
    assert r.status_code == 201
    sid = str(r.json()["id"])
    o = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert o.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _valid_context(user_input: str = "live enforcement") -> dict[str, Any]:
    sid = _seed_full_session(user_input)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return ReasoningContextService().build_for_session(db, UUID(sid))
    finally:
        db_gen.close()


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
                "uncertainty_flags": [],
            }
        )
    return json.dumps({"candidate_assessments": assessments})


def _service_with(provider: FakeProvider) -> LLMReasoningService:
    return LLMReasoningService(provider=provider)


# ---------------------------------------------------------------------------
# Task 104: enforcement is live before provider invocation
# ---------------------------------------------------------------------------


def test_live_rejects_injected_payload_field_before_provider_call() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    service = _service_with(provider)

    real_serialize = LLMReasoningService._serialize_context

    def _tampered(context: Mapping[str, Any]) -> dict[str, Any]:
        payload = real_serialize(context)
        payload["winner"] = "candidate-x"
        return payload

    import unittest.mock as mock

    with mock.patch.object(
        LLMReasoningService, "_serialize_context", staticmethod(_tampered)
    ):
        with pytest.raises(LLMReasoningContractError) as ei:
            service.build(context=ctx)
    assert ei.value.invariant == "INPUT_INCONSISTENT"
    assert provider.calls == []


def test_live_request_carries_exact_allowed_fields() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    _service_with(provider).build(context=ctx)

    assert len(provider.calls) == 1
    request = provider.calls[0]
    assert set(request.payload.keys()) == {
        "session_id",
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
        "reasoning_pipeline",
    }


# ---------------------------------------------------------------------------
# Task 105: authoritative live output validation mapping
# ---------------------------------------------------------------------------


def _live_invariant(ctx: dict[str, Any], output: str) -> str:
    provider = FakeProvider(response_text=output)
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    return ei.value.invariant


def test_live_extra_top_level_key_is_invalid() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["winner"] = "candidate-x"
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INVALID"


def test_live_invalid_assessment_is_invalid() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["assessment"] = "DEFINITELY"
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INVALID"


def test_live_unknown_candidate_is_inconsistent() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INCONSISTENT"


def test_live_unknown_evidence_is_inconsistent() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["supporting_evidence_ids"] = [str(uuid4())]
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INCONSISTENT"


def test_live_unknown_missing_info_is_inconsistent() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["unresolved_information_ids"] = [str(uuid4())]
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INCONSISTENT"


def test_live_reordered_candidates_is_inconsistent() -> None:
    ctx = _valid_context()
    if len(ctx["candidate_state"]) < 2:
        pytest.skip("seed session produced only one candidate")
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"] = list(reversed(output["candidate_assessments"]))
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INCONSISTENT"


def test_live_duplicate_candidate_is_inconsistent() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"].append(
        copy.deepcopy(output["candidate_assessments"][0])
    )
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INCONSISTENT"


def test_live_empty_explanation_is_inconsistent() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["explanation"] = ""
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INCONSISTENT"


def test_live_non_list_uncertainty_flags_is_inconsistent() -> None:
    ctx = _valid_context()
    output = json.loads(_valid_model_output(ctx))
    output["candidate_assessments"][0]["uncertainty_flags"] = "unsure"
    # Schema rejects non-list flags before reference checks run.
    assert _live_invariant(ctx, json.dumps(output)) == "MODEL_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# Task 107: live failure classification delegation
# ---------------------------------------------------------------------------


def test_live_unexpected_exception_delegates_to_107_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the service hardcoded MODEL_UNAVAILABLE, forcing the boundary
    to classify differently would have no effect. Redirecting the
    boundary must redirect the live outcome: proof of delegation."""
    ctx = _valid_context()
    control = FakeProvider(raise_error=RuntimeError("boom"))
    with pytest.raises(LLMReasoningContractError) as ei_control:
        _service_with(control).build(context=ctx)
    assert ei_control.value.invariant == "MODEL_UNAVAILABLE"

    provider = FakeProvider(raise_error=RuntimeError("boom"))
    monkeypatch.setattr(
        ProviderFailureBoundary,
        "normalize_failure",
        staticmethod(lambda exc: "MODEL_OUTPUT_INVALID"),
    )
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_live_provider_error_maps_unavailable() -> None:
    ctx = _valid_context()
    provider = FakeProvider(raise_error=LLMReasoningProviderError("connection reset"))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_UNAVAILABLE"


def test_live_empty_provider_metadata_rejected() -> None:
    ctx = _valid_context()

    class _EmptyMetaProvider(FakeProvider):
        provider_name = ""
        model_name = ""

    provider = _EmptyMetaProvider(response_text=_valid_model_output(ctx))
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# ROP-controlled fields stay ROP-controlled
# ---------------------------------------------------------------------------


def test_live_rop_fields_not_provider_controlled() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    result = _service_with(provider).build(context=ctx)

    assert UUID(str(result["session_id"])) == ctx["session_id"]
    assert result["context_fingerprint"] == compute_fingerprint(serialize_context(ctx))
    assert result["llm_reasoning_source"] == LLM_REASONING_TASK_057
    # Provider/model describe which provider ran (transparency), while
    # session, fingerprint, and source are ROP-computed.
    assert result["provider"] == "fake"
    assert result["model"] == "fake-model"


def test_live_result_has_exact_field_set() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    result = _service_with(provider).build(context=ctx)

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


# ---------------------------------------------------------------------------
# Read-only, no network, deterministic, no raw-text leakage
# ---------------------------------------------------------------------------


def test_live_build_writes_nothing() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    service = _service_with(provider)
    before = client.get("/sessions", params={"limit": 100}).json()
    service.build(context=ctx)
    service.build(context=ctx)
    after = client.get("/sessions", params={"limit": 100}).json()
    assert before == after


def test_live_no_network_tokens_in_boundary_sources() -> None:
    import rop.services.llm_output_validation as m105
    import rop.services.llm_provider_isolation as m107
    import rop.services.llm_reasoning as m057
    import rop.services.llm_request_serialization as m104

    forbidden_modules = {"httpx", "requests", "socket", "urllib", "urllib3", "aiohttp"}
    forbidden_attrs = {"urlopen", "urlretrieve", "create_connection", "getaddrinfo"}
    for mod in (m057, m104, m105, m107):
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert (
                        alias.name.split(".")[0] not in forbidden_modules
                    ), f"{mod.__name__} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[
                    0
                ] not in forbidden_modules, f"{mod.__name__} imports from {node.module}"
            elif isinstance(node, ast.Attribute):
                assert (
                    node.attr not in forbidden_attrs
                ), f"{mod.__name__} uses network attr {node.attr}"


def test_live_deterministic_repeated_builds() -> None:
    ctx = _valid_context()
    first = _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build(
        context=ctx
    )
    second = _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build(
        context=ctx
    )
    assert first == second


def test_live_raw_provider_text_never_public() -> None:
    ctx = _valid_context()
    marker_text = json.dumps({"candidate_assessments": []})
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    result = _service_with(provider).build(context=ctx)

    assert "text" not in result
    assert "raw_text" not in result
    assert "prompt" not in result
    assert marker_text not in json.dumps(result)


def test_live_103_audit_binds_context_provenance() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    proposal = _service_with(provider).build(context=ctx)

    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)
    assert audit["consistency_issues"] == []
    assert audit["fingerprint_consistent"] is True
    assert audit["candidate_order_consistent"] is True

    forged = copy.deepcopy(proposal)
    forged["context_fingerprint"] = "0" * 64
    forged_audit = LLMReasoningAuditService.build(proposal=forged, context=ctx)
    assert "fingerprint_mismatch" in forged_audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Correction proofs: availability binding, exact field sets, provider
# boundary completeness
# ---------------------------------------------------------------------------


def test_live_103_rejects_available_proposal_on_unavailable_context() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    proposal = _service_with(provider).build(context=ctx)
    assert proposal["available"] is True

    unavailable_ctx = dict(ctx)
    unavailable_ctx["available"] = False
    unavailable_ctx["context_consistent"] = False
    audit = LLMReasoningAuditService.build(proposal=proposal, context=unavailable_ctx)

    assert audit["proposal_consistent"] is False
    assert "availability_mismatch" in audit["consistency_issues"]


def test_live_103_rejects_unexpected_top_level_field() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    proposal = _service_with(provider).build(context=ctx)
    proposal["winner"] = "candidate-x"

    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)

    assert audit["proposal_consistent"] is False
    assert "unexpected_field:winner" in audit["consistency_issues"]


def test_live_103_rejects_unexpected_nested_field() -> None:
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    proposal = _service_with(provider).build(context=ctx)
    proposal["candidate_assessments"][0]["tool_call"] = "x"

    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)

    assert audit["proposal_consistent"] is False
    assert "unexpected_assessment_field:tool_call" in audit["consistency_issues"]


def test_live_provider_error_classified_through_107_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMReasoningProviderError must flow through normalize_failure:
    redirecting the boundary redirects the live outcome for this path
    too -- no second competing classification exists."""
    ctx = _valid_context()
    control = FakeProvider(
        raise_error=LLMReasoningProviderError("connection reset by peer")
    )
    with pytest.raises(LLMReasoningContractError) as ei_control:
        _service_with(control).build(context=ctx)
    assert ei_control.value.invariant == "MODEL_UNAVAILABLE"

    provider = FakeProvider(
        raise_error=LLMReasoningProviderError("connection reset by peer")
    )
    monkeypatch.setattr(
        ProviderFailureBoundary,
        "normalize_failure",
        staticmethod(lambda exc: "MODEL_OUTPUT_INVALID"),
    )
    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(provider).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_live_malformed_response_missing_metadata_is_invalid() -> None:
    """A provider object without provider/model metadata must become
    MODEL_OUTPUT_INVALID, never an AttributeError leak."""
    ctx = _valid_context()

    class _NoMetaProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            return SimpleNamespace(text=_valid_model_output(ctx))

    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(_NoMetaProvider()).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_live_non_string_provider_text_is_invalid() -> None:
    """Non-string provider text must become MODEL_OUTPUT_INVALID, never
    a raw TypeError leak from json.loads."""
    ctx = _valid_context()

    class _BadTextProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            response = super().generate_reasoning(request)
            return SimpleNamespace(
                provider=response.provider, model=response.model, text=12345
            )

    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(_BadTextProvider()).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"


def test_live_available_proposal_on_unavailable_context_rejected() -> None:
    """An available proposal cannot be certified against an unavailable
    canonical context."""
    from rop.services.llm_request_serialization import (
        compute_fingerprint,
        serialize_context,
    )

    ctx = _valid_context()
    unavailable_ctx = dict(ctx)
    unavailable_ctx["available"] = False
    unavailable_ctx["context_consistent"] = False
    proposal = {
        "session_id": str(ctx["session_id"]),
        "context_fingerprint": compute_fingerprint(serialize_context(unavailable_ctx)),
        "provider": "fake",
        "model": "fake-model",
        "candidate_assessments": [],
        "available": True,
        "proposal_consistent": True,
        "llm_reasoning_source": "LLM_REASONING_TASK_057",
    }
    audit = LLMReasoningAuditService.build(proposal=proposal, context=unavailable_ctx)

    assert audit["proposal_consistent"] is False
    assert "availability_mismatch" in audit["consistency_issues"]


def test_live_hostile_response_properties_become_invalid() -> None:
    """A provider object whose metadata properties raise on access must
    become MODEL_OUTPUT_INVALID, never a leaked raw exception."""

    class _HostileResponse:
        @property
        def provider(self) -> str:
            raise RuntimeError("property exploded")

        @property
        def model(self) -> str:
            raise RuntimeError("property exploded")

        @property
        def text(self) -> str:
            raise RuntimeError("property exploded")

    hostile = _HostileResponse()
    issues = ProviderFailureBoundary.validate_provider_metadata(hostile, "x" * 64)
    assert any("provider field is empty" in i for i in issues)
    assert any("model field is empty" in i for i in issues)
    assert any("response text is not a string" in i for i in issues)

    ctx = _valid_context()

    class _HostileProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            return _HostileResponse()

    with pytest.raises(LLMReasoningContractError) as ei:
        _service_with(_HostileProvider()).build(context=ctx)
    assert ei.value.invariant == "MODEL_OUTPUT_INVALID"

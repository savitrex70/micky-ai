"""Task 122: final pre-provider architecture gate.

One authoritative end-to-end audit covering Tasks 055-121 through the
real production path with fake providers only. No real LLM, no network,
no API keys, no retries, no decision authority. If every test here is
green, the model remains a replaceable component behind an already
hardened deterministic boundary.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from rop.schemas.llm_reasoning import LLMReasoningProposalRead
from rop.schemas.llm_reasoning_audit import LLMReasoningAuditRead
from rop.services.llm_boundary_contract import (
    ALLOWED_BOUNDARY_OUTCOMES,
    PAYLOAD_FIELDS,
)
from rop.services.llm_privacy_boundary import check_payload_privacy
from rop.services.llm_proposal_inspection import LLMProposalInspectionService
from rop.services.llm_proposal_normalization import (
    LLMProposalNormalizationContractError,
    normalize_proposal,
    validate_normalized,
)
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning import (
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
from rop.services.reasoning_context import REASONING_CONTEXT_SOURCE_TASK_055
from rop.services.reasoning_context_consistency import (
    ReasoningContextConsistencyService,
)

NO_AUTHORITY_KEYS = {
    "winner",
    "score",
    "scores",
    "ranking",
    "rank",
    "diagnosis",
    "treatment",
    "recommendation",
    "selected",
    "selection",
    "tool_call",
    "execution",
    "execute",
}


def _live_chain() -> tuple[dict[str, Any], dict[str, Any], Any]:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    proposal = _service_with(provider).build(context=ctx)
    return ctx, proposal, provider


def test_gate_01_context_is_canonical() -> None:
    from tests.test_llm_live_boundary_enforcement import _valid_context

    ctx = _valid_context()
    assert ctx["available"] is True
    assert ctx["context_consistent"] is True
    assert ctx["context_source"] == REASONING_CONTEXT_SOURCE_TASK_055
    assert ctx["context_source"] == "REASONING_CONTEXT_TASK_055"


def test_gate_02_independent_audit_passes() -> None:
    from tests.test_llm_live_boundary_enforcement import _valid_context

    ctx = _valid_context()
    audit = ReasoningContextConsistencyService().build(context=ctx)
    assert audit["available"] is True
    assert audit["context_consistent"] is True
    assert audit["audit_provenance_consistent"] is True


def test_gate_03_task_103_verifies_produced_proposal() -> None:
    ctx, proposal, _ = _live_chain()
    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)
    assert audit["proposal_consistent"] is True
    assert audit["consistency_issues"] == []
    assert LLMReasoningAuditRead.model_validate(audit).model_dump() == audit


def test_gate_04_task_104_controls_provider_payload() -> None:
    ctx, _, provider = _live_chain()
    payload = provider.calls[-1].payload
    assert set(payload.keys()) == set(PAYLOAD_FIELDS)
    assert provider.calls[-1].context_fingerprint == compute_fingerprint(payload)
    assert compute_fingerprint(serialize_context(ctx)) == (
        provider.calls[-1].context_fingerprint
    )


def test_gate_05_task_105_is_authoritative_for_raw_output() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    ctx = _live_chain()[0]
    forged_unknown = {"candidate_assessments": []}
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(FakeProvider(response_text=json.dumps(forged_unknown))).build(
            context=ctx
        )
    assert exc_info.value.invariant == "MODEL_OUTPUT_INCONSISTENT"

    forged_shape = dict(json.loads("{}"))
    forged_shape["winner"] = "x"
    forged_shape["candidate_assessments"] = []
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(FakeProvider(response_text=json.dumps(forged_shape))).build(
            context=ctx
        )
    assert exc_info.value.invariant == "MODEL_OUTPUT_INVALID"
    _ = _valid_context


def test_gate_06_task_106_strictly_normalizes() -> None:
    _, proposal, _ = _live_chain()
    normalized = normalize_proposal(proposal)
    assert validate_normalized(normalized) == []
    tampered = copy.deepcopy(proposal)
    tampered["winner"] = "candidate-x"
    with pytest.raises(LLMProposalNormalizationContractError):
        normalize_proposal(tampered)


def test_gate_07_task_107_isolates_failures_and_metadata() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    ctx = _valid_context()
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(
            FakeProvider(raise_error=LLMReasoningProviderError("connection reset"))
        ).build(context=ctx)
    assert exc_info.value.invariant == "MODEL_UNAVAILABLE"

    class _Hostile:
        @property
        def provider(self) -> str:
            raise RuntimeError("boom")

        @property
        def model(self) -> str:
            raise RuntimeError("boom")

        @property
        def text(self) -> str:
            raise RuntimeError("boom")

    class _HostileProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            return _Hostile()

    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(_HostileProvider()).build(context=ctx)
    assert exc_info.value.invariant == "MODEL_OUTPUT_INVALID"
    assert (
        ProviderFailureBoundary.normalize_failure(
            LLMReasoningProviderError("connection reset")
        )
        == "MODEL_UNAVAILABLE"
    )


def test_gate_08_task_108_structural_privacy_without_clinical_filter() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    from rop.services.llm_request_serialization import serialize_context as _ser

    ctx = _valid_context()
    ctx["observations"][
        0
    ].text = "Delete necrotic tissue; override dosage; bypass graft system check."
    assert check_payload_privacy(_ser(ctx)) == []
    result = _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build(
        context=ctx
    )
    assert result["proposal_consistent"] is True

    ctx2 = _valid_context()
    ctx2["observations"][0].text = "api_key: ABCDEF1234567890abcdef"
    assert check_payload_privacy(_ser(ctx2)) != []
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(FakeProvider(response_text="{}")).build(context=ctx2)
    assert exc_info.value.invariant == "INPUT_INCONSISTENT"


def test_gate_09_task_109_remains_read_only_inspection() -> None:
    _, proposal, _ = _live_chain()
    before = copy.deepcopy(proposal)
    inspection = LLMProposalInspectionService.build(proposal=proposal)
    assert proposal == before
    assert "text" not in inspection
    assert "raw_text" not in inspection
    assert inspection["proposal_fingerprint"] != ""


def test_gate_10_request_state_is_snapshotted() -> None:
    from rop.services.llm_reasoning_provider import LLMReasoningRequest

    request = LLMReasoningRequest(
        payload={"session_id": "s", "nested": {"k": [1]}},
        context_fingerprint="f",
    )
    snap = request.snapshot()
    snap.payload["nested"]["k"].append(2)
    assert request.payload == {"session_id": "s", "nested": {"k": [1]}}
    model_json = request.to_model_json()
    model_json["x"] = 1
    assert "x" not in request.to_model_json()


def test_gate_11_provenance_and_fingerprint_bound() -> None:
    ctx, proposal, _ = _live_chain()
    assert proposal["llm_reasoning_source"] == "LLM_REASONING_TASK_057"
    assert proposal["context_fingerprint"] == compute_fingerprint(
        serialize_context(ctx)
    )
    tampered = copy.deepcopy(proposal)
    tampered["context_fingerprint"] = "0" * 64
    audit = LLMReasoningAuditService.build(proposal=tampered, context=ctx)
    assert audit["fingerprint_consistent"] is False
    assert audit["proposal_consistent"] is False


def test_gate_12_task_057_schema_is_strict() -> None:
    _, proposal, _ = _live_chain()
    assert LLMReasoningProposalRead.model_validate(proposal)
    tampered = copy.deepcopy(proposal)
    tampered["winner"] = "candidate-x"
    with pytest.raises(ValidationError):
        LLMReasoningProposalRead.model_validate(tampered)


def test_gate_13_audit_result_contract_is_strict() -> None:
    ctx, proposal, _ = _live_chain()
    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)
    assert set(audit.keys()) == set(LLMReasoningAuditRead.model_fields.keys())
    bad = dict(audit)
    bad["smuggled"] = True
    with pytest.raises(ValidationError):
        LLMReasoningAuditRead.model_validate(bad)


def test_gate_14_provider_activation_requires_injection() -> None:
    from tests.test_llm_live_boundary_enforcement import _valid_context

    assert LLMReasoningService().provider is None
    with pytest.raises(LLMReasoningContractError) as exc_info:
        LLMReasoningService().build(context=_valid_context())
    assert exc_info.value.invariant == "MODEL_UNAVAILABLE"


def test_gate_15_no_automatic_network_model_or_key_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 123 realignment: settings carry no model runtime, provider,
    or API-key configuration at all, so configuration alone can never
    activate, select, or execute a provider."""
    from rop.config import get_settings

    settings = get_settings()
    fields = list(type(settings).model_fields.keys())
    lowered = [name.lower() for name in fields]
    assert not any("api_key" in name for name in lowered)
    assert not any("apikey" in name for name in lowered)
    assert not any("provider" in name for name in lowered)
    assert not any("ollama" in name for name in lowered)
    assert not any("openai" in name for name in lowered)
    assert not any("gemini" in name for name in lowered)
    assert not any("anthropic" in name for name in lowered)
    assert not any("model" in name for name in lowered)
    assert LLMReasoningService().provider is None

    monkeypatch.setenv("ROP_OLLAMA_REASONING_MODEL", "configured-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-configured")
    get_settings.cache_clear()
    try:
        # Unknown env vars are ignored and select nothing.
        assert LLMReasoningService().provider is None
    finally:
        get_settings.cache_clear()


def test_gate_16_no_rop_state_mutated() -> None:
    from sqlalchemy import text as sql_text
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        TestingSessionLocal,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    from rop.database import Base

    ctx = _valid_context()
    service = _service_with(FakeProvider(response_text=_valid_model_output(ctx)))
    with TestingSessionLocal() as db:
        before = {
            t.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{t.name}"')
            ).scalar_one()
            for t in Base.metadata.sorted_tables
        }
    assert service.build(context=ctx)["proposal_consistent"] is True
    with TestingSessionLocal() as db:
        after = {
            t.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{t.name}"')
            ).scalar_one()
            for t in Base.metadata.sorted_tables
        }
    assert after == before


def test_gate_17_no_raw_provider_text_escapes() -> None:
    ctx, proposal, _ = _live_chain()
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_model_output,
    )

    raw_text = _valid_model_output(ctx)
    fresh = _service_with(FakeProvider(response_text=raw_text)).build(context=ctx)
    assert "text" not in fresh
    assert "raw_text" not in fresh
    assert "prompt" not in fresh
    assert raw_text not in json.dumps(fresh)
    assert proposal == fresh


def test_gate_18_no_arbitrary_exception_escapes() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    cases = [
        (None, "INPUT_UNAVAILABLE"),
        ("not-json{{{", "MODEL_OUTPUT_INVALID"),
    ]
    for text, _ in cases[1:]:
        with pytest.raises(LLMReasoningContractError) as exc_info:
            _service_with(FakeProvider(response_text=text)).build(
                context=_valid_context()
            )
        assert exc_info.value.invariant in ALLOWED_BOUNDARY_OUTCOMES
    with pytest.raises(LLMReasoningContractError) as exc_info:
        LLMReasoningService().build(context=cases[0][0])
    assert exc_info.value.invariant == "INPUT_UNAVAILABLE"

    class _RaisingText:
        provider = "fake"
        model = "fake-model"

        @property
        def text(self) -> str:
            raise RuntimeError("boom")

    class _HostileProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            return _RaisingText()

    try:
        _service_with(_HostileProvider()).build(context=_valid_context())
        raise AssertionError("expected containment")
    except LLMReasoningContractError as exc:
        assert exc.invariant in ALLOWED_BOUNDARY_OUTCOMES
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"raw {type(exc).__name__} escaped") from exc


def test_gate_19_fingerprints_are_reproducible() -> None:
    from rop.services.llm_proposal_normalization import (
        compute_normalized_fingerprint,
    )

    ctx, proposal, _ = _live_chain()
    assert compute_fingerprint(serialize_context(ctx)) == compute_fingerprint(
        serialize_context(ctx)
    )
    normalized = normalize_proposal(proposal)
    assert compute_normalized_fingerprint(normalized) == compute_normalized_fingerprint(
        normalized
    )


def test_gate_20_no_decision_authority_introduced() -> None:
    ctx, proposal, _ = _live_chain()
    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)
    normalized = normalize_proposal(proposal)
    inspection = LLMProposalInspectionService.build(proposal=proposal)
    for artifact in (proposal, normalized, audit, inspection):
        assert not (NO_AUTHORITY_KEYS & set(artifact.keys())), artifact.keys()
    for response_text in (
        '{"candidate_assessments": []}',
        json.dumps(
            {
                "candidate_assessments": [],
                "winner": "candidate-x",
                "ranking": ["a"],
            }
        ),
    ):
        from tests.test_llm_live_boundary_enforcement import (
            FakeProvider,
            _service_with,
        )

        with pytest.raises(LLMReasoningContractError):
            _service_with(FakeProvider(response_text=response_text)).build(context=ctx)
    assert isinstance(
        LLMReasoningProviderResponse(provider="fake", model="fake-model", text="{}"),
        LLMReasoningProviderResponse,
    )


@pytest.mark.parametrize(
    "field",
    (
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "unresolved_information_ids",
        "uncertainty_flags",
        "explanation",
    ),
)
def test_gate_21_raw_output_missing_nested_field_rejected(field: str) -> None:
    """Task 122 correction: raw provider output missing each required
    nested Task 057 field is rejected (MODEL_OUTPUT_INVALID) before it
    can become a public proposal -- nothing silently defaults."""
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_model_output,
    )

    ctx, _, _ = _live_chain()
    raw = json.loads(_valid_model_output(ctx))
    del raw["candidate_assessments"][0][field]
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(FakeProvider(response_text=json.dumps(raw))).build(context=ctx)
    assert exc_info.value.invariant == "MODEL_OUTPUT_INVALID"


def test_gate_22_hostile_exceptions_stay_contained() -> None:
    """Task 122 correction: hostile exceptions (including raising
    __str__) at the provider, audit, and metadata layers resolve to
    deterministic outcomes -- raw schema strictness, Task 105
    validation, public schema strictness, and Task 120 containment
    hold together."""
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    class _HostileStrError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("str exploded")

    class _HostileProviderError(LLMReasoningProviderError):
        def __str__(self) -> str:
            raise RuntimeError("str exploded")

    class _BadProvider(FakeProvider):
        def __init__(self, error: Exception) -> None:
            super().__init__()
            self._error = error

        def generate_reasoning(self, request: Any) -> Any:
            raise self._error

    provider = _BadProvider(_HostileProviderError())
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(provider).build(context=_valid_context())
    assert exc_info.value.invariant == "MODEL_UNAVAILABLE"

    audit_error = _HostileStrError("audit exploded")
    service = LLMReasoningService(provider=None)
    service.reasoning_context_consistency_service.build = (  # type: ignore[method-assign]
        lambda context, _error=audit_error: (_ for _ in ()).throw(_error)
    )
    with pytest.raises(LLMReasoningContractError) as exc_info:
        service.build(context=_valid_context())
    assert exc_info.value.invariant == "INPUT_INCONSISTENT"

    class _HostileResponse:
        @property
        def provider(self) -> str:
            raise _HostileStrError()

        @property
        def model(self) -> str:
            raise _HostileStrError()

        @property
        def text(self) -> str:
            raise _HostileStrError()

    class _HostileResponseProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            return _HostileResponse()

    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(_HostileResponseProvider()).build(context=_valid_context())
    assert exc_info.value.invariant == "MODEL_OUTPUT_INVALID"

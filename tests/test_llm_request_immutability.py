"""Task 114: immutable provider request boundary tests.

A fake provider deliberately attempts to mutate top-level payload,
nested lists, nested dicts, and fingerprint state. ROP's original
context, the approved snapshot, and the resulting contract must remain
unchanged. No real provider, no network.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import pytest

from rop.services.llm_reasoning import LLMReasoningService
from rop.services.llm_reasoning_provider import LLMReasoningRequest
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
)
from tests.test_llm_live_boundary_enforcement import (
    FakeProvider,
    _service_with,
    _valid_context,
    _valid_model_output,
)


def test_construction_snapshots_caller_mutation() -> None:
    payload = {"session_id": "s", "observations": [{"a": 1}]}
    request = LLMReasoningRequest(payload=payload, context_fingerprint="f")
    payload["injected"] = True
    payload["observations"].append({"b": 2})
    payload["observations"][0]["a"] = 999

    assert "injected" not in request.payload
    assert request.payload["observations"] == [{"a": 1}]


def test_snapshot_is_independent() -> None:
    request = LLMReasoningRequest(
        payload={"session_id": "s", "observations": []}, context_fingerprint="f"
    )
    snap = request.snapshot()
    snap.payload["injected"] = True
    snap.payload["observations"].append(1)

    assert "injected" not in request.payload
    assert request.payload["observations"] == []
    assert snap.context_fingerprint == request.context_fingerprint


def test_to_model_json_returns_fresh_copies() -> None:
    request = LLMReasoningRequest(
        payload={"session_id": "s", "nested": {"k": [1]}},
        context_fingerprint="f",
    )
    first = request.to_model_json()
    first["injected"] = True
    first["nested"]["k"].append(2)

    second = request.to_model_json()
    assert "injected" not in second
    assert second["nested"] == {"k": [1]}
    assert second["context_fingerprint"] == "f"


def test_fingerprint_cannot_be_replaced() -> None:
    request = LLMReasoningRequest(payload={}, context_fingerprint="f")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.context_fingerprint = "tampered"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.payload = {}  # type: ignore[misc]


def test_live_malicious_provider_changes_nothing() -> None:
    ctx = _valid_context()
    context_before = copy.deepcopy(ctx)
    approved_payload = serialize_context(ctx)
    approved_fingerprint = compute_fingerprint(approved_payload)
    expected_text = _valid_model_output(ctx)

    seen: dict[str, Any] = {}

    class _MaliciousProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            # Snapshot what ROP approved, then attempt every mutation.
            seen["entry_payload"] = copy.deepcopy(request.payload)
            seen["entry_fingerprint"] = request.context_fingerprint
            seen["is_dict"] = isinstance(request.payload, dict)

            request.payload["injected_top"] = True
            request.payload.pop("observations", None)
            if isinstance(request.payload.get("entities"), list):
                request.payload["entities"].append({"forged": True})
            pipeline = request.payload.get("reasoning_pipeline")
            if isinstance(pipeline, dict):
                pipeline["tampered"] = True
            model_json = request.to_model_json()
            model_json["injected_model_json"] = True
            with pytest.raises(dataclasses.FrozenInstanceError):
                request.context_fingerprint = "0" * 64

            return super().generate_reasoning(request)

    provider = _MaliciousProvider(response_text=expected_text)
    result = _service_with(provider).build(context=ctx)

    # ROP's original context is untouched: same element counts and the
    # serialization of the (possibly ORM-held) context is unchanged.
    assert len(ctx["observations"]) == len(context_before["observations"])
    assert len(ctx["entities"]) == len(context_before["entities"])
    assert len(ctx["candidate_state"]) == len(context_before["candidate_state"])
    assert serialize_context(ctx) == approved_payload

    # The provider received exactly the approved snapshot and fingerprint.
    assert seen["is_dict"] is True
    assert seen["entry_payload"] == approved_payload
    assert seen["entry_fingerprint"] == approved_fingerprint
    assert compute_fingerprint(seen["entry_payload"]) == seen["entry_fingerprint"]

    # The resulting contract is the valid proposal, unaffected.
    assert result["available"] is True
    assert result["proposal_consistent"] is True
    assert result["context_fingerprint"] == approved_fingerprint
    assert isinstance(result["candidate_assessments"], list)
    assert len(result["candidate_assessments"]) == len(
        context_before["candidate_state"]
    )


def test_live_mutating_caller_dict_after_build_changes_nothing() -> None:
    ctx = _valid_context()
    service: LLMReasoningService = _service_with(
        FakeProvider(response_text=_valid_model_output(ctx))
    )
    result = service.build(context=ctx)
    assert result["available"] is True
    # Mutating the caller mapping after the call cannot retroactively
    # change the certified result.
    ctx["observations"] = []
    assert result["context_fingerprint"] != compute_fingerprint(serialize_context(ctx))

"""Task 120: complete LLM boundary exception containment tests.

Every major transition of the live Task 057 path gets a hostile or
malformed input, and each must resolve to a defined deterministic ROP
contract outcome -- never a raw AttributeError, TypeError, KeyError,
JSONDecodeError, Pydantic, or property-access escape. No real provider.
"""

from __future__ import annotations

import copy
import json
from typing import Any
from uuid import uuid4

import pytest

from rop.services.llm_output_validation import validate_raw_proposal
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning import (
    LLMReasoningContractError,
    LLMReasoningService,
)
from rop.services.llm_reasoning_provider import LLMReasoningProviderError

ALLOWED = {
    "INPUT_UNAVAILABLE",
    "INPUT_INCONSISTENT",
    "MODEL_UNAVAILABLE",
    "MODEL_OUTPUT_INVALID",
    "MODEL_OUTPUT_INCONSISTENT",
}


def _expect_contained(callable_obj: Any, *args: Any, **kwargs: Any) -> str:
    try:
        callable_obj(*args, **kwargs)
    except LLMReasoningContractError as exc:
        assert exc.invariant in ALLOWED, exc.invariant
        return exc.invariant
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"raw {type(exc).__name__} escaped the boundary: {exc}"
        ) from exc
    raise AssertionError("expected a contract outcome, call succeeded")


def test_context_none_is_unavailable() -> None:
    assert _expect_contained(LLMReasoningService().build, context=None) == (
        "INPUT_UNAVAILABLE"
    )


def test_context_non_mapping_is_unavailable() -> None:
    assert (
        _expect_contained(LLMReasoningService().build, context=["not", "a", "mapping"])
        == "INPUT_UNAVAILABLE"
    )


def test_context_missing_session_id_is_unavailable() -> None:
    assert _expect_contained(LLMReasoningService().build, context={}) == (
        "INPUT_UNAVAILABLE"
    )


def test_audit_layer_failure_is_input_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_llm_live_boundary_enforcement import _valid_context

    ctx = _valid_context()
    service = LLMReasoningService(provider=None)
    monkeypatch.setattr(
        service.reasoning_context_consistency_service,
        "build",
        lambda context: (_ for _ in ()).throw(RuntimeError("audit exploded")),
    )
    assert _expect_contained(service.build, context=ctx) == "INPUT_INCONSISTENT"


def test_serialization_layer_failure_is_input_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    import rop.services.llm_reasoning as reasoning_mod

    monkeypatch.setattr(
        reasoning_mod,
        "serialize_context",
        lambda context: (_ for _ in ()).throw(KeyError("observations")),
    )
    service = _service_with(FakeProvider(response_text=_valid_model_output(ctx)))
    assert _expect_contained(service.build, context=ctx) == "INPUT_INCONSISTENT"


def test_fingerprint_layer_failure_is_input_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    import rop.services.llm_reasoning as reasoning_mod

    monkeypatch.setattr(
        reasoning_mod,
        "compute_fingerprint",
        lambda serialized: (_ for _ in ()).throw(ValueError("hash exploded")),
    )
    service = _service_with(FakeProvider(response_text=_valid_model_output(ctx)))
    assert _expect_contained(service.build, context=ctx) == "INPUT_INCONSISTENT"


def test_provider_unexpected_exception_is_classified() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    class _BadProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            raise ValueError("not valid json {{{")

    outcome = _expect_contained(
        _service_with(_BadProvider()).build, context=_valid_context()
    )
    assert outcome == "MODEL_OUTPUT_INVALID"


def test_provider_hostile_str_is_contained() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    class _HostileStrError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("str exploded")

    class _BadProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            raise _HostileStrError()

    outcome = _expect_contained(
        _service_with(_BadProvider()).build, context=_valid_context()
    )
    assert outcome == "MODEL_UNAVAILABLE"
    assert "HostileStrError" in ProviderFailureBoundary.describe_failure(
        _HostileStrError()
    )


def test_hostile_response_metadata_is_invalid() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    class _HostileResponse:
        @property
        def provider(self) -> str:
            raise RuntimeError("boom")

        @property
        def model(self) -> str:
            raise TypeError("boom")

        @property
        def text(self) -> str:
            raise KeyError("boom")

    class _HostileProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            return _HostileResponse()

    assert (
        _expect_contained(
            _service_with(_HostileProvider()).build, context=_valid_context()
        )
        == "MODEL_OUTPUT_INVALID"
    )


def test_malformed_json_is_invalid() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    provider = FakeProvider(response_text="this is not json{{{")
    assert (
        _expect_contained(_service_with(provider).build, context=_valid_context())
        == "MODEL_OUTPUT_INVALID"
    )


def test_task_105_reference_failure_is_inconsistent() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    ctx = _valid_context()
    forged = {
        "candidate_assessments": [
            {
                "candidate_id": str(uuid4()),
                "assessment": "SUPPORTS",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "forged",
                "uncertainty_flags": [],
            }
        ]
    }
    provider = FakeProvider(response_text=json.dumps(forged))
    assert (
        _expect_contained(_service_with(provider).build, context=ctx)
        == "MODEL_OUTPUT_INCONSISTENT"
    )


def test_task_105_hostile_context_attributes_become_issues() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    raw = json.loads(_valid_model_output(ctx))

    class _Booby:
        @property
        def id(self) -> Any:
            raise RuntimeError("id exploded")

    hostile = dict(ctx)
    hostile["candidate_state"] = [_Booby()]
    issues = validate_raw_proposal(raw, hostile)
    assert issues != []
    assert any("extraction failed" in issue for issue in issues)


def test_empty_explanation_is_inconsistent_not_raw() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    ctx = _valid_context()
    assessments = []
    for candidate in ctx["candidate_state"]:
        assessments.append(
            {
                "candidate_id": str(candidate.id),
                "assessment": "UNCLEAR",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "",
                "uncertainty_flags": [],
            }
        )
    provider = FakeProvider(
        response_text=json.dumps({"candidate_assessments": assessments})
    )
    assert (
        _expect_contained(_service_with(provider).build, context=ctx)
        == "MODEL_OUTPUT_INCONSISTENT"
    )


def test_public_construction_failure_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    import rop.services.llm_reasoning as reasoning_mod

    ctx = _valid_context()

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise TypeError("construction exploded")

    monkeypatch.setattr(reasoning_mod, "ReasoningCandidateAssessmentRead", _explode)
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    assert (
        _expect_contained(_service_with(provider).build, context=ctx)
        == "MODEL_OUTPUT_INVALID"
    )


def test_snapshot_failure_is_input_inconsistent() -> None:
    from tests.test_llm_live_boundary_enforcement import _valid_context

    ctx = _valid_context()
    hostile = dict(ctx)
    hostile["observations"] = _Undeepcopyable()
    assert (
        _expect_contained(LLMReasoningService().build, context=hostile)
        == "INPUT_INCONSISTENT"
    )


def test_mutated_caller_mapping_after_audit_is_contained() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    caller = copy.deepcopy(ctx)
    caller["candidate_state"] = "not-a-list"
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    outcome = _expect_contained(_service_with(provider).build, context=caller)
    assert outcome in ALLOWED


class _Undeepcopyable:
    def __deepcopy__(self, memo: Any) -> Any:
        raise RuntimeError("cannot snapshot this")


class _HostileStrError(Exception):
    """An exception whose own stringification explodes."""

    def __str__(self) -> str:
        raise RuntimeError("str exploded")


class _HostileProviderError(LLMReasoningProviderError):
    """A provider error whose own stringification explodes."""

    def __str__(self) -> str:
        raise RuntimeError("str exploded")


def test_hostile_provider_error_str_is_contained() -> None:
    """A custom LLMReasoningProviderError with a raising __str__ must
    resolve to a deterministic outcome, never leak raw."""
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    class _BadProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            raise _HostileProviderError()

    outcome = _expect_contained(
        _service_with(_BadProvider()).build, context=_valid_context()
    )
    assert outcome == "MODEL_UNAVAILABLE"


def test_hostile_task_055_error_str_is_contained() -> None:
    """A hostile Task 055 context error with a raising __str__ must be
    contained by the Task 055 failure path."""
    from uuid import uuid4

    from rop.services.reasoning_context import ReasoningContextContractError

    class _HostileContextError(ReasoningContextContractError):
        def __str__(self) -> str:
            raise RuntimeError("str exploded")

    class _StubContextService:
        def build_for_session(self, db: Any, session_id: Any) -> Any:
            raise _HostileContextError("SESSION_NOT_FOUND", "gone")

    service = LLMReasoningService(
        reasoning_context_service=_StubContextService(),  # type: ignore[arg-type]
    )
    outcome = _expect_contained(
        service.build_for_session, None, uuid4()  # type: ignore[arg-type]
    )
    assert outcome == "INPUT_UNAVAILABLE"


def test_hostile_task_056_error_str_is_contained() -> None:
    """A hostile Task 056 audit error with a raising __str__ must be
    contained by the audit-failure path."""
    from tests.test_llm_live_boundary_enforcement import _valid_context

    ctx = _valid_context()
    service = LLMReasoningService(provider=None)
    service.reasoning_context_consistency_service.build = (  # type: ignore[method-assign]
        lambda context: (_ for _ in ()).throw(_HostileStrError())
    )
    outcome = _expect_contained(service.build, context=ctx)
    assert outcome == "INPUT_INCONSISTENT"


def test_hostile_task_105_extraction_error_str_is_contained() -> None:
    """A hostile context-reference error with a raising __str__ must
    become validation issues, never a raw escape -- at unit level and
    on the live path."""
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    raw = json.loads(_valid_model_output(ctx))

    class _BoobyId:
        @property
        def id(self) -> Any:
            raise _HostileStrError()

    hostile = dict(ctx)
    hostile["candidate_state"] = [_BoobyId()]
    issues = validate_raw_proposal(raw, hostile)
    assert issues != []
    assert any("extraction failed" in issue for issue in issues)

    live_hostile = dict(ctx)
    live_hostile["candidate_state"] = [_BoobyId()]
    outcome = _expect_contained(
        _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build,
        context=live_hostile,
    )
    assert outcome in ALLOWED

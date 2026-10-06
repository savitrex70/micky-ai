"""Task 157: explicit Stage 7 provider dispatch service.

Hands one approved Task 155 request package -- audited consistent by
Task 156 -- to an explicitly injected generic LLMReasoningProvider.
There is no default provider, no discovery, no registry, no
environment or configuration lookup, and no startup selection: without
an explicit provider the dispatch fails closed with the canonical Task
057 MODEL_UNAVAILABLE outcome. The provider receives a defensive
snapshot of the request, so provider-side mutation cannot reach
ROP-owned state.

The raw provider response is never interpreted, parsed, or validated
here; it travels next to the strict projection and is only ever read by
the Task 158 response boundary. No provider is contacted while the
package or its audit is blocked, inconsistent, or unreadable, and no
provider exception ever escapes the boundary: every failure is
classified through the canonical Task 107 normalizer into the Task 057
outcome taxonomy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_dispatch import (
    ReasoningRunStage7DispatchRead,
)
from rop.services.llm_boundary_contract import (
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_INPUT_UNAVAILABLE,
    OUTCOME_MODEL_UNAVAILABLE,
)
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning_provider import (
    LLMReasoningProvider,
    LLMReasoningRequest,
)

REASONING_RUN_STAGE_7_DISPATCH_SOURCE_TASK_157 = (
    "REASONING_RUN_STAGE_7_DISPATCH_TASK_157"
)


class ReasoningRunStage7DispatchContractError(Exception):
    """Task 157: the dispatch result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7DispatchService:
    """Deterministic explicit dispatch of one approved request package."""

    def __init__(self, provider: LLMReasoningProvider | None = None) -> None:
        self.provider = provider

    def dispatch(
        self,
        *,
        request: Mapping[str, Any] | None,
        request_audit: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Hand one approved request package to the injected provider.

        Material gates run first: a blocked package is ``BLOCKED``; an
        unreadable audit, a blocked package, or an unconsumable payload
        is ``UNAVAILABLE`` with the canonical input outcome; an
        inconsistent audit is ``BLOCKED``. No provider is contacted on
        any of those paths. The provider gate runs last: an absent
        provider fails closed with MODEL_UNAVAILABLE, a raising provider
        is classified through the canonical Task 107 normalizer, and
        only a returned response produces ``DISPATCHED``.

        The returned mapping carries the strict projection plus
        ``provider_response``: the untouched, unvalidated provider
        object, or ``None`` when no provider ran. That value is untrusted
        provider surface, never part of the projection, and must only be
        handed to the Task 158 response boundary.
        """
        result: dict[str, Any] = {
            "dispatch_status": "UNAVAILABLE",
            "available": False,
            "session_id": "",
            "request_status": None,
            "request_audit_status": None,
            "request_fingerprint": None,
            "outcome": OUTCOME_INPUT_UNAVAILABLE,
            "dispatch_source": REASONING_RUN_STAGE_7_DISPATCH_SOURCE_TASK_157,
        }

        if not isinstance(request, Mapping):
            return self._project(result, None)

        raw_session = request.get("session_id")
        if isinstance(raw_session, str):
            result["session_id"] = raw_session

        request_status = request.get("request_status")
        if request_status == "BLOCKED":
            result["request_status"] = "BLOCKED"
            result["dispatch_status"] = "BLOCKED"
            result["outcome"] = None
            return self._project(result, None)
        if request_status != "PACKAGED":
            if request_status == "UNAVAILABLE":
                result["request_status"] = "UNAVAILABLE"
            return self._project(result, None)
        result["request_status"] = "PACKAGED"

        if not isinstance(request_audit, Mapping):
            return self._project(result, None)

        audit_status = request_audit.get("request_audit_status")
        if audit_status == "INCONSISTENT":
            result["request_audit_status"] = "INCONSISTENT"
            result["dispatch_status"] = "BLOCKED"
            result["outcome"] = None
            return self._project(result, None)
        if audit_status != "CONSISTENT":
            if audit_status == "UNAVAILABLE":
                result["request_audit_status"] = "UNAVAILABLE"
            return self._project(result, None)
        result["request_audit_status"] = "CONSISTENT"

        payload = request.get("payload")
        fingerprint = request.get("context_fingerprint")
        if not isinstance(payload, Mapping) or not isinstance(fingerprint, str):
            return self._project(result, None)

        provider = self.provider
        if provider is None:
            result["outcome"] = OUTCOME_MODEL_UNAVAILABLE
            return self._project(result, None)

        try:
            handoff = LLMReasoningRequest(
                payload=dict(payload), context_fingerprint=fingerprint
            )
        except Exception:
            result["outcome"] = OUTCOME_INPUT_INCONSISTENT
            return self._project(result, None)

        try:
            provider_response = provider.generate_reasoning(handoff.snapshot())
        except Exception as exc:
            result["outcome"] = ProviderFailureBoundary.normalize_failure(exc)
            return self._project(result, None)

        result["dispatch_status"] = "DISPATCHED"
        result["available"] = True
        result["request_fingerprint"] = fingerprint
        result["outcome"] = None
        return self._project(result, provider_response)

    @staticmethod
    def _project(result: dict[str, Any], provider_response: Any) -> dict[str, Any]:
        try:
            validated = ReasoningRunStage7DispatchRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7DispatchContractError(
                "DISPATCH_RESULT_INVALID", str(exc)
            ) from exc
        return {**validated.model_dump(), "provider_response": provider_response}

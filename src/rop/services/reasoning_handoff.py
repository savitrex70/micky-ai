"""Task 057: validated reasoning handoff service.

Pure, deterministic assembly layer. Validates the supplied Task 055
context via Task 055\'s own contract and the supplied Task 056 audit
via Task 056\'s own contract, then packages both unchanged into a
single handoff result.

Nothing here reasons, decides, calls an LLM, talks to a provider,
opens a database session, or exposes an HTTP endpoint. There is no
provider abstraction and no model configuration -- the handoff is a
contract boundary, not an integration layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.schemas.reasoning_context import ReasoningContextRead
from rop.schemas.reasoning_context_consistency import (
    ReasoningContextConsistencyRead,
)
from rop.schemas.reasoning_handoff import ReasoningHandoffRead
from rop.services.reasoning_context import (
    REASONING_CONTEXT_SOURCE_TASK_055,
    ReasoningContextContractError,
    ReasoningContextService,
)
from rop.services.reasoning_context_consistency import (
    REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056,
    ReasoningContextConsistencyContractError,
    ReasoningContextConsistencyService,
)

REASONING_HANDOFF_TASK_057 = "REASONING_HANDOFF_TASK_057"
"""Fixed structural-contract identifier for Task 057 results."""

_RESULT_REQUIRED_FIELDS = (
    "available",
    "handoff_consistent",
    "session_id",
    "reasoning_context",
    "context_consistency",
    "handoff_source",
)

_RESULT_BOOLEAN_FIELDS = ("available", "handoff_consistent")


class ReasoningHandoffContractError(Exception):
    """Task 057: the supplied inputs cannot be packaged into a valid
    reasoning handoff.

    Raised only when a required input is missing, is not a mapping,
    fails its own upstream validator, or carries the wrong fixed
    source identifier. It is never raised for a normal "the underlying
    reasoning is incomplete or inconsistent" state -- a valid Task 056
    audit that reports context inconsistency is faithfully represented
    by ``handoff_consistent == False`` rather than an exception.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffService:
    """Task 057: validated reasoning handoff assembly.

    Reuses Task 055\'s and Task 056\'s own validators rather than
    re-implementing their rules, preserves both supplied structures as
    typed Pydantic models, and never mutates its inputs.
    """

    def build(
        self,
        *,
        reasoning_context: Mapping[str, Any] | None = None,
        context_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the handoff. Pure; never mutates."""
        if reasoning_context is None:
            raise ReasoningHandoffContractError(
                "MISSING_REASONING_CONTEXT",
                "reasoning_context is required",
            )
        if not isinstance(reasoning_context, Mapping):
            raise ReasoningHandoffContractError(
                "REASONING_CONTEXT_TYPE",
                "reasoning_context is not a mapping: "
                + type(reasoning_context).__name__,
            )
        if context_consistency is None:
            raise ReasoningHandoffContractError(
                "MISSING_CONTEXT_CONSISTENCY",
                "context_consistency is required",
            )
        if not isinstance(context_consistency, Mapping):
            raise ReasoningHandoffContractError(
                "CONTEXT_CONSISTENCY_TYPE",
                "context_consistency is not a mapping: "
                + type(context_consistency).__name__,
            )

        # Validate the nested Task 055 and Task 056 contracts using
        # their own validators. Contract reuse, not re-implementation.
        try:
            ReasoningContextService._validate_result(dict(reasoning_context))
        except ReasoningContextContractError as exc:
            raise ReasoningHandoffContractError(
                "INVALID_REASONING_CONTEXT",
                "Task 055 context failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningHandoffContractError(
                "INVALID_REASONING_CONTEXT",
                "Task 055 context failed its own validator: " + str(exc),
            ) from exc

        try:
            ReasoningContextConsistencyService._validate_result(
                dict(context_consistency)
            )
        except ReasoningContextConsistencyContractError as exc:
            raise ReasoningHandoffContractError(
                "INVALID_CONTEXT_CONSISTENCY",
                "Task 056 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningHandoffContractError(
                "INVALID_CONTEXT_CONSISTENCY",
                "Task 056 audit failed its own validator: " + str(exc),
            ) from exc

        # Fixed source identifiers.
        if reasoning_context.get("context_source") != REASONING_CONTEXT_SOURCE_TASK_055:
            raise ReasoningHandoffContractError(
                "INVALID_REASONING_CONTEXT_SOURCE",
                "reasoning_context is not the Task 055 identifier: "
                + repr(reasoning_context.get("context_source")),
            )
        if (
            context_consistency.get("context_consistency_source")
            != REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
        ):
            raise ReasoningHandoffContractError(
                "INVALID_CONTEXT_CONSISTENCY_SOURCE",
                "context_consistency is not the Task 056 identifier: "
                + repr(context_consistency.get("context_consistency_source")),
            )

        session_id = reasoning_context["session_id"]
        if not isinstance(session_id, UUID):
            raise ReasoningHandoffContractError(
                "INVALID_SESSION_ID",
                "reasoning_context.session_id is not a UUID: "
                + type(session_id).__name__,
            )

        # The audit establishing structural integrity must itself be
        # available and session-consistent. A legitimate audit that
        # reports the *context* as inconsistent is a different case
        # and is preserved below.
        if context_consistency.get("available") is not True:
            raise ReasoningHandoffContractError(
                "AUDIT_UNAVAILABLE",
                "context_consistency.available must be True",
            )
        if context_consistency.get("session_consistent") is not True:
            raise ReasoningHandoffContractError(
                "AUDIT_SESSION_INCONSISTENT",
                "context_consistency.session_consistent must be True",
            )

        # Typed nested projection: validate the supplied structures
        # against their own Read schemas so the handoff carries typed
        # Task 055 and Task 056 results. No .model_dump(mode="json")
        # here -- Task 057 is a core contract boundary, not an HTTP
        # serialization layer; UUIDs and datetimes must not be
        # prematurely converted to strings.
        try:
            context_typed = ReasoningContextRead.model_validate(dict(reasoning_context))
        except Exception as exc:
            raise ReasoningHandoffContractError(
                "NESTED_REASONING_CONTEXT_VALIDATION_FAILED",
                "reasoning_context could not be typed: " + str(exc),
            ) from exc
        try:
            audit_typed = ReasoningContextConsistencyRead.model_validate(
                dict(context_consistency)
            )
        except Exception as exc:
            raise ReasoningHandoffContractError(
                "NESTED_CONTEXT_CONSISTENCY_VALIDATION_FAILED",
                "context_consistency could not be typed: " + str(exc),
            ) from exc

        # The handoff is internally consistent only when the Task 056
        # audit reports the supplied context as structurally
        # consistent. Never derived from Task 055\'s own flag.
        handoff_consistent = context_consistency.get("context_consistent") is True

        result_dict: dict[str, Any] = {
            "available": True,
            "handoff_consistent": handoff_consistent,
            "session_id": session_id,
            "reasoning_context": context_typed,
            "context_consistency": audit_typed,
            "handoff_source": REASONING_HANDOFF_TASK_057,
        }
        model = ReasoningHandoffRead(**result_dict)
        final = model.model_dump()
        self._validate_result(final)
        return final

    @staticmethod
    def _validate_result(result: Mapping[str, Any]) -> None:
        """Verify the final Task 057 result contract."""
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningHandoffContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        reasoning_context = result["reasoning_context"]
        context_consistency = result["context_consistency"]
        if not isinstance(reasoning_context, Mapping):
            raise ReasoningHandoffContractError(
                "REASONING_CONTEXT_RESULT_TYPE",
                "reasoning_context is not a mapping: "
                + type(reasoning_context).__name__,
            )
        if not isinstance(context_consistency, Mapping):
            raise ReasoningHandoffContractError(
                "CONTEXT_CONSISTENCY_RESULT_TYPE",
                "context_consistency is not a mapping: "
                + type(context_consistency).__name__,
            )
        try:
            ReasoningContextService._validate_result(dict(reasoning_context))
        except Exception as exc:
            raise ReasoningHandoffContractError(
                "INVALID_REASONING_CONTEXT_RESULT",
                "nested Task 055 result failed its own validator: " + str(exc),
            ) from exc
        try:
            ReasoningContextConsistencyService._validate_result(
                dict(context_consistency)
            )
        except Exception as exc:
            raise ReasoningHandoffContractError(
                "INVALID_CONTEXT_CONSISTENCY_RESULT",
                "nested Task 056 result failed its own validator: " + str(exc),
            ) from exc
        if reasoning_context.get("context_source") != REASONING_CONTEXT_SOURCE_TASK_055:
            raise ReasoningHandoffContractError(
                "INVALID_REASONING_CONTEXT_SOURCE",
                "reasoning_context.context_source is not the Task 055 "
                "identifier: " + repr(reasoning_context.get("context_source")),
            )
        if (
            context_consistency.get("context_consistency_source")
            != REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
        ):
            raise ReasoningHandoffContractError(
                "INVALID_CONTEXT_CONSISTENCY_SOURCE",
                "context_consistency.context_consistency_source is not "
                "the Task 056 identifier: "
                + repr(context_consistency.get("context_consistency_source")),
            )
        if result["handoff_source"] != REASONING_HANDOFF_TASK_057:
            raise ReasoningHandoffContractError(
                "INVALID_HANDOFF_SOURCE",
                "handoff_source is not the Task 057 identifier: "
                + repr(result["handoff_source"]),
            )
        expected_handoff = context_consistency.get("context_consistent") is True
        if result["handoff_consistent"] != expected_handoff:
            raise ReasoningHandoffContractError(
                "HANDOFF_CONSISTENCY_MISMATCH",
                "handoff_consistent does not match "
                "context_consistency.context_consistent",
            )

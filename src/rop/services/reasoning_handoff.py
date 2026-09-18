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
    re-implementing their rules, preserves both supplied structures
    verbatim (JSON-safe projection only), and never mutates its
    inputs.
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
        # their own validators. This is contract reuse, not
        # re-implementation.
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

        # Project both nested structures into a JSON-safe form via
        # their own pydantic schemas. This is a serialization step,
        # not a rewrite: no field is dropped, reordered, or
        # reinterpreted.
        context_json = ReasoningContextRead.model_validate(
            dict(reasoning_context)
        ).model_dump(mode="json")
        audit_json = ReasoningContextConsistencyRead.model_validate(
            dict(context_consistency)
        ).model_dump(mode="json")

        # The handoff is internally consistent only when the Task 056
        # audit reports the supplied context as structurally
        # consistent. A legitimate audit that reports inconsistency is
        # preserved verbatim; it simply flips this flag.
        handoff_consistent = context_consistency.get("context_consistent") is True

        result: dict[str, Any] = {
            "available": True,
            "handoff_consistent": handoff_consistent,
            "session_id": session_id,
            "reasoning_context": context_json,
            "context_consistency": audit_json,
            "handoff_source": REASONING_HANDOFF_TASK_057,
        }
        model = ReasoningHandoffRead(**result)
        return model.model_dump(mode="json")

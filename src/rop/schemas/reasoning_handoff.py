"""Task 057: validated reasoning handoff contract.

The handoff package wraps the exact Task 055 canonical reasoning
context and the exact Task 056 consistency result in a single
inspectable, deterministic structure. It introduces no reasoning
semantics of its own, has no LLM/provider/HTTP dependencies, and is
model-neutral: the ROP core does not know or care which external
consumer eventually reads this package.

``handoff_consistent`` describes whether the package itself satisfies
the Task 057 structural contract. It never means medically correct,
diagnostically correct, decision-ready, or that the underlying
reasoning succeeded.

``handoff_source`` is a fixed structural identifier.

The nested ``reasoning_context`` and ``context_consistency`` fields
are typed Pydantic models, not generic dictionaries: the handoff
carries the canonical Task 055 and Task 056 structures with their
original Python types (UUIDs, datetimes, nested models) preserved.
JSON serialization is the API layer\'s concern, not Task 057\'s.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_context import ReasoningContextRead
from rop.schemas.reasoning_context_consistency import (
    ReasoningContextConsistencyRead,
)


class ReasoningHandoffRead(BaseModel):
    """Task 057: validated reasoning handoff package.

    ``reasoning_context`` and ``context_consistency`` are the typed
    Task 055 and Task 056 results supplied to the service. They are
    not rewritten, summarized, reordered, or reinterpreted, and their
    UUID / datetime values are preserved as Python objects.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    handoff_consistent: bool
    session_id: UUID
    reasoning_context: ReasoningContextRead
    context_consistency: ReasoningContextConsistencyRead
    handoff_source: str

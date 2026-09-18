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
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffRead(BaseModel):
    """Task 057: validated reasoning handoff package.

    ``reasoning_context`` and ``context_consistency`` are the exact
    Task 055 and Task 056 results supplied to the service, projected
    into a JSON-safe form. They are not rewritten, summarized,
    reordered, or reinterpreted.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    handoff_consistent: bool
    session_id: UUID
    reasoning_context: dict[str, Any]
    context_consistency: dict[str, Any]
    handoff_source: str

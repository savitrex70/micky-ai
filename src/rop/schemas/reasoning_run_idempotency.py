"""Task 127: deterministic reasoning-run idempotency contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunIdempotentExecutionRead(BaseModel):
    """Result of one idempotency-aware reasoning-run request.

    ``disposition`` is exactly one of ``EXECUTED_NEW`` (the workflow
    ran), ``REUSED_IDENTICAL`` (approved inputs match a known completed
    run, so the current state was recomposed read-only without
    rewriting anything), or ``STALE_CHANGED`` (inputs changed; nothing
    executed). ``result`` carries the execution-shaped outcome for the
    first two dispositions and is None for ``STALE_CHANGED``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    disposition: str
    session_id: str
    known_input_fingerprint: str | None
    current_input_fingerprint: str
    result: dict | None

"""Task 135: deterministic idempotency API consistency audit request schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReasoningRunIdempotencyAuditRequest(BaseModel):
    """Complete idempotency envelope for Task 135 consistency audit.

    Mirrors the Task 134 canonical response shape so the audit can
    validate the entire envelope structure and all fingerprint bindings.
    """

    model_config = ConfigDict(extra="forbid")

    disposition: str
    session_id: str
    known_input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: dict | None

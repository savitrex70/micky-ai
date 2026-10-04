"""Task 135: deterministic idempotency API consistency audit contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunIdempotencyConsistencyRead(BaseModel):
    """Strict result of auditing one Task 134 idempotency envelope."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    audit_consistent: bool
    session_id: str
    disposition: str | None
    consistency_issues: list[str]
    audit_source: str

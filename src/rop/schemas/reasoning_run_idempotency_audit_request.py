"""Task 135: deterministic idempotency API consistency audit request schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rop.schemas.reasoning_run_execution import ReasoningRunExecutionRead


class ReasoningRunIdempotencyAuditRequest(BaseModel):
    """Complete Task 134 idempotency envelope supplied to the Task 135 audit.

    The envelope mirrors the Task 134 canonical response exactly:
    ``disposition``, ``session_id``, the observed and known canonical
    fingerprints, and the nested execution result. The nested ``result``
    reuses the canonical Task 044 ``ReasoningRunExecutionRead`` schema --
    the strongest existing execution-result contract -- so the HTTP
    boundary structurally validates the whole envelope instead of
    accepting an arbitrary dictionary. Parseable-but-corrupted
    envelopes (wrong disposition, fingerprint binding contradictions,
    semantically inconsistent nested execution) still reach the Task
    135 audit service and are reported as consistency issues, never
    repaired. Malformed fingerprints fail request validation (HTTP
    422) and are never normalized.
    """

    model_config = ConfigDict(extra="forbid")

    disposition: str
    session_id: str
    known_input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: ReasoningRunExecutionRead | None

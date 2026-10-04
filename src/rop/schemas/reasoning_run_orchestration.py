"""Task 132: canonical deterministic reasoning-run orchestration contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunOrchestrationRead(BaseModel):
    """One controlled pass over the deterministic ROP workflow."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    orchestration_consistent: bool
    session_id: str
    input_fingerprint: str
    failure_stage: str | None
    execution: dict | None
    chain_audit: dict | None
    orchestration_source: str

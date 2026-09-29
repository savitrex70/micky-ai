"""Task 128: deterministic reasoning-run replay contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunReplayStageComparisonRead(BaseModel):
    """One compared stage: expected (recorded) vs replayed identity."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    stage_id: str
    stage_order: int
    expected_source: str
    replayed_source: str
    match: bool


class ReasoningRunReplayRead(BaseModel):
    """Strict replay result: what was recorded, what replay observed,
    and every divergence between them."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    original_run_identity: str
    original_input_fingerprint: str
    replay_input_fingerprint: str
    input_match: bool
    stage_comparison: list[ReasoningRunReplayStageComparisonRead]
    divergences: list[str]
    replay_consistent: bool
    replay_source: str

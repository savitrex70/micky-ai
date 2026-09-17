from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_pipeline import ReasoningPipelineRead


class ReasoningRunStageRead(BaseModel):
    """Task 042: one stage in the composed full ROP reasoning run.

    A deterministic descriptor of one established upstream stage's
    state. Where an upstream stage owns a fixed source identifier,
    ``stage_source`` preserves it; where a stage is a repository state
    with no formal contract source, a Task 042-owned structural
    identifier is used and documented. No decision, winner,
    recommendation, diagnosis, treatment, action, probability,
    confidence, utility, or expected-outcome field appears anywhere in
    this descriptor.
    """

    model_config = ConfigDict(from_attributes=True)

    stage_id: str
    stage_order: int
    stage_source: str
    available: bool
    consistent: bool
    complete: bool


class ReasoningRunRead(BaseModel):
    """Task 042: full ROP reasoning-run composition view.

    Bridges the session's own upstream state (observations, entities,
    missing information, template context, existing candidates) into
    the approved Task 041 reasoning pipeline, producing one coherent
    end-to-end ROP run representation. Read-only: the underlying
    candidate generation is never re-invoked from this contract, so a
    GET never mutates session state. ``reasoning_pipeline`` is the
    exact canonical output of Task 041 -- not transformed or renamed.
    ``run_source`` is a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    run_consistent: bool
    run_complete: bool
    stage_count: int
    completed_stage_count: int
    stages: list[ReasoningRunStageRead]
    candidate_count: int
    candidate_generation_available: bool
    reasoning_pipeline: ReasoningPipelineRead
    run_source: str

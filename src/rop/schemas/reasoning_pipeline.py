from pydantic import BaseModel, ConfigDict

from rop.schemas.decision_execution import DecisionExecutionRead
from rop.schemas.decision_execution_consistency import (
    DecisionExecutionConsistencyRead,
)


class ReasoningPipelineStageRead(BaseModel):
    """Task 041: one stage in the composed end-to-end reasoning pipeline.

    A deterministic descriptor of one established pipeline stage's
    output state. ``stage_source`` preserves the upstream stage's own
    fixed source identifier -- Task 041 never substitutes its own
    source here. No decision, winner, recommendation, diagnosis,
    treatment, action, probability, confidence, utility, or
    expected-outcome field appears anywhere in this stage descriptor.
    """

    model_config = ConfigDict(from_attributes=True)

    stage_id: str
    stage_order: int
    stage_source: str
    available: bool
    consistent: bool
    complete: bool


class ReasoningPipelineRead(BaseModel):
    """Task 041: composed end-to-end reasoning pipeline view.

    Packages the established decision-pipeline stages (031-040) into
    one coherent, inspectable end-to-end run. Reuses only already-
    approved service boundaries -- it introduces no new reasoning,
    re-selects nothing, changes no policy, and mutates no upstream
    output. ``final_execution`` and ``final_execution_consistency`` are
    the exact canonical outputs of Tasks 039 and 040. ``pipeline_source``
    is a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    pipeline_consistent: bool
    pipeline_complete: bool
    stage_count: int
    completed_stage_count: int
    stages: list[ReasoningPipelineStageRead]
    final_execution: DecisionExecutionRead
    final_execution_consistency: DecisionExecutionConsistencyRead
    pipeline_source: str

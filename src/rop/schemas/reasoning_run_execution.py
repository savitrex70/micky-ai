from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_run import ReasoningRunRead
from rop.schemas.reasoning_run_consistency import (
    ReasoningRunConsistencyRead,
)


class ReasoningRunExecutionStageRead(BaseModel):
    """Task 044: one orchestration step in a full reasoning-run execution.

    A deterministic descriptor of one execution stage: which step ran,
    in what order, under which Task 044-owned structural identifier,
    and whether it succeeded. Execution stages are not the same as the
    Task 042 run stages -- they describe orchestration, not reasoning
    contracts. No decision, winner, recommendation, diagnosis,
    treatment, action, probability, confidence, utility, or
    expected-outcome field appears anywhere in this descriptor.
    """

    model_config = ConfigDict(from_attributes=True)

    stage_id: str
    stage_order: int
    stage_source: str
    status: str


class ReasoningRunExecutionRead(BaseModel):
    """Task 044: full reasoning-run execution result.

    The result of running the deterministic reasoning workflow
    end-to-end by delegating to the established services in the
    correct order. ``reasoning_run`` and ``reasoning_run_consistency``
    are the exact canonical outputs of Tasks 042 and 043 -- not
    transformed or renamed. This is an orchestration contract only:
    it does not introduce new reasoning, scoring, ranking, decision
    policy, or LLM behavior. ``execution_source`` is a fixed
    structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    outcome: str
    execution_consistent: bool
    session_id: UUID
    completed_stage_count: int
    stage_count: int
    stages: list[ReasoningRunExecutionStageRead]
    reasoning_run: ReasoningRunRead
    reasoning_run_consistency: ReasoningRunConsistencyRead
    execution_source: str

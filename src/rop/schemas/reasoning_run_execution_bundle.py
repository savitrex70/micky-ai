from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_run_execution import ReasoningRunExecutionRead
from rop.schemas.reasoning_run_execution_consistency import (
    ReasoningRunExecutionConsistencyRead,
)


class ReasoningRunExecutionBundleRead(BaseModel):
    """Task 046: execution plus its independent audit, in one bundle.

    Bundles a Task 044 ``ReasoningRunExecutionRead`` with the Task 045
    ``ReasoningRunExecutionConsistencyRead`` that audits it. This is a
    composition contract only: both nested results are the exact
    canonical outputs of their owners, untouched. No decision,
    winner, recommendation, diagnosis, treatment, action, probability,
    confidence, utility, or expected-outcome field appears anywhere in
    this schema. ``bundle_source`` is a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    execution: ReasoningRunExecutionRead
    execution_consistency: ReasoningRunExecutionConsistencyRead
    bundle_source: str

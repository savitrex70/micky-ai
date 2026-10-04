from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_run_execution_bundle import (
    ReasoningRunExecutionBundleRead,
)
from rop.schemas.reasoning_run_execution_bundle_consistency import (
    ReasoningRunExecutionBundleConsistencyRead,
)


class ReasoningRunExecutionAuditPackageRead(BaseModel):
    """Task 048: fully audited reasoning-run execution package.

    Packages a Task 046 ``ReasoningRunExecutionBundleRead`` with the
    Task 047 ``ReasoningRunExecutionBundleConsistencyRead`` that audits
    it. Both nested results are the exact canonical outputs of their
    owners, untouched.

    ``package_consistent`` derives exclusively from Task 047's
    ``bundle_consistent`` -- which answers "is the Task 046 bundle
    contract internally consistent?" -- never from Task 046's own
    ``bundle_consistent``, which has a different meaning (whether the
    underlying reasoning execution was consistent).

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema. ``package_source`` is a fixed
    structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    execution_bundle: ReasoningRunExecutionBundleRead
    bundle_consistency: ReasoningRunExecutionBundleConsistencyRead
    package_source: str

"""Task 061: fully audited reasoning handoff API response package.

Packages the canonical Task 059 API response metadata and body
(``response``, a Task 057 ``ReasoningHandoffRead``) with the Task 060
audit of that response (``api_consistency``).

``package_consistent`` derives exclusively from Task 060's
``api_consistent`` -- which answers "did the API response faithfully
represent the Task 057 handoff contract?" -- never from Task 057's own
``handoff_consistent``, which answers a different question (whether
the underlying reasoning context was internally consistent).

No decision, winner, recommendation, diagnosis, treatment, action,
probability, confidence, utility, or expected-outcome field appears
anywhere in this schema. ``package_source`` is a fixed structural
identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff import ReasoningHandoffRead
from rop.schemas.reasoning_handoff_api_consistency import (
    ReasoningHandoffApiConsistencyRead,
)


class ReasoningHandoffApiAuditPackageRead(BaseModel):
    """Task 061: fully audited reasoning handoff API response package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    method: str
    path: str
    status_code: int
    response: ReasoningHandoffRead
    api_consistency: ReasoningHandoffApiConsistencyRead
    package_source: str

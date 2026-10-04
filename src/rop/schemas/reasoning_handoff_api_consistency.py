"""Task 060: independent consistency audit of a Task 059 HTTP response.

Audits whether the supplied HTTP response faithfully represents the
canonical Task 057 reasoning handoff contract. Transport metadata is
checked (method, path, status code), the response body is validated
against Task 057's own contract, and provenance binds the audit to the
exact response body it inspected.

Distinction carried over from the earlier API-consistency lineage:

  ``api_consistent`` means "does the supplied HTTP response faithfully
  represent the Task 057 handoff?" -- it is derived solely from whether
  ``consistency_issues`` is empty.

  ``nested_handoff_consistent`` means "does the response body satisfy
  Task 057's own contract?" -- this is distinct from Task 057's own
  ``handoff_consistent`` flag, which the response legitimately carries.

A perfectly faithful API response may legitimately have
``handoff_consistent = False`` (Task 056 reported the underlying
context as inconsistent). Task 060 still reports ``api_consistent =
True`` and ``nested_handoff_consistent = True`` -- because the response
is a correct representation of a valid-but-inconsistent handoff.

No decision, winner, recommendation, diagnosis, treatment, action,
probability, confidence, utility, or expected-outcome field appears
anywhere in this schema.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffApiConsistencyRead(BaseModel):
    """Task 060: audit of a Task 059 reasoning-handoff HTTP response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    api_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    session_consistent: bool
    response_shape_consistent: bool
    nested_handoff_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    api_consistency_source: str
    audited_session_id: str | None
    audited_method: str | None
    audited_path: str | None
    audited_status_code: int | None

    # Provenance: SHA-256 hex digest of the canonicalized response body
    # this audit inspected. Provenance only -- not a medical
    # correctness, reasoning-quality, or model-confidence score.
    audited_response_fingerprint: str

"""Task 076: independent audit of the Task 075 attestation API response.

Mirrors the Task 072/074 audit result contract: a self-contained verdict
made only of derived consistency flags, a deterministically ordered issue
list, and the fixed Task 076 source identifier.

The audit never embeds or rebuilds the Task 075 response it inspects; it
reuses the canonical Task 071-075 validators and reports every
disagreement -- including fingerprint-relationship mismatches between the
nested Task 073 package and the nested Task 074 audit -- as an issue
rather than silently upgrading malformed nested evidence into success.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead(BaseModel):
    """Task 076: independent audit of a Task 075 attestation response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    response_consistent: bool
    session_consistent: bool
    nested_attestation_consistent: bool
    nested_attestation_consistency_consistent: bool
    nested_package_consistent: bool
    nested_package_consistency_consistent: bool
    provenance_consistent: bool
    response_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    response_consistency_source: str

"""Task 088: independent audit of the Task 087 final-attestation response.

Mirrors the Task 076 audit result contract: a self-contained verdict
made only of derived consistency flags, a deterministically ordered issue
list, and the fixed Task 088 source identifier.

The audit never embeds or rebuilds the Task 087 response it inspects; it
reuses the canonical Task 083-087 validators and reports every
disagreement -- including fingerprint-relationship mismatches between the
nested Task 085 bundle and the nested Task 086 audit -- as an issue
rather than silently upgrading malformed nested evidence into success.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead(  # noqa: E501
    BaseModel
):
    """Task 088: independent audit of a Task 087 final-attestation response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    response_consistent: bool
    session_consistent: bool
    nested_bundle_consistent: bool
    nested_bundle_consistency_consistent: bool
    nested_package_consistent: bool
    nested_package_consistency_consistent: bool
    provenance_consistent: bool
    response_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    response_consistency_source: str

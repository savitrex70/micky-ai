"""Task 100: independent audit of the Task 099 release response.

Mirrors the Task 088 audit result contract: a self-contained verdict
made only of derived consistency flags, a deterministically ordered
issue list, and the fixed Task 100 source identifier.

The audit never embeds or rebuilds the Task 099 response it inspects;
it reuses the canonical Task 095-099 validators and reports every
disagreement -- including fingerprint-relationship mismatches between
the nested Task 097 attestation and the nested Task 098 audit, and
between the nested Task 095 bundle and the nested Task 096 audit -- as
an issue rather than silently upgrading malformed nested evidence into
success.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyRead(  # noqa: E501
    BaseModel
):
    """Task 100: independent audit of a Task 099 release response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    response_consistent: bool
    session_consistent: bool
    nested_attestation_consistent: bool
    nested_attestation_consistency_consistent: bool
    nested_bundle_consistent: bool
    nested_bundle_consistency_consistent: bool
    provenance_consistent: bool
    response_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    response_consistency_source: str

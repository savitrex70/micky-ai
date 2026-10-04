"""Task 072: fully audited attestation consistency schema."""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead(BaseModel):
    """Task 072: consistency audit of the Task 071 attestation."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    attestation_consistent: bool
    session_consistent: bool
    nested_bundle_consistent: bool
    nested_bundle_consistency_consistent: bool
    provenance_consistent: bool
    attestation_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    attestation_consistency_source: str
    audited_attestation_fingerprint: str

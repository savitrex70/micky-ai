"""Task 074: independent audit of the Task 073 attestation package."""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead(BaseModel):
    """Task 074: independent audit of a Task 073 attestation package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    nested_attestation_consistent: bool
    nested_attestation_consistency_consistent: bool
    provenance_consistent: bool
    package_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str

    # Self-authenticating provenance. Both fields are mandatory lowercase
    # 64-character SHA-256 strings and must be exactly equal.
    package_fingerprint: str
    audited_package_fingerprint: str

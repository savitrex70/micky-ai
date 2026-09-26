"""Task 084: independent audit of the Task 083 package.

Pure deterministic audit consuming a supplied Task 083 package. Validates
required fields, session identity, nested Task 081 final attestation,
nested Task 082 consistency audit, provenance/source identifiers, and both
mandatory package fingerprint fields -- independently recomputed, exactly
equal to each other, and exactly equal to the freshly recomputed expected
fingerprint with no ``or`` fallback anywhere.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead(  # noqa: E501
    BaseModel
):
    """Task 084: independent audit of a Task 083 package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    nested_final_attestation_consistent: bool
    nested_final_attestation_consistency_consistent: bool
    provenance_consistent: bool
    package_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str
    package_fingerprint: str
    audited_package_fingerprint: str

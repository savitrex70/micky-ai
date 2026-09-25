"""Task 082: independent audit of the Task 081 final attestation.

Pure deterministic audit consuming a supplied Task 081 final attestation.
Validates required fields, session identity, nested Task 079 response
bundle, nested Task 080 bundle consistency audit, provenance/source
identifiers, and both mandatory final attestation fingerprint fields --
independently recomputed, exactly equal to each other, and exactly equal
to the freshly recomputed expected fingerprint with no ``or`` fallback
anywhere. Mutation verification (recomputing the fingerprint after an
adversarial content change) is part of the test rubric; the pure audit
service itself never mutates inputs.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead(
    BaseModel
):
    """Task 082: independent audit of a Task 081 final attestation."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    final_attestation_consistent: bool
    session_consistent: bool
    nested_response_bundle_consistent: bool
    nested_response_bundle_consistency_consistent: bool
    provenance_consistent: bool
    final_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    final_attestation_consistency_source: str
    final_attestation_fingerprint: str
    audited_final_attestation_fingerprint: str

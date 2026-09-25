"""Task 080: independent audit of the Task 079 response bundle.

Pure deterministic audit consuming a supplied Task 079 bundle. Validates
required fields, session identity, nested Task 077 package, nested Task 078
consistency audit, provenance/source identifiers, and both mandatory bundle
fingerprint fields -- independently recomputed, exactly equal to each other,
and exactly equal to the freshly recomputed expected fingerprint with no
``or`` fallback anywhere.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead(
    BaseModel
):
    """Task 080: independent audit of a Task 079 response audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_consistent: bool
    nested_response_package_consistent: bool
    nested_response_package_consistency_consistent: bool
    provenance_consistent: bool
    bundle_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    bundle_consistency_source: str
    bundle_fingerprint: str
    audited_bundle_fingerprint: str

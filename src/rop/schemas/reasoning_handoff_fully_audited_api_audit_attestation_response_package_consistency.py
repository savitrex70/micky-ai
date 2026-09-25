"""Task 078: independent audit of the Task 077 response package.

Pure deterministic audit consuming a supplied Task 077 package. Validates
required fields, session identity, nested Task 075 response, nested Task 076
consistency audit, provenance/source identifiers, and both mandatory
package fingerprint fields -- independently recomputed, exactly equal to
each other, and exactly equal to the freshly recomputed expected
fingerprint with no ``or`` fallback anywhere.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyRead(
    BaseModel
):
    """Task 078: independent audit of a Task 077 response package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    nested_response_consistent: bool
    nested_response_consistency_consistent: bool
    provenance_consistent: bool
    package_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str
    package_fingerprint: str
    audited_package_fingerprint: str

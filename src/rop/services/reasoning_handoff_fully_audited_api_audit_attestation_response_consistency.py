"""Task 076: independent consistency audit of the Task 075 attestation response.

Consumes a supplied Task 075 response and independently re-derives every
consistency relationship: required fields, availability, session identity,
nested Task 071 attestation, nested Task 072 consistency, nested Task 073
package, nested Task 074 package-consistency audit, fixed source
identifiers, fingerprint relationships, and derived consistency flags.
Disagreements are reported through a deterministically ordered issue list.

This module does not execute Task 075, does not make HTTP calls, does not
access the database, does not invoke external models/providers, and never
mutates the caller's input. It reuses the canonical Task 071-075
validators and the canonical Task 073 fingerprint definition instead of
duplicating their contracts, and never replaces an independent check with
``or`` fallback logic nor silently turns malformed nested evidence into
success.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_TASK_076"  # noqa: E501

_RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "attestation_package",
    "attestation_package_consistency",
    "response_source",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "nested_package_consistent",
    "nested_package_consistency_consistent",
    "provenance_consistent",
    "response_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "response_consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "response_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "nested_package_consistent",
    "nested_package_consistency_consistent",
    "provenance_consistent",
    "response_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_RESPONSE_FIELD",
    "INVALID_RESPONSE_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_ATTESTATION_MISMATCH",
    "NESTED_ATTESTATION_CONSISTENCY_MISMATCH",
    "NESTED_PACKAGE_MISMATCH",
    "NESTED_PACKAGE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "ATTESTATION_SOURCE_MISMATCH",
    "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
    "PACKAGE_FINGERPRINT_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
    "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
    "PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
    "RESPONSE_RELATIONSHIP_MISMATCH",
    "RESPONSE_CONTRACT_MISMATCH",
)

_SOURCE_MISMATCH_ISSUES = (
    "ATTESTATION_SOURCE_MISMATCH",
    "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
)

_PROVENANCE_ISSUES = (
    "PACKAGE_FINGERPRINT_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
    "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
    "PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
)

_METADATA_ISSUES = ("MISSING_RESPONSE_FIELD", "INVALID_RESPONSE_AVAILABLE")


def _coerce_session_id(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError):
            return None
    return None


def _deep_normalize_session_ids(value: Any) -> Any:
    """Return a deep copy with every 'session_id' string coerced to UUID."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, val in value.items():
            if key == "session_id" and isinstance(val, str):
                try:
                    result[key] = UUID(val)
                    continue
                except (ValueError, TypeError):
                    pass
            result[key] = _deep_normalize_session_ids(val)
        return result
    if isinstance(value, list):
        return [_deep_normalize_session_ids(item) for item in value]
    return value


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyContractError(
    Exception
):
    """Task 076: the response consistency audit could not be completed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = (
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyContractError
)


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService:
    """Task 076: independent pure consistency audit of a Task 075 response."""

    def build(self, *, response: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Audit a Task 075 response without mutating or rebuilding it."""
        if response is None:
            raise _ContractError("MISSING_RESPONSE", "response is required")
        if not isinstance(response, Mapping):
            raise _ContractError(
                "RESPONSE_TYPE",
                "response is not a mapping: " + type(response).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        # 1. Response structure.
        for field in _RESPONSE_REQUIRED_FIELDS:
            if field not in response:
                _add("MISSING_RESPONSE_FIELD")
        if response.get("available") is not True:
            _add("INVALID_RESPONSE_AVAILABLE")

        # 2. Session identity.
        response_sid = _coerce_session_id(response.get("session_id"))
        if response_sid is None:
            _add("SESSION_ID_INVALID")

        package = response.get("attestation_package")
        package_consistency = response.get("attestation_package_consistency")

        # 3. Nested Task 073 package validity.
        package_valid = False
        if not isinstance(package, Mapping):
            _add("NESTED_PACKAGE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationPackageService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(package)
                )
                package_valid = True
            except Exception:
                _add("NESTED_PACKAGE_MISMATCH")

        # 4. Nested Task 074 package-consistency validity. The Task 074
        # result is validated on its own terms (structure, flags, issue
        # ordering); its fingerprint relationship to the nested package is
        # re-derived independently below rather than delegated, so a
        # tampered fingerprint is always surfaced as its own issue.
        package_consistency_valid = False
        if not isinstance(package_consistency, Mapping):
            _add("NESTED_PACKAGE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService._validate_result(  # noqa: E501
                    dict(package_consistency)
                )
                package_consistency_valid = True
            except Exception:
                _add("NESTED_PACKAGE_CONSISTENCY_MISMATCH")

        # 5. Explicit nested Task 071 attestation and Task 072 consistency
        # checks, independent of the Task 073 package validator.
        attestation = (
            package.get("attestation") if isinstance(package, Mapping) else None
        )
        attestation_consistency = (
            package.get("attestation_consistency")
            if isinstance(package, Mapping)
            else None
        )

        if not isinstance(attestation, Mapping):
            _add("NESTED_ATTESTATION_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(attestation)
                )
            except Exception:
                _add("NESTED_ATTESTATION_MISMATCH")

        if not isinstance(attestation_consistency, Mapping):
            _add("NESTED_ATTESTATION_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService._validate_result(  # noqa: E501
                    dict(attestation_consistency)
                )
            except Exception:
                _add("NESTED_ATTESTATION_CONSISTENCY_MISMATCH")

        # 6. Session binding: response session must equal nested package
        # session, preserving session identity throughout the chain.
        if isinstance(package, Mapping) and response_sid is not None:
            package_sid = _coerce_session_id(package.get("session_id"))
            if package_sid != response_sid:
                _add("SESSION_ID_MISMATCH")

        # 7. Fixed source identifiers for every nested artifact.
        if isinstance(package, Mapping):
            if (
                package.get("package_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073  # noqa: E501
            ):
                _add("PACKAGE_SOURCE_MISMATCH")
        if isinstance(package_consistency, Mapping):
            if (
                package_consistency.get("package_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074  # noqa: E501
            ):
                _add("PACKAGE_CONSISTENCY_SOURCE_MISMATCH")
        if isinstance(attestation, Mapping):
            if (
                attestation.get("attestation_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
            ):
                _add("ATTESTATION_SOURCE_MISMATCH")
        if isinstance(attestation_consistency, Mapping):
            if (
                attestation_consistency.get("attestation_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
            ):
                _add("ATTESTATION_CONSISTENCY_SOURCE_MISMATCH")
        if (
            response.get("response_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
        ):
            _add("RESPONSE_SOURCE_MISMATCH")

        # 8. Fingerprint relationship: the Task 074 audit must bind to the
        # exact nested Task 073 package. Never trust the declared
        # fingerprint -- always recompute it from the package definition.
        if package_valid and package_consistency_valid:
            try:
                expected_fp = ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService._package_fingerprint(  # noqa: E501
                    package
                )
            except Exception:
                _add("PACKAGE_FINGERPRINT_COMPUTE_FAILED")
            else:
                if package_consistency.get("package_fingerprint") != expected_fp:
                    _add("PACKAGE_FINGERPRINT_MISMATCH")
                if (
                    package_consistency.get("audited_package_fingerprint")
                    != expected_fp
                ):
                    _add("AUDITED_PACKAGE_FINGERPRINT_MISMATCH")
        else:
            _add("PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE")

        # 9. Response relationship: the Task 075 response's declared
        # response_consistent must mirror the Task 074 audit's own
        # package_consistent verdict.
        if package_consistency_valid:
            if response.get("response_consistent") != package_consistency.get(
                "package_consistent"
            ):
                _add("RESPONSE_RELATIONSHIP_MISMATCH")

        # 10. Fallback Task 075 contract check.
        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(response)
                )
            except Exception:
                _add("RESPONSE_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        ordered_issues.extend(sorted(unique_issues - set(_ISSUE_ORDER)))

        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_attestation_consistent = (
            "NESTED_ATTESTATION_MISMATCH" not in unique_issues
        )
        nested_attestation_consistency_consistent = (
            "NESTED_ATTESTATION_CONSISTENCY_MISMATCH" not in unique_issues
        )
        nested_package_consistent = "NESTED_PACKAGE_MISMATCH" not in unique_issues
        nested_package_consistency_consistent = (
            "NESTED_PACKAGE_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(i in unique_issues for i in _PROVENANCE_ISSUES)
        response_relationship_consistent = (
            "RESPONSE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues for i in _SOURCE_MISMATCH_ISSUES
        )
        metadata_consistent = not any(i in unique_issues for i in _METADATA_ISSUES)

        result: dict[str, Any] = {
            "available": True,
            "response_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_attestation_consistent": nested_attestation_consistent,
            "nested_attestation_consistency_consistent": (
                nested_attestation_consistency_consistent
            ),
            "nested_package_consistent": nested_package_consistent,
            "nested_package_consistency_consistent": (
                nested_package_consistency_consistent
            ),
            "provenance_consistent": provenance_consistent,
            "response_relationship_consistent": response_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "response_consistency_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076  # noqa: E501
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate the Task 076 result contract."""
        missing = [field for field in _RESULT_REQUIRED_FIELDS if field not in result]
        if missing:
            raise _ContractError("MISSING_RESULT_FIELD", "result has no " + missing[0])

        mistyped = [
            field
            for field in _RESULT_BOOLEAN_FIELDS
            if not isinstance(result[field], bool)
        ]
        if mistyped:
            field = mistyped[0]
            raise _ContractError(
                field.upper() + "_TYPE",
                field + " is not boolean: " + repr(result[field]),
            )

        if result["available"] is not True:
            raise _ContractError("RESULT_UNAVAILABLE", "available is not True")

        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise _ContractError("ISSUES_TYPE", "consistency_issues is not a list")

        if any(not isinstance(issue, str) or not issue for issue in issues):
            raise _ContractError("ISSUE_TYPE", "every issue must be a non-empty string")
        if len(set(issues)) != len(issues):
            raise _ContractError(
                "DUPLICATE_ISSUE", "consistency_issues contains duplicates"
            )

        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        expected_order.extend(sorted(set(issues) - set(_ISSUE_ORDER)))
        if issues != expected_order:
            raise _ContractError(
                "ISSUES_ORDER", "consistency_issues is not in fixed order"
            )

        if (
            result["response_consistency_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076  # noqa: E501
        ):
            raise _ContractError(
                "INVALID_SOURCE",
                "response_consistency_source is not the Task 076 identifier",
            )

        if result["response_consistent"] != (len(issues) == 0):
            raise _ContractError(
                "RESPONSE_CONSISTENT_MISMATCH",
                "response_consistent does not match consistency_issues",
            )

        issue_set = set(issues)
        expected_session_consistent = not any(
            i in issue_set for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        if result["session_consistent"] != expected_session_consistent:
            raise _ContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match consistency_issues",
            )

        expected_nested_attestation = "NESTED_ATTESTATION_MISMATCH" not in issue_set
        if result["nested_attestation_consistent"] != expected_nested_attestation:
            raise _ContractError(
                "NESTED_ATTESTATION_CONSISTENT_MISMATCH",
                "nested_attestation_consistent does not match consistency_issues",
            )

        expected_nested_attestation_consistency = (
            "NESTED_ATTESTATION_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_attestation_consistency_consistent"]
            != expected_nested_attestation_consistency
        ):
            raise _ContractError(
                "NESTED_ATTESTATION_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_attestation_consistency_consistent does not match "
                "consistency_issues",
            )

        expected_nested_package = "NESTED_PACKAGE_MISMATCH" not in issue_set
        if result["nested_package_consistent"] != expected_nested_package:
            raise _ContractError(
                "NESTED_PACKAGE_CONSISTENT_MISMATCH",
                "nested_package_consistent does not match consistency_issues",
            )

        expected_nested_package_consistency = (
            "NESTED_PACKAGE_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_package_consistency_consistent"]
            != expected_nested_package_consistency
        ):
            raise _ContractError(
                "NESTED_PACKAGE_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_package_consistency_consistent does not match "
                "consistency_issues",
            )

        expected_provenance = not any(i in issue_set for i in _PROVENANCE_ISSUES)
        if result["provenance_consistent"] != expected_provenance:
            raise _ContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match consistency_issues",
            )

        expected_relationship = "RESPONSE_RELATIONSHIP_MISMATCH" not in issue_set
        if result["response_relationship_consistent"] != expected_relationship:
            raise _ContractError(
                "RESPONSE_RELATIONSHIP_CONSISTENT_MISMATCH",
                "response_relationship_consistent does not match consistency_issues",
            )

        expected_source = not any(i in issue_set for i in _SOURCE_MISMATCH_ISSUES)
        if result["source_consistency"] != expected_source:
            raise _ContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )

        expected_metadata = not any(i in issue_set for i in _METADATA_ISSUES)
        if result["metadata_consistent"] != expected_metadata:
            raise _ContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

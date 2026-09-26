"""Task 088: independent consistency audit of the Task 087 response.

Consumes a supplied Task 087 final-attestation response and independently
re-derives every consistency relationship: required fields, availability,
session identity, nested Task 085 bundle, nested Task 086 bundle audit,
explicit nested Task 083 package and Task 084 package audit inside the
bundle, fixed source identifiers, fingerprint relationships, and derived
consistency flags. Disagreements are reported through a deterministically
ordered issue list.

This module is pure: it never executes Task 087, never makes HTTP calls,
never touches the database, never invokes external models or providers,
and never mutates the caller's input. It reuses the canonical Task 083
through Task 087 validators and the canonical Task 085 fingerprint
definition instead of duplicating their contracts, and never replaces an
independent check with fallback logic nor silently turns malformed nested
evidence into success.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,
    _expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_TASK_088"  # noqa: E501

_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_attestation_bundle",
    "final_attestation_bundle_consistency",
    "response_source",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
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
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
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
    "NESTED_BUNDLE_MISMATCH",
    "NESTED_BUNDLE_CONSISTENCY_MISMATCH",
    "NESTED_PACKAGE_MISMATCH",
    "NESTED_PACKAGE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
    "BUNDLE_FINGERPRINT_FORMAT",
    "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
    "BUNDLE_FINGERPRINT_MISMATCH",
    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
    "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
    "BUNDLE_FINGERPRINT_CHECK_UNAVAILABLE",
    "RESPONSE_RELATIONSHIP_MISMATCH",
    "RESPONSE_CONTRACT_MISMATCH",
)

_SOURCE_MISMATCH_ISSUES = (
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
)

_PROVENANCE_ISSUES = (
    "BUNDLE_FINGERPRINT_FORMAT",
    "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
    "BUNDLE_FINGERPRINT_MISMATCH",
    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
    "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
    "BUNDLE_FINGERPRINT_CHECK_UNAVAILABLE",
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


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError(  # noqa: E501
    Exception
):
    """Task 088: the response consistency audit could not be completed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService:  # noqa: E501
    """Task 088: independent pure consistency audit of a Task 087 response."""

    def build(self, *, response: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Audit a Task 087 response without mutating or rebuilding it."""
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

        # 2. session identity.
        response_sid = _coerce_session_id(response.get("session_id"))
        if response_sid is None:
            _add("SESSION_ID_INVALID")

        bundle = response.get("final_attestation_bundle")
        bundle_consistency = response.get("final_attestation_bundle_consistency")

        # 3. Nested Task 085 bundle validity.
        bundle_valid = False
        if not isinstance(bundle, Mapping):
            _add("NESTED_BUNDLE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(bundle)
                )
                bundle_valid = True
            except Exception:
                _add("NESTED_BUNDLE_MISMATCH")

        # 4. Nested Task 086 bundle-consistency validity, validated on its
        # own terms without the audited bundle so the fingerprint
        # relationship is re-derived independently below.
        bundle_consistency_valid = False
        if not isinstance(bundle_consistency, Mapping):
            _add("NESTED_BUNDLE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService._validate_result(  # noqa: E501
                    dict(bundle_consistency)
                )
                bundle_consistency_valid = True
            except Exception:
                _add("NESTED_BUNDLE_CONSISTENCY_MISMATCH")

        # 5. Explicit nested Task 083 package and Task 084 consistency
        # checks inside the bundle, independent of the Task 085 validator.
        nested_package = (
            bundle.get("final_attestation_package")
            if isinstance(bundle, Mapping)
            else None
        )
        nested_package_consistency = (
            bundle.get("final_attestation_package_consistency")
            if isinstance(bundle, Mapping)
            else None
        )

        if not isinstance(nested_package, Mapping):
            _add("NESTED_PACKAGE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(nested_package)
                )
            except Exception:
                _add("NESTED_PACKAGE_MISMATCH")

        if not isinstance(nested_package_consistency, Mapping):
            _add("NESTED_PACKAGE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
                    dict(nested_package_consistency)
                )
            except Exception:
                _add("NESTED_PACKAGE_CONSISTENCY_MISMATCH")

        # 6. session binding: response session must equal nested bundle
        # session, and the nested Task 086 audit must report a consistent
        # session, preserving session identity throughout the chain.
        if isinstance(bundle, Mapping) and response_sid is not None:
            bundle_sid = _coerce_session_id(bundle.get("session_id"))
            if bundle_sid != response_sid:
                _add("SESSION_ID_MISMATCH")
        if isinstance(bundle_consistency, Mapping):
            if bundle_consistency.get("session_consistent") is not True:
                _add("SESSION_ID_MISMATCH")

        # 7. Fixed source identifiers for every nested artifact.
        if isinstance(nested_package, Mapping):
            if (
                nested_package.get("package_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
            ):
                _add("PACKAGE_SOURCE_MISMATCH")
        if isinstance(nested_package_consistency, Mapping):
            if (
                nested_package_consistency.get("package_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
            ):
                _add("PACKAGE_CONSISTENCY_SOURCE_MISMATCH")
        if isinstance(bundle, Mapping):
            if (
                bundle.get("bundle_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
            ):
                _add("BUNDLE_SOURCE_MISMATCH")
        if isinstance(bundle_consistency, Mapping):
            if (
                bundle_consistency.get("bundle_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086  # noqa: E501
            ):
                _add("BUNDLE_CONSISTENCY_SOURCE_MISMATCH")
        if (
            response.get("response_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
        ):
            _add("RESPONSE_SOURCE_MISMATCH")

        # 8. Fingerprint relationship: the Task 086 audit must bind to the
        # exact nested Task 085 bundle. Never trust a declared fingerprint;
        # always recompute it from the bundle definition and require both
        # Task 086 fingerprint fields to equal the recomputation, each
        # checked independently with no fallback between them.
        if isinstance(bundle, Mapping) and isinstance(bundle_consistency, Mapping):
            bundle_fp = bundle_consistency.get("bundle_fingerprint")
            audited_fp = bundle_consistency.get("audited_bundle_fingerprint")
            bundle_fp_valid = isinstance(bundle_fp, str) and bool(
                _FINGERPRINT_HEX_RE.fullmatch(bundle_fp)
            )
            audited_fp_valid = isinstance(audited_fp, str) and bool(
                _FINGERPRINT_HEX_RE.fullmatch(audited_fp)
            )
            if not bundle_fp_valid:
                _add("BUNDLE_FINGERPRINT_FORMAT")
            if not audited_fp_valid:
                _add("AUDITED_BUNDLE_FINGERPRINT_FORMAT")
            if bundle_fp_valid and audited_fp_valid and bundle_fp != audited_fp:
                _add("BUNDLE_FINGERPRINT_PAIR_MISMATCH")
            try:
                expected_fp = _expected_bundle_fingerprint(bundle)
            except Exception:
                _add("BUNDLE_FINGERPRINT_COMPUTE_FAILED")
            else:
                if bundle_consistency.get("bundle_fingerprint") != expected_fp:
                    _add("BUNDLE_FINGERPRINT_MISMATCH")
                if bundle_consistency.get("audited_bundle_fingerprint") != expected_fp:
                    _add("AUDITED_BUNDLE_FINGERPRINT_MISMATCH")
        else:
            _add("BUNDLE_FINGERPRINT_CHECK_UNAVAILABLE")

        # 9. Response relationship: the Task 087 response's declared
        # response_consistent must mirror the Task 086 audit's own
        # bundle_consistent verdict.
        if bundle_consistency_valid:
            if response.get("response_consistent") != bundle_consistency.get(
                "bundle_consistent"
            ):
                _add("RESPONSE_RELATIONSHIP_MISMATCH")

        # 10. Fallback Task 087 contract check.
        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(response)
                )
            except Exception:
                _add("RESPONSE_CONTRACT_MISMATCH")

        _ = (bundle_valid, bundle_consistency_valid)

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        ordered_issues.extend(sorted(unique_issues - set(_ISSUE_ORDER)))

        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_bundle_consistent = "NESTED_BUNDLE_MISMATCH" not in unique_issues
        nested_bundle_consistency_consistent = (
            "NESTED_BUNDLE_CONSISTENCY_MISMATCH" not in unique_issues
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
            "nested_bundle_consistent": nested_bundle_consistent,
            "nested_bundle_consistency_consistent": (
                nested_bundle_consistency_consistent
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
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate the Task 088 result contract."""
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
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
        ):
            raise _ContractError(
                "INVALID_SOURCE",
                "response_consistency_source is not the Task 088 identifier",
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

        expected_nested_bundle = "NESTED_BUNDLE_MISMATCH" not in issue_set
        if result["nested_bundle_consistent"] != expected_nested_bundle:
            raise _ContractError(
                "NESTED_BUNDLE_CONSISTENT_MISMATCH",
                "nested_bundle_consistent does not match consistency_issues",
            )

        expected_nested_bundle_consistency = (
            "NESTED_BUNDLE_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_bundle_consistency_consistent"]
            != expected_nested_bundle_consistency
        ):
            raise _ContractError(
                "NESTED_BUNDLE_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_bundle_consistency_consistent does not match "
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

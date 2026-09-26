"""Task 100: independent consistency audit of the Task 099 response.

Consumes a supplied Task 099 final-release-attestation response and
independently re-derives every consistency relationship: required
fields, availability, session identity, nested Task 097 attestation,
nested Task 098 attestation audit, explicit nested Task 095 bundle and
Task 096 bundle audit inside the attestation, fixed source identifiers,
fingerprint relationships, and derived consistency flags.
Disagreements are reported through a deterministically ordered issue
list.

This module is pure: it never executes Task 099, never makes HTTP
calls, never touches the database, never invokes external models or
providers, and never mutates the caller input. It reuses the canonical
Task 095 through Task 099 validators and the canonical Task 095 and
Task 097 fingerprint definitions instead of duplicating their
contracts, and never replaces an independent check with fallback logic
nor silently turns malformed nested evidence into success.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService,  # noqa: E501
    _expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,  # noqa: E501
    _expected_final_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_TASK_100"  # noqa: E501

_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_release_attestation",
    "final_release_attestation_consistency",
    "response_source",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
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
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
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
    "NESTED_BUNDLE_MISMATCH",
    "NESTED_BUNDLE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "RESPONSE_BUNDLE_SOURCE_MISMATCH",
    "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
    "BUNDLE_FINGERPRINT_FORMAT",
    "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
    "BUNDLE_FINGERPRINT_MISMATCH",
    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
    "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
    "BUNDLE_FINGERPRINT_CHECK_UNAVAILABLE",
    "BUNDLE_FINGERPRINT_BINDING_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
    "FINAL_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE",
    "RESPONSE_RELATIONSHIP_MISMATCH",
    "RESPONSE_CONTRACT_MISMATCH",
)

_SOURCE_MISMATCH_ISSUES = (
    "RESPONSE_BUNDLE_SOURCE_MISMATCH",
    "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
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
    "BUNDLE_FINGERPRINT_BINDING_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
    "FINAL_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE",
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


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyContractError(  # noqa: E501
    Exception
):
    """Task 100: the response consistency audit could not be completed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService:  # noqa: E501
    """Task 100: independent pure consistency audit of a Task 099 response."""

    def build(self, *, response: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Audit a Task 099 response without mutating or rebuilding it."""
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

        attestation = response.get("final_release_attestation")
        attestation_consistency = response.get("final_release_attestation_consistency")

        # 3. Nested Task 097 attestation validity.
        attestation_valid = False
        if not isinstance(attestation, Mapping):
            _add("NESTED_ATTESTATION_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(attestation)
                )
                attestation_valid = True
            except Exception:
                _add("NESTED_ATTESTATION_MISMATCH")

        # 4. Nested Task 098 attestation-consistency validity, validated
        # on its own terms without the audited attestation so the
        # fingerprint relationship is re-derived independently below.
        attestation_consistency_valid = False
        if not isinstance(attestation_consistency, Mapping):
            _add("NESTED_ATTESTATION_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService._validate_result(  # noqa: E501
                    dict(attestation_consistency)
                )
                attestation_consistency_valid = True
            except Exception:
                _add("NESTED_ATTESTATION_CONSISTENCY_MISMATCH")

        # 5. Explicit nested Task 095 bundle and Task 096 consistency
        # checks inside the attestation, independent of the Task 097
        # validator.
        nested_bundle = (
            attestation.get("response_bundle")
            if isinstance(attestation, Mapping)
            else None
        )
        nested_bundle_consistency = (
            attestation.get("response_bundle_consistency")
            if isinstance(attestation, Mapping)
            else None
        )

        if not isinstance(nested_bundle, Mapping):
            _add("NESTED_BUNDLE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(nested_bundle)
                )
            except Exception:
                _add("NESTED_BUNDLE_MISMATCH")

        if not isinstance(nested_bundle_consistency, Mapping):
            _add("NESTED_BUNDLE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
                    dict(nested_bundle_consistency)
                )
            except Exception:
                _add("NESTED_BUNDLE_CONSISTENCY_MISMATCH")

        # 6. session binding: response session must equal nested
        # attestation session, and the nested Task 098 audit must report
        # a consistent session, preserving session identity throughout
        # the chain.
        if isinstance(attestation, Mapping) and response_sid is not None:
            attestation_sid = _coerce_session_id(attestation.get("session_id"))
            if attestation_sid != response_sid:
                _add("SESSION_ID_MISMATCH")
        if isinstance(attestation_consistency, Mapping):
            if attestation_consistency.get("session_consistent") is not True:
                _add("SESSION_ID_MISMATCH")

        # 7. Fixed source identifiers for every nested artifact.
        if isinstance(nested_bundle, Mapping):
            if (
                nested_bundle.get("bundle_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
            ):
                _add("RESPONSE_BUNDLE_SOURCE_MISMATCH")
        if isinstance(nested_bundle_consistency, Mapping):
            if (
                nested_bundle_consistency.get("bundle_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096  # noqa: E501
            ):
                _add("RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH")
        if isinstance(attestation, Mapping):
            if (
                attestation.get("final_attestation_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
            ):
                _add("FINAL_ATTESTATION_SOURCE_MISMATCH")
        if isinstance(attestation_consistency, Mapping):
            if (
                attestation_consistency.get("final_attestation_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098  # noqa: E501
            ):
                _add("FINAL_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH")
        if (
            response.get("response_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
        ):
            _add("RESPONSE_SOURCE_MISMATCH")

        # 8. Bundle fingerprint relationship: the nested Task 096 audit
        # must bind to the exact nested Task 095 bundle. Never trust a
        # declared fingerprint; always recompute it from the bundle
        # definition and require both Task 096 fingerprint fields to
        # equal the recomputation, each checked independently with no
        # fallback between them.
        if isinstance(nested_bundle, Mapping) and isinstance(
            nested_bundle_consistency, Mapping
        ):
            bundle_fp = nested_bundle_consistency.get("bundle_fingerprint")
            audited_bundle_fp = nested_bundle_consistency.get(
                "audited_bundle_fingerprint"
            )
            bundle_fp_valid = isinstance(bundle_fp, str) and bool(
                _FINGERPRINT_HEX_RE.fullmatch(bundle_fp)
            )
            audited_bundle_fp_valid = isinstance(audited_bundle_fp, str) and bool(
                _FINGERPRINT_HEX_RE.fullmatch(audited_bundle_fp)
            )
            if not bundle_fp_valid:
                _add("BUNDLE_FINGERPRINT_FORMAT")
            if not audited_bundle_fp_valid:
                _add("AUDITED_BUNDLE_FINGERPRINT_FORMAT")
            if (
                bundle_fp_valid
                and audited_bundle_fp_valid
                and bundle_fp != audited_bundle_fp
            ):
                _add("BUNDLE_FINGERPRINT_PAIR_MISMATCH")
            inner_bundle_fp = nested_bundle.get("bundle_fingerprint")
            if (
                isinstance(inner_bundle_fp, str)
                and isinstance(bundle_fp, str)
                and inner_bundle_fp != bundle_fp
            ):
                _add("BUNDLE_FINGERPRINT_BINDING_MISMATCH")
            try:
                expected_bundle_fp = _expected_bundle_fingerprint(nested_bundle)
            except Exception:
                _add("BUNDLE_FINGERPRINT_COMPUTE_FAILED")
            else:
                if (
                    nested_bundle_consistency.get("bundle_fingerprint")
                    != expected_bundle_fp
                ):
                    _add("BUNDLE_FINGERPRINT_MISMATCH")
                if (
                    nested_bundle_consistency.get("audited_bundle_fingerprint")
                    != expected_bundle_fp
                ):
                    _add("AUDITED_BUNDLE_FINGERPRINT_MISMATCH")
        else:
            _add("BUNDLE_FINGERPRINT_CHECK_UNAVAILABLE")

        # 9. Final fingerprint relationship: the Task 098 audit must bind
        # to the exact nested Task 097 attestation. Never trust a
        # declared fingerprint; always recompute it from the attestation
        # definition and require both Task 098 fingerprint fields to
        # equal the recomputation, each checked independently with no
        # fallback between them.
        if isinstance(attestation, Mapping) and isinstance(
            attestation_consistency, Mapping
        ):
            final_fp = attestation_consistency.get("final_attestation_fingerprint")
            audited_final_fp = attestation_consistency.get(
                "audited_final_attestation_fingerprint"
            )
            final_fp_valid = isinstance(final_fp, str) and bool(
                _FINGERPRINT_HEX_RE.fullmatch(final_fp)
            )
            audited_final_fp_valid = isinstance(audited_final_fp, str) and bool(
                _FINGERPRINT_HEX_RE.fullmatch(audited_final_fp)
            )
            if not final_fp_valid:
                _add("FINAL_ATTESTATION_FINGERPRINT_FORMAT")
            if not audited_final_fp_valid:
                _add("AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT")
            if (
                final_fp_valid
                and audited_final_fp_valid
                and final_fp != audited_final_fp
            ):
                _add("FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH")
            try:
                expected_final_fp = _expected_final_fingerprint(attestation)
            except Exception:
                _add("FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED")
            else:
                if (
                    attestation_consistency.get("final_attestation_fingerprint")
                    != expected_final_fp
                ):
                    _add("FINAL_ATTESTATION_FINGERPRINT_MISMATCH")
                if (
                    attestation_consistency.get("audited_final_attestation_fingerprint")
                    != expected_final_fp
                ):
                    _add("AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH")
        else:
            _add("FINAL_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE")

        # 10. Response relationship: the Task 099 response declared
        # response_consistent must mirror the Task 098 audit own
        # final_attestation_consistent verdict.
        if attestation_consistency_valid:
            if response.get("response_consistent") != attestation_consistency.get(
                "final_attestation_consistent"
            ):
                _add("RESPONSE_RELATIONSHIP_MISMATCH")

        # 11. Fallback Task 099 contract check.
        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(response)
                )
            except Exception:
                _add("RESPONSE_CONTRACT_MISMATCH")

        _ = (attestation_valid, attestation_consistency_valid)

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
        nested_bundle_consistent = "NESTED_BUNDLE_MISMATCH" not in unique_issues
        nested_bundle_consistency_consistent = (
            "NESTED_BUNDLE_CONSISTENCY_MISMATCH" not in unique_issues
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
            "nested_bundle_consistent": nested_bundle_consistent,
            "nested_bundle_consistency_consistent": (
                nested_bundle_consistency_consistent
            ),
            "provenance_consistent": provenance_consistent,
            "response_relationship_consistent": response_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "response_consistency_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100  # noqa: E501
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate the Task 100 result contract."""
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
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100  # noqa: E501
        ):
            raise _ContractError(
                "INVALID_SOURCE",
                "response_consistency_source is not the Task 100 identifier",
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

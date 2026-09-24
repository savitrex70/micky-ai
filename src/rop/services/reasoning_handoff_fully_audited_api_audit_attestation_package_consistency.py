"""Task 074: independent consistency audit of the Task 073 attestation package.

The audit is pure and deterministic. It validates the complete Task 073 package,
independently recomputes its package fingerprint from the exact Task 073
fingerprint definition, requires both package fingerprint fields, and never
uses one fingerprint field as a fallback for the other.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageService,
    _canonicalize as _task073_canonicalize,
    _compute_package_fingerprint as _task073_compute_package_fingerprint,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_TASK_074"
)

_PACKAGE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "attestation",
    "attestation_consistency",
    "package_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_PACKAGE_FIELD",
    "INVALID_PACKAGE_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_ATTESTATION_MISMATCH",
    "NESTED_ATTESTATION_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "PACKAGE_FINGERPRINT_FORMAT",
    "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
    "PACKAGE_FINGERPRINT_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
    "PACKAGE_FINGERPRINT_PAIR_MISMATCH",
    "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
    "PACKAGE_RELATIONSHIP_MISMATCH",
    "ATTESTATION_SOURCE_MISMATCH",
    "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONTRACT_MISMATCH",
)


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
    """Return a deep copy with every session_id string coerced to UUID."""
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


def _task073_package_core(package: Mapping[str, Any]) -> dict[str, Any]:
    """Recreate the exact core hashed by Task 073."""
    sid = package.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    return {
        "session_id": sid_str,
        "attestation": _task073_canonicalize(package.get("attestation")),
        "attestation_consistency": _task073_canonicalize(
            package.get("attestation_consistency")
        ),
    }


def _expected_package_fingerprint(package: Mapping[str, Any]) -> str:
    """Recompute the exact Task 073 package fingerprint definition."""
    return _task073_compute_package_fingerprint(_task073_package_core(package))


class ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError(
    Exception
):
    """Task 074: attestation-package consistency audit contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = (
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyContractError
)


class ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService:
    """Task 074: pure consistency audit of a Task 073 package."""

    def build(
        self, *, package: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Audit a Task 073 package without mutating or rebuilding it."""
        if package is None:
            raise _ContractError("MISSING_PACKAGE", "package is required")
        if not isinstance(package, Mapping):
            raise _ContractError(
                "PACKAGE_TYPE",
                "package is not a mapping: " + type(package).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in package:
                _add("MISSING_PACKAGE_FIELD")

        if package.get("available") is not True:
            _add("INVALID_PACKAGE_AVAILABLE")

        package_sid = _coerce_session_id(package.get("session_id"))
        if package_sid is None:
            _add("SESSION_ID_INVALID")

        attestation = package.get("attestation")
        attestation_consistency = package.get("attestation_consistency")

        attestation_valid = False
        if not isinstance(attestation, Mapping):
            _add("NESTED_ATTESTATION_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(
                    _deep_normalize_session_ids(attestation)
                )
                attestation_valid = True
            except Exception:
                _add("NESTED_ATTESTATION_MISMATCH")

        attestation_consistency_valid = False
        if not isinstance(attestation_consistency, Mapping):
            _add("NESTED_ATTESTATION_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService._validate_result(
                    dict(attestation_consistency)
                )
                attestation_consistency_valid = True
            except Exception:
                _add("NESTED_ATTESTATION_CONSISTENCY_MISMATCH")

        if isinstance(attestation, Mapping):
            att_sid = _coerce_session_id(attestation.get("session_id"))
            if att_sid is None:
                _add("SESSION_ID_INVALID")
            elif package_sid is not None and att_sid != package_sid:
                _add("SESSION_ID_MISMATCH")

        if isinstance(attestation_consistency, Mapping):
            if attestation_consistency.get("session_consistent") is not True:
                _add("SESSION_ID_MISMATCH")

        if isinstance(attestation, Mapping):
            if (
                attestation.get("attestation_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
            ):
                _add("ATTESTATION_SOURCE_MISMATCH")

        if isinstance(attestation_consistency, Mapping):
            if (
                attestation_consistency.get("attestation_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072
            ):
                _add("ATTESTATION_CONSISTENCY_SOURCE_MISMATCH")

        if (
            package.get("package_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073
        ):
            _add("PACKAGE_SOURCE_MISMATCH")

        package_fp = package.get("package_fingerprint")
        audited_package_fp = package.get("audited_package_fingerprint")
        package_fp_valid = isinstance(package_fp, str) and bool(
            _PACKAGE_FINGERPRINT_HEX_RE.fullmatch(package_fp)
        )
        audited_package_fp_valid = isinstance(audited_package_fp, str) and bool(
            _PACKAGE_FINGERPRINT_HEX_RE.fullmatch(audited_package_fp)
        )

        if not package_fp_valid:
            _add("PACKAGE_FINGERPRINT_FORMAT")
        if not audited_package_fp_valid:
            _add("AUDITED_PACKAGE_FINGERPRINT_FORMAT")
        if package_fp_valid and audited_package_fp_valid and package_fp != audited_package_fp:
            _add("PACKAGE_FINGERPRINT_PAIR_MISMATCH")

        try:
            expected_fp = _expected_package_fingerprint(package)
        except Exception:
            _add("PACKAGE_FINGERPRINT_COMPUTE_FAILED")
            expected_fp = None
        else:
            if package_fp_valid and package_fp != expected_fp:
                _add("PACKAGE_FINGERPRINT_MISMATCH")
            if audited_package_fp_valid and audited_package_fp != expected_fp:
                _add("AUDITED_PACKAGE_FINGERPRINT_MISMATCH")

        if attestation_valid and attestation_consistency_valid:
            expected_package_consistent = bool(
                attestation.get("attestation_consistent", False)
                and attestation_consistency.get("attestation_consistent", False)
            )
            if package.get("package_consistent") != expected_package_consistent:
                _add("PACKAGE_RELATIONSHIP_MISMATCH")

        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationPackageService._validate_result(
                    _deep_normalize_session_ids(dict(package))
                )
            except Exception:
                _add("PACKAGE_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        ordered_issues.extend(sorted(unique_issues - set(_ISSUE_ORDER)))

        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_attestation_consistent = "NESTED_ATTESTATION_MISMATCH" not in unique_issues
        nested_attestation_consistency_consistent = (
            "NESTED_ATTESTATION_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "PACKAGE_FINGERPRINT_FORMAT",
                "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
                "PACKAGE_FINGERPRINT_MISMATCH",
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "PACKAGE_FINGERPRINT_PAIR_MISMATCH",
                "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        package_relationship_consistent = (
            "PACKAGE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "ATTESTATION_SOURCE_MISMATCH",
                "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
                "PACKAGE_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in ("MISSING_PACKAGE_FIELD", "INVALID_PACKAGE_AVAILABLE")
        )

        if expected_fp is None:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute a self-authenticating package fingerprint",
            )

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_attestation_consistent": nested_attestation_consistent,
            "nested_attestation_consistency_consistent": (
                nested_attestation_consistency_consistent
            ),
            "provenance_consistent": provenance_consistent,
            "package_relationship_consistent": package_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "package_consistency_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074,
            "package_fingerprint": expected_fp,
            "audited_package_fingerprint": expected_fp,
        }
        self._validate_result(result, package=package)
        return result

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        package: Mapping[str, Any] | None = None,
    ) -> None:
        """Validate the Task 074 result and, when supplied, its audited package."""
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
            raise _ContractError("DUPLICATE_ISSUE", "consistency_issues contains duplicates")

        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        expected_order.extend(sorted(set(issues) - set(_ISSUE_ORDER)))
        if issues != expected_order:
            raise _ContractError("ISSUES_ORDER", "consistency_issues is not in fixed order")

        if result["package_consistency_source"] != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074:
            raise _ContractError(
                "INVALID_SOURCE",
                "package_consistency_source is not the Task 074 identifier",
            )

        if result["package_consistent"] != (len(issues) == 0):
            raise _ContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match consistency_issues",
            )

        package_fp = result["package_fingerprint"]
        audited_package_fp = result["audited_package_fingerprint"]
        if not isinstance(package_fp, str) or not _PACKAGE_FINGERPRINT_HEX_RE.fullmatch(package_fp):
            raise _ContractError(
                "PACKAGE_FINGERPRINT_FORMAT",
                "package_fingerprint is not a lowercase 64-character SHA-256 string",
            )
        if not isinstance(audited_package_fp, str) or not _PACKAGE_FINGERPRINT_HEX_RE.fullmatch(
            audited_package_fp
        ):
            raise _ContractError(
                "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
                "audited_package_fingerprint is not a lowercase 64-character SHA-256 string",
            )
        if package_fp != audited_package_fp:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_PAIR_MISMATCH",
                "audited_package_fingerprint does not equal package_fingerprint",
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

        expected_nested_consistency = (
            "NESTED_ATTESTATION_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_attestation_consistency_consistent"]
            != expected_nested_consistency
        ):
            raise _ContractError(
                "NESTED_ATTESTATION_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_attestation_consistency_consistent does not match consistency_issues",
            )

        expected_provenance = not any(
            i in issue_set
            for i in (
                "PACKAGE_FINGERPRINT_FORMAT",
                "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
                "PACKAGE_FINGERPRINT_MISMATCH",
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "PACKAGE_FINGERPRINT_PAIR_MISMATCH",
                "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        if result["provenance_consistent"] != expected_provenance:
            raise _ContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match consistency_issues",
            )

        expected_relationship = "PACKAGE_RELATIONSHIP_MISMATCH" not in issue_set
        if result["package_relationship_consistent"] != expected_relationship:
            raise _ContractError(
                "PACKAGE_RELATIONSHIP_CONSISTENT_MISMATCH",
                "package_relationship_consistent does not match consistency_issues",
            )

        expected_source = not any(
            i in issue_set
            for i in (
                "ATTESTATION_SOURCE_MISMATCH",
                "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
                "PACKAGE_SOURCE_MISMATCH",
            )
        )
        if result["source_consistency"] != expected_source:
            raise _ContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )

        expected_metadata = not any(
            i in issue_set for i in ("MISSING_PACKAGE_FIELD", "INVALID_PACKAGE_AVAILABLE")
        )
        if result["metadata_consistent"] != expected_metadata:
            raise _ContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

        if package is not None:
            try:
                expected = _expected_package_fingerprint(package)
            except Exception as exc:
                raise _ContractError(
                    "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                    "could not recompute package fingerprint: " + str(exc),
                ) from exc
            if result["package_fingerprint"] != expected:
                raise _ContractError(
                    "PACKAGE_FINGERPRINT_MISMATCH",
                    "package_fingerprint does not match the exact Task 073 package definition",
                )
            if result["audited_package_fingerprint"] != expected:
                raise _ContractError(
                    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                    "audited_package_fingerprint does not match the exact Task 073 package definition",
                )

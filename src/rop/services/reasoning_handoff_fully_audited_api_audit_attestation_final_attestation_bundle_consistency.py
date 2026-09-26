"""Task 086: independent consistency audit of the Task 085 bundle.

The audit is pure and deterministic. It validates the complete Task 085
bundle, independently recomputes its bundle fingerprint from the exact
Task 085 fingerprint definition, requires both bundle fingerprint fields,
and never uses one fingerprint field as a fallback for the other.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    _canonicalize as _task085_canonicalize,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    _compute_bundle_fingerprint as _task085_compute_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_TASK_086"  # noqa: E501

_BUNDLE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "final_attestation_package",
    "final_attestation_package_consistency",
    "bundle_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_final_attestation_package_consistent",
    "nested_final_attestation_package_consistency_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_final_attestation_package_consistent",
    "nested_final_attestation_package_consistency_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_BUNDLE_FIELD",
    "INVALID_BUNDLE_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_FINAL_ATTESTATION_PACKAGE_MISMATCH",
    "NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "BUNDLE_FINGERPRINT_FORMAT",
    "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
    "BUNDLE_FINGERPRINT_MISMATCH",
    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
    "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
    "BUNDLE_RELATIONSHIP_MISMATCH",
    "PACKAGE_FINGERPRINT_BINDING_MISMATCH",
    "FINAL_ATTESTATION_PACKAGE_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONTRACT_MISMATCH",
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


def _task085_bundle_core(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Recreate the exact core hashed by Task 085."""
    sid = bundle.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    return {
        "session_id": sid_str,
        "final_attestation_package": _task085_canonicalize(
            bundle.get("final_attestation_package")
        ),
        "final_attestation_package_consistency": _task085_canonicalize(
            bundle.get("final_attestation_package_consistency")
        ),
    }


def _expected_bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
    """Recompute the exact Task 085 bundle fingerprint definition."""
    return _task085_compute_bundle_fingerprint(_task085_bundle_core(bundle))


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyContractError(  # noqa: E501
    Exception
):
    """Task 086: final-attestation-bundle consistency audit contract violation."""  # noqa: E501

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService:  # noqa: E501
    """Task 086: pure consistency audit of a Task 085 bundle."""

    def build(self, *, bundle: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Audit a Task 085 bundle without mutating or rebuilding it."""
        if bundle is None:
            raise _ContractError("MISSING_BUNDLE", "bundle is required")
        if not isinstance(bundle, Mapping):
            raise _ContractError(
                "BUNDLE_TYPE",
                "bundle is not a mapping: " + type(bundle).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in bundle:
                _add("MISSING_BUNDLE_FIELD")

        if bundle.get("available") is not True:
            _add("INVALID_BUNDLE_AVAILABLE")

        bundle_sid = _coerce_session_id(bundle.get("session_id"))
        if bundle_sid is None:
            _add("SESSION_ID_INVALID")

        final_package = bundle.get("final_attestation_package")
        final_package_consistency = bundle.get("final_attestation_package_consistency")

        pkg_valid = False
        if not isinstance(final_package, Mapping):
            _add("NESTED_FINAL_ATTESTATION_PACKAGE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(final_package)
                )
                pkg_valid = True
            except Exception:
                _add("NESTED_FINAL_ATTESTATION_PACKAGE_MISMATCH")

        pkg_consistency_valid = False
        if not isinstance(final_package_consistency, Mapping):
            _add("NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService._validate_result(  # noqa: E501
                    dict(final_package_consistency)
                )
                pkg_consistency_valid = True
            except Exception:
                _add("NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH")

        if isinstance(final_package, Mapping):
            pkg_sid = _coerce_session_id(final_package.get("session_id"))
            if pkg_sid is None:
                _add("SESSION_ID_INVALID")
            elif bundle_sid is not None and pkg_sid != bundle_sid:
                _add("SESSION_ID_MISMATCH")

        if isinstance(final_package_consistency, Mapping):
            if final_package_consistency.get("session_consistent") is not True:
                _add("SESSION_ID_MISMATCH")

        if isinstance(final_package, Mapping):
            if (
                final_package.get("package_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
            ):
                _add("FINAL_ATTESTATION_PACKAGE_SOURCE_MISMATCH")

        if isinstance(final_package_consistency, Mapping):
            if (
                final_package_consistency.get("package_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
            ):
                _add("FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_MISMATCH")

        if isinstance(final_package, Mapping) and isinstance(
            final_package_consistency, Mapping
        ):
            pkg_fp = final_package.get("package_fingerprint")
            cons_fp = final_package_consistency.get("package_fingerprint")
            if (
                isinstance(pkg_fp, str)
                and isinstance(cons_fp, str)
                and pkg_fp != cons_fp
            ):
                _add("PACKAGE_FINGERPRINT_BINDING_MISMATCH")

        if (
            bundle.get("bundle_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
        ):
            _add("BUNDLE_SOURCE_MISMATCH")

        bundle_fp = bundle.get("bundle_fingerprint")
        audited_bundle_fp = bundle.get("audited_bundle_fingerprint")
        bundle_fp_valid = isinstance(bundle_fp, str) and bool(
            _BUNDLE_FINGERPRINT_HEX_RE.fullmatch(bundle_fp)
        )
        audited_bundle_fp_valid = isinstance(audited_bundle_fp, str) and bool(
            _BUNDLE_FINGERPRINT_HEX_RE.fullmatch(audited_bundle_fp)
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

        try:
            expected_fp = _expected_bundle_fingerprint(bundle)
        except Exception:
            _add("BUNDLE_FINGERPRINT_COMPUTE_FAILED")
            expected_fp = None
        else:
            if bundle_fp_valid and bundle_fp != expected_fp:
                _add("BUNDLE_FINGERPRINT_MISMATCH")
            if audited_bundle_fp_valid and audited_bundle_fp != expected_fp:
                _add("AUDITED_BUNDLE_FINGERPRINT_MISMATCH")

        if pkg_valid and pkg_consistency_valid:
            expected_bundle_consistent = bool(
                final_package.get("package_consistent", False)
                and final_package_consistency.get("package_consistent", False)
            )
            if bundle.get("bundle_consistent") != expected_bundle_consistent:
                _add("BUNDLE_RELATIONSHIP_MISMATCH")

        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(dict(bundle))
                )
            except Exception:
                _add("BUNDLE_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        ordered_issues.extend(sorted(unique_issues - set(_ISSUE_ORDER)))

        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_pkg = "NESTED_FINAL_ATTESTATION_PACKAGE_MISMATCH" not in unique_issues
        nested_pkg_cons = (
            "NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "BUNDLE_FINGERPRINT_FORMAT",
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "BUNDLE_FINGERPRINT_MISMATCH",
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        bundle_relationship_consistent = (
            "BUNDLE_RELATIONSHIP_MISMATCH" not in unique_issues
            and "PACKAGE_FINGERPRINT_BINDING_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "FINAL_ATTESTATION_PACKAGE_SOURCE_MISMATCH",
                "FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                "BUNDLE_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in ("MISSING_BUNDLE_FIELD", "INVALID_BUNDLE_AVAILABLE")
        )

        if expected_fp is None:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute a self-authenticating bundle fingerprint",
            )

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_final_attestation_package_consistent": nested_pkg,
            "nested_final_attestation_package_consistency_consistent": (
                nested_pkg_cons
            ),
            "provenance_consistent": provenance_consistent,
            "bundle_relationship_consistent": bundle_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "bundle_consistency_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086,  # noqa: E501
            "bundle_fingerprint": expected_fp,
            "audited_bundle_fingerprint": expected_fp,
        }
        self._validate_result(result, bundle=bundle)
        return result

    @staticmethod
    def _bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
        """Return the exact Task 085 bundle fingerprint of ``bundle``."""
        return _expected_bundle_fingerprint(bundle)

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        bundle: Mapping[str, Any] | None = None,
    ) -> None:
        """Validate the Task 086 result and, when supplied, its audited bundle."""  # noqa: E501
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
            result["bundle_consistency_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086  # noqa: E501
        ):
            raise _ContractError(
                "INVALID_SOURCE",
                "bundle_consistency_source is not the Task 086 identifier",
            )

        if result["bundle_consistent"] != (len(issues) == 0):
            raise _ContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match consistency_issues",
            )

        bundle_fp = result["bundle_fingerprint"]
        audited_bundle_fp = result["audited_bundle_fingerprint"]
        if not isinstance(bundle_fp, str) or not _BUNDLE_FINGERPRINT_HEX_RE.fullmatch(
            bundle_fp
        ):
            raise _ContractError(
                "BUNDLE_FINGERPRINT_FORMAT",
                "bundle_fingerprint is not a lowercase 64-character SHA-256 string",
            )
        if not isinstance(
            audited_bundle_fp, str
        ) or not _BUNDLE_FINGERPRINT_HEX_RE.fullmatch(audited_bundle_fp):
            raise _ContractError(
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "audited_bundle_fingerprint is not a lowercase 64-character "
                "SHA-256 string",
            )

        if bundle is not None:
            try:
                expected = _expected_bundle_fingerprint(bundle)
            except Exception as exc:
                raise _ContractError(
                    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                    "could not recompute bundle fingerprint: " + str(exc),
                ) from exc
            if result["bundle_fingerprint"] != expected:
                raise _ContractError(
                    "BUNDLE_FINGERPRINT_MISMATCH",
                    "bundle_fingerprint does not match the exact Task 085 "
                    "bundle definition",
                )
            if result["audited_bundle_fingerprint"] != expected:
                raise _ContractError(
                    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                    "audited_bundle_fingerprint does not match the exact "
                    "Task 085 bundle definition",
                )

        if bundle_fp != audited_bundle_fp:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
                "audited_bundle_fingerprint does not equal bundle_fingerprint",
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

        expected_nested_pkg = (
            "NESTED_FINAL_ATTESTATION_PACKAGE_MISMATCH" not in issue_set
        )
        if result["nested_final_attestation_package_consistent"] != expected_nested_pkg:
            raise _ContractError(
                "NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENT_MISMATCH",
                "nested_final_attestation_package_consistent does not match "
                "consistency_issues",
            )

        expected_nested_pkg_cons = (
            "NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_final_attestation_package_consistency_consistent"]
            != expected_nested_pkg_cons
        ):
            raise _ContractError(
                "NESTED_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_CONSISTENT_MISMATCH",  # noqa: E501
                "nested_final_attestation_package_consistency_consistent does "
                "not match consistency_issues",
            )

        expected_provenance = not any(
            i in issue_set
            for i in (
                "BUNDLE_FINGERPRINT_FORMAT",
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "BUNDLE_FINGERPRINT_MISMATCH",
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        if result["provenance_consistent"] != expected_provenance:
            raise _ContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match consistency_issues",
            )

        expected_relationship = not any(
            i in issue_set
            for i in (
                "BUNDLE_RELATIONSHIP_MISMATCH",
                "PACKAGE_FINGERPRINT_BINDING_MISMATCH",
            )
        )
        if result["bundle_relationship_consistent"] != expected_relationship:
            raise _ContractError(
                "BUNDLE_RELATIONSHIP_CONSISTENT_MISMATCH",
                "bundle_relationship_consistent does not match consistency_issues",
            )

        expected_source = not any(
            i in issue_set
            for i in (
                "FINAL_ATTESTATION_PACKAGE_SOURCE_MISMATCH",
                "FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                "BUNDLE_SOURCE_MISMATCH",
            )
        )
        if result["source_consistency"] != expected_source:
            raise _ContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )

        expected_metadata = not any(
            i in issue_set for i in ("MISSING_BUNDLE_FIELD", "INVALID_BUNDLE_AVAILABLE")
        )
        if result["metadata_consistent"] != expected_metadata:
            raise _ContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

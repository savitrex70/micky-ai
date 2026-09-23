"""Task 070: pure audit of a Task 069 fully audited API audit bundle.

Consumes an already-built ReasoningHandoffFullyAuditedApiAuditBundleRead,
independently re-derives every consistency relationship, and reports
disagreements through consistency_issues. Reuses Task 067's and Task
068's and Task 069's own validators for the nested results. Never
queries the database, never performs HTTP, never calls Task 065's
endpoint, never invokes Task 059-069 build workflows, never mutates
its input.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_bundle import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069,
    ReasoningHandoffFullyAuditedApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067,
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068,
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_TASK_070"
)

_BUNDLE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
    "audited_bundle_fingerprint",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_package_consistent",
    "nested_package_consistency_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
    "audited_bundle_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_package_consistent",
    "nested_package_consistency_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_BUNDLE_FIELD",
    "INVALID_BUNDLE_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_PACKAGE_MISMATCH",
    "NESTED_PACKAGE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
    "AUDITED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
    "BUNDLE_RELATIONSHIP_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "CONSISTENCY_SOURCE_MISMATCH",
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


def _canonicalize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _canonicalize(bundle), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(Exception):
    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService:
    def build(self, *, bundle: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if bundle is None:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "MISSING_BUNDLE", "bundle is required"
            )
        if not isinstance(bundle, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "BUNDLE_TYPE", "bundle is not a mapping: " + type(bundle).__name__
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        # 1. bundle structure
        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in bundle:
                _add("MISSING_BUNDLE_FIELD")
        if bundle.get("available") is not True:
            _add("INVALID_BUNDLE_AVAILABLE")

        bundle_sid = _coerce_session_id(bundle.get("session_id"))
        if bundle_sid is None:
            _add("SESSION_ID_INVALID")

        package = bundle.get("api_audit_package")
        audit = bundle.get("api_audit_package_consistency")

        # 4. nested Task 067 package validity
        package_valid = False
        if not isinstance(package, Mapping):
            _add("NESTED_PACKAGE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(
                    _deep_normalize_session_ids(package)
                )
                package_valid = True
            except Exception:
                _add("NESTED_PACKAGE_MISMATCH")

        # 5. nested Task 068 audit validity
        audit_valid = False
        if not isinstance(audit, Mapping):
            _add("NESTED_PACKAGE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
                    dict(audit)
                )
                audit_valid = True
            except Exception:
                _add("NESTED_PACKAGE_CONSISTENCY_MISMATCH")

        # 6. package session equals bundle session
        if isinstance(package, Mapping) and bundle_sid is not None:
            package_sid = _coerce_session_id(package.get("session_id"))
            if package_sid != bundle_sid:
                _add("SESSION_ID_MISMATCH")

        # 7/8. fingerprint provenance
        if package_valid and audit_valid:
            try:
                expected_fp = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._package_fingerprint(  # noqa: E501
                    package
                )
            except Exception:
                _add("AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED")
            else:
                actual_fp = audit.get("audited_package_fingerprint")
                if actual_fp != expected_fp:
                    _add("AUDITED_PACKAGE_FINGERPRINT_MISMATCH")
        else:
            _add("AUDITED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE")

        # 9. bundle relationship
        if audit_valid:
            if bundle.get("bundle_consistent") != audit.get("package_consistent"):
                _add("BUNDLE_RELATIONSHIP_MISMATCH")

        # 10. sources
        if isinstance(package, Mapping):
            if (
                package.get("package_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
            ):
                _add("PACKAGE_SOURCE_MISMATCH")
        if isinstance(audit, Mapping):
            if (
                audit.get("package_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068  # noqa: E501
            ):
                _add("CONSISTENCY_SOURCE_MISMATCH")
        if (
            bundle.get("bundle_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069
        ):
            _add("BUNDLE_SOURCE_MISMATCH")

        # 11. fallback Task 069 contract
        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditBundleService._validate_result(
                    dict(bundle)
                )
            except Exception:
                _add("BUNDLE_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        session_consistent = (
            "SESSION_ID_INVALID" not in unique_issues
            and "SESSION_ID_MISMATCH" not in unique_issues
        )
        nested_package_consistent = "NESTED_PACKAGE_MISMATCH" not in unique_issues
        nested_package_consistency_consistent = (
            "NESTED_PACKAGE_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "AUDITED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        bundle_relationship_consistent = (
            "BUNDLE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "PACKAGE_SOURCE_MISMATCH",
                "CONSISTENCY_SOURCE_MISMATCH",
                "BUNDLE_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in ("MISSING_BUNDLE_FIELD", "INVALID_BUNDLE_AVAILABLE")
        )

        try:
            audited_bundle_fingerprint = _bundle_fingerprint(bundle)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute audited bundle fingerprint: " + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_package_consistent": nested_package_consistent,
            "nested_package_consistency_consistent": nested_package_consistency_consistent,  # noqa: E501
            "provenance_consistent": provenance_consistent,
            "bundle_relationship_consistent": bundle_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "bundle_consistency_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070,  # noqa: E501
            "audited_bundle_fingerprint": audited_bundle_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        missing = [f for f in _RESULT_REQUIRED_FIELDS if f not in result]
        if missing:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "MISSING_RESULT_FIELD", "result has no " + missing[0]
            )
        mistyped = [
            f for f in _RESULT_BOOLEAN_FIELDS if not isinstance(result[f], bool)
        ]
        if mistyped:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                mistyped[0].upper() + "_TYPE",
                mistyped[0] + " is not boolean: " + repr(result[mistyped[0]]),
            )
        if result["available"] is not True:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        bad = [i for i in issues if not isinstance(i, str) or not i]
        if bad:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "ISSUE_TYPE", "issue is not non-empty string: " + repr(bad[0])
            )
        if len(set(issues)) != len(issues):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "DUPLICATE_ISSUE", "duplicates: " + repr(issues)
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "ISSUES_ORDER", "not in fixed order: " + repr(issues)
            )
        if (
            result["bundle_consistency_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070  # noqa: E501
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "INVALID_SOURCE",
                "bundle_consistency_source is not Task 070 identifier: "
                + repr(result["bundle_consistency_source"]),
            )
        if result["bundle_consistent"] != (len(issues) == 0):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match consistency_issues",
            )
        fp = result["audited_bundle_fingerprint"]
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "audited_bundle_fingerprint is not 64-char hex: " + repr(fp),
            )
        issue_set = set(issues)
        expected_session_consistent = (
            "SESSION_ID_INVALID" not in issue_set
            and "SESSION_ID_MISMATCH" not in issue_set
        )
        if result["session_consistent"] != expected_session_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match issues",
            )
        expected_nested_package_consistent = "NESTED_PACKAGE_MISMATCH" not in issue_set
        if result["nested_package_consistent"] != expected_nested_package_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "NESTED_PACKAGE_CONSISTENT_MISMATCH",
                "nested_package_consistent does not match issues",
            )
        expected_nested_consistency = (
            "NESTED_PACKAGE_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_package_consistency_consistent"]
            != expected_nested_consistency
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "NESTED_PACKAGE_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_package_consistency_consistent does not match issues",
            )
        expected_provenance_consistent = not any(
            i in issue_set
            for i in (
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "AUDITED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        if result["provenance_consistent"] != expected_provenance_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match issues",
            )
        expected_bundle_relationship_consistent = (
            "BUNDLE_RELATIONSHIP_MISMATCH" not in issue_set
        )
        if (
            result["bundle_relationship_consistent"]
            != expected_bundle_relationship_consistent
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "BUNDLE_RELATIONSHIP_CONSISTENT_MISMATCH",
                "bundle_relationship_consistent does not match issues",
            )
        expected_source_consistency = not any(
            i in issue_set
            for i in (
                "PACKAGE_SOURCE_MISMATCH",
                "CONSISTENCY_SOURCE_MISMATCH",
                "BUNDLE_SOURCE_MISMATCH",
            )
        )
        if result["source_consistency"] != expected_source_consistency:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "SOURCE_CONSISTENT_MISMATCH", "source_consistency does not match issues"
            )
        expected_metadata_consistent = not any(
            i in issue_set for i in ("MISSING_BUNDLE_FIELD", "INVALID_BUNDLE_AVAILABLE")
        )
        if result["metadata_consistent"] != expected_metadata_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditBundleConsistencyContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match issues",
            )

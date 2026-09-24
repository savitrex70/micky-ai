"""Task 064: pure audit of a Task 063 API audit bundle.

Consumes an already-built ReasoningHandoffApiAuditBundleRead,
independently re-derives every consistency relationship, and reports
disagreements through consistency_issues. Reuses Task 061's and Task
062's own validators for the nested results and reuses Task 062's
package-fingerprint helper (without calling Task 062's build()). Never
queries the database, never performs HTTP, never calls Task
059/060/061/062/063 build workflows, never mutates its input.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_api_audit_bundle import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063,
    ReasoningHandoffApiAuditBundleService,
)
from rop.services.reasoning_handoff_api_audit_package import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061,
    ReasoningHandoffApiAuditPackageService,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062,
    ReasoningHandoffApiAuditPackageConsistencyService,
)

REASONING_HANDOFF_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_064 = (
    "REASONING_HANDOFF_API_AUDIT_BUNDLE_CONSISTENCY_TASK_064"
)

_BUNDLE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "nested_package_consistent",
    "nested_package_audit_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_bundle_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "nested_package_consistent",
    "nested_package_audit_consistent",
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
    "NESTED_PACKAGE_AUDIT_MISMATCH",
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


class ReasoningHandoffApiAuditBundleConsistencyContractError(Exception):
    """Task 064: the supplied bundle cannot be audited at all."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffApiAuditBundleConsistencyService:
    """Task 064: pure audit of a Task 063 API audit bundle."""

    def build(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if bundle is None:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "MISSING_BUNDLE", "bundle is required"
            )
        if not isinstance(bundle, Mapping):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "BUNDLE_TYPE",
                "bundle is not a mapping: " + type(bundle).__name__,
            )

        issues: list[str] = []

        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in bundle:
                issues.append("MISSING_BUNDLE_FIELD")

        if bundle.get("available") is not True:
            issues.append("INVALID_BUNDLE_AVAILABLE")

        bundle_session_id = _coerce_session_id(bundle.get("session_id"))
        if bundle_session_id is None:
            issues.append("SESSION_ID_INVALID")

        package = bundle.get("api_audit_package")
        package_valid = False
        if not isinstance(package, Mapping):
            issues.append("NESTED_PACKAGE_MISMATCH")
        else:
            package_for_validation = _deep_normalize_session_ids(package)
            try:
                ReasoningHandoffApiAuditPackageService._validate_result(
                    package_for_validation
                )
                package_valid = True
            except Exception:
                issues.append("NESTED_PACKAGE_MISMATCH")

        audit = bundle.get("api_audit_package_consistency")
        audit_valid = False
        if not isinstance(audit, Mapping):
            issues.append("NESTED_PACKAGE_AUDIT_MISMATCH")
        else:
            try:
                ReasoningHandoffApiAuditPackageConsistencyService._validate_result(
                    dict(audit)
                )
                audit_valid = True
            except Exception:
                issues.append("NESTED_PACKAGE_AUDIT_MISMATCH")

        if isinstance(package, Mapping) and bundle_session_id is not None:
            package_sid = _coerce_session_id(package.get("session_id"))
            if package_sid != bundle_session_id:
                issues.append("SESSION_ID_MISMATCH")

        if package_valid and audit_valid:
            try:
                fingerprint_helper = ReasoningHandoffApiAuditPackageConsistencyService
                expected_fingerprint = fingerprint_helper._package_fingerprint(package)
            except Exception:
                issues.append("AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED")
            else:
                actual_fingerprint = audit.get("audited_package_fingerprint")
                if actual_fingerprint != expected_fingerprint:
                    issues.append("AUDITED_PACKAGE_FINGERPRINT_MISMATCH")
        else:
            issues.append("AUDITED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE")

        if audit_valid:
            if bundle.get("bundle_consistent") != audit.get("package_consistent"):
                issues.append("BUNDLE_RELATIONSHIP_MISMATCH")

        if isinstance(package, Mapping):
            if (
                package.get("package_source")
                != REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061
            ):
                issues.append("PACKAGE_SOURCE_MISMATCH")
        if isinstance(audit, Mapping):
            if (
                audit.get("package_consistency_source")
                != REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062
            ):
                issues.append("CONSISTENCY_SOURCE_MISMATCH")
        if (
            bundle.get("bundle_source")
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        ):
            issues.append("BUNDLE_SOURCE_MISMATCH")

        if not issues:
            try:
                ReasoningHandoffApiAuditBundleService._validate_result(
                    _deep_normalize_session_ids(bundle)
                )
            except Exception:
                issues.append("BUNDLE_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_package_consistent = "NESTED_PACKAGE_MISMATCH" not in unique_issues
        nested_package_audit_consistent = (
            "NESTED_PACKAGE_AUDIT_MISMATCH" not in unique_issues
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
            for i in (
                "MISSING_BUNDLE_FIELD",
                "INVALID_BUNDLE_AVAILABLE",
            )
        )

        try:
            audited_bundle_fingerprint = (
                ReasoningHandoffApiAuditBundleConsistencyService._bundle_fingerprint(
                    bundle
                )
            )
        except Exception as exc:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute the audited bundle fingerprint: " + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_package_consistent": nested_package_consistent,
            "nested_package_audit_consistent": (nested_package_audit_consistent),
            "provenance_consistent": provenance_consistent,
            "bundle_relationship_consistent": (bundle_relationship_consistent),
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "package_consistency_source": (
                REASONING_HANDOFF_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_064
            ),
            "audited_bundle_fingerprint": audited_bundle_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(k): ReasoningHandoffApiAuditBundleConsistencyService._canonicalize(
                    v
                )
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [
                ReasoningHandoffApiAuditBundleConsistencyService._canonicalize(item)
                for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
        canonical = ReasoningHandoffApiAuditBundleConsistencyService._canonicalize(
            bundle
        )
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["package_consistency_source"]
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_064
        ):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                "package_consistency_source is not the Task 064 "
                "identifier: " + repr(result["package_consistency_source"]),
            )
        if result["package_consistent"] != (len(issues) == 0):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match consistency_issues",
            )
        fp = result["audited_bundle_fingerprint"]
        if not isinstance(fp, str) or not (_BUNDLE_FINGERPRINT_HEX_RE.fullmatch(fp)):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "audited_bundle_fingerprint is not a 64-char lowercase "
                "hex string: " + repr(fp),
            )

        issue_set = set(issues)
        expected_session_consistent = not any(
            i in issue_set for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        if result["session_consistent"] != expected_session_consistent:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match consistency_issues",
            )
        expected_nested_package_consistent = "NESTED_PACKAGE_MISMATCH" not in issue_set
        if result["nested_package_consistent"] != expected_nested_package_consistent:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "NESTED_PACKAGE_CONSISTENT_MISMATCH",
                "nested_package_consistent does not match " "consistency_issues",
            )
        expected_nested_package_audit_consistent = (
            "NESTED_PACKAGE_AUDIT_MISMATCH" not in issue_set
        )
        if (
            result["nested_package_audit_consistent"]
            != expected_nested_package_audit_consistent
        ):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "NESTED_PACKAGE_AUDIT_CONSISTENT_MISMATCH",
                "nested_package_audit_consistent does not match " "consistency_issues",
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
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match " "consistency_issues",
            )
        expected_bundle_relationship_consistent = (
            "BUNDLE_RELATIONSHIP_MISMATCH" not in issue_set
        )
        if (
            result["bundle_relationship_consistent"]
            != expected_bundle_relationship_consistent
        ):
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "BUNDLE_RELATIONSHIP_CONSISTENT_MISMATCH",
                "bundle_relationship_consistent does not match " "consistency_issues",
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
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )
        expected_metadata_consistent = not any(
            i in issue_set
            for i in (
                "MISSING_BUNDLE_FIELD",
                "INVALID_BUNDLE_AVAILABLE",
            )
        )
        if result["metadata_consistent"] != expected_metadata_consistent:
            raise ReasoningHandoffApiAuditBundleConsistencyContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

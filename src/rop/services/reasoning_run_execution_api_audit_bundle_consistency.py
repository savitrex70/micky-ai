from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run_execution_api_audit_bundle import (
    REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053,
)
from rop.services.reasoning_run_execution_api_audit_package import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051,
    ReasoningRunExecutionApiAuditPackageService,
)
from rop.services.reasoning_run_execution_api_audit_package_consistency import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052,
    ReasoningRunExecutionApiAuditPackageConsistencyService,
)

REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_054 = (
    "REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_CONSISTENCY_TASK_054"
)

_EXPECTED_METHOD = "POST"
_EXPECTED_STATUS_CODE = 200
_PATH_PATTERN = re.compile(
    r"^/sessions/(?P<session_id>[^/]+)"
    r"/reasoning-run/execute-fully-audited$"
)

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_package_consistent",
    "nested_package_audit_consistent",
    "package_audit_provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_package_consistent",
    "nested_package_audit_consistent",
    "package_audit_provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_BUNDLE_FIELD",
    "INVALID_BUNDLE_AVAILABLE",
    "SESSION_ID_INVALID",
    "PATH_INVALID",
    "SESSION_ID_MISMATCH",
    "METHOD_INVALID",
    "STATUS_CODE_INVALID",
    "NESTED_PACKAGE_MISMATCH",
    "NESTED_PACKAGE_AUDIT_MISMATCH",
    "PACKAGE_SESSION_MISMATCH",
    "METHOD_MISMATCH",
    "PATH_MISMATCH",
    "STATUS_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
    "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
    "PROVENANCE_CHECK_UNAVAILABLE",
    "BUNDLE_RELATIONSHIP_MISMATCH",
    "RESPONSE_PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_AUDIT_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
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


class ReasoningRunExecutionApiAuditBundleConsistencyContractError(Exception):
    """Task 054: the supplied bundle cannot be audited at all.

    Raised only when ``bundle`` is missing or is not a mapping. All
    other contract disagreements are reported through
    ``consistency_issues`` in the returned audit object rather than
    raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionApiAuditBundleConsistencyService:
    """Task 054: pure audit of a Task 053 API audit bundle.

    Consumes an already-built ReasoningRunExecutionApiAuditBundleRead,
    independently re-derives every bundle-consistency relationship, and
    reports disagreements through consistency_issues. Reuses Task 051's
    and Task 052's own validators for the nested results and reuses
    Task 052's package-fingerprint computation (without calling Task
    052's build()). Never queries the database, never performs HTTP,
    never calls Task 051/052/053 build or build_for_session workflows,
    never mutates its input.
    """

    def build(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied Task 053 bundle. Pure and deterministic."""
        if bundle is None:
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "MISSING_BUNDLE", "bundle is required"
            )
        if not isinstance(bundle, Mapping):
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "BUNDLE_TYPE",
                "bundle is not a mapping: " + type(bundle).__name__,
            )

        issues: list[str] = []

        # --- Top-level structure ---
        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in bundle:
                issues.append("MISSING_BUNDLE_FIELD")

        if bundle.get("available") is not True:
            issues.append("INVALID_BUNDLE_AVAILABLE")

        bundle_session_id = _coerce_session_id(bundle.get("session_id"))
        if bundle_session_id is None:
            issues.append("SESSION_ID_INVALID")

        path = bundle.get("path")
        if not isinstance(path, str):
            issues.append("PATH_INVALID")
        else:
            path_match = _PATH_PATTERN.match(path)
            if path_match is None:
                issues.append("PATH_INVALID")
            else:
                path_sid = _coerce_session_id(
                    path_match.group("session_id")
                )
                if path_sid is None:
                    issues.append("SESSION_ID_INVALID")
                elif (
                    bundle_session_id is not None
                    and path_sid != bundle_session_id
                ):
                    issues.append("SESSION_ID_MISMATCH")

        if bundle.get("method") != _EXPECTED_METHOD:
            issues.append("METHOD_INVALID")

        status_code = bundle.get("status_code")
        if (
            not isinstance(status_code, int)
            or isinstance(status_code, bool)
            or status_code != _EXPECTED_STATUS_CODE
        ):
            issues.append("STATUS_CODE_INVALID")

        # --- Nested Task 051 package ---
        api_audit_package = bundle.get("api_audit_package")
        if not isinstance(api_audit_package, Mapping):
            issues.append("NESTED_PACKAGE_MISMATCH")
        else:
            package_for_validation = _deep_normalize_session_ids(
                api_audit_package
            )
            try:
                ReasoningRunExecutionApiAuditPackageService._validate_result(
                    package_for_validation
                )
            except Exception:
                issues.append("NESTED_PACKAGE_MISMATCH")

        # --- Nested Task 052 audit ---
        api_audit_package_consistency = bundle.get(
            "api_audit_package_consistency"
        )
        if not isinstance(api_audit_package_consistency, Mapping):
            issues.append("NESTED_PACKAGE_AUDIT_MISMATCH")
        else:
            try:
                ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
                    dict(api_audit_package_consistency)
                )
            except Exception:
                issues.append("NESTED_PACKAGE_AUDIT_MISMATCH")

        # --- Session identity between bundle and nested Task 051 ---
        if (
            isinstance(api_audit_package, Mapping)
            and bundle_session_id is not None
        ):
            pkg_sid = _coerce_session_id(
                api_audit_package.get("session_id")
            )
            if pkg_sid != bundle_session_id:
                issues.append("PACKAGE_SESSION_MISMATCH")

        # --- HTTP metadata agreement with nested Task 051 ---
        if isinstance(api_audit_package, Mapping):
            if api_audit_package.get("method") != bundle.get("method"):
                issues.append("METHOD_MISMATCH")
            if api_audit_package.get("path") != bundle.get("path"):
                issues.append("PATH_MISMATCH")
            if api_audit_package.get("status_code") != bundle.get(
                "status_code"
            ):
                issues.append("STATUS_MISMATCH")

        # --- Task 052 availability ---
        if isinstance(api_audit_package_consistency, Mapping):
            if api_audit_package_consistency.get("available") is not True:
                issues.append("NESTED_PACKAGE_AUDIT_MISMATCH")

        # --- Provenance: recompute Task 051 package fingerprint ---
        if not isinstance(api_audit_package, Mapping) or not isinstance(
            api_audit_package_consistency, Mapping
        ):
            # Without both nested objects, the provenance check cannot
            # be performed. It must be reported explicitly so the
            # dedicated flag never reads True when no proof exists.
            issues.append("PROVENANCE_CHECK_UNAVAILABLE")
        else:
            # Failure to compute the proof is itself a provenance
            # failure. It must never be silently converted to a
            # skip-the-check that leaves the flag True.
            try:
                expected_fingerprint = (
                    ReasoningRunExecutionApiAuditPackageConsistencyService
                    ._package_fingerprint(api_audit_package)
                )
            except Exception:
                issues.append(
                    "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED"
                )
            else:
                if (
                    api_audit_package_consistency.get(
                        "audited_package_fingerprint"
                    )
                    != expected_fingerprint
                ):
                    issues.append("AUDITED_PACKAGE_FINGERPRINT_MISMATCH")

        # --- Bundle relationship ---
        # bundle.bundle_consistent must equal
        # api_audit_package_consistency.package_consistent.
        # (Task 053's own contract.)
        if isinstance(api_audit_package_consistency, Mapping):
            if bundle.get("bundle_consistent") != (
                api_audit_package_consistency.get("package_consistent")
            ):
                issues.append("BUNDLE_RELATIONSHIP_MISMATCH")

        # --- Sources ---
        if isinstance(api_audit_package, Mapping):
            if (
                api_audit_package.get("package_source")
                != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051
            ):
                issues.append("RESPONSE_PACKAGE_SOURCE_MISMATCH")
        if isinstance(api_audit_package_consistency, Mapping):
            if (
                api_audit_package_consistency.get(
                    "package_consistency_source"
                )
                != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052
            ):
                issues.append("PACKAGE_AUDIT_SOURCE_MISMATCH")
        if (
            bundle.get("bundle_source")
            != REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053
        ):
            issues.append("BUNDLE_SOURCE_MISMATCH")

        # --- Deterministic ordering, dedupe ---
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # --- Derive flags ---
        session_consistent = not any(
            i in unique_issues
            for i in (
                "SESSION_ID_INVALID",
                "SESSION_ID_MISMATCH",
                "PACKAGE_SESSION_MISMATCH",
            )
        )
        method_consistent = not any(
            i in unique_issues for i in ("METHOD_INVALID", "METHOD_MISMATCH")
        )
        path_consistent = not any(
            i in unique_issues
            for i in ("PATH_INVALID", "PATH_MISMATCH")
        )
        status_consistent = not any(
            i in unique_issues
            for i in ("STATUS_CODE_INVALID", "STATUS_MISMATCH")
        )
        nested_package_consistent = (
            "NESTED_PACKAGE_MISMATCH" not in unique_issues
        )
        nested_package_audit_consistent = (
            "NESTED_PACKAGE_AUDIT_MISMATCH" not in unique_issues
        )
        package_audit_provenance_consistent = not any(
            i in unique_issues
            for i in (
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "PROVENANCE_CHECK_UNAVAILABLE",
            )
        )
        bundle_relationship_consistent = (
            "BUNDLE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "RESPONSE_PACKAGE_SOURCE_MISMATCH",
                "PACKAGE_AUDIT_SOURCE_MISMATCH",
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

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "method_consistent": method_consistent,
            "path_consistent": path_consistent,
            "status_consistent": status_consistent,
            "nested_package_consistent": nested_package_consistent,
            "nested_package_audit_consistent": (
                nested_package_audit_consistent
            ),
            "package_audit_provenance_consistent": (
                package_audit_provenance_consistent
            ),
            "bundle_relationship_consistent": (
                bundle_relationship_consistent
            ),
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "bundle_consistency_source": (
                REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_054
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: "
                + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["bundle_consistency_source"]
            != REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_054
        ):
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "bundle_consistency_source is not the Task 054 "
                "identifier: "
                + repr(result["bundle_consistency_source"]),
            )
        if result["bundle_consistent"] != (len(issues) == 0):
            raise ReasoningRunExecutionApiAuditBundleConsistencyContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match consistency_issues",
            )

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run_execution_api_audit_package import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051,
    ReasoningRunExecutionApiAuditPackageService,
)
from rop.services.reasoning_run_execution_audit_package import (
    REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048,
    ReasoningRunExecutionAuditPackageService,
)
from rop.services.reasoning_run_execution_audit_package_api_consistency import (
    REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050,
    ReasoningRunExecutionAuditPackageApiConsistencyService,
)

REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052 = (
    "REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_TASK_052"
)

_PACKAGE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "response",
    "api_consistency",
    "package_source",
)

_EXPECTED_STATUS_CODE = 200
_PATH_PATTERN = re.compile(
    r"^/sessions/(?P<session_id>[^/]+)"
    r"/reasoning-run/execute-fully-audited$"
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_package_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_PACKAGE_FIELD",
    "INVALID_PACKAGE_AVAILABLE",
    "SESSION_ID_INVALID",
    "METHOD_INVALID",
    "PATH_INVALID",
    "STATUS_CODE_INVALID",
    "NESTED_RESPONSE_MISMATCH",
    "NESTED_API_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "AUDITED_SESSION_ID_MISMATCH",
    "AUDITED_METHOD_MISMATCH",
    "AUDITED_PATH_MISMATCH",
    "AUDITED_STATUS_CODE_MISMATCH",
    "AUDITED_RESPONSE_FINGERPRINT_MISMATCH",
    "PACKAGE_RELATIONSHIP_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
    "API_CONSISTENCY_SOURCE_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
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


class ReasoningRunExecutionApiAuditPackageConsistencyContractError(Exception):
    """Task 052: the supplied package cannot be audited at all.

    Raised only when ``package`` is missing or is not a mapping. All
    other contract disagreements are reported through
    ``consistency_issues`` in the returned audit object rather than
    raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionApiAuditPackageConsistencyService:
    """Task 052: pure audit of a Task 051 API audit package.

    Consumes an already-built ReasoningRunExecutionApiAuditPackageRead,
    independently re-derives every consistency relationship, and
    reports disagreements through consistency_issues. Reuses Task 048's
    and Task 050's own validators for the nested results and reuses
    Task 050's response-fingerprint computation (without calling Task
    050's build()). Never queries the database, never performs HTTP,
    never calls Task 048/049/050/051 build or build_for_session
    workflows, never mutates its input.
    """

    def build(
        self,
        *,
        package: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied Task 051 package. Pure and deterministic."""
        if package is None:
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "MISSING_PACKAGE", "package is required"
            )
        if not isinstance(package, Mapping):
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "PACKAGE_TYPE",
                "package is not a mapping: " + type(package).__name__,
            )

        issues: list[str] = []

        # --- Top-level structure ---
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in package:
                issues.append("MISSING_PACKAGE_FIELD")

        if package.get("available") is not True:
            issues.append("INVALID_PACKAGE_AVAILABLE")

        package_session_id = _coerce_session_id(package.get("session_id"))
        if package_session_id is None:
            issues.append("SESSION_ID_INVALID")

        if package.get("method") != "POST":
            issues.append("METHOD_INVALID")

        path = package.get("path")
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
                    package_session_id is not None
                    and path_sid != package_session_id
                ):
                    issues.append("SESSION_ID_MISMATCH")

        status_code = package.get("status_code")
        if (
            not isinstance(status_code, int)
            or isinstance(status_code, bool)
        ):
            issues.append("STATUS_CODE_INVALID")
        elif status_code != _EXPECTED_STATUS_CODE:
            issues.append("STATUS_CODE_INVALID")

        # --- Nested Task 048 response ---
        response = package.get("response")
        response_valid = False
        if not isinstance(response, Mapping):
            issues.append("NESTED_RESPONSE_MISMATCH")
        else:
            response_for_validation = _deep_normalize_session_ids(response)
            try:
                ReasoningRunExecutionAuditPackageService._validate_result(
                    response_for_validation
                )
                response_valid = True
            except Exception:
                issues.append("NESTED_RESPONSE_MISMATCH")

        # --- Nested Task 050 API consistency result ---
        api_consistency = package.get("api_consistency")
        api_consistency_valid = False
        if not isinstance(api_consistency, Mapping):
            issues.append("NESTED_API_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningRunExecutionAuditPackageApiConsistencyService._validate_result(
                    dict(api_consistency)
                )
                api_consistency_valid = True
            except Exception:
                issues.append("NESTED_API_CONSISTENCY_MISMATCH")

        # --- Nested Task 050 semantic flags ---
        # The Task 050 validator does not guarantee these relationships,
        # so Task 052 checks them explicitly. Any of the five core
        # semantic flags being false means the nested audit itself
        # reports the response as problematic.
        if api_consistency_valid:
            for flag in (
                "available",
                "session_consistent",
                "method_consistent",
                "path_consistent",
                "status_consistent",
            ):
                if api_consistency.get(flag) is not True:
                    issues.append("NESTED_API_CONSISTENCY_MISMATCH")

        # --- Session consistency ---
        # str(package.session_id) == str(response.session_id).
        # Checked independently of whether the nested response passed
        # its own validator: a response whose session_id disagrees with
        # the package is a session mismatch regardless of other
        # structural problems.
        if isinstance(response, Mapping) and package_session_id is not None:
            response_sid = _coerce_session_id(response.get("session_id"))
            if response_sid != package_session_id:
                issues.append("SESSION_ID_MISMATCH")

        # str(package.session_id) == api_consistency.audited_session_id
        if api_consistency_valid and package_session_id is not None:
            audited_sid = api_consistency.get("audited_session_id")
            if audited_sid != str(package_session_id):
                issues.append("AUDITED_SESSION_ID_MISMATCH")

        # --- Method / path / status consistency with the audit provenance ---
        if api_consistency_valid:
            if api_consistency.get("audited_method") != package.get("method"):
                issues.append("AUDITED_METHOD_MISMATCH")
            if api_consistency.get("audited_path") != package.get("path"):
                issues.append("AUDITED_PATH_MISMATCH")
            if api_consistency.get("audited_status_code") != package.get(
                "status_code"
            ):
                issues.append("AUDITED_STATUS_CODE_MISMATCH")

        # --- Response provenance: recompute fingerprint independently ---
        if (
            api_consistency_valid
            and isinstance(response, Mapping)
            and package.get("response") is not None
        ):
            try:
                expected_fingerprint = (
                    ReasoningRunExecutionAuditPackageApiConsistencyService
                    ._response_fingerprint(response)
                )
            except Exception:
                expected_fingerprint = None
            if (
                expected_fingerprint is not None
                and api_consistency.get("audited_response_fingerprint")
                != expected_fingerprint
            ):
                issues.append("AUDITED_RESPONSE_FINGERPRINT_MISMATCH")

        # --- Package relationship ---
        # package.package_consistent == api_consistency.api_consistent
        # (never compared to response.package_consistent)
        if api_consistency_valid:
            if package.get("package_consistent") != api_consistency.get(
                "api_consistent"
            ):
                issues.append("PACKAGE_RELATIONSHIP_MISMATCH")

        # --- Sources ---
        if isinstance(response, Mapping):
            if (
                response.get("package_source")
                != REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048
            ):
                issues.append("RESPONSE_SOURCE_MISMATCH")
        if isinstance(api_consistency, Mapping):
            if (
                api_consistency.get("api_consistency_source")
                != REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050
            ):
                issues.append("API_CONSISTENCY_SOURCE_MISMATCH")
        if (
            package.get("package_source")
            != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051
        ):
            issues.append("PACKAGE_SOURCE_MISMATCH")

        # --- Task 051 contract fallback ---
        # Belt-and-suspenders: run Task 051's own validator on a
        # normalized copy. If it fails AND no specific issue above
        # already explains why, report PACKAGE_CONTRACT_MISMATCH, so
        # Task 052 cannot silently accept something Task 051 itself
        # would reject.
        if not issues:
            try:
                ReasoningRunExecutionApiAuditPackageService._validate_result(
                    _deep_normalize_session_ids(package)
                )
            except Exception:
                issues.append("PACKAGE_CONTRACT_MISMATCH")

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
                "AUDITED_SESSION_ID_MISMATCH",
            )
        )
        method_consistent = "METHOD_INVALID" not in unique_issues and (
            "AUDITED_METHOD_MISMATCH" not in unique_issues
        )
        path_consistent = "PATH_INVALID" not in unique_issues and (
            "AUDITED_PATH_MISMATCH" not in unique_issues
        )
        status_consistent = not any(
            i in unique_issues
            for i in ("STATUS_CODE_INVALID", "AUDITED_STATUS_CODE_MISMATCH")
        )
        nested_response_consistent = (
            "NESTED_RESPONSE_MISMATCH" not in unique_issues
        )
        nested_api_consistency_consistent = (
            "NESTED_API_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = (
            "AUDITED_RESPONSE_FINGERPRINT_MISMATCH" not in unique_issues
        )
        package_relationship_consistent = (
            "PACKAGE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "RESPONSE_SOURCE_MISMATCH",
                "API_CONSISTENCY_SOURCE_MISMATCH",
                "PACKAGE_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in (
                "MISSING_PACKAGE_FIELD",
                "INVALID_PACKAGE_AVAILABLE",
            )
        )

        try:
            audited_package_fingerprint = (
                ReasoningRunExecutionApiAuditPackageConsistencyService
                ._package_fingerprint(package)
            )
        except Exception as exc:
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute the audited package fingerprint: "
                + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "method_consistent": method_consistent,
            "path_consistent": path_consistent,
            "status_consistent": status_consistent,
            "nested_response_consistent": nested_response_consistent,
            "nested_api_consistency_consistent": (
                nested_api_consistency_consistent
            ),
            "provenance_consistent": provenance_consistent,
            "package_relationship_consistent": (
                package_relationship_consistent
            ),
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "package_consistency_source": (
                REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052
            ),
            "audited_package_fingerprint": audited_package_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        """Return a deterministic, JSON-serializable canonical form."""
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(k):
                    ReasoningRunExecutionApiAuditPackageConsistencyService
                    ._canonicalize(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [
                ReasoningRunExecutionApiAuditPackageConsistencyService
                ._canonicalize(item)
                for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _package_fingerprint(package: Mapping[str, Any]) -> str:
        """Return a SHA-256 hex digest of the canonicalized package."""
        canonical = (
            ReasoningRunExecutionApiAuditPackageConsistencyService
            ._canonicalize(package)
        )
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: "
                + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["package_consistency_source"]
            != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052
        ):
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                "package_consistency_source is not the Task 052 "
                "identifier: "
                + repr(result["package_consistency_source"]),
            )
        if result["package_consistent"] != (len(issues) == 0):
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match consistency_issues",
            )
        fp = result["audited_package_fingerprint"]
        if not isinstance(fp, str) or not (
            _PACKAGE_FINGERPRINT_HEX_RE.match(fp)
        ):
            raise ReasoningRunExecutionApiAuditPackageConsistencyContractError(
                "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
                "audited_package_fingerprint is not a 64-char lowercase "
                "hex string: " + repr(fp),
            )

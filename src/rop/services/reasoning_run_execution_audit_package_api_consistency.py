from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run_execution_audit_package import (
    REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048,
    ReasoningRunExecutionAuditPackageService,
)

REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050 = (
    "REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_TASK_050"
)

_EXPECTED_METHOD = "POST"
_EXPECTED_STATUS = 200
_PATH_PATTERN = re.compile(
    r"^/sessions/(?P<session_id>[^/]+)" r"/reasoning-run/execute-fully-audited$"
)

_EXPECTED_BODY_FIELDS = frozenset(
    {
        "available",
        "package_consistent",
        "session_id",
        "execution_bundle",
        "bundle_consistency",
        "package_source",
    }
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_package_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "api_consistency_source",
    "audited_session_id",
    "audited_method",
    "audited_path",
    "audited_status_code",
    "audited_response_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_package_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_RESPONSE_FIELD",
    "INVALID_METHOD",
    "INVALID_PATH",
    "INVALID_STATUS",
    "SESSION_ID_INVALID",
    "SESSION_ID_MISMATCH",
    "RESPONSE_SHAPE_MISMATCH",
    "NESTED_PACKAGE_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "API_SOURCE_MISMATCH",
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
    """Return a deep copy with every 'session_id' string coerced to UUID.

    Recursively walks mappings and lists. Non-mapping, non-list, or
    malformed session_id values are left unchanged so upstream
    validators can still report them.
    """
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


class ReasoningRunExecutionAuditPackageApiConsistencyContractError(Exception):
    """Task 050: the supplied API response cannot be audited at all.

    Raised only when ``response_body`` is missing or not a mapping --
    i.e. there is no API response to audit. Ordinary contract
    disagreements (wrong method, path, status, session, shape, nested
    package, or source) are reported through consistency_issues.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionAuditPackageApiConsistencyService:
    """Task 050: pure audit of a Task 049 API response.

    Consumes an already-produced API response (method, path, status
    code, body) plus the expected session_id, and independently
    verifies that the response faithfully represents the canonical
    Task 048 package contract. Reuses Task 048's own validator for the
    nested package. Never queries the database, never invokes Task
    049 or Task 048's build_for_session, never mutates its input.
    """

    def build(
        self,
        *,
        session_id: Any = None,
        method: Any = None,
        path: Any = None,
        status_code: Any = None,
        response_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied API response. Pure and deterministic."""
        if response_body is None:
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "MISSING_RESPONSE_BODY", "response_body is required"
            )
        if not isinstance(response_body, Mapping):
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "RESPONSE_BODY_TYPE",
                "response_body is not a mapping: " + type(response_body).__name__,
            )

        issues: list[str] = []

        # Session id (the externally supplied one).
        sid = _coerce_session_id(session_id)
        if sid is None:
            issues.append("SESSION_ID_INVALID")

        # Method check: the Task 050 contract requires exactly "POST".
        # No case normalization -- "post", "Post", and "pOsT" are all
        # invalid HTTP method representations of the contract.
        if method != _EXPECTED_METHOD:
            issues.append("INVALID_METHOD")

        # Path check.
        if not isinstance(path, str):
            issues.append("INVALID_PATH")
        else:
            match = _PATH_PATTERN.match(path)
            if match is None:
                issues.append("INVALID_PATH")
            else:
                path_sid = _coerce_session_id(match.group("session_id"))
                if path_sid is None:
                    issues.append("SESSION_ID_INVALID")
                elif sid is not None and path_sid != sid:
                    issues.append("SESSION_ID_MISMATCH")

        # Status check.
        if status_code != _EXPECTED_STATUS:
            issues.append("INVALID_STATUS")

        # Response body shape.
        body_keys = set(response_body.keys())
        if _EXPECTED_BODY_FIELDS - body_keys:
            issues.append("MISSING_RESPONSE_FIELD")
        if body_keys != _EXPECTED_BODY_FIELDS:
            issues.append("RESPONSE_SHAPE_MISMATCH")

        # Body session id.
        body_sid = _coerce_session_id(response_body.get("session_id"))
        if body_sid is None:
            issues.append("SESSION_ID_INVALID")
        elif sid is not None and body_sid != sid:
            issues.append("SESSION_ID_MISMATCH")

        # Nested Task 048 package validation. Over HTTP, session_id
        # arrives as a string at every nesting level; the upstream
        # validators require UUIDs. Deep-normalize on a copy so we can
        # delegate to Task 048's validator without mutating the input.
        body_for_validation = _deep_normalize_session_ids(response_body)
        try:
            ReasoningRunExecutionAuditPackageService._validate_result(
                body_for_validation
            )
        except Exception:
            issues.append("NESTED_PACKAGE_MISMATCH")

        # Task 048 package_source check.
        if (
            response_body.get("package_source")
            != REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048
        ):
            issues.append("PACKAGE_SOURCE_MISMATCH")

        # Provenance: bind the audit to the exact inputs it audited.
        raw_session_id_for_provenance = session_id
        if isinstance(raw_session_id_for_provenance, UUID):
            audited_session_id = str(raw_session_id_for_provenance)
        elif isinstance(raw_session_id_for_provenance, str):
            audited_session_id = raw_session_id_for_provenance
        else:
            audited_session_id = None

        audited_method = method if isinstance(method, str) else None
        audited_path = path if isinstance(path, str) else None
        audited_status_code = (
            status_code
            if isinstance(status_code, int) and not isinstance(status_code, bool)
            else None
        )
        audited_response_fingerprint = ReasoningRunExecutionAuditPackageApiConsistencyService._response_fingerprint(  # noqa: E501
            response_body
        )

        # Deterministic ordering, dedupe.
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # Derive flags.
        method_consistent = "INVALID_METHOD" not in unique_issues
        path_consistent = "INVALID_PATH" not in unique_issues
        status_consistent = "INVALID_STATUS" not in unique_issues
        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        response_shape_consistent = not any(
            i in unique_issues
            for i in ("MISSING_RESPONSE_FIELD", "RESPONSE_SHAPE_MISMATCH")
        )
        nested_package_consistent = "NESTED_PACKAGE_MISMATCH" not in unique_issues
        source_consistency = "PACKAGE_SOURCE_MISMATCH" not in unique_issues
        metadata_consistent = not any(
            i in unique_issues
            for i in (
                "INVALID_METHOD",
                "INVALID_PATH",
                "INVALID_STATUS",
                "SESSION_ID_INVALID",
                "SESSION_ID_MISMATCH",
                "MISSING_RESPONSE_FIELD",
                "RESPONSE_SHAPE_MISMATCH",
            )
        )

        result: dict[str, Any] = {
            "available": True,
            "api_consistent": not ordered_issues,
            "method_consistent": method_consistent,
            "path_consistent": path_consistent,
            "status_consistent": status_consistent,
            "session_consistent": session_consistent,
            "response_shape_consistent": response_shape_consistent,
            "nested_package_consistent": nested_package_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "api_consistency_source": (
                REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050
            ),
            "audited_session_id": audited_session_id,
            "audited_method": audited_method,
            "audited_path": audited_path,
            "audited_status_code": audited_status_code,
            "audited_response_fingerprint": audited_response_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        """Return a deterministic, JSON-serializable canonical form.

        UUIDs become strings so in-process UUID representations and
        JSON string representations of the same response body hash
        identically. Mapping keys are sorted.
        """
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(
                    k
                ): ReasoningRunExecutionAuditPackageApiConsistencyService._canonicalize(
                    v
                )
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [
                ReasoningRunExecutionAuditPackageApiConsistencyService._canonicalize(
                    item
                )
                for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _response_fingerprint(response_body: Mapping[str, Any]) -> str:
        """Return a deterministic SHA-256 hex digest of the response body.

        Stable across repeated identical inputs and across UUID-vs-string
        representations of the same logical response.
        """
        canonical = (
            ReasoningRunExecutionAuditPackageApiConsistencyService._canonicalize(
                response_body
            )
        )
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["api_consistency_source"]
            != REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050
        ):
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "API_SOURCE_MISMATCH",
                "api_consistency_source is not the Task 050 identifier: "
                + repr(result["api_consistency_source"]),
            )
        if result["api_consistent"] != (len(issues) == 0):
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "API_CONSISTENT_MISMATCH",
                "api_consistent does not match consistency_issues",
            )
        # Provenance field types (all nullable).
        for field in (
            "audited_session_id",
            "audited_method",
            "audited_path",
            "audited_response_fingerprint",
        ):
            value = result[field]
            if value is not None and not isinstance(value, str):
                raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not a string or None: " + repr(value),
                )
        raw_status = result["audited_status_code"]
        if raw_status is not None and (
            not isinstance(raw_status, int) or isinstance(raw_status, bool)
        ):
            raise ReasoningRunExecutionAuditPackageApiConsistencyContractError(
                "AUDITED_STATUS_CODE_TYPE",
                "audited_status_code is not an int or None: " + repr(raw_status),
            )

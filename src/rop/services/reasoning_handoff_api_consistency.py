"""Task 060: pure audit of a Task 059 reasoning-handoff HTTP response.

Consumes already-supplied HTTP metadata and a response body. Does not
call the API, does not rebuild the handoff, does not touch the
database, does not import FastAPI or any HTTP client. Reuses Task 057's
own ``_validate_result`` for the nested handoff contract -- never
re-implements Task 055/056/057 rules.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff import (
    REASONING_HANDOFF_TASK_057,
    ReasoningHandoffService,
)

REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060 = (
    "REASONING_HANDOFF_API_CONSISTENCY_TASK_060"
)

_RESPONSE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Fields the Task 057 handoff exposes. The response body must contain
# exactly these -- missing is MISSING_RESPONSE_FIELD, extras are
# RESPONSE_SHAPE_MISMATCH.
_EXPECTED_RESPONSE_FIELDS = (
    "available",
    "handoff_consistent",
    "session_id",
    "reasoning_context",
    "context_consistency",
    "handoff_source",
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS_CODE = 200
_PATH_PATTERN = re.compile(r"^/sessions/(?P<session_id>[^/]+)/reasoning-handoff$")

_RESULT_REQUIRED_FIELDS = (
    "available",
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_handoff_consistent",
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
    "nested_handoff_consistent",
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
    "NESTED_HANDOFF_MISMATCH",
    "HANDOFF_SOURCE_MISMATCH",
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

    The HTTP layer serializes UUIDs as strings. Task 057's own
    validator expects UUID objects. This helper bridges the two
    without mutating the supplied body.
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


class ReasoningHandoffApiConsistencyContractError(Exception):
    """Task 060: the supplied input cannot be audited at all.

    Raised only when ``response_body`` is missing or is not a mapping.
    Every other transport/body disagreement is reported through
    ``consistency_issues`` in the returned audit result.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffApiConsistencyService:
    """Task 060: pure audit of a Task 059 HTTP response.

    Consumes an already-captured HTTP response (method, path, status,
    body) and independently determines whether it faithfully represents
    the Task 057 handoff contract. Never calls the API, never rebuilds
    the handoff, never touches the database, never mutates inputs.
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
        """Audit the supplied HTTP response. Pure and deterministic."""
        if response_body is None:
            raise ReasoningHandoffApiConsistencyContractError(
                "MISSING_RESPONSE_BODY", "response_body is required"
            )
        if not isinstance(response_body, Mapping):
            raise ReasoningHandoffApiConsistencyContractError(
                "RESPONSE_BODY_TYPE",
                "response_body is not a mapping: " + type(response_body).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        # --- Transport: method ---
        if method != _EXPECTED_METHOD:
            _add("INVALID_METHOD")

        # --- Transport: path ---
        path_match = None
        if not isinstance(path, str):
            _add("INVALID_PATH")
        else:
            path_match = _PATH_PATTERN.match(path)
            if path_match is None:
                _add("INVALID_PATH")

        # --- Transport: status ---
        if not isinstance(status_code, int) or isinstance(status_code, bool):
            _add("INVALID_STATUS")
        elif status_code != _EXPECTED_STATUS_CODE:
            _add("INVALID_STATUS")

        # --- Session identity: supplied vs. path ---
        supplied_session = _coerce_session_id(session_id)
        if supplied_session is None:
            _add("SESSION_ID_INVALID")
        if path_match is not None:
            path_session = _coerce_session_id(path_match.group("session_id"))
            if path_session is None:
                _add("SESSION_ID_INVALID")
            elif supplied_session is not None and path_session != supplied_session:
                _add("SESSION_ID_MISMATCH")

        # --- Response shape ---
        for field in _EXPECTED_RESPONSE_FIELDS:
            if field not in response_body:
                _add("MISSING_RESPONSE_FIELD")
        extras = set(response_body.keys()) - set(_EXPECTED_RESPONSE_FIELDS)
        if extras:
            _add("RESPONSE_SHAPE_MISMATCH")

        # --- Response session id ---
        response_session = _coerce_session_id(response_body.get("session_id"))
        if response_session is None:
            _add("SESSION_ID_INVALID")
        elif supplied_session is not None and response_session != supplied_session:
            _add("SESSION_ID_MISMATCH")

        # --- Nested handoff validation via Task 057's own validator ---
        # Task 057 expects UUID objects for session ids. The HTTP body
        # has strings. Normalize a deep copy -- never the original.
        normalized = _deep_normalize_session_ids(response_body)
        try:
            ReasoningHandoffService._validate_result(normalized)
        except Exception:
            _add("NESTED_HANDOFF_MISMATCH")

        # --- Source check ---
        if response_body.get("handoff_source") != REASONING_HANDOFF_TASK_057:
            _add("HANDOFF_SOURCE_MISMATCH")

        # --- Deterministic ordering, dedupe ---
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # --- Derive flags ---
        method_consistent = "INVALID_METHOD" not in unique_issues
        path_consistent = "INVALID_PATH" not in unique_issues
        status_consistent = "INVALID_STATUS" not in unique_issues
        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        response_shape_consistent = not any(
            i in unique_issues
            for i in (
                "MISSING_RESPONSE_FIELD",
                "RESPONSE_SHAPE_MISMATCH",
            )
        )
        nested_handoff_consistent = "NESTED_HANDOFF_MISMATCH" not in unique_issues
        source_consistency = "HANDOFF_SOURCE_MISMATCH" not in unique_issues
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

        # --- Provenance: audited inputs, echoed back verbatim ---
        audited_session_id: str | None
        if isinstance(session_id, UUID):
            audited_session_id = str(session_id)
        elif isinstance(session_id, str):
            audited_session_id = session_id
        else:
            audited_session_id = None

        audited_method: str | None = method if isinstance(method, str) else None
        audited_path: str | None = path if isinstance(path, str) else None
        audited_status_code: int | None = (
            status_code
            if isinstance(status_code, int) and not isinstance(status_code, bool)
            else None
        )

        try:
            audited_response_fingerprint = (
                ReasoningHandoffApiConsistencyService._response_fingerprint(
                    response_body
                )
            )
        except Exception as exc:
            raise ReasoningHandoffApiConsistencyContractError(
                "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute the audited response fingerprint: " + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "api_consistent": not ordered_issues,
            "method_consistent": method_consistent,
            "path_consistent": path_consistent,
            "status_consistent": status_consistent,
            "session_consistent": session_consistent,
            "response_shape_consistent": response_shape_consistent,
            "nested_handoff_consistent": nested_handoff_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "api_consistency_source": (
                REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060
            ),
            "audited_session_id": audited_session_id,
            "audited_method": audited_method,
            "audited_path": audited_path,
            "audited_status_code": audited_status_code,
            "audited_response_fingerprint": (audited_response_fingerprint),
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
                str(k): ReasoningHandoffApiConsistencyService._canonicalize(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [
                ReasoningHandoffApiConsistencyService._canonicalize(item)
                for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _response_fingerprint(response_body: Mapping[str, Any]) -> str:
        """SHA-256 hex digest of the canonicalized response body."""
        canonical = ReasoningHandoffApiConsistencyService._canonicalize(response_body)
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffApiConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffApiConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningHandoffApiConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningHandoffApiConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningHandoffApiConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningHandoffApiConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["api_consistency_source"]
            != REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060
        ):
            raise ReasoningHandoffApiConsistencyContractError(
                "INVALID_SOURCE",
                "api_consistency_source is not the Task 060 "
                "identifier: " + repr(result["api_consistency_source"]),
            )
        if result["api_consistent"] != (len(issues) == 0):
            raise ReasoningHandoffApiConsistencyContractError(
                "API_CONSISTENT_MISMATCH",
                "api_consistent does not match consistency_issues",
            )
        for field in (
            "audited_session_id",
            "audited_method",
            "audited_path",
        ):
            value = result[field]
            if value is not None and not isinstance(value, str):
                raise ReasoningHandoffApiConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is neither str nor None: " + repr(value),
                )
        sc = result["audited_status_code"]
        if sc is not None and (not isinstance(sc, int) or isinstance(sc, bool)):
            raise ReasoningHandoffApiConsistencyContractError(
                "AUDITED_STATUS_CODE_TYPE",
                "audited_status_code is neither int nor None: " + repr(sc),
            )
        fp = result["audited_response_fingerprint"]
        if not isinstance(fp, str) or not (_RESPONSE_FINGERPRINT_HEX_RE.fullmatch(fp)):
            raise ReasoningHandoffApiConsistencyContractError(
                "AUDITED_RESPONSE_FINGERPRINT_FORMAT",
                "audited_response_fingerprint is not a 64-char "
                "lowercase hex string: " + repr(fp),
            )

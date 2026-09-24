"""Task 066: pure audit of a Task 065 fully audited API response.

Consumes an already-captured HTTP response (method, path, status, body)
for the Task 065 ``/sessions/{session_id}/reasoning-handoff/fully-audited``
route and independently determines whether it faithfully represents the
Task 063 audit bundle contract. Reuses Task 063's own validator for the
nested bundle, Task 062's own validator for the nested package audit, and
Task 062's own package-fingerprint helper for the provenance proof --
never reimplementing Tasks 058-064 rules.

Never queries the database, never performs HTTP, never calls the Task 065
endpoint, never invokes Task 061/062/063 build workflows, never mutates
its input.
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
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    ReasoningHandoffApiAuditPackageConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_TASK_066"
)

_RESPONSE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Fields the Task 065 endpoint exposes. The response body must contain
# exactly these -- missing is MISSING_RESPONSE_FIELD, extras are
# RESPONSE_SHAPE_MISMATCH.
_EXPECTED_RESPONSE_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS_CODE = 200
_PATH_PATTERN = re.compile(
    r"^/sessions/(?P<session_id>[^/]+)/reasoning-handoff/fully-audited$"
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_bundle_consistent",
    "nested_package_audit_consistent",
    "provenance_consistent",
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
    "nested_bundle_consistent",
    "nested_package_audit_consistent",
    "provenance_consistent",
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
    "NESTED_BUNDLE_MISMATCH",
    "NESTED_PACKAGE_AUDIT_MISMATCH",
    "NESTED_PACKAGE_FINGERPRINT_MISMATCH",
    "NESTED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
    "NESTED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
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
    """Return a deep copy with every 'session_id' string coerced to UUID.

    The HTTP layer serializes UUIDs as strings. Upstream validators expect
    UUID objects. This helper bridges the two without mutating the
    supplied body.
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


class ReasoningHandoffFullyAuditedApiConsistencyContractError(Exception):
    """Task 066: the supplied API response cannot be audited at all.

    Raised only when ``response_body`` is missing or is not a mapping, or
    when the audited response fingerprint cannot be computed. Every other
    transport/body disagreement is reported through ``consistency_issues``
    in the returned audit result.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffFullyAuditedApiConsistencyService:
    """Task 066: pure audit of a Task 065 API response.

    Consumes an already-captured HTTP response and independently
    determines whether it faithfully represents the Task 063 audit
    bundle contract. Never calls the endpoint, never rebuilds any
    upstream layer, never touches the database, never mutates inputs.
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
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "MISSING_RESPONSE_BODY", "response_body is required"
            )
        if not isinstance(response_body, Mapping):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
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

        # --- Response session id (top-level) ---
        response_session = _coerce_session_id(response_body.get("session_id"))
        if response_session is None:
            _add("SESSION_ID_INVALID")
        elif supplied_session is not None and response_session != supplied_session:
            _add("SESSION_ID_MISMATCH")

        package = response_body.get("api_audit_package")

        # --- Response session id vs nested Task 063 bundle session id ---
        # Checked explicitly here because Task 063's validator does not
        # compare the bundle's top-level session_id against the nested
        # package session in every failure mode.
        if isinstance(package, Mapping):
            nested_session = _coerce_session_id(package.get("session_id"))
            if (
                response_session is not None
                and nested_session is not None
                and nested_session != response_session
            ):
                _add("SESSION_ID_MISMATCH")

        # --- Nested Task 063 bundle validation via its own validator ---
        normalized = _deep_normalize_session_ids(response_body)
        try:
            ReasoningHandoffApiAuditBundleService._validate_result(normalized)
        except Exception:
            _add("NESTED_BUNDLE_MISMATCH")

        # --- Nested Task 062 package audit validation via its validator ---
        nested_audit = response_body.get("api_audit_package_consistency")
        nested_audit_valid = False
        if not isinstance(nested_audit, Mapping):
            _add("NESTED_PACKAGE_AUDIT_MISMATCH")
        else:
            try:
                ReasoningHandoffApiAuditPackageConsistencyService._validate_result(
                    dict(nested_audit)
                )
                nested_audit_valid = True
            except Exception:
                _add("NESTED_PACKAGE_AUDIT_MISMATCH")

        # --- Provenance: the nested audit must bind to the nested package ---
        # "Could not verify" must never silently become "verified".
        if nested_audit_valid and isinstance(package, Mapping):
            try:
                fingerprint_service = ReasoningHandoffApiAuditPackageConsistencyService
                expected_fingerprint = fingerprint_service._package_fingerprint(package)
            except Exception:
                _add("NESTED_PACKAGE_FINGERPRINT_COMPUTE_FAILED")
            else:
                if (
                    nested_audit.get("audited_package_fingerprint")
                    != expected_fingerprint
                ):
                    _add("NESTED_PACKAGE_FINGERPRINT_MISMATCH")
        else:
            _add("NESTED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE")

        # --- Source check ---
        if (
            response_body.get("bundle_source")
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        ):
            _add("BUNDLE_SOURCE_MISMATCH")

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
        nested_bundle_consistent = "NESTED_BUNDLE_MISMATCH" not in unique_issues
        nested_package_audit_consistent = (
            "NESTED_PACKAGE_AUDIT_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "NESTED_PACKAGE_FINGERPRINT_MISMATCH",
                "NESTED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "NESTED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        source_consistency = "BUNDLE_SOURCE_MISMATCH" not in unique_issues
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
                ReasoningHandoffFullyAuditedApiConsistencyService._response_fingerprint(
                    response_body
                )
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
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
            "nested_bundle_consistent": nested_bundle_consistent,
            "nested_package_audit_consistent": nested_package_audit_consistent,
            "provenance_consistent": provenance_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "api_consistency_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
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
        """Return a deterministic, JSON-serializable canonical form."""
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(k): ReasoningHandoffFullyAuditedApiConsistencyService._canonicalize(
                    v
                )
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [
                ReasoningHandoffFullyAuditedApiConsistencyService._canonicalize(item)
                for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _response_fingerprint(response_body: Mapping[str, Any]) -> str:
        """SHA-256 hex digest of the canonicalized response body."""
        canonical = ReasoningHandoffFullyAuditedApiConsistencyService._canonicalize(
            response_body
        )
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["api_consistency_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
        ):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "INVALID_SOURCE",
                "api_consistency_source is not the Task 066 identifier: "
                + repr(result["api_consistency_source"]),
            )
        if result["api_consistent"] != (len(issues) == 0):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
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
                raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is neither str nor None: " + repr(value),
                )
        sc = result["audited_status_code"]
        if sc is not None and (not isinstance(sc, int) or isinstance(sc, bool)):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "AUDITED_STATUS_CODE_TYPE",
                "audited_status_code is neither int nor None: " + repr(sc),
            )
        fp = result["audited_response_fingerprint"]
        if not isinstance(fp, str) or not (_RESPONSE_FINGERPRINT_HEX_RE.fullmatch(fp)):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "AUDITED_RESPONSE_FINGERPRINT_FORMAT",
                "audited_response_fingerprint is not a 64-char lowercase "
                "hex string: " + repr(fp),
            )

        issue_set = set(issues)
        expected_method_consistent = "INVALID_METHOD" not in issue_set
        if result["method_consistent"] != expected_method_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "METHOD_CONSISTENT_MISMATCH",
                "method_consistent does not match consistency_issues",
            )
        expected_path_consistent = "INVALID_PATH" not in issue_set
        if result["path_consistent"] != expected_path_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "PATH_CONSISTENT_MISMATCH",
                "path_consistent does not match consistency_issues",
            )
        expected_status_consistent = "INVALID_STATUS" not in issue_set
        if result["status_consistent"] != expected_status_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "STATUS_CONSISTENT_MISMATCH",
                "status_consistent does not match consistency_issues",
            )
        expected_session_consistent = not any(
            i in issue_set for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        if result["session_consistent"] != expected_session_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match consistency_issues",
            )
        # Coherence: build() only ever displays an unproven session (None
        # or an unparseable string) when coercion failed, which always
        # records SESSION_ID_INVALID. A silently unproven session must
        # never ride alongside session_consistent=True.
        audited_sid = result["audited_session_id"]
        if audited_sid is None:
            sid_provable = False
        else:
            try:
                UUID(audited_sid)
            except (ValueError, TypeError):
                sid_provable = False
            else:
                sid_provable = True
        if not sid_provable and "SESSION_ID_INVALID" not in issue_set:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "AUDITED_SESSION_ID_INCOHERENT",
                "audited_session_id is not a UUID yet SESSION_ID_INVALID "
                "is absent: " + repr(audited_sid),
            )
        expected_response_shape_consistent = not any(
            i in issue_set
            for i in ("MISSING_RESPONSE_FIELD", "RESPONSE_SHAPE_MISMATCH")
        )
        if result["response_shape_consistent"] != expected_response_shape_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "RESPONSE_SHAPE_CONSISTENT_MISMATCH",
                "response_shape_consistent does not match consistency_issues",
            )
        expected_nested_bundle_consistent = "NESTED_BUNDLE_MISMATCH" not in issue_set
        if result["nested_bundle_consistent"] != expected_nested_bundle_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "NESTED_BUNDLE_CONSISTENT_MISMATCH",
                "nested_bundle_consistent does not match consistency_issues",
            )
        expected_nested_package_audit_consistent = (
            "NESTED_PACKAGE_AUDIT_MISMATCH" not in issue_set
        )
        if (
            result["nested_package_audit_consistent"]
            != expected_nested_package_audit_consistent
        ):
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "NESTED_PACKAGE_AUDIT_CONSISTENT_MISMATCH",
                "nested_package_audit_consistent does not match " "consistency_issues",
            )
        expected_provenance_consistent = not any(
            i in issue_set
            for i in (
                "NESTED_PACKAGE_FINGERPRINT_MISMATCH",
                "NESTED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "NESTED_PACKAGE_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        if result["provenance_consistent"] != expected_provenance_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match consistency_issues",
            )
        expected_source_consistency = "BUNDLE_SOURCE_MISMATCH" not in issue_set
        if result["source_consistency"] != expected_source_consistency:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )
        expected_metadata_consistent = not any(
            i in issue_set
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
        if result["metadata_consistent"] != expected_metadata_consistent:
            raise ReasoningHandoffFullyAuditedApiConsistencyContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

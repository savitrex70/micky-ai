"""Task 061: package a Task 059 API response with its Task 060 audit.

Composition only. Reuses Task 057\'s and Task 060\'s own validators for
the nested results. Never queries the database, never performs HTTP,
never invokes Task 059\'s endpoint or Task 060\'s build method, never
mutates its inputs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff import (
    REASONING_HANDOFF_TASK_057,
    ReasoningHandoffContractError,
    ReasoningHandoffService,
)
from rop.services.reasoning_handoff_api_consistency import (
    REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060,
    ReasoningHandoffApiConsistencyContractError,
    ReasoningHandoffApiConsistencyService,
)

REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061 = (
    "REASONING_HANDOFF_API_AUDIT_PACKAGE_TASK_061"
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS = 200
_PATH_PATTERN = re.compile(r"^/sessions/(?P<session_id>[^/]+)/reasoning-handoff$")

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

_PACKAGE_BOOLEAN_FIELDS = ("available", "package_consistent")


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


class ReasoningHandoffApiAuditPackageContractError(Exception):
    """Task 061: the package could not be assembled into a valid contract.

    Raised when the Task 057 response or the Task 060 audit is not
    shaped like its own contract, when session identity or HTTP
    metadata disagrees, when a fixed source identifier is wrong, or
    when the package\'s own ``package_consistent`` field does not
    correctly mirror the Task 060 audit.

    A valid Task 057 response whose own ``handoff_consistent`` is
    ``False`` (because the underlying reasoning context is
    legitimately inconsistent) is not a package failure: the API
    response may still have faithfully represented it, which Task 060
    reports as ``api_consistent=True``, and Task 061 then derives
    ``package_consistent=True``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffApiAuditPackageService:
    """Task 061: package a Task 059 API response with its Task 060 audit."""

    def build(
        self,
        *,
        session_id: Any = None,
        method: Any = None,
        path: Any = None,
        status_code: Any = None,
        response: Mapping[str, Any] | None = None,
        api_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the package. Pure; never mutates inputs."""
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(response, Mapping):
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "response is required and must be a mapping",
            )
        if not isinstance(api_consistency, Mapping):
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "api_consistency is required and must be a mapping",
            )

        # HTTP metadata checks.
        if method != _EXPECTED_METHOD:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_METHOD",
                "method is not GET: " + repr(method),
            )
        if status_code != _EXPECTED_STATUS:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_STATUS",
                "status_code is not 200: " + repr(status_code),
            )
        if not isinstance(path, str):
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_PATH",
                "path is not a string: " + type(path).__name__,
            )
        match = _PATH_PATTERN.match(path)
        if match is None:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_PATH",
                "path does not match the Task 059 handoff route: " + repr(path),
            )
        path_sid = _coerce_session_id(match.group("session_id"))
        if path_sid is None:
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "path session id is not a UUID: " + repr(match.group("session_id")),
            )
        if path_sid != sid:
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "path session id does not match the supplied session_id",
            )

        # Source checks -- hoisted above the nested validators so the
        # more specific error fires when the only defect is a wrong
        # source identifier.
        if response.get("handoff_source") != REASONING_HANDOFF_TASK_057:
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response.handoff_source is not the Task 057 identifier: "
                + repr(response.get("handoff_source")),
            )
        if (
            api_consistency.get("api_consistency_source")
            != REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_AUDIT_SOURCE_MISMATCH",
                "api_consistency.api_consistency_source is not the Task "
                "060 identifier: "
                + repr(api_consistency.get("api_consistency_source")),
            )

        # Response contract (Task 057).
        response_for_validation = _deep_normalize_session_ids(response)
        try:
            ReasoningHandoffService._validate_result(response_for_validation)
        except ReasoningHandoffContractError as exc:
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "Task 057 response failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "Task 057 response failed its own validator: " + str(exc),
            ) from exc

        # Response session identity.
        response_sid = _coerce_session_id(response.get("session_id"))
        if response_sid != sid:
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "response.session_id does not match the supplied " "session_id",
            )

        # Response nested reasoning_context session identity.
        reasoning_context = response.get("reasoning_context")
        if isinstance(reasoning_context, Mapping):
            nested_sid = _coerce_session_id(reasoning_context.get("session_id"))
            if nested_sid != sid:
                raise ReasoningHandoffApiAuditPackageContractError(
                    "SESSION_ID_MISMATCH",
                    "response.reasoning_context.session_id does not "
                    "match the supplied session_id",
                )

        # API audit contract (Task 060).
        audit_for_validation = dict(api_consistency)
        try:
            ReasoningHandoffApiConsistencyService._validate_result(audit_for_validation)
        except ReasoningHandoffApiConsistencyContractError as exc:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "Task 060 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "Task 060 audit failed its own validator: " + str(exc),
            ) from exc

        # API audit availability and source.
        if api_consistency.get("available") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_AUDIT_UNAVAILABLE",
                "api_consistency.available is not True",
            )
        if api_consistency.get("session_consistent") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_AUDIT_SESSION_MISMATCH",
                "api_consistency.session_consistent is not True",
            )
        # Transport flag cross-checks.
        if api_consistency.get("method_consistent") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_METHOD",
                "api_consistency.method_consistent is not True",
            )
        if api_consistency.get("path_consistent") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_PATH",
                "api_consistency.path_consistent is not True",
            )
        if api_consistency.get("status_consistent") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_STATUS",
                "api_consistency.status_consistent is not True",
            )

        # Provenance: the audit must have been produced from this exact
        # session, method, path, status code, and response body.
        audited_session_id = api_consistency.get("audited_session_id")
        if audited_session_id != str(sid):
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "api_consistency.audited_session_id does not match the "
                "supplied session_id: " + repr(audited_session_id),
            )
        audited_method = api_consistency.get("audited_method")
        if audited_method != method:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_METHOD",
                "api_consistency.audited_method does not match the "
                "supplied method: " + repr(audited_method),
            )
        audited_path = api_consistency.get("audited_path")
        if audited_path != path:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_PATH",
                "api_consistency.audited_path does not match the "
                "supplied path: " + repr(audited_path),
            )
        audited_status_code = api_consistency.get("audited_status_code")
        if audited_status_code != status_code:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_STATUS",
                "api_consistency.audited_status_code does not match the "
                "supplied status_code: " + repr(audited_status_code),
            )
        expected_fingerprint = (
            ReasoningHandoffApiConsistencyService._response_fingerprint(response)
        )
        audited_fingerprint = api_consistency.get("audited_response_fingerprint")
        if audited_fingerprint != expected_fingerprint:
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "api_consistency.audited_response_fingerprint does not "
                "match the supplied response body",
            )

        expected_package_consistent = bool(api_consistency.get("api_consistent", False))

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": expected_package_consistent,
            "session_id": sid,
            "method": method,
            "path": path,
            "status_code": status_code,
            "response": response,
            "api_consistency": api_consistency,
            "package_source": (REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffApiAuditPackageContractError(
                    "MISSING_PACKAGE_FIELD", "result has no " + field
                )
        for field in _PACKAGE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffApiAuditPackageContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        if not isinstance(result["method"], str):
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_METHOD", "method is not a string"
            )
        if result["method"] != _EXPECTED_METHOD:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_METHOD",
                "method is not GET: " + repr(result["method"]),
            )
        if not isinstance(result["path"], str):
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_PATH", "path is not a string"
            )
        if not isinstance(result["status_code"], int) or isinstance(
            result["status_code"], bool
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_STATUS", "status_code is not an int"
            )
        if result["status_code"] != _EXPECTED_STATUS:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_STATUS",
                "status_code is not 200: " + repr(result["status_code"]),
            )
        if not isinstance(result["response"], Mapping):
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH", "response is not a mapping"
            )
        if not isinstance(result["api_consistency"], Mapping):
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "api_consistency is not a mapping",
            )

        # Nested validators.
        response_for_validation = _deep_normalize_session_ids(result["response"])
        try:
            ReasoningHandoffService._validate_result(response_for_validation)
        except Exception as exc:
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "nested Task 057 response failed its own validator: " + str(exc),
            ) from exc
        try:
            ReasoningHandoffApiConsistencyService._validate_result(
                dict(result["api_consistency"])
            )
        except Exception as exc:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "nested Task 060 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity.
        response_sid = _coerce_session_id(result["response"].get("session_id"))
        if response_sid != result["session_id"]:
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "response.session_id does not match package session_id",
            )
        reasoning_context = result["response"].get("reasoning_context")
        if isinstance(reasoning_context, Mapping):
            nested_sid = _coerce_session_id(reasoning_context.get("session_id"))
            if nested_sid != result["session_id"]:
                raise ReasoningHandoffApiAuditPackageContractError(
                    "SESSION_ID_MISMATCH",
                    "response.reasoning_context.session_id does not "
                    "match package session_id",
                )

        # Audit availability.
        if result["api_consistency"].get("available") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_AUDIT_UNAVAILABLE",
                "api_consistency.available is not True",
            )
        if result["api_consistency"].get("session_consistent") is not True:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_AUDIT_SESSION_MISMATCH",
                "api_consistency.session_consistent is not True",
            )

        # Sources.
        if result["response"].get("handoff_source") != REASONING_HANDOFF_TASK_057:
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response.handoff_source is not the Task 057 identifier",
            )
        if (
            result["api_consistency"].get("api_consistency_source")
            != REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_AUDIT_SOURCE_MISMATCH",
                "api_consistency.api_consistency_source is not the Task "
                "060 identifier",
            )
        if (
            result["package_source"]
            != REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "PACKAGE_SOURCE_MISMATCH",
                "package_source is not the Task 061 identifier: "
                + repr(result["package_source"]),
            )

        # Package consistency relationship.
        expected = bool(result["api_consistency"].get("api_consistent", False))
        if result["package_consistent"] != expected:
            raise ReasoningHandoffApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "package_consistent does not match Task 060's "
                "api_consistent: "
                + repr(result["package_consistent"])
                + " != "
                + repr(expected),
            )

        # Provenance metadata cross-checks.
        if result["api_consistency"].get("audited_method") != result["method"]:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_METHOD",
                "api_consistency.audited_method does not match package " "method",
            )
        if result["api_consistency"].get("audited_path") != result["path"]:
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_PATH",
                "api_consistency.audited_path does not match package path",
            )
        if (
            result["api_consistency"].get("audited_status_code")
            != result["status_code"]
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "INVALID_STATUS",
                "api_consistency.audited_status_code does not match "
                "package status_code",
            )
        if result["api_consistency"].get("audited_session_id") != str(
            result["session_id"]
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "api_consistency.audited_session_id does not match "
                "package session_id",
            )

        # Fingerprint provenance.
        expected_fingerprint = (
            ReasoningHandoffApiConsistencyService._response_fingerprint(
                result["response"]
            )
        )
        if (
            result["api_consistency"].get("audited_response_fingerprint")
            != expected_fingerprint
        ):
            raise ReasoningHandoffApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "api_consistency.audited_response_fingerprint does not "
                "match package response",
            )

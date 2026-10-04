"""Task 067: package a Task 065 API response with its Task 066 audit.

Composition only. Reuses Task 063's and Task 066's own validators for the
nested results, and Task 066's own canonical-JSON fingerprint helper for
the provenance binding. Never queries the database, never performs HTTP,
never calls the Task 065 endpoint, never invokes Task 059/060/061/062/063
build workflows, never mutates its inputs, and never alters the upstream
response before fingerprinting it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_api_audit_bundle import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063,
    ReasoningHandoffApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066,
    ReasoningHandoffFullyAuditedApiConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_TASK_067"
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS = 200
_PATH_PATTERN = re.compile(
    r"^/sessions/(?P<session_id>[^/]+)/reasoning-handoff/fully-audited$"
)

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
    "audited_response_fingerprint",
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


class ReasoningHandoffFullyAuditedApiAuditPackageContractError(Exception):
    """Task 067: the package could not be assembled into a valid contract.

    Raised when the Task 063 response or the Task 066 audit is not shaped
    like its own contract, when session identity or HTTP metadata
    disagrees, when a fixed source identifier is wrong, when the audit's
    provenance does not bind to the supplied response, or when the
    package's own ``package_consistent`` does not correctly mirror the
    Task 066 audit.

    A valid Task 063 response whose own ``bundle_consistent`` is ``False``
    (because the Task 062 audit reported the Task 061 package as
    inconsistent) is not a package failure: the API response may still
    have faithfully represented it, which Task 066 reports as
    ``api_consistent=True``, and Task 067 then derives
    ``package_consistent=True``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffFullyAuditedApiAuditPackageService:
    """Task 067: package a Task 065 API response with its Task 066 audit."""

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
        """Assemble and validate the package. Pure; never mutates inputs.

        ``package_consistent`` mirrors Task 066's ``api_consistent``
        exactly: a Task 066 audit that legitimately reports a defect is
        packaged with ``package_consistent = False`` rather than being
        rejected or silently upgraded, matching Task 061's established
        behaviour for a defect-reporting Task 060 audit. An audit that is
        unavailable, whose session identity disagrees, or that does not
        bind to the supplied response is refused outright.
        """
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(response, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "response is required and must be a mapping",
            )
        if not isinstance(api_consistency, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "api_consistency is required and must be a mapping",
            )

        # HTTP metadata checks.
        if method != _EXPECTED_METHOD:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_METHOD",
                "method is not GET: " + repr(method),
            )
        if status_code != _EXPECTED_STATUS:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_STATUS",
                "status_code is not 200: " + repr(status_code),
            )
        if not isinstance(path, str):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "path is not a string: " + type(path).__name__,
            )
        match = _PATH_PATTERN.match(path)
        if match is None:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "path does not match the Task 065 fully audited route: " + repr(path),
            )
        path_sid = _coerce_session_id(match.group("session_id"))
        if path_sid is None:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "path session id is not a UUID: " + repr(match.group("session_id")),
            )
        if path_sid != sid:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "path session id does not match the supplied session_id",
            )

        # Source checks -- hoisted above the nested validators so the more
        # specific error fires when the only defect is a wrong source.
        if (
            response.get("bundle_source")
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response.bundle_source is not the Task 063 identifier: "
                + repr(response.get("bundle_source")),
            )
        if (
            api_consistency.get("api_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_AUDIT_SOURCE_MISMATCH",
                "api_consistency.api_consistency_source is not the Task 066 "
                "identifier: " + repr(api_consistency.get("api_consistency_source")),
            )

        # Session identity -- checked before the nested validators so a
        # nested-session-only defect surfaces SESSION_ID_MISMATCH.
        response_sid = _coerce_session_id(response.get("session_id"))
        if response_sid != sid:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "response.session_id does not match the supplied session_id",
            )

        # Nested Task 063 contract.
        try:
            ReasoningHandoffApiAuditBundleService._validate_result(
                _deep_normalize_session_ids(response)
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "Task 063 response failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 066 contract.
        try:
            ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(
                dict(api_consistency)
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "Task 066 audit failed its own validator: " + str(exc),
            ) from exc

        # Audit availability and transport cross-checks.
        if api_consistency.get("available") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_AUDIT_UNAVAILABLE",
                "api_consistency.available is not True",
            )
        if api_consistency.get("session_consistent") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_AUDIT_SESSION_MISMATCH",
                "api_consistency.session_consistent is not True",
            )
        if api_consistency.get("method_consistent") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_METHOD",
                "api_consistency.method_consistent is not True",
            )
        if api_consistency.get("path_consistent") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "api_consistency.path_consistent is not True",
            )
        if api_consistency.get("status_consistent") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_STATUS",
                "api_consistency.status_consistent is not True",
            )

        # Provenance: the audit must have been produced from this exact
        # session, method, path, status code, and response body.
        audited_session_id = api_consistency.get("audited_session_id")
        if audited_session_id != str(sid):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "api_consistency.audited_session_id does not match the "
                "supplied session_id: " + repr(audited_session_id),
            )
        audited_method = api_consistency.get("audited_method")
        if audited_method != method:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_METHOD",
                "api_consistency.audited_method does not match the "
                "supplied method: " + repr(audited_method),
            )
        audited_path = api_consistency.get("audited_path")
        if audited_path != path:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "api_consistency.audited_path does not match the supplied "
                "path: " + repr(audited_path),
            )
        audited_status_code = api_consistency.get("audited_status_code")
        if audited_status_code != status_code:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_STATUS",
                "api_consistency.audited_status_code does not match the "
                "supplied status_code: " + repr(audited_status_code),
            )

        # Response fingerprint, computed with Task 066's own canonical JSON
        # helper -- delegated, never reimplemented -- over the exact
        # response representation supplied here. The upstream response is
        # never altered before fingerprinting, so the fingerprint binds
        # this package to the exact representation that was audited.
        try:
            expected_fingerprint = (
                ReasoningHandoffFullyAuditedApiConsistencyService._response_fingerprint(
                    response
                )
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute the response fingerprint: " + str(exc),
            ) from exc
        audited_fingerprint = api_consistency.get("audited_response_fingerprint")
        if audited_fingerprint != expected_fingerprint:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "api_consistency.audited_response_fingerprint does not match "
                "the supplied response",
            )

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": bool(api_consistency.get("api_consistent", False)),
            "session_id": sid,
            "method": method,
            "path": path,
            "status_code": status_code,
            "response": response,
            "api_consistency": api_consistency,
            "package_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
            ),
            "audited_response_fingerprint": expected_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: Mapping[str, Any]) -> None:
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                    "MISSING_PACKAGE_FIELD", "result has no " + field
                )
        for field in _PACKAGE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        if result["method"] != _EXPECTED_METHOD:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_METHOD",
                "method is not GET: " + repr(result["method"]),
            )
        if result["status_code"] != _EXPECTED_STATUS:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_STATUS",
                "status_code is not 200: " + repr(result["status_code"]),
            )
        if not isinstance(result["path"], str):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "path is not a string: " + type(result["path"]).__name__,
            )
        match = _PATH_PATTERN.match(result["path"])
        if match is None:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "path does not match the Task 065 fully audited route: "
                + repr(result["path"]),
            )
        path_sid = _coerce_session_id(match.group("session_id"))
        if path_sid is None:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_INVALID",
                "path session id is not a UUID",
            )
        if path_sid != result["session_id"]:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "path session id does not match package session_id",
            )
        if not isinstance(result["response"], Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "response is not a mapping",
            )
        if not isinstance(result["api_consistency"], Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "api_consistency is not a mapping",
            )

        # Nested validators.
        try:
            ReasoningHandoffApiAuditBundleService._validate_result(
                _deep_normalize_session_ids(result["response"])
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "nested Task 063 response failed its own validator: " + str(exc),
            ) from exc
        try:
            ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(
                dict(result["api_consistency"])
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "nested Task 066 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity.
        response_sid = _coerce_session_id(result["response"].get("session_id"))
        if response_sid != result["session_id"]:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "response.session_id does not match package session_id",
            )

        # Audit availability.
        audit = result["api_consistency"]
        if audit.get("available") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_AUDIT_UNAVAILABLE",
                "api_consistency.available is not True",
            )
        if audit.get("session_consistent") is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_AUDIT_SESSION_MISMATCH",
                "api_consistency.session_consistent is not True",
            )

        # Sources.
        if (
            result["response"].get("bundle_source")
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response.bundle_source is not the Task 063 identifier",
            )
        if (
            audit.get("api_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_AUDIT_SOURCE_MISMATCH",
                "api_consistency.api_consistency_source is not the Task 066 "
                "identifier",
            )
        if (
            result["package_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "PACKAGE_SOURCE_MISMATCH",
                "package_source is not the Task 067 identifier: "
                + repr(result["package_source"]),
            )

        # Package consistency relationship.
        expected = bool(audit.get("api_consistent", False))
        if result["package_consistent"] != expected:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "API_CONSISTENCY_MISMATCH",
                "package_consistent does not match Task 066's api_consistent: "
                + repr(result["package_consistent"])
                + " != "
                + repr(expected),
            )

        # Provenance metadata cross-checks.
        if audit.get("audited_method") != result["method"]:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_METHOD",
                "api_consistency.audited_method does not match package method",
            )
        if audit.get("audited_path") != result["path"]:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_PATH",
                "api_consistency.audited_path does not match package path",
            )
        if audit.get("audited_status_code") != result["status_code"]:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "INVALID_STATUS",
                "api_consistency.audited_status_code does not match package "
                "status_code",
            )
        if audit.get("audited_session_id") != str(result["session_id"]):
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "api_consistency.audited_session_id does not match package "
                "session_id",
            )

        # Fingerprint provenance: the package's declared fingerprint must
        # equal a fingerprint recomputed from the carried response, and the
        # audit's declared fingerprint must agree with it as well. A failed
        # recomputation is an explicit provenance failure -- never a raw
        # exception escaping the validator, and never a silent pass.
        fingerprint_helper = (
            ReasoningHandoffFullyAuditedApiConsistencyService._response_fingerprint
        )
        try:
            recomputed = fingerprint_helper(result["response"])
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED",
                "audited_response_fingerprint could not be recomputed: " + str(exc),
            ) from exc
        if result["audited_response_fingerprint"] != recomputed:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_FINGERPRINT_MISMATCH",
                "audited_response_fingerprint does not match the package " "response",
            )
        if audit.get("audited_response_fingerprint") != recomputed:
            raise ReasoningHandoffFullyAuditedApiAuditPackageContractError(
                "RESPONSE_MISMATCH",
                "api_consistency.audited_response_fingerprint does not match "
                "package response",
            )

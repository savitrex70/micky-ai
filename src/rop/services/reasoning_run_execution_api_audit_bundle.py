from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run_execution_api_audit_package import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051,
    ReasoningRunExecutionApiAuditPackageContractError,
    ReasoningRunExecutionApiAuditPackageService,
)
from rop.services.reasoning_run_execution_api_audit_package_consistency import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052,
    ReasoningRunExecutionApiAuditPackageConsistencyContractError,
    ReasoningRunExecutionApiAuditPackageConsistencyService,
)

REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053 = (
    "REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_TASK_053"
)

_EXPECTED_METHOD = "POST"
_EXPECTED_STATUS = 200

_RESULT_REQUIRED_FIELDS = (
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

_RESULT_BOOLEAN_FIELDS = ("available", "bundle_consistent")


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


class ReasoningRunExecutionApiAuditBundleContractError(Exception):
    """Task 053: the bundle could not be assembled into a valid contract.

    Raised when the Task 051 API audit package or the Task 052
    consistency audit is not shaped like its own contract, when
    session identity or HTTP metadata disagrees, when a fixed source
    identifier is wrong, or when the bundle's own
    ``bundle_consistent`` field does not correctly mirror the Task 052
    audit.

    A valid Task 051 package whose own ``package_consistent`` is
    ``False`` is not a bundle failure: it means Task 051 correctly
    recorded that its underlying response/audit bind was problematic.
    Task 052 may still find the Task 051 package internally consistent
    (``package_consistent = True``), and Task 053 then derives
    ``bundle_consistent = True``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionApiAuditBundleService:
    """Task 053: package a Task 051 API audit with its Task 052 audit.

    Pure composition only. Reuses Task 051's and Task 052's own
    validators for the nested results. Never queries the database,
    never performs HTTP, never invokes Task 049/050/051/052 build or
    build_for_session workflows, never mutates its inputs. Both nested
    objects are stored by reference so exact identity is preserved.
    """

    def build(
        self,
        *,
        session_id: Any = None,
        method: Any = None,
        path: Any = None,
        status_code: Any = None,
        api_audit_package: Mapping[str, Any] | None = None,
        api_audit_package_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the bundle. Pure; never mutates inputs."""
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(api_audit_package, Mapping):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "MISSING_API_AUDIT_PACKAGE",
                "api_audit_package is required and must be a mapping",
            )
        if not isinstance(api_audit_package_consistency, Mapping):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "MISSING_API_AUDIT_PACKAGE_CONSISTENCY",
                "api_audit_package_consistency is required and must be "
                "a mapping",
            )

        # HTTP metadata checks (exact; no normalization).
        if method != _EXPECTED_METHOD:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_METHOD",
                "method is not POST: " + repr(method),
            )
        if status_code != _EXPECTED_STATUS:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_STATUS",
                "status_code is not 200: " + repr(status_code),
            )
        if not isinstance(path, str) or not path:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_PATH",
                "path is not a non-empty string: " + repr(path),
            )

        # Validate the nested Task 051 object.
        package_for_validation = _deep_normalize_session_ids(
            api_audit_package
        )
        try:
            ReasoningRunExecutionApiAuditPackageService._validate_result(
                package_for_validation
            )
        except ReasoningRunExecutionApiAuditPackageContractError as exc:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE",
                "Task 051 package failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE",
                "Task 051 package failed its own validator: " + str(exc),
            ) from exc

        # Validate the nested Task 052 object.
        try:
            ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
                dict(api_audit_package_consistency)
            )
        except ReasoningRunExecutionApiAuditPackageConsistencyContractError as exc:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE_CONSISTENCY",
                "Task 052 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE_CONSISTENCY",
                "Task 052 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity.
        package_session_id = _coerce_session_id(
            api_audit_package.get("session_id")
        )
        if package_session_id != sid:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_package.session_id does not match the supplied "
                "session_id",
            )

        # HTTP metadata agreement with nested Task 051 object.
        if api_audit_package.get("method") != method:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "METHOD_MISMATCH",
                "api_audit_package.method does not match the supplied "
                "method: " + repr(api_audit_package.get("method")),
            )
        if api_audit_package.get("path") != path:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "PATH_MISMATCH",
                "api_audit_package.path does not match the supplied path: "
                + repr(api_audit_package.get("path")),
            )
        if api_audit_package.get("status_code") != status_code:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "STATUS_MISMATCH",
                "api_audit_package.status_code does not match the supplied "
                "status_code: "
                + repr(api_audit_package.get("status_code")),
            )

        # Task 052 availability.
        if api_audit_package_consistency.get("available") is not True:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "AUDIT_UNAVAILABLE",
                "api_audit_package_consistency.available is not True",
            )

        # Provenance: the Task 052 audit must have been produced from
        # this exact Task 051 package. Recompute the fingerprint with
        # Task 052's own staticmethod (delegated, not reimplemented)
        # and require an exact match.
        expected_fingerprint = (
            ReasoningRunExecutionApiAuditPackageConsistencyService
            ._package_fingerprint(api_audit_package)
        )
        audited_fingerprint = api_audit_package_consistency.get(
            "audited_package_fingerprint"
        )
        if audited_fingerprint != expected_fingerprint:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "AUDIT_PACKAGE_FINGERPRINT_MISMATCH",
                "api_audit_package_consistency.audited_package_fingerprint "
                "does not match the supplied Task 051 package",
            )

        # Sources.
        if (
            api_audit_package.get("package_source")
            != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE_SOURCE",
                "api_audit_package.package_source is not the Task 051 "
                "identifier: "
                + repr(api_audit_package.get("package_source")),
            )
        if (
            api_audit_package_consistency.get("package_consistency_source")
            != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_CONSISTENCY_SOURCE",
                "api_audit_package_consistency.package_consistency_source "
                "is not the Task 052 identifier: "
                + repr(
                    api_audit_package_consistency.get(
                        "package_consistency_source"
                    )
                ),
            )

        # Bundle consistency derives only from Task 052's package_consistent.
        # NOT from api_audit_package.package_consistent (different meaning).
        expected_bundle_consistent = bool(
            api_audit_package_consistency.get("package_consistent", False)
        )

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": expected_bundle_consistent,
            "session_id": sid,
            "method": method,
            "path": path,
            "status_code": status_code,
            "api_audit_package": api_audit_package,
            "api_audit_package_consistency": (
                api_audit_package_consistency
            ),
            "bundle_source": (
                REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionApiAuditBundleContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionApiAuditBundleContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: "
                + type(result["session_id"]).__name__,
            )
        if result["method"] != _EXPECTED_METHOD:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_METHOD",
                "method is not POST: " + repr(result["method"]),
            )
        if not isinstance(result["path"], str) or not result["path"]:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_PATH",
                "path is not a non-empty string: " + repr(result["path"]),
            )
        if (
            not isinstance(result["status_code"], int)
            or isinstance(result["status_code"], bool)
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_STATUS",
                "status_code is not an int: "
                + repr(result["status_code"]),
            )
        if result["status_code"] != _EXPECTED_STATUS:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_STATUS",
                "status_code is not 200: " + repr(result["status_code"]),
            )
        if not isinstance(result["api_audit_package"], Mapping):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_TYPE",
                "api_audit_package is not a mapping: "
                + type(result["api_audit_package"]).__name__,
            )
        if not isinstance(
            result["api_audit_package_consistency"], Mapping
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_TYPE",
                "api_audit_package_consistency is not a mapping: "
                + type(result["api_audit_package_consistency"]).__name__,
            )
        # Nested validators.
        package_for_validation = _deep_normalize_session_ids(
            result["api_audit_package"]
        )
        try:
            ReasoningRunExecutionApiAuditPackageService._validate_result(
                package_for_validation
            )
        except Exception as exc:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE",
                "nested Task 051 package failed its own validator: "
                + str(exc),
            ) from exc
        try:
            ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
                dict(result["api_audit_package_consistency"])
            )
        except Exception as exc:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE_CONSISTENCY",
                "nested Task 052 audit failed its own validator: "
                + str(exc),
            ) from exc
        # Session identity.
        package_sid = _coerce_session_id(
            result["api_audit_package"].get("session_id")
        )
        if package_sid != result["session_id"]:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_package.session_id does not match bundle "
                "session_id",
            )
        # HTTP metadata agreement.
        if result["api_audit_package"].get("method") != result["method"]:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "METHOD_MISMATCH",
                "api_audit_package.method does not match bundle method",
            )
        if result["api_audit_package"].get("path") != result["path"]:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "PATH_MISMATCH",
                "api_audit_package.path does not match bundle path",
            )
        if (
            result["api_audit_package"].get("status_code")
            != result["status_code"]
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "STATUS_MISMATCH",
                "api_audit_package.status_code does not match bundle "
                "status_code",
            )
        # Audit availability.
        if result["api_audit_package_consistency"].get("available") is not True:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "AUDIT_UNAVAILABLE",
                "api_audit_package_consistency.available is not True",
            )
        # Sources.
        if (
            result["api_audit_package"].get("package_source")
            != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_PACKAGE_SOURCE",
                "api_audit_package.package_source is not the Task 051 "
                "identifier",
            )
        if (
            result["api_audit_package_consistency"].get(
                "package_consistency_source"
            )
            != REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_API_AUDIT_CONSISTENCY_SOURCE",
                "api_audit_package_consistency.package_consistency_source "
                "is not the Task 052 identifier",
            )
        if (
            result["bundle_source"]
            != REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053
        ):
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "INVALID_BUNDLE_SOURCE",
                "bundle_source is not the Task 053 identifier: "
                + repr(result["bundle_source"]),
            )
        # Bundle consistency relationship.
        expected = bool(
            result["api_audit_package_consistency"].get(
                "package_consistent", False
            )
        )
        if result["bundle_consistent"] != expected:
            raise ReasoningRunExecutionApiAuditBundleContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match Task 052's "
                "package_consistent: "
                + repr(result["bundle_consistent"])
                + " != " + repr(expected),
            )

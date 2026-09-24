"""Task 063: compose a Task 061 package with its Task 062 audit.

Composition only. Reuses Task 061\'s and Task 062\'s own validators for
the nested results. Never queries the database, never performs HTTP,
never invokes Task 059/060/061/062 build workflows, never mutates its
inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_api_audit_package import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061,
    ReasoningHandoffApiAuditPackageContractError,
    ReasoningHandoffApiAuditPackageService,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062,
    ReasoningHandoffApiAuditPackageConsistencyContractError,
    ReasoningHandoffApiAuditPackageConsistencyService,
)

REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063 = (
    "REASONING_HANDOFF_API_AUDIT_BUNDLE_TASK_063"
)

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)

_BUNDLE_BOOLEAN_FIELDS = ("available", "bundle_consistent")


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


class ReasoningHandoffApiAuditBundleContractError(Exception):
    """Task 063: the bundle could not be assembled into a valid contract.

    Raised when the Task 061 package or the Task 062 audit is not
    shaped like its own contract, when session identity disagrees,
    when a fixed source identifier is wrong, or when the bundle\'s own
    ``bundle_consistent`` field does not correctly mirror the Task 062
    audit.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffApiAuditBundleService:
    """Task 063: compose a Task 061 package with its Task 062 audit."""

    def build(
        self,
        *,
        session_id: Any = None,
        api_audit_package: Mapping[str, Any] | None = None,
        api_audit_package_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the bundle. Pure; never mutates inputs."""
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningHandoffApiAuditBundleContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(api_audit_package, Mapping):
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "api_audit_package is required and must be a mapping",
            )
        if not isinstance(api_audit_package_consistency, Mapping):
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "api_audit_package_consistency is required and must be " "a mapping",
            )

        # Source checks -- hoisted above nested validators so a
        # wrong-source-only defect surfaces the specific invariant.
        if (
            api_audit_package.get("package_source")
            != REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061
        ):
            raise ReasoningHandoffApiAuditBundleContractError(
                "PACKAGE_SOURCE_MISMATCH",
                "api_audit_package.package_source is not the Task 061 "
                "identifier: " + repr(api_audit_package.get("package_source")),
            )
        if (
            api_audit_package_consistency.get("package_consistency_source")
            != REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062
        ):
            raise ReasoningHandoffApiAuditBundleContractError(
                "CONSISTENCY_SOURCE_MISMATCH",
                "api_audit_package_consistency.package_consistency_source "
                "is not the Task 062 identifier: "
                + repr(api_audit_package_consistency.get("package_consistency_source")),
            )

        # Session identity -- checked before nested validators so a
        # nested-session-only defect surfaces SESSION_ID_MISMATCH.
        package_sid = _coerce_session_id(api_audit_package.get("session_id"))
        if package_sid != sid:
            raise ReasoningHandoffApiAuditBundleContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_package.session_id does not match the "
                "supplied session_id",
            )

        # The audit must be available. Checked here (before the nested
        # validators) so an unavailable audit surfaces the specific
        # API_AUDIT_PACKAGE_CONSISTENCY_UNAVAILABLE invariant rather
        # than a generic validator error.
        if api_audit_package_consistency.get("available") is not True:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_UNAVAILABLE",
                "api_audit_package_consistency.available is not True",
            )

        # Nested Task 061 contract.
        package_for_validation = _deep_normalize_session_ids(api_audit_package)
        try:
            ReasoningHandoffApiAuditPackageService._validate_result(
                package_for_validation
            )
        except ReasoningHandoffApiAuditPackageContractError as exc:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "Task 061 package failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "Task 061 package failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 062 contract.
        try:
            ReasoningHandoffApiAuditPackageConsistencyService._validate_result(
                dict(api_audit_package_consistency)
            )
        except ReasoningHandoffApiAuditPackageConsistencyContractError as exc:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "Task 062 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "Task 062 audit failed its own validator: " + str(exc),
            ) from exc

        # bundle_consistent derives exactly from Task 062's
        # package_consistent.
        expected_bundle_consistent = bool(
            api_audit_package_consistency.get("package_consistent", False)
        )

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": expected_bundle_consistent,
            "session_id": sid,
            "api_audit_package": api_audit_package,
            "api_audit_package_consistency": api_audit_package_consistency,
            "bundle_source": (REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffApiAuditBundleContractError(
                    "MISSING_BUNDLE_FIELD", "result has no " + field
                )
        for field in _BUNDLE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffApiAuditBundleContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise ReasoningHandoffApiAuditBundleContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningHandoffApiAuditBundleContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        if not isinstance(result["api_audit_package"], Mapping):
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "api_audit_package is not a mapping",
            )
        if not isinstance(result["api_audit_package_consistency"], Mapping):
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "api_audit_package_consistency is not a mapping",
            )

        # Nested validators.
        try:
            ReasoningHandoffApiAuditPackageService._validate_result(
                _deep_normalize_session_ids(result["api_audit_package"])
            )
        except Exception as exc:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "nested Task 061 package failed its own validator: " + str(exc),
            ) from exc
        try:
            ReasoningHandoffApiAuditPackageConsistencyService._validate_result(
                dict(result["api_audit_package_consistency"])
            )
        except Exception as exc:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "nested Task 062 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity.
        package_sid = _coerce_session_id(result["api_audit_package"].get("session_id"))
        if package_sid != result["session_id"]:
            raise ReasoningHandoffApiAuditBundleContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_package.session_id does not match bundle " "session_id",
            )

        # Task 062 availability.
        if result["api_audit_package_consistency"].get("available") is not True:
            raise ReasoningHandoffApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_UNAVAILABLE",
                "api_audit_package_consistency.available is not True",
            )

        # Sources.
        if (
            result["api_audit_package"].get("package_source")
            != REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061
        ):
            raise ReasoningHandoffApiAuditBundleContractError(
                "PACKAGE_SOURCE_MISMATCH",
                "api_audit_package.package_source is not the Task 061 " "identifier",
            )
        if (
            result["api_audit_package_consistency"].get("package_consistency_source")
            != REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062
        ):
            raise ReasoningHandoffApiAuditBundleContractError(
                "CONSISTENCY_SOURCE_MISMATCH",
                "api_audit_package_consistency.package_consistency_source "
                "is not the Task 062 identifier",
            )
        if (
            result["bundle_source"]
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        ):
            raise ReasoningHandoffApiAuditBundleContractError(
                "BUNDLE_SOURCE_MISMATCH",
                "bundle_source is not the Task 063 identifier: "
                + repr(result["bundle_source"]),
            )

        # bundle_consistent relationship.
        expected = bool(
            result["api_audit_package_consistency"].get("package_consistent", False)
        )
        if result["bundle_consistent"] != expected:
            raise ReasoningHandoffApiAuditBundleContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match Task 062's "
                "package_consistent: "
                + repr(result["bundle_consistent"])
                + " != "
                + repr(expected),
            )

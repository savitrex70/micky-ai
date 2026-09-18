from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_run_execution_bundle import (
    REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046,
    ReasoningRunExecutionBundleContractError,
    ReasoningRunExecutionBundleService,
)
from rop.services.reasoning_run_execution_bundle_consistency import (
    REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047,
    ReasoningRunExecutionBundleConsistencyContractError,
    ReasoningRunExecutionBundleConsistencyService,
)

REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048 = (
    "REASONING_RUN_EXECUTION_AUDIT_PACKAGE_TASK_048"
)

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "execution_bundle",
    "bundle_consistency",
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


class ReasoningRunExecutionAuditPackageContractError(Exception):
    """Task 048: the package could not be assembled into a valid contract.

    Raised when the Task 046 bundle or the Task 047 bundle audit is not
    shaped like its own contract, when session identity disagrees,
    when a fixed source identifier is wrong, or when the Task 047
    audit itself is unavailable or reports the bundle session as
    inconsistent. A valid Task 046 ``bundle_consistent=False`` -- which
    simply mirrors a legitimately-inconsistent underlying reasoning
    execution -- is not a package failure.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionAuditPackageService:
    """Task 048: package a Task 046 bundle with its Task 047 audit.

    Composition only. Delegates the bundle to Task 046 and audits the
    exact returned bundle through Task 047, then assembles and
    validates one package. It does not execute reasoning, does not
    call Task 044 or Task 045 directly, and does not reimplement any
    Task 046/047 logic.
    """

    def __init__(
        self,
        reasoning_run_execution_bundle_service: (
            ReasoningRunExecutionBundleService | None
        ) = None,
        reasoning_run_execution_bundle_consistency_service: (
            ReasoningRunExecutionBundleConsistencyService | None
        ) = None,
    ) -> None:
        self.reasoning_run_execution_bundle_service = (
            reasoning_run_execution_bundle_service
            or ReasoningRunExecutionBundleService()
        )
        self.reasoning_run_execution_bundle_consistency_service = (
            reasoning_run_execution_bundle_consistency_service
            or ReasoningRunExecutionBundleConsistencyService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Delegate Task 046 -> Task 047 -> Task 048 assemble."""
        # 1. Task 046 bundle.
        try:
            bundle = (
                self.reasoning_run_execution_bundle_service
                .build_for_session(db, session_id)
            )
        except ReasoningRunExecutionBundleContractError as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_FAILED",
                "Task 046 bundle failed: " + str(exc),
            ) from exc

        # 2. Task 047 audit of the exact returned bundle.
        try:
            consistency = (
                self.reasoning_run_execution_bundle_consistency_service
                .build(bundle=bundle)
            )
        except ReasoningRunExecutionBundleConsistencyContractError as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_CONSISTENCY_FAILED",
                "Task 047 audit failed: " + str(exc),
            ) from exc

        # 3. Assemble + validate.
        return self.build(
            session_id=session_id,
            execution_bundle=bundle,
            bundle_consistency=consistency,
        )

    def build(
        self,
        *,
        session_id: UUID,
        execution_bundle: Mapping[str, Any] | None = None,
        bundle_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the package. Pure; never mutates inputs."""
        if not isinstance(session_id, UUID):
            raise ReasoningRunExecutionAuditPackageContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(execution_bundle, Mapping):
            raise ReasoningRunExecutionAuditPackageContractError(
                "MISSING_EXECUTION_BUNDLE",
                "execution_bundle is required and must be a mapping",
            )
        if not isinstance(bundle_consistency, Mapping):
            raise ReasoningRunExecutionAuditPackageContractError(
                "MISSING_BUNDLE_CONSISTENCY",
                "bundle_consistency is required and must be a mapping",
            )

        # Normalize nested session_id on a local copy so we can delegate
        # to the upstream validators without mutating the caller's dicts.
        bundle_for_validation = dict(execution_bundle)
        raw_bundle_session_id = bundle_for_validation.get("session_id")
        if isinstance(raw_bundle_session_id, str):
            try:
                bundle_for_validation["session_id"] = UUID(
                    raw_bundle_session_id
                )
            except (ValueError, TypeError):
                pass

        # Validate the nested Task 046 bundle.
        try:
            ReasoningRunExecutionBundleService._validate_result(
                bundle_for_validation
            )
        except ReasoningRunExecutionBundleContractError as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_EXECUTION_BUNDLE",
                "Task 046 bundle failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_EXECUTION_BUNDLE",
                "Task 046 bundle failed its own validator: " + str(exc),
            ) from exc

        # Validate the nested Task 047 audit.
        try:
            ReasoningRunExecutionBundleConsistencyService._validate_result(
                dict(bundle_consistency)
            )
        except ReasoningRunExecutionBundleConsistencyContractError as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_CONSISTENCY",
                "Task 047 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_CONSISTENCY",
                "Task 047 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity agreement.
        bundle_session_id = _coerce_session_id(
            execution_bundle.get("session_id")
        )
        if bundle_session_id != session_id:
            raise ReasoningRunExecutionAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "execution_bundle.session_id does not match package "
                "session_id",
            )

        # Bundle audit availability and session consistency.
        if bundle_consistency.get("available") is not True:
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_AUDIT_UNAVAILABLE",
                "bundle_consistency.available is not True",
            )
        if bundle_consistency.get("session_consistent") is not True:
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_AUDIT_SESSION_INCONSISTENT",
                "bundle_consistency.session_consistent is not True",
            )

        # Fixed sources.
        if (
            execution_bundle.get("bundle_source")
            != REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046
        ):
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_SOURCE",
                "execution_bundle.bundle_source is not the Task 046 "
                "identifier: "
                + repr(execution_bundle.get("bundle_source")),
            )
        if (
            bundle_consistency.get("bundle_consistency_source")
            != REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047
        ):
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_CONSISTENCY_SOURCE",
                "bundle_consistency.bundle_consistency_source is not the "
                "Task 047 identifier: "
                + repr(
                    bundle_consistency.get("bundle_consistency_source")
                ),
            )

        # Package consistency derives from Task 047's bundle_consistent.
        # We deliberately do NOT compare Task 046's bundle_consistent
        # with Task 047's -- they have different meanings.
        expected_package_consistent = bool(
            bundle_consistency.get("bundle_consistent", False)
        )

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": expected_package_consistent,
            "session_id": session_id,
            "execution_bundle": dict(execution_bundle),
            "bundle_consistency": dict(bundle_consistency),
            "package_source": (
                REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionAuditPackageContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _PACKAGE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionAuditPackageContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningRunExecutionAuditPackageContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: "
                + type(result["session_id"]).__name__,
            )
        if not isinstance(result["execution_bundle"], Mapping):
            raise ReasoningRunExecutionAuditPackageContractError(
                "EXECUTION_BUNDLE_TYPE",
                "execution_bundle is not a mapping: "
                + type(result["execution_bundle"]).__name__,
            )
        if not isinstance(result["bundle_consistency"], Mapping):
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_CONSISTENCY_TYPE",
                "bundle_consistency is not a mapping: "
                + type(result["bundle_consistency"]).__name__,
            )
        # Nested validators, with session_id normalization.
        bundle_for_validation = dict(result["execution_bundle"])
        raw = bundle_for_validation.get("session_id")
        if isinstance(raw, str):
            try:
                bundle_for_validation["session_id"] = UUID(raw)
            except (ValueError, TypeError):
                pass
        try:
            ReasoningRunExecutionBundleService._validate_result(
                bundle_for_validation
            )
        except Exception as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_EXECUTION_BUNDLE",
                "nested Task 046 bundle failed its own validator: "
                + str(exc),
            ) from exc
        try:
            ReasoningRunExecutionBundleConsistencyService._validate_result(
                dict(result["bundle_consistency"])
            )
        except Exception as exc:
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_CONSISTENCY",
                "nested Task 047 audit failed its own validator: "
                + str(exc),
            ) from exc
        # Session identity.
        bundle_sid = _coerce_session_id(
            result["execution_bundle"].get("session_id")
        )
        if bundle_sid != result["session_id"]:
            raise ReasoningRunExecutionAuditPackageContractError(
                "SESSION_ID_MISMATCH",
                "execution_bundle.session_id does not match package "
                "session_id",
            )
        if result["bundle_consistency"].get("available") is not True:
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_AUDIT_UNAVAILABLE",
                "bundle_consistency.available is not True",
            )
        if (
            result["bundle_consistency"].get("session_consistent")
            is not True
        ):
            raise ReasoningRunExecutionAuditPackageContractError(
                "BUNDLE_AUDIT_SESSION_INCONSISTENT",
                "bundle_consistency.session_consistent is not True",
            )
        # Sources.
        if (
            result["execution_bundle"].get("bundle_source")
            != REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046
        ):
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_SOURCE",
                "execution_bundle.bundle_source is not the Task 046 "
                "identifier",
            )
        if (
            result["bundle_consistency"].get("bundle_consistency_source")
            != REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047
        ):
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_BUNDLE_CONSISTENCY_SOURCE",
                "bundle_consistency.bundle_consistency_source is not the "
                "Task 047 identifier",
            )
        if (
            result["package_source"]
            != REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048
        ):
            raise ReasoningRunExecutionAuditPackageContractError(
                "INVALID_PACKAGE_SOURCE",
                "package_source is not the Task 048 identifier: "
                + repr(result["package_source"]),
            )
        # Package consistency relationship.
        expected = bool(
            result["bundle_consistency"].get("bundle_consistent", False)
        )
        if result["package_consistent"] != expected:
            raise ReasoningRunExecutionAuditPackageContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match the Task 047 audit: "
                + repr(result["package_consistent"])
                + " != " + repr(expected),
            )

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_run_execution import (
    REASONING_RUN_EXECUTION_SOURCE_TASK_044,
    ReasoningRunExecutionContractError,
    ReasoningRunExecutionService,
)
from rop.services.reasoning_run_execution_consistency import (
    REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045,
    ReasoningRunExecutionConsistencyContractError,
    ReasoningRunExecutionConsistencyService,
)

REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046 = (
    "REASONING_RUN_EXECUTION_BUNDLE_TASK_046"
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "execution",
    "execution_consistency",
    "bundle_source",
)

_RESULT_BOOLEAN_FIELDS = ("available", "bundle_consistent")


class ReasoningRunExecutionBundleContractError(Exception):
    """Task 046: the bundle could not be assembled into a valid contract.

    Raised only when:

    - the Task 044 execution result is not shaped like its own contract,
    - the Task 045 audit result is not shaped like its own contract,
    - session identity or a fixed source identifier disagrees, or
    - the Task 045 audit itself is unavailable or internally invalid.

    Note that ``execution.execution_consistent`` (Task 044) and
    ``execution_consistency.execution_consistent`` (Task 045) have
    different meanings and are intentionally NOT required to be equal:

    - Task 044's value answers whether the underlying reasoning run
      was consistent.
    - Task 045's value answers whether the Task 044 execution contract
      itself was internally consistent.

    A valid FAILED execution, or a valid execution whose underlying
    reasoning run is legitimately inconsistent, is therefore a valid
    Task 046 bundle: both nested contracts are well-formed, and the
    bundle reports ``bundle_consistent = execution_consistency.execution_consistent``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionBundleService:
    """Task 046: bundle a Task 044 execution with its Task 045 audit.

    Composition only. Delegates execution to Task 044, then passes the
    exact returned execution result to Task 045, then assembles and
    validates the bundle. It does not execute the reasoning workflow,
    does not audit, and does not touch Tasks 042/043 or the underlying
    observation/candidate/evidence services directly.
    """

    def __init__(
        self,
        reasoning_run_execution_service: (
            ReasoningRunExecutionService | None
        ) = None,
        reasoning_run_execution_consistency_service: (
            ReasoningRunExecutionConsistencyService | None
        ) = None,
    ) -> None:
        self.reasoning_run_execution_service = (
            reasoning_run_execution_service
            or ReasoningRunExecutionService()
        )
        self.reasoning_run_execution_consistency_service = (
            reasoning_run_execution_consistency_service
            or ReasoningRunExecutionConsistencyService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Execute, audit, and bundle. Delegates exclusively to 044/045."""
        # 1. Task 044 execution.
        try:
            execution = self.reasoning_run_execution_service.execute_for_session(
                db, session_id
            )
        except ReasoningRunExecutionContractError as exc:
            raise ReasoningRunExecutionBundleContractError(
                "EXECUTION_FAILED",
                "Task 044 execution failed: " + str(exc),
            ) from exc

        # 2. Task 045 audit of the exact returned execution.
        try:
            audit = self.reasoning_run_execution_consistency_service.build(
                execution=execution
            )
        except ReasoningRunExecutionConsistencyContractError as exc:
            raise ReasoningRunExecutionBundleContractError(
                "AUDIT_FAILED",
                "Task 045 audit failed: " + str(exc),
            ) from exc

        # 3. Bundle + validate.
        return self.build(
            session_id=session_id,
            execution=execution,
            execution_consistency=audit,
        )

    def build(
        self,
        *,
        session_id: UUID,
        execution: Mapping[str, Any] | None = None,
        execution_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the bundle. Pure; never mutates inputs."""
        if not isinstance(session_id, UUID):
            raise ReasoningRunExecutionBundleContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(execution, Mapping):
            raise ReasoningRunExecutionBundleContractError(
                "MISSING_EXECUTION",
                "execution is required and must be a mapping",
            )
        if not isinstance(execution_consistency, Mapping):
            raise ReasoningRunExecutionBundleContractError(
                "MISSING_EXECUTION_CONSISTENCY",
                "execution_consistency is required and must be a mapping",
            )

        # Normalize the execution's session_id: in-process it is a UUID,
        # but through the JSON API it arrives as a string. Task 044's
        # validator requires a UUID, so coerce on a copy before
        # delegating.
        execution = dict(execution)
        raw_execution_session_id = execution.get("session_id")
        if isinstance(raw_execution_session_id, str):
            try:
                execution["session_id"] = UUID(raw_execution_session_id)
            except (ValueError, TypeError):
                pass

        # Rule A: delegate Task 044's validator.
        try:
            ReasoningRunExecutionService._validate_result(dict(execution))
        except ReasoningRunExecutionContractError as exc:
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION",
                "Task 044 execution failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION",
                "Task 044 execution failed its own validator: " + str(exc),
            ) from exc

        # Rule B: delegate Task 045's validator.
        try:
            ReasoningRunExecutionConsistencyService._validate_result(
                dict(execution_consistency)
            )
        except ReasoningRunExecutionConsistencyContractError as exc:
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION_CONSISTENCY",
                "Task 045 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION_CONSISTENCY",
                "Task 045 audit failed its own validator: " + str(exc),
            ) from exc

        # Rule C: session identity agrees.
        execution_session_id = execution.get("session_id")
        if isinstance(execution_session_id, str):
            try:
                execution_session_id = UUID(execution_session_id)
            except (ValueError, TypeError):
                execution_session_id = None
        if execution_session_id != session_id:
            raise ReasoningRunExecutionBundleContractError(
                "SESSION_ID_MISMATCH",
                "execution.session_id does not match the bundle session_id",
            )
        if execution_consistency.get("session_consistent") is not True:
            raise ReasoningRunExecutionBundleContractError(
                "SESSION_CONSISTENCY_FALSE",
                "execution_consistency.session_consistent is not True",
            )

        # Rule F: fixed sources.
        if (
            execution.get("execution_source")
            != REASONING_RUN_EXECUTION_SOURCE_TASK_044
        ):
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION_SOURCE",
                "execution.execution_source is not the Task 044 identifier: "
                + repr(execution.get("execution_source")),
            )
        if (
            execution_consistency.get("execution_consistency_source")
            != REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045
        ):
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_AUDIT_SOURCE",
                "execution_consistency.execution_consistency_source is not "
                "the Task 045 identifier: "
                + repr(execution_consistency.get("execution_consistency_source")),
            )

        # Rule E: bundle_consistent derives from Task 045's
        # execution_consistent.
        expected_bundle_consistent = bool(
            execution_consistency.get("execution_consistent", False)
        )
        if (
            bool(execution_consistency.get("available", False)) is not True
        ):
            raise ReasoningRunExecutionBundleContractError(
                "AUDIT_UNAVAILABLE",
                "execution_consistency.available is not True",
            )

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": expected_bundle_consistent,
            "session_id": session_id,
            "execution": dict(execution),
            "execution_consistency": dict(execution_consistency),
            "bundle_source": (
                REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionBundleContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionBundleContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningRunExecutionBundleContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: "
                + type(result["session_id"]).__name__,
            )
        if not isinstance(result["execution"], Mapping):
            raise ReasoningRunExecutionBundleContractError(
                "EXECUTION_TYPE",
                "execution is not a mapping: "
                + type(result["execution"]).__name__,
            )
        if not isinstance(result["execution_consistency"], Mapping):
            raise ReasoningRunExecutionBundleContractError(
                "EXECUTION_CONSISTENCY_TYPE",
                "execution_consistency is not a mapping: "
                + type(result["execution_consistency"]).__name__,
            )
        # Re-run the nested validators.
        try:
            ReasoningRunExecutionService._validate_result(
                dict(result["execution"])
            )
        except Exception as exc:
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION",
                "nested execution failed its own validator: " + str(exc),
            ) from exc
        try:
            ReasoningRunExecutionConsistencyService._validate_result(
                dict(result["execution_consistency"])
            )
        except Exception as exc:
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION_CONSISTENCY",
                "nested audit failed its own validator: " + str(exc),
            ) from exc
        # Audit availability and session consistency, mirrored from
        # build() so a manually supplied malformed bundle cannot
        # bypass them.
        if result["execution_consistency"].get("available") is not True:
            raise ReasoningRunExecutionBundleContractError(
                "AUDIT_UNAVAILABLE",
                "execution_consistency.available is not True",
            )
        if (
            result["execution_consistency"].get("session_consistent")
            is not True
        ):
            raise ReasoningRunExecutionBundleContractError(
                "SESSION_CONSISTENCY_FALSE",
                "execution_consistency.session_consistent is not True",
            )
        # Bundle consistency relationship.
        expected = bool(
            result["execution_consistency"].get(
                "execution_consistent", False
            )
        )
        if result["bundle_consistent"] != expected:
            raise ReasoningRunExecutionBundleContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match the nested audit: "
                + repr(result["bundle_consistent"])
                + " != " + repr(expected),
            )
        # Source identifiers.
        if (
            result["execution"].get("execution_source")
            != REASONING_RUN_EXECUTION_SOURCE_TASK_044
        ):
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_EXECUTION_SOURCE",
                "execution.execution_source is not the Task 044 identifier: "
                + repr(result["execution"].get("execution_source")),
            )
        if (
            result["execution_consistency"].get(
                "execution_consistency_source"
            )
            != REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045
        ):
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_AUDIT_SOURCE",
                "execution_consistency.execution_consistency_source is "
                "not the Task 045 identifier: "
                + repr(
                    result["execution_consistency"].get(
                        "execution_consistency_source"
                    )
                ),
            )
        if (
            result["bundle_source"]
            != REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046
        ):
            raise ReasoningRunExecutionBundleContractError(
                "INVALID_BUNDLE_SOURCE",
                "bundle_source is not the Task 046 identifier: "
                + repr(result["bundle_source"]),
            )
        # Session identity agreement.
        exec_session_id = result["execution"].get("session_id")
        if isinstance(exec_session_id, str):
            try:
                exec_session_id = UUID(exec_session_id)
            except (ValueError, TypeError):
                exec_session_id = None
        if exec_session_id != result["session_id"]:
            raise ReasoningRunExecutionBundleContractError(
                "SESSION_ID_MISMATCH",
                "execution.session_id does not match bundle session_id",
            )

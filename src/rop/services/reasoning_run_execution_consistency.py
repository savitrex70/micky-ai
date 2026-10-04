from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run import (
    REASONING_RUN_SOURCE_TASK_042,
    ReasoningRunContractError,
    ReasoningRunService,
)
from rop.services.reasoning_run_consistency import (
    REASONING_RUN_CONSISTENCY_SOURCE_TASK_043,
    ReasoningRunConsistencyContractError,
    ReasoningRunConsistencyService,
)
from rop.services.reasoning_run_execution import (
    EXECUTION_STAGE_IDS,
    EXECUTION_STAGE_SOURCES,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_SESSION_NOT_FOUND,
    REASONING_RUN_EXECUTION_SOURCE_TASK_044,
)

REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045 = (
    "REASONING_RUN_EXECUTION_CONSISTENCY_TASK_045"
)

_STATUS_COMPLETED = "COMPLETED"
_STATUS_FAILED = "FAILED"
_STATUS_SKIPPED = "SKIPPED"

_VALID_STATUSES = frozenset({_STATUS_COMPLETED, _STATUS_FAILED, _STATUS_SKIPPED})

_EXECUTION_REQUIRED_FIELDS = (
    "available",
    "outcome",
    "execution_consistent",
    "session_id",
    "completed_stage_count",
    "stage_count",
    "stages",
    "reasoning_run",
    "reasoning_run_consistency",
    "execution_source",
)

_STAGE_REQUIRED_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "status",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "execution_consistent",
    "session_consistent",
    "outcome_consistent",
    "availability_consistent",
    "stage_structure_consistent",
    "stage_status_consistent",
    "stage_count_consistent",
    "completed_stage_count_consistent",
    "nested_reasoning_run_consistent",
    "nested_reasoning_run_audit_consistent",
    "metadata_consistent",
    "source_consistency",
    "consistency_issues",
    "execution_consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "execution_consistent",
    "session_consistent",
    "outcome_consistent",
    "availability_consistent",
    "stage_structure_consistent",
    "stage_status_consistent",
    "stage_count_consistent",
    "completed_stage_count_consistent",
    "nested_reasoning_run_consistent",
    "nested_reasoning_run_audit_consistent",
    "metadata_consistent",
    "source_consistency",
)

# Deterministic issue ordering.
_ISSUE_ORDER = (
    "MISSING_EXECUTION_FIELD",
    "INVALID_EXECUTION_OUTCOME",
    "SESSION_ID_INVALID",
    "STAGE_STRUCTURE_MISMATCH",
    "STAGE_ORDER_MISMATCH",
    "STAGE_SOURCE_MISMATCH",
    "STAGE_STATUS_MISMATCH",
    "STAGE_COUNT_MISMATCH",
    "COMPLETED_STAGE_COUNT_MISMATCH",
    "OUTCOME_MISMATCH",
    "AVAILABILITY_MISMATCH",
    "NESTED_REASONING_RUN_MISMATCH",
    "NESTED_REASONING_RUN_AUDIT_MISMATCH",
    "EXECUTION_CONSISTENCY_MISMATCH",
    "EXECUTION_SOURCE_MISMATCH",
)


class ReasoningRunExecutionConsistencyContractError(Exception):
    """Task 045: the supplied execution cannot be audited at all.

    Raised only when the input is not a mapping or is so malformed that
    no audit can be produced. Ordinary execution-contract disagreements
    are reported as consistency_issues, not raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionConsistencyService:
    """Task 045: pure audit of a Task 044 execution result.

    Consumes a supplied ReasoningRunExecutionRead, independently
    derives every consistency relationship declared by the Task 044
    contract, and reports disagreements through consistency_issues.
    Reuses Task 042's and Task 043's own validators for the nested
    results. Never queries the database, never invokes Task 044
    execution, never mutates its input.
    """

    def build(
        self,
        *,
        execution: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied Task 044 execution result. Pure."""
        if execution is None:
            raise ReasoningRunExecutionConsistencyContractError(
                "MISSING_EXECUTION", "execution is required"
            )
        if not isinstance(execution, Mapping):
            raise ReasoningRunExecutionConsistencyContractError(
                "EXECUTION_TYPE",
                "execution is not a mapping: " + type(execution).__name__,
            )

        issues: list[str] = []
        for field in _EXECUTION_REQUIRED_FIELDS:
            if field not in execution:
                issues.append("MISSING_EXECUTION_FIELD")

        outcome = execution.get("outcome")
        if outcome not in (
            OUTCOME_COMPLETED,
            OUTCOME_FAILED,
            OUTCOME_SESSION_NOT_FOUND,
        ):
            issues.append("INVALID_EXECUTION_OUTCOME")
        elif outcome == OUTCOME_SESSION_NOT_FOUND:
            # Task 044 never returns SESSION_NOT_FOUND as a result; it
            # raises for that case. A supplied result carrying it is
            # invalid execution data.
            issues.append("INVALID_EXECUTION_OUTCOME")

        # session_id may be a UUID (in-process result) or its JSON
        # string form (API response). Accept either; reject anything
        # that is neither a UUID nor a UUID-shaped string.
        raw_session_id = execution.get("session_id")
        if isinstance(raw_session_id, UUID):
            pass
        elif isinstance(raw_session_id, str):
            try:
                UUID(raw_session_id)
            except (ValueError, TypeError):
                issues.append("SESSION_ID_INVALID")
        else:
            issues.append("SESSION_ID_INVALID")

        # --- Stage structure checks ---
        stages = execution.get("stages")
        stage_by_id: dict[str, Mapping[str, Any]] = {}
        if not isinstance(stages, list):
            issues.append("STAGE_STRUCTURE_MISMATCH")
            stages = []
        else:
            actual_ids = []
            seen_ids: set[str] = set()
            for s in stages:
                if not isinstance(s, Mapping):
                    issues.append("STAGE_STRUCTURE_MISMATCH")
                    continue
                for field in _STAGE_REQUIRED_FIELDS:
                    if field not in s:
                        issues.append("STAGE_STRUCTURE_MISMATCH")
                sid = s.get("stage_id")
                if not isinstance(sid, str) or not sid:
                    issues.append("STAGE_STRUCTURE_MISMATCH")
                    continue
                if sid in seen_ids:
                    issues.append("STAGE_STRUCTURE_MISMATCH")
                seen_ids.add(sid)
                actual_ids.append(sid)
                stage_by_id[sid] = s
            if tuple(actual_ids) != EXECUTION_STAGE_IDS:
                if "STAGE_STRUCTURE_MISMATCH" not in issues:
                    issues.append("STAGE_STRUCTURE_MISMATCH")

        # Stage order.
        for i, s in enumerate(stages):
            if not isinstance(s, Mapping):
                continue
            if s.get("stage_order") != i + 1:
                if "STAGE_ORDER_MISMATCH" not in issues:
                    issues.append("STAGE_ORDER_MISMATCH")

        # Stage source.
        for s in stages:
            if not isinstance(s, Mapping):
                continue
            sid = s.get("stage_id")
            expected_source = EXECUTION_STAGE_SOURCES.get(sid)
            if expected_source is None or s.get("stage_source") != expected_source:
                if "STAGE_SOURCE_MISMATCH" not in issues:
                    issues.append("STAGE_SOURCE_MISMATCH")

        # Stage status.
        for s in stages:
            if not isinstance(s, Mapping):
                continue
            if s.get("status") not in _VALID_STATUSES:
                if "STAGE_STATUS_MISMATCH" not in issues:
                    issues.append("STAGE_STATUS_MISMATCH")

        # --- Count checks ---
        if execution.get("stage_count") != len(stages):
            issues.append("STAGE_COUNT_MISMATCH")
        completed = sum(
            1
            for s in stages
            if isinstance(s, Mapping) and s.get("status") == _STATUS_COMPLETED
        )
        if execution.get("completed_stage_count") != completed:
            issues.append("COMPLETED_STAGE_COUNT_MISMATCH")

        # --- Outcome / availability semantics ---
        available = execution.get("available")
        if outcome == OUTCOME_COMPLETED:
            if available is not True:
                issues.append("AVAILABILITY_MISMATCH")
            if any(
                not isinstance(s, Mapping) or s.get("status") != _STATUS_COMPLETED
                for s in stages
            ):
                issues.append("OUTCOME_MISMATCH")
            if execution.get("reasoning_run") is None:
                issues.append("OUTCOME_MISMATCH")
                issues.append("NESTED_REASONING_RUN_MISMATCH")
            if execution.get("reasoning_run_consistency") is None:
                issues.append("OUTCOME_MISMATCH")
                issues.append("NESTED_REASONING_RUN_AUDIT_MISMATCH")
        elif outcome == OUTCOME_FAILED:
            if available is not False:
                issues.append("AVAILABILITY_MISMATCH")
            failed_count = sum(
                1
                for s in stages
                if isinstance(s, Mapping) and s.get("status") == _STATUS_FAILED
            )
            if failed_count != 1:
                issues.append("OUTCOME_MISMATCH")
            else:
                # Stages before the failed stage must be COMPLETED;
                # stages after must be SKIPPED.
                failed_index = next(
                    i
                    for i, s in enumerate(stages)
                    if isinstance(s, Mapping) and s.get("status") == _STATUS_FAILED
                )
                for i, s in enumerate(stages):
                    if not isinstance(s, Mapping):
                        continue
                    status = s.get("status")
                    if i < failed_index and status != _STATUS_COMPLETED:
                        issues.append("OUTCOME_MISMATCH")
                    if i > failed_index and status != _STATUS_SKIPPED:
                        issues.append("OUTCOME_MISMATCH")
            if execution.get("reasoning_run") is not None:
                issues.append("OUTCOME_MISMATCH")
            if execution.get("reasoning_run_consistency") is not None:
                issues.append("OUTCOME_MISMATCH")
            if execution.get("execution_consistent") is not False:
                issues.append("EXECUTION_CONSISTENCY_MISMATCH")

        # --- Nested Task 042 validation ---
        nested_run = execution.get("reasoning_run")
        derived_execution_consistent: bool | None = None
        if outcome == OUTCOME_COMPLETED and nested_run is not None:
            if not isinstance(nested_run, Mapping):
                issues.append("NESTED_REASONING_RUN_MISMATCH")
            else:
                try:
                    ReasoningRunService._validate_result(dict(nested_run))
                except ReasoningRunContractError:
                    issues.append("NESTED_REASONING_RUN_MISMATCH")
                except Exception:
                    issues.append("NESTED_REASONING_RUN_MISMATCH")
                if nested_run.get("run_source") != REASONING_RUN_SOURCE_TASK_042:
                    issues.append("NESTED_REASONING_RUN_MISMATCH")

        # --- Nested Task 043 validation ---
        nested_audit = execution.get("reasoning_run_consistency")
        if outcome == OUTCOME_COMPLETED and nested_audit is not None:
            if not isinstance(nested_audit, Mapping):
                issues.append("NESTED_REASONING_RUN_AUDIT_MISMATCH")
            else:
                try:
                    ReasoningRunConsistencyService._validate_result(dict(nested_audit))
                except ReasoningRunConsistencyContractError:
                    issues.append("NESTED_REASONING_RUN_AUDIT_MISMATCH")
                except Exception:
                    issues.append("NESTED_REASONING_RUN_AUDIT_MISMATCH")
                if (
                    nested_audit.get("run_consistency_source")
                    != REASONING_RUN_CONSISTENCY_SOURCE_TASK_043
                ):
                    issues.append("NESTED_REASONING_RUN_AUDIT_MISMATCH")
                derived_execution_consistent = bool(
                    nested_audit.get("run_consistent", False)
                )

        # For a COMPLETED execution, execution_consistent must match the
        # nested Task 043 run_consistent.
        if outcome == OUTCOME_COMPLETED and derived_execution_consistent is not None:
            if execution.get("execution_consistent") != derived_execution_consistent:
                issues.append("EXECUTION_CONSISTENCY_MISMATCH")

        # --- Execution source ---
        if execution.get("execution_source") != REASONING_RUN_EXECUTION_SOURCE_TASK_044:
            issues.append("EXECUTION_SOURCE_MISMATCH")

        # --- Deterministic issue ordering, dedupe ---
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # --- Derive flags ---
        session_consistent = "SESSION_ID_INVALID" not in unique_issues
        outcome_consistent = not any(
            i in unique_issues
            for i in (
                "OUTCOME_MISMATCH",
                "INVALID_EXECUTION_OUTCOME",
            )
        )
        availability_consistent = "AVAILABILITY_MISMATCH" not in unique_issues
        stage_structure_consistent = (
            "STAGE_STRUCTURE_MISMATCH" not in unique_issues
            and "STAGE_ORDER_MISMATCH" not in unique_issues
        )
        stage_status_consistent = "STAGE_STATUS_MISMATCH" not in unique_issues
        stage_count_consistent = "STAGE_COUNT_MISMATCH" not in unique_issues
        completed_stage_count_consistent = (
            "COMPLETED_STAGE_COUNT_MISMATCH" not in unique_issues
        )
        nested_reasoning_run_consistent = (
            "NESTED_REASONING_RUN_MISMATCH" not in unique_issues
        )
        nested_reasoning_run_audit_consistent = (
            "NESTED_REASONING_RUN_AUDIT_MISMATCH" not in unique_issues
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in (
                "STAGE_STRUCTURE_MISMATCH",
                "STAGE_ORDER_MISMATCH",
                "STAGE_COUNT_MISMATCH",
                "COMPLETED_STAGE_COUNT_MISMATCH",
            )
        )
        # Nested source checks are independent of the issues list: a
        # wrong nested source produces NESTED_REASONING_RUN_MISMATCH
        # (or the audit equivalent), but source_consistency must
        # additionally reflect the source check directly, not rely on
        # the general-purpose nested mismatch flag.
        _nested_run_source_bad = (
            isinstance(nested_run, Mapping)
            and nested_run.get("run_source") != REASONING_RUN_SOURCE_TASK_042
        )
        _nested_audit_source_bad = (
            isinstance(nested_audit, Mapping)
            and nested_audit.get("run_consistency_source")
            != REASONING_RUN_CONSISTENCY_SOURCE_TASK_043
        )
        source_consistency = (
            not any(
                i in unique_issues
                for i in (
                    "STAGE_SOURCE_MISMATCH",
                    "EXECUTION_SOURCE_MISMATCH",
                )
            )
            and not _nested_run_source_bad
            and not _nested_audit_source_bad
        )

        result: dict[str, Any] = {
            "available": True,
            "execution_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "outcome_consistent": outcome_consistent,
            "availability_consistent": availability_consistent,
            "stage_structure_consistent": stage_structure_consistent,
            "stage_status_consistent": stage_status_consistent,
            "stage_count_consistent": stage_count_consistent,
            "completed_stage_count_consistent": completed_stage_count_consistent,
            "nested_reasoning_run_consistent": nested_reasoning_run_consistent,
            "nested_reasoning_run_audit_consistent": (
                nested_reasoning_run_audit_consistent
            ),
            "metadata_consistent": metadata_consistent,
            "source_consistency": source_consistency,
            "consistency_issues": ordered_issues,
            "execution_consistency_source": (
                REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningRunExecutionConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningRunExecutionConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningRunExecutionConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningRunExecutionConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["execution_consistency_source"]
            != REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045
        ):
            raise ReasoningRunExecutionConsistencyContractError(
                "INVALID_SOURCE",
                "execution_consistency_source is not the Task 045 "
                "identifier: " + repr(result["execution_consistency_source"]),
            )
        if result["execution_consistent"] != (len(issues) == 0):
            raise ReasoningRunExecutionConsistencyContractError(
                "EXECUTION_CONSISTENT_MISMATCH",
                "execution_consistent does not match consistency_issues",
            )

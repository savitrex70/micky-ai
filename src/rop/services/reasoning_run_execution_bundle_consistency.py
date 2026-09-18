from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run_execution import (
    REASONING_RUN_EXECUTION_SOURCE_TASK_044,
    ReasoningRunExecutionContractError,
    ReasoningRunExecutionService,
)
from rop.services.reasoning_run_execution_bundle import (
    REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046,
)
from rop.services.reasoning_run_execution_consistency import (
    REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045,
    ReasoningRunExecutionConsistencyContractError,
    ReasoningRunExecutionConsistencyService,
)

REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047 = (
    "REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_TASK_047"
)

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "execution",
    "execution_consistency",
    "bundle_source",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_execution_consistent",
    "nested_execution_audit_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_execution_consistent",
    "nested_execution_audit_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_BUNDLE_FIELD",
    "INVALID_BUNDLE_AVAILABLE",
    "SESSION_ID_INVALID",
    "SESSION_ID_MISMATCH",
    "NESTED_EXECUTION_MISMATCH",
    "NESTED_EXECUTION_AUDIT_MISMATCH",
    "BUNDLE_AVAILABILITY_MISMATCH",
    "BUNDLE_RELATIONSHIP_MISMATCH",
    "AUDIT_UNAVAILABLE",
    "EXECUTION_SOURCE_MISMATCH",
    "EXECUTION_AUDIT_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
)


class ReasoningRunExecutionBundleConsistencyContractError(Exception):
    """Task 047: the supplied bundle cannot be audited at all.

    Raised only when the input is not a mapping or is so malformed that
    no audit can be produced. Ordinary bundle-contract disagreements
    are reported as consistency_issues, not raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _coerce_session_id(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError):
            return None
    return None


class ReasoningRunExecutionBundleConsistencyService:
    """Task 047: pure audit of a Task 046 execution + audit bundle.

    Consumes a supplied ReasoningRunExecutionBundleRead, independently
    re-derives every bundle-contract relationship, and reports
    disagreements through consistency_issues. Reuses Task 044's and
    Task 045's own validators for the nested results. Never queries
    the database, never invokes Task 044 or Task 045 execution
    workflows, never mutates its input.
    """

    def build(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied Task 046 bundle. Pure and deterministic."""
        if bundle is None:
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "MISSING_BUNDLE", "bundle is required"
            )
        if not isinstance(bundle, Mapping):
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "BUNDLE_TYPE",
                "bundle is not a mapping: " + type(bundle).__name__,
            )

        issues: list[str] = []

        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in bundle:
                issues.append("MISSING_BUNDLE_FIELD")

        # Availability.
        if bundle.get("available") is not True:
            if "available" in bundle:
                issues.append("INVALID_BUNDLE_AVAILABLE")
            issues.append("BUNDLE_AVAILABILITY_MISMATCH")

        # Session id.
        bundle_session_id = _coerce_session_id(bundle.get("session_id"))
        if bundle_session_id is None:
            issues.append("SESSION_ID_INVALID")

        # Nested objects.
        execution = bundle.get("execution")
        execution_consistency = bundle.get("execution_consistency")

        if not isinstance(execution, Mapping):
            issues.append("NESTED_EXECUTION_MISMATCH")
        else:
            # The JSON API returns session_id as a string; Task 044's
            # validator requires a UUID. Coerce on a local copy so we
            # can delegate to the canonical validator without mutating
            # the caller's mapping.
            execution_for_validation = dict(execution)
            raw_sid = execution_for_validation.get("session_id")
            if isinstance(raw_sid, str):
                try:
                    execution_for_validation["session_id"] = UUID(raw_sid)
                except (ValueError, TypeError):
                    pass
            try:
                ReasoningRunExecutionService._validate_result(
                    execution_for_validation
                )
            except ReasoningRunExecutionContractError:
                issues.append("NESTED_EXECUTION_MISMATCH")
            except Exception:
                issues.append("NESTED_EXECUTION_MISMATCH")

        if not isinstance(execution_consistency, Mapping):
            issues.append("NESTED_EXECUTION_AUDIT_MISMATCH")
        else:
            try:
                ReasoningRunExecutionConsistencyService._validate_result(
                    dict(execution_consistency)
                )
            except ReasoningRunExecutionConsistencyContractError:
                issues.append("NESTED_EXECUTION_AUDIT_MISMATCH")
            except Exception:
                issues.append("NESTED_EXECUTION_AUDIT_MISMATCH")

        # Session identity agreement.
        if isinstance(execution, Mapping) and bundle_session_id is not None:
            exec_session_id = _coerce_session_id(
                execution.get("session_id")
            )
            if exec_session_id != bundle_session_id:
                issues.append("SESSION_ID_MISMATCH")
        if isinstance(execution_consistency, Mapping):
            if execution_consistency.get("session_consistent") is not True:
                if "SESSION_ID_MISMATCH" not in issues:
                    issues.append("SESSION_ID_MISMATCH")

        # Bundle relationship: bundle.bundle_consistent must mirror the
        # nested Task 045 execution_consistent. We do NOT compare
        # execution.execution_consistent against
        # execution_consistency.execution_consistent -- those are
        # deliberately different fields.
        if isinstance(execution_consistency, Mapping):
            expected_bundle_consistent = bool(
                execution_consistency.get("execution_consistent", False)
            )
            if bundle.get("bundle_consistent") != expected_bundle_consistent:
                issues.append("BUNDLE_RELATIONSHIP_MISMATCH")

        # Audit availability.
        if isinstance(execution_consistency, Mapping):
            if execution_consistency.get("available") is not True:
                issues.append("AUDIT_UNAVAILABLE")

        # Source checks.
        if isinstance(execution, Mapping):
            if (
                execution.get("execution_source")
                != REASONING_RUN_EXECUTION_SOURCE_TASK_044
            ):
                issues.append("EXECUTION_SOURCE_MISMATCH")
        if isinstance(execution_consistency, Mapping):
            if (
                execution_consistency.get("execution_consistency_source")
                != REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045
            ):
                issues.append("EXECUTION_AUDIT_SOURCE_MISMATCH")
        if (
            bundle.get("bundle_source")
            != REASONING_RUN_EXECUTION_BUNDLE_SOURCE_TASK_046
        ):
            issues.append("BUNDLE_SOURCE_MISMATCH")

        # Deterministic ordering, dedupe.
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # Derive flags.
        session_consistent = not any(
            i in unique_issues
            for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_execution_consistent = (
            "NESTED_EXECUTION_MISMATCH" not in unique_issues
        )
        nested_execution_audit_consistent = (
            "NESTED_EXECUTION_AUDIT_MISMATCH" not in unique_issues
            and "AUDIT_UNAVAILABLE" not in unique_issues
        )
        bundle_relationship_consistent = (
            "BUNDLE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "EXECUTION_SOURCE_MISMATCH",
                "EXECUTION_AUDIT_SOURCE_MISMATCH",
                "BUNDLE_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in (
                "MISSING_BUNDLE_FIELD",
                "INVALID_BUNDLE_AVAILABLE",
                "BUNDLE_AVAILABILITY_MISMATCH",
            )
        )

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_execution_consistent": nested_execution_consistent,
            "nested_execution_audit_consistent": (
                nested_execution_audit_consistent
            ),
            "bundle_relationship_consistent": (
                bundle_relationship_consistent
            ),
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "bundle_consistency_source": (
                REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionBundleConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunExecutionBundleConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: "
                + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningRunExecutionBundleConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["bundle_consistency_source"]
            != REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047
        ):
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "INVALID_SOURCE",
                "bundle_consistency_source is not the Task 047 identifier: "
                + repr(result["bundle_consistency_source"]),
            )
        if result["bundle_consistent"] != (len(issues) == 0):
            raise ReasoningRunExecutionBundleConsistencyContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match consistency_issues",
            )

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_run import (
    ReasoningRunService,
)
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
)

REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056 = (
    "REASONING_CONTEXT_CONSISTENCY_TASK_056"
)
"""Fixed structural-contract identifier for Task 056 results."""

_CONTEXT_REQUIRED_FIELDS = (
    "available",
    "context_consistent",
    "session_id",
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
    "reasoning_pipeline",
    "reasoning_run_consistency",
    "context_source",
)

_EXPECTED_CONTEXT_SOURCE = "REASONING_CONTEXT_TASK_055"

_RESULT_REQUIRED_FIELDS = (
    "available",
    "context_consistent",
    "session_consistent",
    "nested_reasoning_run_consistent",
    "nested_reasoning_run_audit_consistent",
    "candidate_state_consistent",
    "candidate_count_consistent",
    "audit_provenance_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "context_consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "context_consistent",
    "session_consistent",
    "nested_reasoning_run_consistent",
    "nested_reasoning_run_audit_consistent",
    "candidate_state_consistent",
    "candidate_count_consistent",
    "audit_provenance_consistent",
    "source_consistency",
    "metadata_consistent",
)

# Deterministic fixed ordering for consistency_issues.
_ISSUE_ORDER = (
    "MISSING_CONTEXT_FIELD",
    "CONTEXT_NOT_AVAILABLE",
    "INVALID_SESSION_ID",
    "INVALID_OBSERVATIONS",
    "INVALID_ENTITIES",
    "INVALID_MISSING_INFORMATION",
    "INVALID_TEMPLATE_CONTEXT",
    "INVALID_CANDIDATE_STATE",
    "INVALID_REASONING_PIPELINE_TYPE",
    "INVALID_REASONING_RUN_CONSISTENCY_TYPE",
    "INVALID_CONTEXT_SOURCE",
    "INVALID_NESTED_REASONING_RUN",
    "INVALID_NESTED_REASONING_RUN_CONSISTENCY",
    "AUDIT_PROVENANCE_COMPUTE_FAILED",
    "AUDIT_PROVENANCE_MISMATCH",
    "CANDIDATE_COUNT_MISMATCH",
)

_LIST_FIELD_ISSUES = (
    ("observations", "INVALID_OBSERVATIONS"),
    ("entities", "INVALID_ENTITIES"),
    ("missing_information", "INVALID_MISSING_INFORMATION"),
    ("template_context", "INVALID_TEMPLATE_CONTEXT"),
    ("candidate_state", "INVALID_CANDIDATE_STATE"),
)


class ReasoningContextConsistencyContractError(Exception):
    """Task 056: the supplied input is too malformed to audit.

    Raised only when the input is not a mapping at all (or is missing
    entirely), so no audit can be produced. Ordinary disagreements
    between the package and the nested contracts are recorded in
    ``consistency_issues`` instead of raising.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningContextConsistencyService:
    """Task 056: deterministic audit of a Task 055 context package.

    Pure, read-only, DB-free, HTTP-free, LLM-free. Delegates nested
    structural validation to Task 042's and Task 043's own static
    validators and provenance to Task 043's canonical fingerprint
    helper -- never re-implements them and never calls any ``build``
    method on an upstream service.
    """

    def build(
        self,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied Task 055 context. Pure; never mutates."""
        if context is None:
            raise ReasoningContextConsistencyContractError(
                "MISSING_CONTEXT", "context is required"
            )
        if not isinstance(context, Mapping):
            raise ReasoningContextConsistencyContractError(
                "CONTEXT_TYPE",
                "context is not a mapping: "
                + type(context).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        # --- Top-level structure ---
        for field in _CONTEXT_REQUIRED_FIELDS:
            if field not in context:
                _add("MISSING_CONTEXT_FIELD")

        # --- Availability ---
        if context.get("available") is not True:
            _add("CONTEXT_NOT_AVAILABLE")

        # --- Session identity ---
        if not isinstance(context.get("session_id"), UUID):
            _add("INVALID_SESSION_ID")

        # --- List fields ---
        for field, issue in _LIST_FIELD_ISSUES:
            if field in context and not isinstance(context[field], list):
                _add(issue)

        # --- Context source ---
        if context.get("context_source") != _EXPECTED_CONTEXT_SOURCE:
            _add("INVALID_CONTEXT_SOURCE")

        # --- Nested Task 042 ---
        reasoning_pipeline = context.get("reasoning_pipeline")
        if not isinstance(reasoning_pipeline, Mapping):
            _add("INVALID_REASONING_PIPELINE_TYPE")
            _add("INVALID_NESTED_REASONING_RUN")
        else:
            try:
                ReasoningRunService._validate_result(
                    dict(reasoning_pipeline)
                )
            except Exception:
                _add("INVALID_NESTED_REASONING_RUN")

        # --- Nested Task 043 ---
        reasoning_run_consistency = context.get("reasoning_run_consistency")
        if not isinstance(reasoning_run_consistency, Mapping):
            _add("INVALID_REASONING_RUN_CONSISTENCY_TYPE")
            _add("INVALID_NESTED_REASONING_RUN_CONSISTENCY")
        else:
            try:
                ReasoningRunConsistencyService._validate_result(
                    dict(reasoning_run_consistency)
                )
            except Exception:
                _add("INVALID_NESTED_REASONING_RUN_CONSISTENCY")

        # --- Provenance (recompute fingerprint from the supplied run) ---
        if isinstance(reasoning_pipeline, Mapping) and isinstance(
            reasoning_run_consistency, Mapping
        ):
            try:
                expected_fingerprint = (
                    ReasoningRunConsistencyService._run_fingerprint(
                        reasoning_pipeline
                    )
                )
            except Exception:
                _add("AUDIT_PROVENANCE_COMPUTE_FAILED")
            else:
                actual_fingerprint = reasoning_run_consistency.get(
                    "audited_run_fingerprint"
                )
                if actual_fingerprint != expected_fingerprint:
                    _add("AUDIT_PROVENANCE_MISMATCH")

        # --- Candidate count relationship ---
        candidate_state = context.get("candidate_state")
        if isinstance(reasoning_pipeline, Mapping) and isinstance(
            candidate_state, list
        ):
            if (
                reasoning_pipeline.get("candidate_count")
                != len(candidate_state)
            ):
                _add("CANDIDATE_COUNT_MISMATCH")

        # --- Deterministic ordering, dedupe, append unknowns sorted ---
        unique = set(issues)
        ordered = [i for i in _ISSUE_ORDER if i in unique]
        leftovers = sorted(unique - set(_ISSUE_ORDER))
        ordered.extend(leftovers)

        candidate_state_consistent = (
            "INVALID_CANDIDATE_STATE" not in unique
        )
        candidate_count_consistent = (
            "CANDIDATE_COUNT_MISMATCH" not in unique
        )
        session_consistent = "INVALID_SESSION_ID" not in unique
        nested_reasoning_run_consistent = (
            "INVALID_NESTED_REASONING_RUN" not in unique
        )
        nested_reasoning_run_audit_consistent = (
            "INVALID_NESTED_REASONING_RUN_CONSISTENCY" not in unique
        )
        audit_provenance_consistent = (
            "AUDIT_PROVENANCE_MISMATCH" not in unique
            and "AUDIT_PROVENANCE_COMPUTE_FAILED" not in unique
        )
        source_consistency = "INVALID_CONTEXT_SOURCE" not in unique
        metadata_consistent = (
            "MISSING_CONTEXT_FIELD" not in unique
            and "CANDIDATE_COUNT_MISMATCH" not in unique
        )
        context_consistent = not ordered

        result: dict[str, Any] = {
            "available": True,
            "context_consistent": context_consistent,
            "session_consistent": session_consistent,
            "nested_reasoning_run_consistent": (
                nested_reasoning_run_consistent
            ),
            "nested_reasoning_run_audit_consistent": (
                nested_reasoning_run_audit_consistent
            ),
            "candidate_state_consistent": candidate_state_consistent,
            "candidate_count_consistent": candidate_count_consistent,
            "audit_provenance_consistent": audit_provenance_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered,
            "context_consistency_source": (
                REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningContextConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningContextConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningContextConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: "
                + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningContextConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningContextConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningContextConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: "
                + repr(issues),
            )
        if (
            result["context_consistency_source"]
            != REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
        ):
            raise ReasoningContextConsistencyContractError(
                "INVALID_SOURCE",
                "context_consistency_source is not the Task 056 "
                "identifier: "
                + repr(result["context_consistency_source"]),
            )
        if result["context_consistent"] != (len(issues) == 0):
            raise ReasoningContextConsistencyContractError(
                "CONTEXT_CONSISTENT_MISMATCH",
                "context_consistent does not match consistency_issues",
            )

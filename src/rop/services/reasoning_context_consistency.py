from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.schemas.candidate_hypothesis import CandidateHypothesisRead
from rop.schemas.entity import EntityRead
from rop.schemas.missing_information import MissingInformationRead
from rop.schemas.observation import ObservationRead
from rop.schemas.reasoning_context import ReasoningContextRead
from rop.schemas.template_match import TemplateMatchRead
from rop.services.reasoning_run import (
    ReasoningRunService,
)
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
)

REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056 = "REASONING_CONTEXT_CONSISTENCY_TASK_056"
"""Fixed structural-contract identifier for Task 056 results."""

_CONTEXT_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

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
    "audited_context_fingerprint",
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
    "INVALID_OBSERVATION_ITEM",
    "OBSERVATION_SESSION_MISMATCH",
    "INVALID_ENTITIES",
    "INVALID_ENTITY_ITEM",
    "ENTITY_SESSION_MISMATCH",
    "INVALID_MISSING_INFORMATION",
    "INVALID_MISSING_INFORMATION_ITEM",
    "MISSING_INFORMATION_SESSION_MISMATCH",
    "INVALID_TEMPLATE_CONTEXT",
    "INVALID_TEMPLATE_MATCH_ITEM",
    "TEMPLATE_MATCH_SESSION_MISMATCH",
    "INVALID_CANDIDATE_STATE",
    "INVALID_CANDIDATE_ITEM",
    "CANDIDATE_SESSION_MISMATCH",
    "INVALID_REASONING_PIPELINE_TYPE",
    "INVALID_REASONING_RUN_CONSISTENCY_TYPE",
    "INVALID_CONTEXT_SOURCE",
    "INVALID_NESTED_REASONING_RUN",
    "INVALID_NESTED_REASONING_RUN_CONSISTENCY",
    "AUDIT_PROVENANCE_CHECK_UNAVAILABLE",
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

# Typed-collection contracts from Task 055's schema. Each list element
# is validated against its Pydantic Read model (reused, not
# duplicated), and where the model carries session_id, that value must
# match the context's session_id.
_ELEMENT_SCHEMAS = (
    (
        "observations",
        ObservationRead,
        "INVALID_OBSERVATION_ITEM",
        "OBSERVATION_SESSION_MISMATCH",
    ),
    (
        "entities",
        EntityRead,
        "INVALID_ENTITY_ITEM",
        "ENTITY_SESSION_MISMATCH",
    ),
    (
        "missing_information",
        MissingInformationRead,
        "INVALID_MISSING_INFORMATION_ITEM",
        "MISSING_INFORMATION_SESSION_MISMATCH",
    ),
    (
        "template_context",
        TemplateMatchRead,
        "INVALID_TEMPLATE_MATCH_ITEM",
        "TEMPLATE_MATCH_SESSION_MISMATCH",
    ),
    (
        "candidate_state",
        CandidateHypothesisRead,
        "INVALID_CANDIDATE_ITEM",
        "CANDIDATE_SESSION_MISMATCH",
    ),
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
                "context is not a mapping: " + type(context).__name__,
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

        # --- Per-element contract validation ---
        # Each list is typed (list[SomeRead]). Validate every element
        # against its schema and, where the schema carries session_id,
        # verify it belongs to this context's session. Missing or
        # non-list values were already reported above; skip them here
        # so we don't double-report.
        context_session_id = context.get("session_id")
        candidate_items_ok = True
        for (
            field_name,
            schema_cls,
            invalid_issue,
            mismatch_issue,
        ) in _ELEMENT_SCHEMAS:
            value = context.get(field_name)
            if not isinstance(value, list):
                continue
            for item in value:
                try:
                    validated = schema_cls.model_validate(item)
                except Exception:
                    _add(invalid_issue)
                    if field_name == "candidate_state":
                        candidate_items_ok = False
                    continue
                if validated.session_id != context_session_id:
                    _add(mismatch_issue)
                    if field_name == "candidate_state":
                        candidate_items_ok = False

        # --- Context source ---
        if context.get("context_source") != _EXPECTED_CONTEXT_SOURCE:
            _add("INVALID_CONTEXT_SOURCE")

        # --- Nested Task 042 ---
        reasoning_pipeline = context.get("reasoning_pipeline")
        pipeline_valid = False
        if not isinstance(reasoning_pipeline, Mapping):
            _add("INVALID_REASONING_PIPELINE_TYPE")
            _add("INVALID_NESTED_REASONING_RUN")
        else:
            try:
                ReasoningRunService._validate_result(dict(reasoning_pipeline))
                pipeline_valid = True
            except Exception:
                _add("INVALID_NESTED_REASONING_RUN")

        # --- Nested Task 043 ---
        reasoning_run_consistency = context.get("reasoning_run_consistency")
        audit_valid = False
        if not isinstance(reasoning_run_consistency, Mapping):
            _add("INVALID_REASONING_RUN_CONSISTENCY_TYPE")
            _add("INVALID_NESTED_REASONING_RUN_CONSISTENCY")
        else:
            try:
                ReasoningRunConsistencyService._validate_result(
                    dict(reasoning_run_consistency)
                )
                audit_valid = True
            except Exception:
                _add("INVALID_NESTED_REASONING_RUN_CONSISTENCY")

        # --- Provenance ---
        # Provenance can only be True when BOTH nested contracts are
        # structurally valid. If the check cannot be performed, the
        # dedicated flag must be False, never silently True.
        if not pipeline_valid or not audit_valid:
            _add("AUDIT_PROVENANCE_CHECK_UNAVAILABLE")
        else:
            try:
                expected_fingerprint = ReasoningRunConsistencyService._run_fingerprint(
                    reasoning_pipeline
                )
            except Exception:
                _add("AUDIT_PROVENANCE_COMPUTE_FAILED")
            else:
                actual_fingerprint = reasoning_run_consistency.get(
                    "audited_run_fingerprint"
                )
                if actual_fingerprint != expected_fingerprint:
                    _add("AUDIT_PROVENANCE_MISMATCH")

        # --- Candidate-state relationship ---
        # A missing or non-list candidate_state means the relationship
        # cannot be checked, so both dedicated flags must be False.
        candidate_state_present = "candidate_state" in context
        candidate_state_is_list = isinstance(context.get("candidate_state"), list)
        candidate_state_consistent = (
            candidate_state_present and candidate_state_is_list and candidate_items_ok
        )
        candidate_count_consistent = False
        if candidate_state_consistent and isinstance(reasoning_pipeline, Mapping):
            pipeline_count = reasoning_pipeline.get("candidate_count")
            if (
                isinstance(pipeline_count, int)
                and not isinstance(pipeline_count, bool)
                and pipeline_count == len(context["candidate_state"])
            ):
                candidate_count_consistent = True
            else:
                _add("CANDIDATE_COUNT_MISMATCH")

        # --- Deterministic ordering, dedupe, append unknowns sorted ---
        unique = set(issues)
        ordered = [i for i in _ISSUE_ORDER if i in unique]
        leftovers = sorted(unique - set(_ISSUE_ORDER))
        ordered.extend(leftovers)

        session_consistent = "INVALID_SESSION_ID" not in unique
        nested_reasoning_run_consistent = pipeline_valid
        nested_reasoning_run_audit_consistent = audit_valid
        audit_provenance_consistent = not any(
            issue in unique
            for issue in (
                "AUDIT_PROVENANCE_CHECK_UNAVAILABLE",
                "AUDIT_PROVENANCE_COMPUTE_FAILED",
                "AUDIT_PROVENANCE_MISMATCH",
            )
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
            "nested_reasoning_run_consistent": (nested_reasoning_run_consistent),
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
        # Provenance: SHA-256 of the exact context supplied to this
        # audit. Computed once, from the actual input, before any
        # validation of the final result.
        result["audited_context_fingerprint"] = (
            ReasoningContextConsistencyService._context_fingerprint(context)
        )
        self._validate_result(result)
        return result

    @staticmethod
    def _canonicalize(value: Any) -> Any:
        """Return a deterministic, JSON-serializable canonical form."""
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(k): ReasoningContextConsistencyService._canonicalize(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [
                ReasoningContextConsistencyService._canonicalize(item) for item in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _context_fingerprint(context: Mapping[str, Any]) -> str:
        """SHA-256 hex digest of the canonicalized Task 055 context.

        The supplied context may carry ORM objects and nested typed
        models. ``ReasoningContextRead.model_validate`` normalizes
        them into a JSON-safe form deterministically; the JSON-safe
        form is used internally for hashing only and is never returned
        or exposed to callers.
        """
        try:
            typed = ReasoningContextRead.model_validate(dict(context))
            serialized = typed.model_dump(mode="json")
        except Exception:
            # Malformed context (missing fields, wrong types, etc.).
            # The audit still needs a fingerprint -- it flags the
            # malformation through consistency_issues rather than
            # refusing to produce a result -- so fall back to
            # canonicalizing the raw mapping. The fallback is less
            # canonical than the typed path, but the input is already
            # flagged as inconsistent by the caller.
            serialized = ReasoningContextConsistencyService._canonicalize(context)
        canonical = ReasoningContextConsistencyService._canonicalize(serialized)
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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
                "consistency_issues is not a list: " + type(issues).__name__,
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
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["context_consistency_source"]
            != REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
        ):
            raise ReasoningContextConsistencyContractError(
                "INVALID_SOURCE",
                "context_consistency_source is not the Task 056 "
                "identifier: " + repr(result["context_consistency_source"]),
            )
        if result["context_consistent"] != (len(issues) == 0):
            raise ReasoningContextConsistencyContractError(
                "CONTEXT_CONSISTENT_MISMATCH",
                "context_consistent does not match consistency_issues",
            )
        fingerprint = result["audited_context_fingerprint"]
        if not isinstance(fingerprint, str):
            raise ReasoningContextConsistencyContractError(
                "AUDITED_CONTEXT_FINGERPRINT_TYPE",
                "audited_context_fingerprint is not a string: " + repr(fingerprint),
            )
        if not _CONTEXT_FINGERPRINT_HEX_RE.fullmatch(fingerprint):
            raise ReasoningContextConsistencyContractError(
                "AUDITED_CONTEXT_FINGERPRINT_FORMAT",
                "audited_context_fingerprint is not a 64-character "
                "lowercase hexadecimal SHA-256 digest: " + repr(fingerprint),
            )

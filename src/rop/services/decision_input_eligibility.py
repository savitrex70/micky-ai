from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_context import CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031
from rop.services.decision_evaluation_consistency import (
    CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033,
    DecisionEvaluationConsistencyService,
)

ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034 = (
    "DECISION_INPUT_ELIGIBILITY_TASK_034"
)
"""Fixed structural-contract identifier for Task 034 results.

Names *which* contract produced the result. It is not a score, a
probability, a confidence, or a recommendation, and it never changes
per session or per call.
"""

BLOCKING_DECISION_NOT_READY = "DECISION_NOT_READY"
BLOCKING_CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"
BLOCKING_NO_CANDIDATES = "NO_CANDIDATES"
BLOCKING_NO_EVALUATIONS = "NO_EVALUATIONS"
BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE = "CANDIDATE_COVERAGE_INCOMPLETE"
BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT = "EVALUATION_STRUCTURE_INCONSISTENT"
BLOCKING_CRITERIA_INCOMPLETE = "CRITERIA_INCOMPLETE"

# Fixed, deterministic ordering. This is stable output ordering only --
# it is never a ranking of problems, and no other ordering is valid.
_BLOCKING_CONDITION_ORDER = (
    BLOCKING_DECISION_NOT_READY,
    BLOCKING_CONTEXT_UNAVAILABLE,
    BLOCKING_NO_CANDIDATES,
    BLOCKING_NO_EVALUATIONS,
    BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE,
    BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT,
    BLOCKING_CRITERIA_INCOMPLETE,
)
_VALID_BLOCKING_CONDITIONS = frozenset(_BLOCKING_CONDITION_ORDER)

_REQUIRED_CONTEXT_FIELDS = (
    "decision_ready",
    "context_available",
    "candidate_count",
    "differential",
    "context_source",
)

_REQUIRED_CONSISTENCY_FIELDS = (
    "consistent",
    "evaluation_count",
    "expected_candidate_count",
    "candidate_count_matches",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "has_structural_mismatch",
    "consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "eligible",
    "decision_ready",
    "context_available",
    "has_candidates",
    "evaluations_available",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "candidate_count_matches",
    "evaluation_structure_consistent",
)


class DecisionInputEligibilityContractError(Exception):
    """Task 034: structurally unusable or internally contradictory input.

    Raised only when the Task 031 decision context or the Task 033
    consistency result is not shaped like its own established contract
    at all -- ``None`` in its place, wrong type, a missing required
    field, a non-boolean where a boolean is required, a negative count,
    or a source identifier that does not match the upstream task that
    is supposed to have produced it. It is never raised for a normal
    "not eligible" state -- an unready differential, an unavailable
    context, zero candidates, missing evaluations, incomplete coverage,
    inconsistent structure, or incomplete criteria are all valid,
    fully typed responses reported through ``blocking_conditions``
    instead. Like the Task 025-033 contract errors, this must never be
    exposed verbatim to API clients; the API layer converts it to a
    generic 500.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionInputEligibilityService:
    """Task 034: the final gate before the future decision engine.

    Sits directly above Task 031's ``DecisionContext`` and Task 033's
    ``DecisionEvaluationConsistencyRead`` -- it does not reach into
    evidence, observations, entities, hypothesis scores, ranking
    internals, or repositories, and it does not build a second,
    independent candidate-discovery or evaluation pipeline. It
    introduces no new scoring, ranking, or evidence logic, and no
    decision rule.

    This answers "is the current decision input structurally valid
    and sufficiently prepared to enter the future decision engine?" --
    never "which candidate should be chosen?". There is no winner,
    best candidate, diagnosis, recommendation, action, probability,
    confidence, utility, weighted score, expected outcome, or
    treatment anywhere in this service.

    ``eligible`` is an explicit conjunction (see ``build``); it is
    never derived from a candidate's score, ranking position, score
    separation, tie presence, or evidence direction -- those remain
    upstream descriptive facts and never become hidden decision
    thresholds here.

    Read-only throughout: nothing is persisted, and no input is
    mutated.
    """

    def __init__(
        self,
        decision_evaluation_consistency_service: (
            DecisionEvaluationConsistencyService | None
        ) = None,
    ) -> None:
        self.decision_evaluation_consistency_service = (
            decision_evaluation_consistency_service
            or DecisionEvaluationConsistencyService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Return the session's decision input eligibility.

        Walks the established dependency chain rather than bypassing
        it, but builds the Task 031 decision context exactly once --
        matching the fix already applied at the Task 032/033 boundary:
        calling Task 033's own ``check_session`` here would rebuild
        the context internally and a second time would be needed for
        this task's own ``decision_ready``/``context_available``
        fields. Instead this method builds the context itself via the
        Task 033 service's own ``decision_candidate_evaluation_service
        .decision_context_service`` dependency, then reuses that one
        context both to evaluate candidates -- via Task 032's
        ``evaluate``, the same entry point Task 033 itself uses for
        exactly this purpose -- and to derive the expected candidate
        ids for the Task 033 consistency check. This is still never a
        second, independently constructed decision-context pipeline:
        it is the same dependency Tasks 032 and 033 already depend on,
        called once.
        """
        consistency_service = self.decision_evaluation_consistency_service
        candidate_evaluation_service = (
            consistency_service.decision_candidate_evaluation_service
        )
        context_service = candidate_evaluation_service.decision_context_service

        context = context_service.build_for_session(db, session_id, candidates)
        evaluations = candidate_evaluation_service.evaluate(context)
        expected_candidate_ids = [
            entry["hypothesis_id"] for entry in context["differential"]
        ]
        consistency_result = consistency_service.check(
            evaluations, expected_candidate_ids
        )
        return self.build(context, consistency_result)

    def build(
        self,
        context: Mapping[str, Any] | None,
        consistency_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Derive the eligibility contract from already-built upstream results.

        Kept separate from ``build_for_session`` so eligibility can be
        exercised directly against a hand-built Task 031 context and
        Task 033 consistency result, without going through the full
        pipeline. Never mutates its inputs. Recalculates nothing that
        Task 030, 031, or 033 already established -- ``decision_ready``
        and ``context_available`` are taken verbatim from the context,
        and every consistency-derived field is taken verbatim from the
        Task 033 result.
        """
        decision_ready, context_available, candidate_count = (
            self._validate_and_extract_context(context)
        )
        (
            evaluation_count,
            candidate_count_matches,
            all_candidates_evaluated,
            all_criteria_evaluated,
            has_structural_mismatch,
        ) = self._validate_and_extract_consistency(consistency_result)

        has_candidates = candidate_count > 0
        evaluations_available = evaluation_count > 0
        evaluation_structure_consistent = not has_structural_mismatch

        blocking_conditions: list[str] = []
        if not decision_ready:
            blocking_conditions.append(BLOCKING_DECISION_NOT_READY)
        if not context_available:
            blocking_conditions.append(BLOCKING_CONTEXT_UNAVAILABLE)
        if not has_candidates:
            blocking_conditions.append(BLOCKING_NO_CANDIDATES)
        if has_candidates and not evaluations_available:
            blocking_conditions.append(BLOCKING_NO_EVALUATIONS)
        if not all_candidates_evaluated or not candidate_count_matches:
            blocking_conditions.append(BLOCKING_CANDIDATE_COVERAGE_INCOMPLETE)
        if not evaluation_structure_consistent:
            blocking_conditions.append(BLOCKING_EVALUATION_STRUCTURE_INCONSISTENT)
        if not all_criteria_evaluated:
            blocking_conditions.append(BLOCKING_CRITERIA_INCOMPLETE)

        eligible = (
            decision_ready
            and context_available
            and has_candidates
            and evaluations_available
            and all_candidates_evaluated
            and all_criteria_evaluated
            and candidate_count_matches
            and evaluation_structure_consistent
        )

        result: dict[str, Any] = {
            "eligible": eligible,
            "decision_ready": decision_ready,
            "context_available": context_available,
            "has_candidates": has_candidates,
            "evaluations_available": evaluations_available,
            "all_candidates_evaluated": all_candidates_evaluated,
            "all_criteria_evaluated": all_criteria_evaluated,
            "candidate_count_matches": candidate_count_matches,
            "evaluation_structure_consistent": evaluation_structure_consistent,
            "blocking_conditions": blocking_conditions,
            "eligibility_source": (
                ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034
            ),
        }
        self._validate_result(result)
        return result

    # ------------------------------------------------------------------
    # Input contract: Task 031's decision context
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_extract_context(
        context: Mapping[str, Any] | None,
    ) -> tuple[bool, bool, int]:
        if context is None:
            raise DecisionInputEligibilityContractError(
                "MISSING_CONTEXT", "context is required"
            )
        if not isinstance(context, Mapping):
            raise DecisionInputEligibilityContractError(
                "CONTEXT_TYPE", f"context is not a mapping: {type(context).__name__}"
            )
        for field in _REQUIRED_CONTEXT_FIELDS:
            if field not in context:
                raise DecisionInputEligibilityContractError(
                    "MISSING_CONTEXT_FIELD", f"context has no {field}"
                )

        decision_ready = context["decision_ready"]
        if not isinstance(decision_ready, bool):
            raise DecisionInputEligibilityContractError(
                "DECISION_READY_TYPE",
                f"decision_ready is not boolean: {decision_ready!r}",
            )

        context_available = context["context_available"]
        if not isinstance(context_available, bool):
            raise DecisionInputEligibilityContractError(
                "CONTEXT_AVAILABLE_TYPE",
                f"context_available is not boolean: {context_available!r}",
            )

        candidate_count = context["candidate_count"]
        if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
            raise DecisionInputEligibilityContractError(
                "CANDIDATE_COUNT_TYPE",
                f"candidate_count is not an int: {candidate_count!r}",
            )
        if candidate_count < 0:
            raise DecisionInputEligibilityContractError(
                "CANDIDATE_COUNT_NEGATIVE",
                f"candidate_count is negative: {candidate_count!r}",
            )

        differential = context["differential"]
        if not isinstance(differential, list):
            raise DecisionInputEligibilityContractError(
                "DIFFERENTIAL_TYPE",
                f"differential is not a list: {type(differential).__name__}",
            )
        if candidate_count != len(differential):
            raise DecisionInputEligibilityContractError(
                "CANDIDATE_COUNT_MISMATCH",
                "candidate_count does not match len(differential): "
                f"{candidate_count} != {len(differential)}",
            )

        context_source = context["context_source"]
        if context_source != CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031:
            raise DecisionInputEligibilityContractError(
                "INVALID_CONTEXT_SOURCE",
                f"context_source is not the Task 031 identifier: {context_source!r}",
            )

        return decision_ready, context_available, candidate_count

    # ------------------------------------------------------------------
    # Input contract: Task 033's consistency result
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_extract_consistency(
        consistency_result: Mapping[str, Any] | None,
    ) -> tuple[int, bool, bool, bool, bool]:
        if consistency_result is None:
            raise DecisionInputEligibilityContractError(
                "MISSING_CONSISTENCY_RESULT", "consistency_result is required"
            )
        if not isinstance(consistency_result, Mapping):
            raise DecisionInputEligibilityContractError(
                "CONSISTENCY_RESULT_TYPE",
                f"consistency_result is not a mapping: "
                f"{type(consistency_result).__name__}",
            )
        for field in _REQUIRED_CONSISTENCY_FIELDS:
            if field not in consistency_result:
                raise DecisionInputEligibilityContractError(
                    "MISSING_CONSISTENCY_FIELD",
                    f"consistency_result has no {field}",
                )

        evaluation_count = consistency_result["evaluation_count"]
        if not isinstance(evaluation_count, int) or isinstance(evaluation_count, bool):
            raise DecisionInputEligibilityContractError(
                "EVALUATION_COUNT_TYPE",
                f"evaluation_count is not an int: {evaluation_count!r}",
            )
        if evaluation_count < 0:
            raise DecisionInputEligibilityContractError(
                "EVALUATION_COUNT_NEGATIVE",
                f"evaluation_count is negative: {evaluation_count!r}",
            )

        boolean_consistency_fields = (
            "candidate_count_matches",
            "all_candidates_evaluated",
            "all_criteria_evaluated",
            "has_structural_mismatch",
        )
        extracted: dict[str, bool] = {}
        for field in boolean_consistency_fields:
            value = consistency_result[field]
            if not isinstance(value, bool):
                raise DecisionInputEligibilityContractError(
                    f"{field.upper()}_TYPE", f"{field} is not boolean: {value!r}"
                )
            extracted[field] = value

        consistency_source = consistency_result["consistency_source"]
        if (
            consistency_source
            != CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033
        ):
            raise DecisionInputEligibilityContractError(
                "INVALID_CONSISTENCY_SOURCE",
                "consistency_source is not the Task 033 identifier: "
                f"{consistency_source!r}",
            )

        return (
            evaluation_count,
            extracted["candidate_count_matches"],
            extracted["all_candidates_evaluated"],
            extracted["all_criteria_evaluated"],
            extracted["has_structural_mismatch"],
        )

    # ------------------------------------------------------------------
    # Output contract: the eligibility result itself
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Verify the assembled result invariants before returning it.

        This exists to catch a defect in this service's own derivation
        logic, never to second-guess or repair a legitimate eligibility
        finding it just computed.
        """
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise DecisionInputEligibilityContractError(
                    "RESULT_FIELD_TYPE", f"{field} is not boolean: {result[field]!r}"
                )

        blocking_conditions = result["blocking_conditions"]
        if not isinstance(blocking_conditions, list):
            raise DecisionInputEligibilityContractError(
                "BLOCKING_CONDITIONS_TYPE",
                f"blocking_conditions is not a list: "
                f"{type(blocking_conditions).__name__}",
            )
        for condition in blocking_conditions:
            if condition not in _VALID_BLOCKING_CONDITIONS:
                raise DecisionInputEligibilityContractError(
                    "INVALID_BLOCKING_CONDITION",
                    f"unknown blocking condition: {condition!r}",
                )
        if len(blocking_conditions) != len(set(blocking_conditions)):
            raise DecisionInputEligibilityContractError(
                "DUPLICATE_BLOCKING_CONDITION",
                f"blocking_conditions contains duplicates: {blocking_conditions!r}",
            )
        present_in_order = [
            condition
            for condition in _BLOCKING_CONDITION_ORDER
            if condition in blocking_conditions
        ]
        if blocking_conditions != present_in_order:
            raise DecisionInputEligibilityContractError(
                "BLOCKING_CONDITIONS_ORDER",
                f"blocking_conditions is not in the fixed deterministic order: "
                f"{blocking_conditions!r}",
            )

        if result["eligible"] and blocking_conditions:
            raise DecisionInputEligibilityContractError(
                "ELIGIBLE_WITH_BLOCKING_CONDITIONS",
                "eligible is True but blocking_conditions is non-empty: "
                f"{blocking_conditions!r}",
            )
        if not result["eligible"] and not blocking_conditions:
            raise DecisionInputEligibilityContractError(
                "INELIGIBLE_WITHOUT_BLOCKING_CONDITIONS",
                "eligible is False but blocking_conditions is empty",
            )

        if (
            result["eligibility_source"]
            != ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034
        ):
            raise DecisionInputEligibilityContractError(
                "INVALID_ELIGIBILITY_SOURCE",
                f"eligibility_source is not the Task 034 identifier: "
                f"{result['eligibility_source']!r}",
            )

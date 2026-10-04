from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_candidate_evaluation import (
    DEFAULT_CRITERIA,
    EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032,
    DecisionCandidateEvaluationService,
)

CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033 = (
    "DECISION_EVALUATION_CONSISTENCY_TASK_033"
)
"""Fixed structural-contract identifier for Task 033 results.

Names *which* contract produced the result. It is not a score, a
probability, a confidence, or a recommendation, and it never changes
per session or per call.
"""

_DECLARED_CRITERION_IDS = frozenset(c.criterion_id for c in DEFAULT_CRITERIA)
_DECLARED_CRITERIA_BY_ID = {c.criterion_id: c for c in DEFAULT_CRITERIA}

_REQUIRED_EVALUATION_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "criteria",
    "criterion_count",
    "criteria_satisfied",
    "criteria_unsatisfied",
    "required_criteria_satisfied",
    "required_criteria_unsatisfied",
    "evaluation_complete",
    "evaluation_source",
)

_REQUIRED_CRITERION_FIELDS = (
    "criterion_id",
    "criterion_name",
    "satisfied",
    "required",
    "reason",
)

_INT_FIELDS = (
    "criterion_count",
    "criteria_satisfied",
    "criteria_unsatisfied",
    "required_criteria_satisfied",
    "required_criteria_unsatisfied",
)

_RESULT_BOOLEAN_FIELDS = (
    "consistent",
    "candidate_count_matches",
    "criterion_sets_match",
    "criterion_count_matches",
    "criterion_definitions_match",
    "required_flags_match",
    "evaluation_completeness_matches",
    "candidate_ids_unique",
    "criterion_ids_unique_per_candidate",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "has_missing_candidate_evaluation",
    "has_incomplete_evaluation",
    "has_structural_mismatch",
)


class DecisionEvaluationConsistencyContractError(Exception):
    """Task 033: structurally impossible input to the consistency contract.

    Raised only when a candidate evaluation or criterion result is not
    shaped like the Task 032 contract at all -- wrong type, a missing
    required field, a non-boolean where a boolean is required, a
    non-int where an int is required, a null/empty id. It is never
    raised for a legitimate structural *mismatch* between well-typed
    candidates or against the declared criterion set -- detecting
    those is this task's entire purpose, and they are reported through
    the returned booleans instead. Like the Task 025-032 contract
    errors, this must never be exposed verbatim to API clients; the
    API layer converts it to a generic 500.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionEvaluationConsistencyService:
    """Task 033: structural consistency/coverage analysis over Task 032.

    Consumes only the output of ``DecisionCandidateEvaluationService``
    (Task 032) -- it does not reach into evidence, evidence
    aggregation, scoring, ranking, ranking summary, ranking
    consistency, readiness, observations, entities, hypotheses, or
    database evidence records, and duplicates no logic already owned
    by Tasks 020-032. The expected candidate count is obtained through
    Task 032's own ``decision_context_service`` dependency rather than
    a second, independently constructed candidate-discovery pipeline.

    This answers "are the candidate evaluations complete, structurally
    consistent, and fully comparable across the current decision
    context?" -- never "which candidate should be chosen?". There is
    no winner, selected candidate, decision, diagnosis, probability,
    confidence, or weighted/utility score anywhere in this service.
    Every structural fact is independently recalculated from the
    evaluations themselves rather than trusted from Task 032's own
    summary fields. Read-only throughout: nothing is persisted, and no
    input is mutated.
    """

    def __init__(
        self,
        decision_candidate_evaluation_service: (
            DecisionCandidateEvaluationService | None
        ) = None,
    ) -> None:
        self.decision_candidate_evaluation_service = (
            decision_candidate_evaluation_service
            or DecisionCandidateEvaluationService()
        )

    def check_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Evaluate the session via Task 032 and check its consistency.

        Walks the established dependency chain rather than bypassing
        it, but builds the Task 031 decision context exactly once:
        ``evaluate_session`` on Task 032 would build its own context
        internally and discard it, so instead this method builds the
        context itself via Task 032's own
        ``decision_context_service`` dependency, then reuses that one
        context both for evaluation -- via Task 032's ``evaluate``,
        the entry point Task 032 already exposes for exactly this
        purpose -- and for deriving the expected candidate ids. This
        is still never a second, independently constructed
        decision-context pipeline: it is the same
        ``decision_context_service`` Task 032 itself depends on,
        called once instead of twice.
        """
        context_service = (
            self.decision_candidate_evaluation_service.decision_context_service
        )
        context = context_service.build_for_session(db, session_id, candidates)
        evaluations = self.decision_candidate_evaluation_service.evaluate(context)
        expected_candidate_ids = [
            entry["hypothesis_id"] for entry in context["differential"]
        ]
        return self.check(evaluations, expected_candidate_ids)

    def check(
        self,
        evaluations: list[Mapping[str, Any]] | None,
        expected_candidate_ids: list[Any] | None,
    ) -> dict[str, Any]:
        """Check the structural consistency of an already-built evaluation set.

        Kept separate from ``check_session`` so consistency checking
        can be exercised directly against hand-built evaluations and
        an expected-candidate-id list, without going through the full
        pipeline. Never mutates its inputs.
        """
        normalized_evaluations = self._validate_and_normalize_evaluations(evaluations)
        expected_ids = self._validate_and_normalize_expected_ids(expected_candidate_ids)

        evaluation_count = len(normalized_evaluations)
        expected_candidate_count = len(expected_ids)

        evaluated_ids = [entry["hypothesis_id"] for entry in normalized_evaluations]
        evaluated_id_set = set(evaluated_ids)
        candidate_ids_unique = len(evaluated_ids) == len(evaluated_id_set)

        expected_id_set = set(expected_ids)
        missing_candidates = expected_id_set - evaluated_id_set
        unexpected_candidates = evaluated_id_set - expected_id_set

        candidate_count_matches = evaluation_count == expected_candidate_count
        has_missing_candidate_evaluation = len(missing_candidates) > 0
        all_candidates_evaluated = (
            not missing_candidates
            and not unexpected_candidates
            and candidate_ids_unique
        )

        per_candidate = [
            self._check_candidate(entry) for entry in normalized_evaluations
        ]

        criterion_ids_unique_per_candidate = all(
            c["criterion_ids_unique"] for c in per_candidate
        )
        criterion_sets_match = all(c["criterion_set_matches"] for c in per_candidate)
        criterion_count_matches = all(
            c["criterion_count_matches"] for c in per_candidate
        )
        criterion_definitions_match = all(
            c["criterion_names_match"] for c in per_candidate
        )
        required_flags_match = all(c["required_flags_match"] for c in per_candidate)
        all_criteria_evaluated = all(c["all_criteria_evaluated"] for c in per_candidate)
        evaluation_completeness_matches = all(
            c["completeness_flag_matches"] for c in per_candidate
        )
        counts_internally_consistent = all(
            c["counts_internally_consistent"] for c in per_candidate
        )
        has_incomplete_evaluation = not all_criteria_evaluated

        has_structural_mismatch = not (
            candidate_ids_unique
            and criterion_ids_unique_per_candidate
            and criterion_sets_match
            and criterion_count_matches
            and criterion_definitions_match
            and required_flags_match
            and evaluation_completeness_matches
            and counts_internally_consistent
        )

        consistent = (
            candidate_count_matches
            and all_candidates_evaluated
            and not has_missing_candidate_evaluation
            and not has_incomplete_evaluation
            and not has_structural_mismatch
        )

        result: dict[str, Any] = {
            "consistent": consistent,
            "evaluation_count": evaluation_count,
            "expected_candidate_count": expected_candidate_count,
            "candidate_count_matches": candidate_count_matches,
            "criterion_sets_match": criterion_sets_match,
            "criterion_count_matches": criterion_count_matches,
            "criterion_definitions_match": criterion_definitions_match,
            "required_flags_match": required_flags_match,
            "evaluation_completeness_matches": evaluation_completeness_matches,
            "candidate_ids_unique": candidate_ids_unique,
            "criterion_ids_unique_per_candidate": criterion_ids_unique_per_candidate,
            "all_candidates_evaluated": all_candidates_evaluated,
            "all_criteria_evaluated": all_criteria_evaluated,
            "has_missing_candidate_evaluation": has_missing_candidate_evaluation,
            "has_incomplete_evaluation": has_incomplete_evaluation,
            "has_structural_mismatch": has_structural_mismatch,
            "consistency_source": (
                CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033
            ),
        }
        self._validate_result(result)
        return result

    # ------------------------------------------------------------------
    # Per-candidate independent structural checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_candidate(entry: Mapping[str, Any]) -> dict[str, bool]:
        criteria = entry["criteria"]
        criterion_ids = [c["criterion_id"] for c in criteria]
        criterion_id_set = set(criterion_ids)
        criterion_ids_unique = len(criterion_ids) == len(criterion_id_set)

        criterion_set_matches = criterion_id_set == _DECLARED_CRITERION_IDS
        criterion_count_matches = entry["criterion_count"] == len(criteria)

        names_match = True
        required_match = True
        for criterion_result in criteria:
            declared = _DECLARED_CRITERIA_BY_ID.get(criterion_result["criterion_id"])
            if declared is None:
                # An undeclared/unexpected criterion id cannot be
                # compared against any definition at all.
                names_match = False
                required_match = False
                continue
            if criterion_result["criterion_name"] != declared.name:
                names_match = False
            if criterion_result["required"] != declared.required:
                required_match = False

        satisfied_count = sum(1 for c in criteria if c["satisfied"] is True)
        unsatisfied_count = len(criteria) - satisfied_count
        required_criteria = [c for c in criteria if c["required"] is True]
        required_satisfied_count = sum(
            1 for c in required_criteria if c["satisfied"] is True
        )
        required_unsatisfied_count = len(required_criteria) - required_satisfied_count

        counts_internally_consistent = (
            entry["criteria_satisfied"] == satisfied_count
            and entry["criteria_unsatisfied"] == unsatisfied_count
            and entry["criteria_satisfied"] + entry["criteria_unsatisfied"]
            == entry["criterion_count"]
            and entry["required_criteria_satisfied"] == required_satisfied_count
            and entry["required_criteria_unsatisfied"] == required_unsatisfied_count
            and entry["required_criteria_satisfied"]
            + entry["required_criteria_unsatisfied"]
            == len(required_criteria)
        )

        all_criteria_evaluated = (
            criterion_ids_unique
            and criterion_set_matches
            and len(criteria) == len(DEFAULT_CRITERIA)
        )
        completeness_flag_matches = (
            entry["evaluation_complete"] == all_criteria_evaluated
        )

        return {
            "criterion_ids_unique": criterion_ids_unique,
            "criterion_set_matches": criterion_set_matches,
            "criterion_count_matches": criterion_count_matches,
            "criterion_names_match": names_match,
            "required_flags_match": required_match,
            "counts_internally_consistent": counts_internally_consistent,
            "all_criteria_evaluated": all_criteria_evaluated,
            "completeness_flag_matches": completeness_flag_matches,
        }

    # ------------------------------------------------------------------
    # Input contract: Task 032's evaluation output
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_normalize_evaluations(
        evaluations: list[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if evaluations is None:
            raise DecisionEvaluationConsistencyContractError(
                "MISSING_EVALUATIONS", "evaluations is required"
            )
        if not isinstance(evaluations, list):
            raise DecisionEvaluationConsistencyContractError(
                "EVALUATIONS_TYPE",
                f"evaluations is not a list: {type(evaluations).__name__}",
            )

        normalized: list[dict[str, Any]] = []
        for candidate in evaluations:
            if not isinstance(candidate, Mapping):
                raise DecisionEvaluationConsistencyContractError(
                    "MALFORMED_CANDIDATE_EVALUATION",
                    f"candidate evaluation is not a mapping: "
                    f"{type(candidate).__name__}",
                )
            for field in _REQUIRED_EVALUATION_FIELDS:
                if field not in candidate:
                    raise DecisionEvaluationConsistencyContractError(
                        "MISSING_EVALUATION_FIELD",
                        f"candidate evaluation has no {field}",
                    )

            hypothesis_id = candidate["hypothesis_id"]
            if hypothesis_id is None:
                raise DecisionEvaluationConsistencyContractError(
                    "MISSING_CANDIDATE_ID",
                    "candidate evaluation has no hypothesis_id",
                )
            if not isinstance(hypothesis_id, UUID):
                raise DecisionEvaluationConsistencyContractError(
                    "INVALID_CANDIDATE_ID_TYPE",
                    f"hypothesis_id is not a UUID: " f"{type(hypothesis_id).__name__}",
                )

            hypothesis_name = candidate["hypothesis_name"]
            if not isinstance(hypothesis_name, str):
                raise DecisionEvaluationConsistencyContractError(
                    "HYPOTHESIS_NAME_TYPE",
                    f"hypothesis_name is not a string: "
                    f"{type(hypothesis_name).__name__}",
                )

            criteria = candidate["criteria"]
            if not isinstance(criteria, list):
                raise DecisionEvaluationConsistencyContractError(
                    "CRITERIA_TYPE",
                    f"criteria is not a list: {type(criteria).__name__}",
                )

            normalized_criteria: list[dict[str, Any]] = []
            for criterion_result in criteria:
                if not isinstance(criterion_result, Mapping):
                    raise DecisionEvaluationConsistencyContractError(
                        "MALFORMED_CRITERION",
                        f"criterion result is not a mapping: "
                        f"{type(criterion_result).__name__}",
                    )
                for field in _REQUIRED_CRITERION_FIELDS:
                    if field not in criterion_result:
                        raise DecisionEvaluationConsistencyContractError(
                            "MISSING_CRITERION_FIELD",
                            f"criterion result has no {field}",
                        )

                criterion_id = criterion_result["criterion_id"]
                if (
                    criterion_id is None
                    or not isinstance(criterion_id, str)
                    or not criterion_id
                ):
                    raise DecisionEvaluationConsistencyContractError(
                        "INVALID_CRITERION_ID",
                        f"criterion_id is invalid: {criterion_id!r}",
                    )

                criterion_name = criterion_result["criterion_name"]
                if not isinstance(criterion_name, str):
                    raise DecisionEvaluationConsistencyContractError(
                        "CRITERION_NAME_TYPE",
                        f"criterion_name is not a string: {criterion_name!r}",
                    )

                reason = criterion_result["reason"]
                if not isinstance(reason, str):
                    raise DecisionEvaluationConsistencyContractError(
                        "CRITERION_REASON_TYPE",
                        f"reason is not a string: {reason!r}",
                    )

                satisfied = criterion_result["satisfied"]
                required = criterion_result["required"]
                if not isinstance(satisfied, bool):
                    raise DecisionEvaluationConsistencyContractError(
                        "SATISFIED_TYPE", f"satisfied is not boolean: {satisfied!r}"
                    )
                if not isinstance(required, bool):
                    raise DecisionEvaluationConsistencyContractError(
                        "REQUIRED_TYPE", f"required is not boolean: {required!r}"
                    )

                normalized_criteria.append(
                    {
                        "criterion_id": criterion_id,
                        "criterion_name": criterion_name,
                        "satisfied": satisfied,
                        "required": required,
                        "reason": reason,
                    }
                )

            for field in _INT_FIELDS:
                DecisionEvaluationConsistencyService._require_int(
                    candidate[field], field
                )

            evaluation_complete = candidate["evaluation_complete"]
            if not isinstance(evaluation_complete, bool):
                raise DecisionEvaluationConsistencyContractError(
                    "EVALUATION_COMPLETE_TYPE",
                    f"evaluation_complete is not boolean: {evaluation_complete!r}",
                )

            evaluation_source = candidate["evaluation_source"]
            if not isinstance(evaluation_source, str):
                raise DecisionEvaluationConsistencyContractError(
                    "EVALUATION_SOURCE_TYPE",
                    f"evaluation_source is not a string: "
                    f"{type(evaluation_source).__name__}",
                )
            if (
                evaluation_source
                != EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032
            ):
                raise DecisionEvaluationConsistencyContractError(
                    "INVALID_EVALUATION_SOURCE",
                    f"evaluation_source is not the Task 032 identifier: "
                    f"{evaluation_source!r}",
                )

            normalized.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "hypothesis_name": hypothesis_name,
                    "criteria": normalized_criteria,
                    "criterion_count": candidate["criterion_count"],
                    "criteria_satisfied": candidate["criteria_satisfied"],
                    "criteria_unsatisfied": candidate["criteria_unsatisfied"],
                    "required_criteria_satisfied": candidate[
                        "required_criteria_satisfied"
                    ],
                    "required_criteria_unsatisfied": candidate[
                        "required_criteria_unsatisfied"
                    ],
                    "evaluation_complete": evaluation_complete,
                    "evaluation_source": evaluation_source,
                }
            )

        return normalized

    @staticmethod
    def _validate_and_normalize_expected_ids(
        expected_candidate_ids: list[Any] | None,
    ) -> list[Any]:
        if expected_candidate_ids is None:
            raise DecisionEvaluationConsistencyContractError(
                "MISSING_EXPECTED_CANDIDATES", "expected_candidate_ids is required"
            )
        if not isinstance(expected_candidate_ids, list):
            raise DecisionEvaluationConsistencyContractError(
                "EXPECTED_CANDIDATES_TYPE",
                f"expected_candidate_ids is not a list: "
                f"{type(expected_candidate_ids).__name__}",
            )
        seen: set[UUID] = set()
        for candidate_id in expected_candidate_ids:
            if candidate_id is None:
                raise DecisionEvaluationConsistencyContractError(
                    "INVALID_EXPECTED_CANDIDATE_ID",
                    "expected_candidate_ids contains a null id",
                )
            if not isinstance(candidate_id, UUID):
                raise DecisionEvaluationConsistencyContractError(
                    "INVALID_EXPECTED_CANDIDATE_ID_TYPE",
                    f"expected candidate id is not a UUID: "
                    f"{type(candidate_id).__name__}",
                )
            if candidate_id in seen:
                raise DecisionEvaluationConsistencyContractError(
                    "DUPLICATE_EXPECTED_CANDIDATE_ID",
                    f"expected_candidate_ids contains a duplicate id: "
                    f"{candidate_id!r}",
                )
            seen.add(candidate_id)
        return list(expected_candidate_ids)

    @staticmethod
    def _require_int(value: Any, field_name: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise DecisionEvaluationConsistencyContractError(
                f"{field_name.upper()}_TYPE",
                f"{field_name} is not an int: {value!r}",
            )
        if value < 0:
            raise DecisionEvaluationConsistencyContractError(
                f"{field_name.upper()}_NEGATIVE",
                f"{field_name} is negative: {value!r}",
            )

    # ------------------------------------------------------------------
    # Output contract: the consistency result itself
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Verify the assembled result invariants before returning it.

        This exists to catch a defect in this service's own derivation
        logic, never to second-guess or repair a legitimate structural
        finding it just computed.
        """
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise DecisionEvaluationConsistencyContractError(
                    "RESULT_FIELD_TYPE", f"{field} is not boolean: {result[field]!r}"
                )
        if result["evaluation_count"] < 0 or result["expected_candidate_count"] < 0:
            raise DecisionEvaluationConsistencyContractError(
                "IMPOSSIBLE_COUNT",
                "evaluation_count/expected_candidate_count is negative",
            )
        if (
            result["consistency_source"]
            != CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033
        ):
            raise DecisionEvaluationConsistencyContractError(
                "INVALID_CONSISTENCY_SOURCE",
                f"consistency_source is not the Task 033 identifier: "
                f"{result['consistency_source']!r}",
            )

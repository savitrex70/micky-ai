from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_candidate_evaluation import (
    EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032,
)
from rop.services.decision_candidate_set import (
    DecisionCandidateSetService,
)
from rop.services.decision_evaluation_consistency import (
    CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033,
)

ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036 = (
    "DECISION_CANDIDATE_ASSESSMENT_TASK_036"
)
"""Fixed structural-contract identifier for Task 036 results."""

_CANDIDATE_SET_FIELDS = (
    "available",
    "candidate_count",
    "candidates",
    "candidate_order_preserved",
    "candidate_set_complete",
    "candidate_set_source",
)

_CANDIDATE_SET_BOOLEAN_FIELDS = (
    "available",
    "candidate_order_preserved",
    "candidate_set_complete",
)

_CANDIDATE_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "rank",
    "score",
    "is_tied",
    "tie_group_size",
    "score_gap_to_next_higher",
    "score_gap_to_next_lower",
)

_EVALUATION_FIELDS = (
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

_CRITERION_FIELDS = (
    "criterion_id",
    "criterion_name",
    "satisfied",
    "required",
    "reason",
)

_CONSISTENCY_FIELDS = (
    "consistent",
    "evaluation_count",
    "expected_candidate_count",
    "candidate_count_matches",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "has_missing_candidate_evaluation",
    "has_incomplete_evaluation",
    "has_structural_mismatch",
    "consistency_source",
)

_CONSISTENCY_BOOLEAN_FIELDS = (
    "consistent",
    "candidate_count_matches",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "has_missing_candidate_evaluation",
    "has_incomplete_evaluation",
    "has_structural_mismatch",
)


class DecisionCandidateAssessmentContractError(Exception):
    """Task 036: malformed upstream input or an internal derivation bug.

    Raised only when the Task 035 candidate set, the Task 032
    evaluations, or the Task 033 consistency result are not shaped
    like their own established contracts, the join between them is
    impossible, or this service's own derivation produced an
    internally contradictory result. It is never raised for a normal
    unavailable state -- that is a valid, fully typed response.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionCandidateAssessmentService:
    """Task 036: structural candidate-assessment packaging boundary.

    Joins Task 035's candidate set (identity, rank, score, tie
    metadata, score gaps) with Task 032's per-candidate evaluations
    (criteria results and counts) under the structural guarantees
    reported by Task 033. Introduces no scoring, ranking, tie-breaking,
    selection, or decision logic; performs no persistence; mutates no
    input. Preserves every field verbatim and preserves both the
    candidate order and each candidate's criterion order.
    """

    def __init__(
        self,
        decision_candidate_set_service: DecisionCandidateSetService | None = None,
    ) -> None:
        self.decision_candidate_set_service = (
            decision_candidate_set_service or DecisionCandidateSetService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Delegate the upstream chain to Task 035, then join.

        Task 035 owns the orchestration of Tasks 031-035. This service
        asks Task 035's ``build_for_session_with_inputs`` for the full
        pipeline output (candidate set plus the evaluations and
        consistency result that Task 035 already computed) and then
        joins them -- it does not re-walk the chain or reach into
        Task 031/032/033/034 services directly.
        """
        candidate_set, evaluations, consistency_result = (
            self.decision_candidate_set_service.build_for_session_with_inputs(
                db, session_id, candidates
            )
        )
        return self.build(candidate_set, evaluations, consistency_result)

    def build(
        self,
        candidate_set: Mapping[str, Any] | None,
        evaluations: list[Mapping[str, Any]] | None,
        consistency_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Join the candidate set with evaluations under Task 033's verdict.

        Pure transformation -- never mutates inputs, never recomputes a
        criterion result, count, rank, score, tie, or gap, and never
        reorders a candidate or criterion.
        """
        candidate_available, candidates = self._validate_and_extract_candidate_set(
            candidate_set
        )
        evals_by_id = self._validate_and_extract_evaluations(evaluations)
        (
            consistent,
            coverage_complete,
            criteria_complete,
        ) = self._validate_and_extract_consistency(consistency_result)

        upstream_order_preserved = candidate_set["candidate_order_preserved"]
        upstream_set_complete = candidate_set["candidate_set_complete"]

        # Task 032's hypothesis_name must agree with Task 035's for the
        # same hypothesis_id -- conflicting names are malformed upstream
        # data, not something to silently drop.
        for candidate in candidates:
            hid = candidate["hypothesis_id"]
            eval_entry = evals_by_id.get(hid)
            if eval_entry is None:
                continue
            if eval_entry["hypothesis_name"] != candidate["hypothesis_name"]:
                raise DecisionCandidateAssessmentContractError(
                    "EVALUATION_NAME_MISMATCH",
                    f"candidate {hid}: Task 035 name "
                    f"{candidate['hypothesis_name']!r} != Task 032 name "
                    f"{eval_entry['hypothesis_name']!r}",
                )

        evaluation_coverage_complete = coverage_complete
        assessment_structure_consistent = consistent
        available = (
            candidate_available
            and upstream_order_preserved
            and upstream_set_complete
            and evaluation_coverage_complete
            and assessment_structure_consistent
            and criteria_complete
        )

        assessments: list[dict[str, Any]] = []
        if available:
            candidate_ids = [c["hypothesis_id"] for c in candidates]
            for cid in candidate_ids:
                if cid not in evals_by_id:
                    raise DecisionCandidateAssessmentContractError(
                        "MISSING_EVALUATION",
                        f"candidate {cid} has no matching Task 032 evaluation",
                    )
            for eid in evals_by_id:
                if eid not in candidate_ids:
                    raise DecisionCandidateAssessmentContractError(
                        "UNEXPECTED_EVALUATION",
                        f"Task 032 evaluation {eid} has no matching candidate",
                    )
            for candidate in candidates:
                evaluation = evals_by_id[candidate["hypothesis_id"]]
                assessments.append(self._join(candidate, evaluation))

        result: dict[str, Any] = {
            "available": available,
            "candidate_count": len(assessments),
            "assessments": assessments,
            "candidate_order_preserved": upstream_order_preserved,
            "evaluation_coverage_complete": evaluation_coverage_complete,
            "assessment_structure_consistent": assessment_structure_consistent,
            "assessment_source": (
                ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
            ),
        }
        self._validate_result(result, candidate_set, evaluations, consistency_result)
        return result

    @staticmethod
    def _validate_and_extract_candidate_set(
        candidate_set: Mapping[str, Any] | None,
    ) -> tuple[bool, list[Mapping[str, Any]]]:
        if candidate_set is None:
            raise DecisionCandidateAssessmentContractError(
                "MISSING_CANDIDATE_SET", "candidate_set is required"
            )
        if not isinstance(candidate_set, Mapping):
            raise DecisionCandidateAssessmentContractError(
                "CANDIDATE_SET_TYPE",
                f"candidate_set is not a mapping: " f"{type(candidate_set).__name__}",
            )
        for field in _CANDIDATE_SET_FIELDS:
            if field not in candidate_set:
                raise DecisionCandidateAssessmentContractError(
                    "MISSING_CANDIDATE_SET_FIELD",
                    f"candidate_set has no {field}",
                )
        for field in _CANDIDATE_SET_BOOLEAN_FIELDS:
            value = candidate_set[field]
            if not isinstance(value, bool):
                raise DecisionCandidateAssessmentContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {value!r}",
                )
        count = candidate_set["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionCandidateAssessmentContractError(
                "CANDIDATE_SET_COUNT_TYPE",
                f"candidate_count is not an int: {count!r}",
            )
        if count < 0:
            raise DecisionCandidateAssessmentContractError(
                "CANDIDATE_SET_COUNT_NEGATIVE",
                f"candidate_count is negative: {count!r}",
            )
        candidates = candidate_set["candidates"]
        if not isinstance(candidates, list):
            raise DecisionCandidateAssessmentContractError(
                "CANDIDATES_TYPE",
                f"candidates is not a list: {type(candidates).__name__}",
            )
        if count != len(candidates):
            raise DecisionCandidateAssessmentContractError(
                "CANDIDATE_SET_COUNT_MISMATCH",
                f"candidate_count {count} != len(candidates) {len(candidates)}",
            )
        seen: set[UUID] = set()
        for entry in candidates:
            if not isinstance(entry, Mapping):
                raise DecisionCandidateAssessmentContractError(
                    "MALFORMED_CANDIDATE",
                    f"candidate is not a mapping: {type(entry).__name__}",
                )
            for field in _CANDIDATE_FIELDS:
                if field not in entry:
                    raise DecisionCandidateAssessmentContractError(
                        "MISSING_CANDIDATE_FIELD",
                        f"candidate has no {field}",
                    )
            hid = entry["hypothesis_id"]
            if not isinstance(hid, UUID):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_CANDIDATE_ID",
                    f"hypothesis_id is not a UUID: {type(hid).__name__}",
                )
            if hid in seen:
                raise DecisionCandidateAssessmentContractError(
                    "DUPLICATE_CANDIDATE_ID",
                    f"duplicate candidate id: {hid}",
                )
            seen.add(hid)
            if not isinstance(entry["hypothesis_name"], str):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_CANDIDATE_NAME",
                    f"hypothesis_name is not a string: "
                    f"{type(entry['hypothesis_name']).__name__}",
                )
            if not isinstance(entry["rank"], int) or isinstance(entry["rank"], bool):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_CANDIDATE_RANK",
                    f"rank is not an int: {entry['rank']!r}",
                )
            if not isinstance(entry["score"], (int, float)) or isinstance(
                entry["score"], bool
            ):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_CANDIDATE_SCORE",
                    f"score is not numeric: {entry['score']!r}",
                )
            if not isinstance(entry["is_tied"], bool):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_IS_TIED",
                    f"is_tied is not boolean: {entry['is_tied']!r}",
                )
            if not isinstance(entry["tie_group_size"], int) or isinstance(
                entry["tie_group_size"], bool
            ):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_TIE_GROUP_SIZE",
                    f"tie_group_size is not an int: " f"{entry['tie_group_size']!r}",
                )
            for gap_field in (
                "score_gap_to_next_higher",
                "score_gap_to_next_lower",
            ):
                g = entry[gap_field]
                if g is not None and (
                    not isinstance(g, (int, float)) or isinstance(g, bool)
                ):
                    raise DecisionCandidateAssessmentContractError(
                        f"INVALID_{gap_field.upper()}",
                        f"{gap_field} is not numeric/None: {g!r}",
                    )
        source = candidate_set["candidate_set_source"]
        if source != "DECISION_CANDIDATE_SET_TASK_035":
            raise DecisionCandidateAssessmentContractError(
                "INVALID_CANDIDATE_SET_SOURCE",
                f"candidate_set_source is not the Task 035 identifier: {source!r}",
            )
        return candidate_set["available"], candidates

    @staticmethod
    def _validate_and_extract_evaluations(
        evaluations: list[Mapping[str, Any]] | None,
    ) -> dict[UUID, Mapping[str, Any]]:
        if evaluations is None:
            raise DecisionCandidateAssessmentContractError(
                "MISSING_EVALUATIONS", "evaluations is required"
            )
        if not isinstance(evaluations, list):
            raise DecisionCandidateAssessmentContractError(
                "EVALUATIONS_TYPE",
                f"evaluations is not a list: {type(evaluations).__name__}",
            )
        by_id: dict[UUID, Mapping[str, Any]] = {}
        for entry in evaluations:
            if not isinstance(entry, Mapping):
                raise DecisionCandidateAssessmentContractError(
                    "MALFORMED_EVALUATION",
                    f"evaluation is not a mapping: {type(entry).__name__}",
                )
            for field in _EVALUATION_FIELDS:
                if field not in entry:
                    raise DecisionCandidateAssessmentContractError(
                        "MISSING_EVALUATION_FIELD",
                        f"evaluation has no {field}",
                    )
            hid = entry["hypothesis_id"]
            if not isinstance(hid, UUID):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_EVALUATION_ID",
                    f"hypothesis_id is not a UUID: {type(hid).__name__}",
                )
            if hid in by_id:
                raise DecisionCandidateAssessmentContractError(
                    "DUPLICATE_EVALUATION_ID",
                    f"duplicate evaluation for hypothesis_id: {hid}",
                )
            if not isinstance(entry["hypothesis_name"], str):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_EVALUATION_NAME",
                    f"hypothesis_name is not a string: "
                    f"{type(entry['hypothesis_name']).__name__}",
                )
            criteria = entry["criteria"]
            if not isinstance(criteria, list):
                raise DecisionCandidateAssessmentContractError(
                    "CRITERIA_TYPE",
                    f"criteria is not a list: {type(criteria).__name__}",
                )
            seen_criterion_ids: set[str] = set()
            for c in criteria:
                if not isinstance(c, Mapping):
                    raise DecisionCandidateAssessmentContractError(
                        "MALFORMED_CRITERION",
                        f"criterion is not a mapping: {type(c).__name__}",
                    )
                for field in _CRITERION_FIELDS:
                    if field not in c:
                        raise DecisionCandidateAssessmentContractError(
                            "MISSING_CRITERION_FIELD",
                            f"criterion has no {field}",
                        )
                if not isinstance(c["criterion_id"], str):
                    raise DecisionCandidateAssessmentContractError(
                        "INVALID_CRITERION_ID",
                        f"criterion_id is not a string: "
                        f"{type(c['criterion_id']).__name__}",
                    )
                if c["criterion_id"] in seen_criterion_ids:
                    raise DecisionCandidateAssessmentContractError(
                        "DUPLICATE_CRITERION_ID",
                        f"duplicate criterion_id within candidate: "
                        f"{c['criterion_id']!r}",
                    )
                seen_criterion_ids.add(c["criterion_id"])
                if not isinstance(c["criterion_name"], str):
                    raise DecisionCandidateAssessmentContractError(
                        "INVALID_CRITERION_NAME",
                        f"criterion_name is not a string: "
                        f"{type(c['criterion_name']).__name__}",
                    )
                if not isinstance(c["satisfied"], bool):
                    raise DecisionCandidateAssessmentContractError(
                        "INVALID_CRITERION_SATISFIED",
                        f"satisfied is not boolean: {c['satisfied']!r}",
                    )
                if not isinstance(c["required"], bool):
                    raise DecisionCandidateAssessmentContractError(
                        "INVALID_CRITERION_REQUIRED",
                        f"required is not boolean: {c['required']!r}",
                    )
                if not isinstance(c["reason"], str):
                    raise DecisionCandidateAssessmentContractError(
                        "INVALID_CRITERION_REASON",
                        f"reason is not a string: " f"{type(c['reason']).__name__}",
                    )
            for count_field in (
                "criterion_count",
                "criteria_satisfied",
                "criteria_unsatisfied",
                "required_criteria_satisfied",
                "required_criteria_unsatisfied",
            ):
                value = entry[count_field]
                if not isinstance(value, int) or isinstance(value, bool):
                    raise DecisionCandidateAssessmentContractError(
                        f"INVALID_{count_field.upper()}",
                        f"{count_field} is not an int: {value!r}",
                    )
                if value < 0:
                    raise DecisionCandidateAssessmentContractError(
                        f"NEGATIVE_{count_field.upper()}",
                        f"{count_field} is negative: {value!r}",
                    )
            if not isinstance(entry["evaluation_complete"], bool):
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_EVALUATION_COMPLETE",
                    f"evaluation_complete is not boolean: "
                    f"{entry['evaluation_complete']!r}",
                )
            derived_counts = DecisionCandidateAssessmentService._derive_counts(criteria)
            for count_field, derived_value in derived_counts.items():
                declared_value = entry[count_field]
                if declared_value != derived_value:
                    raise DecisionCandidateAssessmentContractError(
                        "DECLARED_COUNT_MISMATCH",
                        f"{count_field} declared as {declared_value} but "
                        f"derived from criteria as {derived_value}",
                    )
            src = entry["evaluation_source"]
            if src != EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032:
                raise DecisionCandidateAssessmentContractError(
                    "INVALID_EVALUATION_SOURCE",
                    "evaluation_source is not the Task 032 identifier: " f"{src!r}",
                )
            by_id[hid] = entry
        return by_id

    @staticmethod
    def _validate_and_extract_consistency(
        consistency_result: Mapping[str, Any] | None,
    ) -> tuple[bool, bool, bool]:
        if consistency_result is None:
            raise DecisionCandidateAssessmentContractError(
                "MISSING_CONSISTENCY", "consistency_result is required"
            )
        if not isinstance(consistency_result, Mapping):
            raise DecisionCandidateAssessmentContractError(
                "CONSISTENCY_TYPE",
                f"consistency_result is not a mapping: "
                f"{type(consistency_result).__name__}",
            )
        for field in _CONSISTENCY_FIELDS:
            if field not in consistency_result:
                raise DecisionCandidateAssessmentContractError(
                    "MISSING_CONSISTENCY_FIELD",
                    f"consistency_result has no {field}",
                )
        for field in _CONSISTENCY_BOOLEAN_FIELDS:
            value = consistency_result[field]
            if not isinstance(value, bool):
                raise DecisionCandidateAssessmentContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {value!r}",
                )
        for count_field in ("evaluation_count", "expected_candidate_count"):
            value = consistency_result[count_field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise DecisionCandidateAssessmentContractError(
                    f"{count_field.upper()}_TYPE",
                    f"{count_field} is not an int: {value!r}",
                )
            if value < 0:
                raise DecisionCandidateAssessmentContractError(
                    f"{count_field.upper()}_NEGATIVE",
                    f"{count_field} is negative: {value!r}",
                )
        source = consistency_result["consistency_source"]
        if source != CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033:
            raise DecisionCandidateAssessmentContractError(
                "INVALID_CONSISTENCY_SOURCE",
                "consistency_source is not the Task 033 identifier: " f"{source!r}",
            )
        coverage_complete = (
            consistency_result["all_candidates_evaluated"]
            and consistency_result["candidate_count_matches"]
        )
        criteria_complete = consistency_result["all_criteria_evaluated"]
        return (
            consistency_result["consistent"],
            coverage_complete,
            criteria_complete,
        )

    @staticmethod
    def _derive_counts(
        criteria: list[Mapping[str, Any]],
    ) -> dict[str, int]:
        """Derive the five structural criterion counts from the criteria list.

        Task 036 owns this derivation per its spec. The declared upstream
        counts are validated against this derivation during input
        validation, never trusted blindly.
        """
        criterion_count = len(criteria)
        criteria_satisfied = sum(1 for c in criteria if c["satisfied"])
        criteria_unsatisfied = sum(1 for c in criteria if not c["satisfied"])
        required_satisfied = sum(
            1 for c in criteria if c["required"] and c["satisfied"]
        )
        required_unsatisfied = sum(
            1 for c in criteria if c["required"] and not c["satisfied"]
        )
        return {
            "criterion_count": criterion_count,
            "criteria_satisfied": criteria_satisfied,
            "criteria_unsatisfied": criteria_unsatisfied,
            "required_criteria_satisfied": required_satisfied,
            "required_criteria_unsatisfied": required_unsatisfied,
        }

    @staticmethod
    def _join(
        candidate: Mapping[str, Any],
        evaluation: Mapping[str, Any],
    ) -> dict[str, Any]:
        counts = DecisionCandidateAssessmentService._derive_counts(
            evaluation["criteria"]
        )
        return {
            "hypothesis_id": candidate["hypothesis_id"],
            "hypothesis_name": candidate["hypothesis_name"],
            "rank": candidate["rank"],
            "score": candidate["score"],
            "is_tied": candidate["is_tied"],
            "tie_group_size": candidate["tie_group_size"],
            "score_gap_to_next_higher": candidate["score_gap_to_next_higher"],
            "score_gap_to_next_lower": candidate["score_gap_to_next_lower"],
            "criteria": [
                {
                    "criterion_id": c["criterion_id"],
                    "criterion_name": c["criterion_name"],
                    "satisfied": c["satisfied"],
                    "required": c["required"],
                    "reason": c["reason"],
                }
                for c in evaluation["criteria"]
            ],
            "criterion_count": counts["criterion_count"],
            "criteria_satisfied": counts["criteria_satisfied"],
            "criteria_unsatisfied": counts["criteria_unsatisfied"],
            "required_criteria_satisfied": counts["required_criteria_satisfied"],
            "required_criteria_unsatisfied": (counts["required_criteria_unsatisfied"]),
            "evaluation_complete": evaluation["evaluation_complete"],
            "assessment_source": (
                ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
            ),
        }

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        candidate_set: Mapping[str, Any],
        evaluations: list[Mapping[str, Any]],
        consistency_result: Mapping[str, Any],
    ) -> None:
        for field in (
            "available",
            "candidate_order_preserved",
            "evaluation_coverage_complete",
            "assessment_structure_consistent",
        ):
            if not isinstance(result[field], bool):
                raise DecisionCandidateAssessmentContractError(
                    "RESULT_FIELD_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )
        count = result["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionCandidateAssessmentContractError(
                "RESULT_COUNT_TYPE", f"count is not int: {count!r}"
            )
        if count < 0:
            raise DecisionCandidateAssessmentContractError(
                "RESULT_COUNT_NEGATIVE", f"count is negative: {count!r}"
            )
        assessments = result["assessments"]
        if not isinstance(assessments, list):
            raise DecisionCandidateAssessmentContractError(
                "ASSESSMENTS_TYPE",
                f"assessments is not a list: {type(assessments).__name__}",
            )
        if count != len(assessments):
            raise DecisionCandidateAssessmentContractError(
                "RESULT_COUNT_MISMATCH",
                f"count {count} != assessments length {len(assessments)}",
            )
        if (
            result["candidate_order_preserved"]
            != candidate_set["candidate_order_preserved"]
        ):
            raise DecisionCandidateAssessmentContractError(
                "ORDER_MISMATCH",
                "candidate_order_preserved does not match upstream "
                f"Task 035: {result['candidate_order_preserved']!r} != "
                f"{candidate_set['candidate_order_preserved']!r}",
            )
        if result["available"] is not (
            candidate_set["available"]
            and candidate_set["candidate_order_preserved"]
            and candidate_set["candidate_set_complete"]
            and result["evaluation_coverage_complete"]
            and result["assessment_structure_consistent"]
            and consistency_result["all_criteria_evaluated"]
        ):
            raise DecisionCandidateAssessmentContractError(
                "AVAILABLE_MISMATCH",
                "available does not match upstream availability",
            )
        if result["evaluation_coverage_complete"] is not (
            consistency_result["all_candidates_evaluated"]
            and consistency_result["candidate_count_matches"]
        ):
            raise DecisionCandidateAssessmentContractError(
                "COVERAGE_MISMATCH",
                "evaluation_coverage_complete does not match upstream",
            )
        if result["assessment_structure_consistent"] is not (
            consistency_result["consistent"]
        ):
            raise DecisionCandidateAssessmentContractError(
                "STRUCTURE_MISMATCH",
                "assessment_structure_consistent does not match upstream",
            )
        if (
            result["assessment_source"]
            != ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
        ):
            raise DecisionCandidateAssessmentContractError(
                "INVALID_SOURCE",
                "assessment_source is not the Task 036 identifier: "
                f"{result['assessment_source']!r}",
            )
        if result["available"]:
            upstream_candidates = candidate_set["candidates"]
            if len(assessments) != len(upstream_candidates):
                raise DecisionCandidateAssessmentContractError(
                    "UPSTREAM_COUNT_MISMATCH",
                    f"assessments length {len(assessments)} != upstream "
                    f"count {len(upstream_candidates)}",
                )
            evals_by_id = {e["hypothesis_id"]: e for e in evaluations}
            for i, (a, c) in enumerate(
                zip(assessments, upstream_candidates, strict=True)
            ):
                if a["hypothesis_id"] != c["hypothesis_id"]:
                    raise DecisionCandidateAssessmentContractError(
                        "ID_MISMATCH", f"assessment {i}: id differs"
                    )
                if a["hypothesis_name"] != c["hypothesis_name"]:
                    raise DecisionCandidateAssessmentContractError(
                        "NAME_MISMATCH", f"assessment {i}: name differs"
                    )
                if a["rank"] != c["rank"]:
                    raise DecisionCandidateAssessmentContractError(
                        "RANK_MISMATCH", f"assessment {i}: rank differs"
                    )
                if a["score"] != c["score"]:
                    raise DecisionCandidateAssessmentContractError(
                        "SCORE_MISMATCH", f"assessment {i}: score differs"
                    )
                if a["is_tied"] != c["is_tied"]:
                    raise DecisionCandidateAssessmentContractError(
                        "IS_TIED_MISMATCH", f"assessment {i}: is_tied differs"
                    )
                if a["tie_group_size"] != c["tie_group_size"]:
                    raise DecisionCandidateAssessmentContractError(
                        "TIE_GROUP_SIZE_MISMATCH",
                        f"assessment {i}: tie_group_size differs",
                    )
                if a["score_gap_to_next_higher"] != c["score_gap_to_next_higher"]:
                    raise DecisionCandidateAssessmentContractError(
                        "GAP_HIGHER_MISMATCH",
                        f"assessment {i}: gap_higher differs",
                    )
                if a["score_gap_to_next_lower"] != c["score_gap_to_next_lower"]:
                    raise DecisionCandidateAssessmentContractError(
                        "GAP_LOWER_MISMATCH",
                        f"assessment {i}: gap_lower differs",
                    )
                upstream_eval = evals_by_id.get(a["hypothesis_id"])
                if upstream_eval is None:
                    raise DecisionCandidateAssessmentContractError(
                        "MISSING_EVALUATION_AT_VALIDATION",
                        f"assessment {i}: no upstream evaluation",
                    )
                if a["criterion_count"] != upstream_eval["criterion_count"]:
                    raise DecisionCandidateAssessmentContractError(
                        "CRITERION_COUNT_MISMATCH",
                        f"assessment {i}: criterion_count differs",
                    )
                if a["criteria_satisfied"] != upstream_eval["criteria_satisfied"]:
                    raise DecisionCandidateAssessmentContractError(
                        "CRITERIA_SATISFIED_MISMATCH",
                        f"assessment {i}: criteria_satisfied differs",
                    )
                if a["criteria_unsatisfied"] != upstream_eval["criteria_unsatisfied"]:
                    raise DecisionCandidateAssessmentContractError(
                        "CRITERIA_UNSATISFIED_MISMATCH",
                        f"assessment {i}: criteria_unsatisfied differs",
                    )
                if (
                    a["required_criteria_satisfied"]
                    != upstream_eval["required_criteria_satisfied"]
                ):
                    raise DecisionCandidateAssessmentContractError(
                        "REQ_SATISFIED_MISMATCH",
                        f"assessment {i}: required_criteria_satisfied differs",
                    )
                if (
                    a["required_criteria_unsatisfied"]
                    != upstream_eval["required_criteria_unsatisfied"]
                ):
                    raise DecisionCandidateAssessmentContractError(
                        "REQ_UNSATISFIED_MISMATCH",
                        f"assessment {i}: required_criteria_unsatisfied " "differs",
                    )
                if a["evaluation_complete"] != upstream_eval["evaluation_complete"]:
                    raise DecisionCandidateAssessmentContractError(
                        "EVAL_COMPLETE_MISMATCH",
                        f"assessment {i}: evaluation_complete differs",
                    )
                if len(a["criteria"]) != len(upstream_eval["criteria"]):
                    raise DecisionCandidateAssessmentContractError(
                        "CRITERIA_LENGTH_MISMATCH",
                        f"assessment {i}: criteria list length differs",
                    )
                for j, (ac, uc) in enumerate(
                    zip(a["criteria"], upstream_eval["criteria"], strict=True)
                ):
                    if ac["criterion_id"] != uc["criterion_id"]:
                        raise DecisionCandidateAssessmentContractError(
                            "CRITERION_ID_MISMATCH",
                            f"assessment {i} criterion {j}: id differs",
                        )
                    if ac["criterion_name"] != uc["criterion_name"]:
                        raise DecisionCandidateAssessmentContractError(
                            "CRITERION_NAME_MISMATCH",
                            f"assessment {i} criterion {j}: name differs",
                        )
                    if ac["satisfied"] != uc["satisfied"]:
                        raise DecisionCandidateAssessmentContractError(
                            "CRITERION_SATISFIED_MISMATCH",
                            f"assessment {i} criterion {j}: satisfied differs",
                        )
                    if ac["required"] != uc["required"]:
                        raise DecisionCandidateAssessmentContractError(
                            "CRITERION_REQUIRED_MISMATCH",
                            f"assessment {i} criterion {j}: required differs",
                        )
                    if ac["reason"] != uc["reason"]:
                        raise DecisionCandidateAssessmentContractError(
                            "CRITERION_REASON_MISMATCH",
                            f"assessment {i} criterion {j}: reason differs",
                        )
        else:
            if assessments:
                raise DecisionCandidateAssessmentContractError(
                    "NONEMPTY_WHEN_UNAVAILABLE",
                    f"assessments must be empty when unavailable: "
                    f"{len(assessments)} entries",
                )

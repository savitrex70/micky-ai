from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_context import CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031
from rop.services.decision_input_eligibility import (
    ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
    DecisionInputEligibilityService,
)

CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035 = "DECISION_CANDIDATE_SET_TASK_035"
"""Fixed structural-contract identifier for Task 035 results."""

_REQUIRED_CONTEXT_FIELDS = (
    "context_available",
    "decision_ready",
    "candidate_count",
    "differential",
    "context_source",
)

_REQUIRED_ELIGIBILITY_FIELDS = (
    "eligible",
    "decision_ready",
    "context_available",
    "evaluation_consistent",
    "has_candidates",
    "evaluations_available",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "candidate_count_matches",
    "evaluation_structure_consistent",
    "blocking_conditions",
    "eligibility_source",
)

_CONTEXT_BOOLEAN_FIELDS = ("context_available", "decision_ready")

_ELIGIBILITY_BOOLEAN_FIELDS = (
    "eligible",
    "decision_ready",
    "context_available",
    "evaluation_consistent",
    "has_candidates",
    "evaluations_available",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "candidate_count_matches",
    "evaluation_structure_consistent",
)

_CANDIDATE_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "rank",
    "hypothesis_score",
    "is_tied",
    "tie_group_size",
    "score_gap_to_next_higher",
    "score_gap_to_next_lower",
)

# Task 034's fixed blocking-condition identifiers, in their fixed
# deterministic order. Duplicated here deliberately so this service
# can validate the upstream contract without importing anything
# other than the source identifier constant.
_BLOCKING_CONDITION_ORDER = (
    "DECISION_NOT_READY",
    "CONTEXT_UNAVAILABLE",
    "NO_CANDIDATES",
    "NO_EVALUATIONS",
    "CANDIDATE_COVERAGE_INCOMPLETE",
    "EVALUATION_STRUCTURE_INCONSISTENT",
    "CRITERIA_INCOMPLETE",
)
_VALID_BLOCKING_CONDITIONS = frozenset(_BLOCKING_CONDITION_ORDER)

# Task 034's Section 5 conjunction -- the eight booleans whose AND is
# the authoritative definition of ``eligible``. ``evaluation_consistent``
# is exposed as a passthrough field but is not part of this conjunction.
_ELIGIBILITY_CONJUNCTION_FIELDS = (
    "decision_ready",
    "context_available",
    "has_candidates",
    "evaluations_available",
    "all_candidates_evaluated",
    "all_criteria_evaluated",
    "candidate_count_matches",
    "evaluation_structure_consistent",
)


class DecisionCandidateSetContractError(Exception):
    """Task 035: malformed upstream input or an internal derivation bug.

    Raised only when the Task 031 context or Task 034 eligibility result
    is not shaped like its own established contract, the differential
    is malformed, or this service's own derivation produced an
    internally contradictory result. It is never raised for a normal
    unavailable state -- that is a valid, fully typed response.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionCandidateSetService:
    """Task 035: structural candidate-set handoff boundary.

    Consumes Task 031's ``DecisionContextRead`` and Task 034's
    ``DecisionInputEligibilityRead`` unchanged. Introduces no scoring,
    ranking, tie-breaking, filtering, or selection logic; performs no
    persistence; mutates no input. When available, every candidate from
    the Task 031 differential is forwarded in the exact original order;
    when unavailable, the set is empty.
    """

    def __init__(
        self,
        decision_input_eligibility_service: (
            DecisionInputEligibilityService | None
        ) = None,
    ) -> None:
        self.decision_input_eligibility_service = (
            decision_input_eligibility_service or DecisionInputEligibilityService()
        )

    def build_for_session_with_inputs(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        """Walk the established chain once and return the intermediates.

        Builds the Task 031 context exactly once -- the same
        single-build pattern already established at the Task
        032/033/034 boundary -- reuses it for Task 032 evaluation,
        Task 033 consistency, and Task 034 eligibility, then passes the
        same context and eligibility result into this service's
        ``build``. No duplicate pipeline is created.
        """
        eligibility_service = self.decision_input_eligibility_service
        consistency_service = (
            eligibility_service.decision_evaluation_consistency_service
        )
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
        eligibility_result = eligibility_service.build(context, consistency_result)
        candidate_set = self.build(context, eligibility_result)
        return candidate_set, evaluations, consistency_result

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Return only the candidate set.

        Convenience wrapper around ``build_for_session_with_inputs`` for
        existing callers (e.g. the Task 035 API endpoint) that do not
        need the intermediate evaluations/consistency result.
        """
        candidate_set, _, _ = self.build_for_session_with_inputs(
            db, session_id, candidates
        )
        return candidate_set

    def build(
        self,
        context: Mapping[str, Any] | None,
        eligibility_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Package the candidate set into the Task 035 output contract.

        Pure transformation -- never mutates inputs, never recomputes a
        score, rank, tie, or gap, never reorders or removes a candidate.
        """
        (
            context_available,
            decision_ready,
            candidate_count,
            differential,
        ) = self._validate_and_extract_context(context)
        eligible = self._validate_and_extract_eligibility(eligibility_result)

        available = (
            eligible and context_available and decision_ready and candidate_count > 0
        )

        if available:
            projected = [self._project_candidate(entry) for entry in differential]
        else:
            projected = []

        result: dict[str, Any] = {
            "available": available,
            "candidate_count": len(projected),
            "candidates": projected,
            "candidate_order_preserved": True,
            "candidate_set_complete": available,
            "candidate_set_source": (
                CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035
            ),
        }
        self._validate_result(result, available, differential)
        return result

    @staticmethod
    def _validate_and_extract_context(
        context: Mapping[str, Any] | None,
    ) -> tuple[bool, bool, int, list[Mapping[str, Any]]]:
        if context is None:
            raise DecisionCandidateSetContractError(
                "MISSING_CONTEXT", "context is required"
            )
        if not isinstance(context, Mapping):
            raise DecisionCandidateSetContractError(
                "CONTEXT_TYPE",
                f"context is not a mapping: {type(context).__name__}",
            )
        for field in _REQUIRED_CONTEXT_FIELDS:
            if field not in context:
                raise DecisionCandidateSetContractError(
                    "MISSING_CONTEXT_FIELD", f"context has no {field}"
                )

        for field in _CONTEXT_BOOLEAN_FIELDS:
            value = context[field]
            if not isinstance(value, bool):
                raise DecisionCandidateSetContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {value!r}",
                )

        candidate_count = context["candidate_count"]
        if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
            raise DecisionCandidateSetContractError(
                "CANDIDATE_COUNT_TYPE",
                f"candidate_count is not an int: {candidate_count!r}",
            )
        if candidate_count < 0:
            raise DecisionCandidateSetContractError(
                "CANDIDATE_COUNT_NEGATIVE",
                f"candidate_count is negative: {candidate_count!r}",
            )

        differential = context["differential"]
        if not isinstance(differential, list):
            raise DecisionCandidateSetContractError(
                "DIFFERENTIAL_TYPE",
                f"differential is not a list: {type(differential).__name__}",
            )
        if candidate_count != len(differential):
            raise DecisionCandidateSetContractError(
                "CANDIDATE_COUNT_MISMATCH",
                "candidate_count does not match len(differential): "
                f"{candidate_count} != {len(differential)}",
            )

        seen_ids: set[UUID] = set()
        for entry in differential:
            if not isinstance(entry, Mapping):
                raise DecisionCandidateSetContractError(
                    "MALFORMED_CANDIDATE",
                    "candidate entry is not a mapping: " f"{type(entry).__name__}",
                )
            for field in _CANDIDATE_FIELDS:
                if field not in entry:
                    raise DecisionCandidateSetContractError(
                        "MISSING_CANDIDATE_FIELD",
                        f"candidate entry has no {field}",
                    )
            hid = entry["hypothesis_id"]
            if not isinstance(hid, UUID):
                raise DecisionCandidateSetContractError(
                    "INVALID_HYPOTHESIS_ID",
                    f"hypothesis_id is not a UUID: {type(hid).__name__}",
                )
            if hid in seen_ids:
                raise DecisionCandidateSetContractError(
                    "DUPLICATE_HYPOTHESIS_ID",
                    f"duplicate hypothesis_id: {hid}",
                )
            seen_ids.add(hid)
            name = entry["hypothesis_name"]
            if not isinstance(name, str):
                raise DecisionCandidateSetContractError(
                    "INVALID_HYPOTHESIS_NAME",
                    f"hypothesis_name is not a string: {type(name).__name__}",
                )
            rank = entry["rank"]
            if not isinstance(rank, int) or isinstance(rank, bool):
                raise DecisionCandidateSetContractError(
                    "INVALID_RANK", f"rank is not an int: {rank!r}"
                )
            score = entry["hypothesis_score"]
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise DecisionCandidateSetContractError(
                    "INVALID_SCORE", f"score is not numeric: {score!r}"
                )
            is_tied = entry["is_tied"]
            if not isinstance(is_tied, bool):
                raise DecisionCandidateSetContractError(
                    "INVALID_IS_TIED", f"is_tied is not boolean: {is_tied!r}"
                )
            tgs = entry["tie_group_size"]
            if not isinstance(tgs, int) or isinstance(tgs, bool):
                raise DecisionCandidateSetContractError(
                    "INVALID_TIE_GROUP_SIZE",
                    f"tie_group_size is not an int: {tgs!r}",
                )
            gh = entry["score_gap_to_next_higher"]
            if gh is not None and (
                not isinstance(gh, (int, float)) or isinstance(gh, bool)
            ):
                raise DecisionCandidateSetContractError(
                    "INVALID_GAP_HIGHER",
                    f"score_gap_to_next_higher is not numeric/None: {gh!r}",
                )
            gl = entry["score_gap_to_next_lower"]
            if gl is not None and (
                not isinstance(gl, (int, float)) or isinstance(gl, bool)
            ):
                raise DecisionCandidateSetContractError(
                    "INVALID_GAP_LOWER",
                    f"score_gap_to_next_lower is not numeric/None: {gl!r}",
                )

        context_source = context["context_source"]
        if context_source != CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031:
            raise DecisionCandidateSetContractError(
                "INVALID_CONTEXT_SOURCE",
                f"context_source is not the Task 031 identifier: {context_source!r}",
            )

        return (
            context["context_available"],
            context["decision_ready"],
            candidate_count,
            differential,
        )

    @staticmethod
    def _validate_and_extract_eligibility(
        eligibility_result: Mapping[str, Any] | None,
    ) -> bool:
        if eligibility_result is None:
            raise DecisionCandidateSetContractError(
                "MISSING_ELIGIBILITY", "eligibility_result is required"
            )
        if not isinstance(eligibility_result, Mapping):
            raise DecisionCandidateSetContractError(
                "ELIGIBILITY_TYPE",
                "eligibility_result is not a mapping: "
                f"{type(eligibility_result).__name__}",
            )
        for field in _REQUIRED_ELIGIBILITY_FIELDS:
            if field not in eligibility_result:
                raise DecisionCandidateSetContractError(
                    "MISSING_ELIGIBILITY_FIELD",
                    f"eligibility_result has no {field}",
                )
        for field in _ELIGIBILITY_BOOLEAN_FIELDS:
            value = eligibility_result[field]
            if not isinstance(value, bool):
                raise DecisionCandidateSetContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {value!r}",
                )
        source = eligibility_result["eligibility_source"]
        if source != ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034:
            raise DecisionCandidateSetContractError(
                "INVALID_ELIGIBILITY_SOURCE",
                f"eligibility_source is not the Task 034 identifier: {source!r}",
            )

        blocking_conditions = eligibility_result["blocking_conditions"]
        if not isinstance(blocking_conditions, list):
            raise DecisionCandidateSetContractError(
                "BLOCKING_CONDITIONS_TYPE",
                "blocking_conditions is not a list: "
                f"{type(blocking_conditions).__name__}",
            )
        for condition in blocking_conditions:
            if condition not in _VALID_BLOCKING_CONDITIONS:
                raise DecisionCandidateSetContractError(
                    "INVALID_BLOCKING_CONDITION",
                    f"unknown blocking condition: {condition!r}",
                )
        if len(blocking_conditions) != len(set(blocking_conditions)):
            raise DecisionCandidateSetContractError(
                "DUPLICATE_BLOCKING_CONDITION",
                f"blocking_conditions contains duplicates: " f"{blocking_conditions!r}",
            )
        present_in_order = [
            condition
            for condition in _BLOCKING_CONDITION_ORDER
            if condition in blocking_conditions
        ]
        if blocking_conditions != present_in_order:
            raise DecisionCandidateSetContractError(
                "BLOCKING_CONDITIONS_ORDER",
                "blocking_conditions is not in the fixed deterministic "
                f"order: {blocking_conditions!r}",
            )

        eligible = eligibility_result["eligible"]
        if eligible and blocking_conditions:
            raise DecisionCandidateSetContractError(
                "ELIGIBLE_WITH_BLOCKING_CONDITIONS",
                "eligible is True but blocking_conditions is non-empty: "
                f"{blocking_conditions!r}",
            )
        if not eligible and not blocking_conditions:
            raise DecisionCandidateSetContractError(
                "INELIGIBLE_WITHOUT_BLOCKING_CONDITIONS",
                "eligible is False but blocking_conditions is empty",
            )

        recomputed_eligible = all(
            eligibility_result[field] for field in _ELIGIBILITY_CONJUNCTION_FIELDS
        )
        if eligible != recomputed_eligible:
            raise DecisionCandidateSetContractError(
                "ELIGIBLE_CONJUNCTION_MISMATCH",
                "eligible does not match the recomputed Task 034 conjunction: "
                f"{eligible!r} != {recomputed_eligible!r}",
            )

        return eligible

    @staticmethod
    def _project_candidate(entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "hypothesis_id": entry["hypothesis_id"],
            "hypothesis_name": entry["hypothesis_name"],
            "rank": entry["rank"],
            "score": entry["hypothesis_score"],
            "is_tied": entry["is_tied"],
            "tie_group_size": entry["tie_group_size"],
            "score_gap_to_next_higher": entry["score_gap_to_next_higher"],
            "score_gap_to_next_lower": entry["score_gap_to_next_lower"],
        }

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        upstream_available: bool,
        upstream_differential: list[Mapping[str, Any]],
    ) -> None:
        for field in (
            "available",
            "candidate_order_preserved",
            "candidate_set_complete",
        ):
            if not isinstance(result[field], bool):
                raise DecisionCandidateSetContractError(
                    "RESULT_FIELD_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )
        count = result["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionCandidateSetContractError(
                "COUNT_TYPE", f"count is not an int: {count!r}"
            )
        if count < 0:
            raise DecisionCandidateSetContractError(
                "COUNT_NEGATIVE", f"count is negative: {count!r}"
            )
        candidates = result["candidates"]
        if not isinstance(candidates, list):
            raise DecisionCandidateSetContractError(
                "CANDIDATES_TYPE",
                f"candidates is not a list: {type(candidates).__name__}",
            )
        if count != len(candidates):
            raise DecisionCandidateSetContractError(
                "COUNT_MISMATCH",
                f"count {count} != candidates length {len(candidates)}",
            )
        seen: set[UUID] = set()
        for c in candidates:
            hid = c["hypothesis_id"]
            if not isinstance(hid, UUID):
                raise DecisionCandidateSetContractError(
                    "INVALID_ID_IN_RESULT",
                    f"id is not a UUID: {type(hid).__name__}",
                )
            if hid in seen:
                raise DecisionCandidateSetContractError(
                    "DUPLICATE_ID_IN_RESULT", f"duplicate id: {hid}"
                )
            seen.add(hid)
        if result["candidate_order_preserved"] is not True:
            raise DecisionCandidateSetContractError(
                "ORDER_NOT_PRESERVED",
                "candidate_order_preserved must be True",
            )
        if result["available"] != upstream_available:
            raise DecisionCandidateSetContractError(
                "AVAILABLE_MISMATCH",
                "available does not match upstream availability: "
                f"{result['available']!r} != {upstream_available!r}",
            )
        if result["candidate_set_complete"] != upstream_available:
            raise DecisionCandidateSetContractError(
                "CANDIDATE_SET_COMPLETE_MISMATCH",
                "candidate_set_complete does not match upstream "
                f"availability: {result['candidate_set_complete']!r} != "
                f"{upstream_available!r}",
            )
        if upstream_available:
            if len(candidates) != len(upstream_differential):
                raise DecisionCandidateSetContractError(
                    "UPSTREAM_COUNT_MISMATCH",
                    f"candidates length {len(candidates)} != upstream "
                    f"count {len(upstream_differential)}",
                )
            for i, (c, u) in enumerate(
                zip(candidates, upstream_differential, strict=True)
            ):
                if c["hypothesis_id"] != u["hypothesis_id"]:
                    raise DecisionCandidateSetContractError(
                        "ID_MISMATCH", f"candidate {i}: id differs"
                    )
                if c["hypothesis_name"] != u["hypothesis_name"]:
                    raise DecisionCandidateSetContractError(
                        "NAME_MISMATCH", f"candidate {i}: name differs"
                    )
                if c["rank"] != u["rank"]:
                    raise DecisionCandidateSetContractError(
                        "RANK_MISMATCH", f"candidate {i}: rank differs"
                    )
                if c["score"] != u["hypothesis_score"]:
                    raise DecisionCandidateSetContractError(
                        "SCORE_MISMATCH", f"candidate {i}: score differs"
                    )
                if c["is_tied"] != u["is_tied"]:
                    raise DecisionCandidateSetContractError(
                        "IS_TIED_MISMATCH", f"candidate {i}: is_tied differs"
                    )
                if c["tie_group_size"] != u["tie_group_size"]:
                    raise DecisionCandidateSetContractError(
                        "TIE_GROUP_SIZE_MISMATCH",
                        f"candidate {i}: tie_group_size differs",
                    )
                if c["score_gap_to_next_higher"] != u["score_gap_to_next_higher"]:
                    raise DecisionCandidateSetContractError(
                        "GAP_HIGHER_MISMATCH",
                        f"candidate {i}: score_gap_to_next_higher differs",
                    )
                if c["score_gap_to_next_lower"] != u["score_gap_to_next_lower"]:
                    raise DecisionCandidateSetContractError(
                        "GAP_LOWER_MISMATCH",
                        f"candidate {i}: score_gap_to_next_lower differs",
                    )
        else:
            if candidates:
                raise DecisionCandidateSetContractError(
                    "NONEMPTY_WHEN_UNAVAILABLE",
                    f"candidates must be empty when unavailable: "
                    f"{len(candidates)} entries",
                )
        if (
            result["candidate_set_source"]
            != CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035
        ):
            raise DecisionCandidateSetContractError(
                "INVALID_SOURCE",
                "candidate_set_source is not the Task 035 identifier: "
                f"{result['candidate_set_source']!r}",
            )

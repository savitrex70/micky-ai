from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_input_eligibility import (
    ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
    DecisionInputEligibilityService,
)

SELECTION_SOURCE_DECISION_CANDIDATE_SELECTION_TASK_035 = (
    "DECISION_CANDIDATE_SELECTION_TASK_035"
)
"""Fixed structural-contract identifier for Task 035 results.

Names *which* contract produced the result -- not a score, a
probability, a confidence, or a recommendation.
"""

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

_RESULT_BOOLEAN_FIELDS = (
    "selection_available",
    "all_candidates_forwarded",
    "candidate_order_preserved",
)


class DecisionCandidateSelectionContractError(Exception):
    """Task 035: malformed upstream input or an internal derivation bug.

    Raised only when the Task 034 eligibility result is not shaped
    like its own established contract, the differential candidate
    list is malformed, or this service's own derivation produced an
    internally contradictory result. It is never raised for a normal
    ineligible state -- that is a valid, fully typed response with
    ``selection_available == False`` and empty candidate lists.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionCandidateSelectionService:
    """Task 035: structural candidate selection boundary.

    Consumes only Task 034's ``DecisionInputEligibilityRead`` output
    and the Task 031 context's already-established differential. It
    introduces no scoring, ranking, tie-breaking, or decision logic,
    performs no persistence, and mutates no input. When eligible, it
    forwards every candidate in the exact differential order; when
    not eligible, it forwards none.
    """

    def __init__(
        self,
        decision_input_eligibility_service: (
            DecisionInputEligibilityService | None
        ) = None,
    ) -> None:
        self.decision_input_eligibility_service = (
            decision_input_eligibility_service
            or DecisionInputEligibilityService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Walk the established dependency chain and return the selection.

        Builds the Task 031 decision context exactly once -- the same
        single-build pattern already established at the Task 032/033/034
        boundary -- then evaluates candidates via Task 032, checks
        consistency via Task 033, derives eligibility via Task 034's
        ``build``, and finally calls this service's ``build`` with the
        eligibility result and the differential that was already part
        of that context.
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
        return self.build(eligibility_result, context["differential"])

    def build(
        self,
        eligibility_result: Mapping[str, Any] | None,
        differential: list[Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        """Derive the candidate-selection contract from already-built inputs.

        Kept separate from ``build_for_session`` so selection can be
        exercised directly against a hand-built Task 034 result and
        differential. Never mutates its inputs. Never reorders, ranks,
        scores, or removes candidates.
        """
        eligible = self._validate_and_extract_eligibility(eligibility_result)
        upstream_ids, upstream_names = self._validate_and_extract_differential(
            differential
        )

        if eligible:
            ids: list[UUID] = list(upstream_ids)
            names: list[str] = list(upstream_names)
            selection_available = True
            all_candidates_forwarded = True
        else:
            ids = []
            names = []
            selection_available = False
            all_candidates_forwarded = False

        result: dict[str, Any] = {
            "selection_available": selection_available,
            "eligible_candidate_count": len(ids),
            "eligible_candidate_ids": ids,
            "eligible_candidate_names": names,
            "all_candidates_forwarded": all_candidates_forwarded,
            "candidate_order_preserved": True,
            "selection_source": (
                SELECTION_SOURCE_DECISION_CANDIDATE_SELECTION_TASK_035
            ),
        }
        self._validate_result(result, eligible, upstream_ids, upstream_names)
        return result

    @staticmethod
    def _validate_and_extract_eligibility(
        eligibility_result: Mapping[str, Any] | None,
    ) -> bool:
        if eligibility_result is None:
            raise DecisionCandidateSelectionContractError(
                "MISSING_ELIGIBILITY", "eligibility_result is required"
            )
        if not isinstance(eligibility_result, Mapping):
            raise DecisionCandidateSelectionContractError(
                "ELIGIBILITY_TYPE",
                "eligibility_result is not a mapping: "
                f"{type(eligibility_result).__name__}",
            )
        for field in _REQUIRED_ELIGIBILITY_FIELDS:
            if field not in eligibility_result:
                raise DecisionCandidateSelectionContractError(
                    "MISSING_ELIGIBILITY_FIELD",
                    f"eligibility_result has no {field}",
                )
        for field in _ELIGIBILITY_BOOLEAN_FIELDS:
            value = eligibility_result[field]
            if not isinstance(value, bool):
                raise DecisionCandidateSelectionContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {value!r}",
                )
        source = eligibility_result["eligibility_source"]
        if source != ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034:
            raise DecisionCandidateSelectionContractError(
                "INVALID_ELIGIBILITY_SOURCE",
                f"eligibility_source is not the Task 034 identifier: {source!r}",
            )
        return eligibility_result["eligible"]

    @staticmethod
    def _validate_and_extract_differential(
        differential: list[Mapping[str, Any]] | None,
    ) -> tuple[list[UUID], list[str]]:
        if differential is None:
            raise DecisionCandidateSelectionContractError(
                "MISSING_DIFFERENTIAL", "differential is required"
            )
        if not isinstance(differential, list):
            raise DecisionCandidateSelectionContractError(
                "DIFFERENTIAL_TYPE",
                f"differential is not a list: {type(differential).__name__}",
            )
        ids: list[UUID] = []
        names: list[str] = []
        seen: set[UUID] = set()
        for entry in differential:
            if not isinstance(entry, Mapping):
                raise DecisionCandidateSelectionContractError(
                    "MALFORMED_DIFFERENTIAL_ENTRY",
                    "differential entry is not a mapping: "
                    f"{type(entry).__name__}",
                )
            if "hypothesis_id" not in entry:
                raise DecisionCandidateSelectionContractError(
                    "MISSING_HYPOTHESIS_ID",
                    "differential entry has no hypothesis_id",
                )
            if "hypothesis_name" not in entry:
                raise DecisionCandidateSelectionContractError(
                    "MISSING_HYPOTHESIS_NAME",
                    "differential entry has no hypothesis_name",
                )
            hid = entry["hypothesis_id"]
            if not isinstance(hid, UUID):
                raise DecisionCandidateSelectionContractError(
                    "INVALID_HYPOTHESIS_ID",
                    f"hypothesis_id is not a UUID: {type(hid).__name__}",
                )
            if hid in seen:
                raise DecisionCandidateSelectionContractError(
                    "DUPLICATE_HYPOTHESIS_ID",
                    f"duplicate hypothesis_id: {hid}",
                )
            seen.add(hid)
            name = entry["hypothesis_name"]
            if not isinstance(name, str):
                raise DecisionCandidateSelectionContractError(
                    "INVALID_HYPOTHESIS_NAME",
                    f"hypothesis_name is not a string: {type(name).__name__}",
                )
            ids.append(hid)
            names.append(name)
        return ids, names

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        upstream_eligible: bool,
        upstream_ids: list[UUID],
        upstream_names: list[str],
    ) -> None:
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise DecisionCandidateSelectionContractError(
                    "RESULT_FIELD_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )
        count = result["eligible_candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionCandidateSelectionContractError(
                "COUNT_TYPE", f"count is not an int: {count!r}"
            )
        if count < 0:
            raise DecisionCandidateSelectionContractError(
                "COUNT_NEGATIVE", f"count is negative: {count!r}"
            )
        ids = result["eligible_candidate_ids"]
        names = result["eligible_candidate_names"]
        if not isinstance(ids, list):
            raise DecisionCandidateSelectionContractError(
                "IDS_TYPE", f"ids is not a list: {type(ids).__name__}"
            )
        if not isinstance(names, list):
            raise DecisionCandidateSelectionContractError(
                "NAMES_TYPE", f"names is not a list: {type(names).__name__}"
            )
        for hid in ids:
            if not isinstance(hid, UUID):
                raise DecisionCandidateSelectionContractError(
                    "INVALID_ID_IN_RESULT",
                    f"result id is not a UUID: {type(hid).__name__}",
                )
        for name in names:
            if not isinstance(name, str):
                raise DecisionCandidateSelectionContractError(
                    "INVALID_NAME_IN_RESULT",
                    f"result name is not a string: {type(name).__name__}",
                )
        if len(set(ids)) != len(ids):
            raise DecisionCandidateSelectionContractError(
                "DUPLICATE_ID_IN_RESULT", f"ids contains duplicates: {ids!r}"
            )
        if len(ids) != len(names):
            raise DecisionCandidateSelectionContractError(
                "ID_NAME_LENGTH_MISMATCH",
                f"ids length {len(ids)} != names length {len(names)}",
            )
        if count != len(ids):
            raise DecisionCandidateSelectionContractError(
                "COUNT_MISMATCH",
                f"count {count} != ids length {len(ids)}",
            )
        if result["selection_available"] != upstream_eligible:
            raise DecisionCandidateSelectionContractError(
                "SELECTION_AVAILABLE_MISMATCH",
                "selection_available does not match upstream eligibility: "
                f"{result['selection_available']!r} != {upstream_eligible!r}",
            )
        if result["all_candidates_forwarded"] != upstream_eligible:
            raise DecisionCandidateSelectionContractError(
                "ALL_FORWARDED_MISMATCH",
                "all_candidates_forwarded does not match upstream eligibility: "
                f"{result['all_candidates_forwarded']!r} != {upstream_eligible!r}",
            )
        if result["candidate_order_preserved"] is not True:
            raise DecisionCandidateSelectionContractError(
                "ORDER_NOT_PRESERVED",
                "candidate_order_preserved must be True",
            )
        if upstream_eligible:
            if list(ids) != list(upstream_ids):
                raise DecisionCandidateSelectionContractError(
                    "IDS_MISMATCH",
                    "eligible_candidate_ids does not match upstream candidate ids",
                )
            if list(names) != list(upstream_names):
                raise DecisionCandidateSelectionContractError(
                    "NAMES_MISMATCH",
                    "eligible_candidate_names does not match upstream "
                    "candidate names",
                )
        else:
            if ids:
                raise DecisionCandidateSelectionContractError(
                    "NONEMPTY_IDS_WHEN_INELIGIBLE",
                    f"ids must be empty when ineligible: {ids!r}",
                )
            if names:
                raise DecisionCandidateSelectionContractError(
                    "NONEMPTY_NAMES_WHEN_INELIGIBLE",
                    f"names must be empty when ineligible: {names!r}",
                )
        if (
            result["selection_source"]
            != SELECTION_SOURCE_DECISION_CANDIDATE_SELECTION_TASK_035
        ):
            raise DecisionCandidateSelectionContractError(
                "INVALID_SELECTION_SOURCE",
                "selection_source is not the Task 035 identifier: "
                f"{result['selection_source']!r}",
            )

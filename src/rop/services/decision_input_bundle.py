from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_candidate_assessment import (
    DecisionCandidateAssessmentService,
)
from rop.services.decision_candidate_set import DecisionCandidateSetService

INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037 = "DECISION_INPUT_BUNDLE_TASK_037"
"""Fixed structural-contract identifier for Task 037 results."""

_CANDIDATE_SET_SOURCE = "DECISION_CANDIDATE_SET_TASK_035"
_ASSESSMENT_SET_SOURCE = "DECISION_CANDIDATE_ASSESSMENT_TASK_036"

_CANDIDATE_SET_REQUIRED_FIELDS = (
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

_ASSESSMENT_SET_REQUIRED_FIELDS = (
    "available",
    "candidate_count",
    "assessments",
    "candidate_order_preserved",
    "evaluation_coverage_complete",
    "assessment_structure_consistent",
    "assessment_source",
)

_ASSESSMENT_SET_BOOLEAN_FIELDS = (
    "available",
    "candidate_order_preserved",
    "evaluation_coverage_complete",
    "assessment_structure_consistent",
)


class DecisionInputBundleContractError(Exception):
    """Task 037: malformed upstream bundle or an internal derivation bug.

    Raised only when the Task 035 candidate set or the Task 036
    assessment set is not shaped like its own established contract,
    when the two do not describe the same candidate sequence, or when
    this service's own derivation produced an internally contradictory
    result. It is never raised for a normal unavailable state -- that
    is a valid, fully typed response.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionInputBundleService:
    """Task 037: final audited input-bundle packaging boundary.

    Packages the Task 035 candidate set and the Task 036 assessment
    set into one cross-validated structure. Introduces no scoring,
    ranking, filtering, selection, or decision logic; performs no
    persistence; mutates no input. Both nested contracts are preserved
    verbatim; the only derived fields are the bundle-level structural
    flags.
    """

    def __init__(
        self,
        decision_candidate_set_service: (
            DecisionCandidateSetService | None
        ) = None,
        decision_candidate_assessment_service: (
            DecisionCandidateAssessmentService | None
        ) = None,
    ) -> None:
        self.decision_candidate_set_service = (
            decision_candidate_set_service or DecisionCandidateSetService()
        )
        self.decision_candidate_assessment_service = (
            decision_candidate_assessment_service
            or DecisionCandidateAssessmentService(
                self.decision_candidate_set_service
            )
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Delegate the upstream chain to Task 035, then to Task 036.

        Task 035 owns the orchestration of Tasks 031-035 via its
        ``build_for_session_with_inputs`` boundary; Task 036 owns the
        candidate/evaluation join. This method composes those two
        boundaries -- it does not walk the pipeline itself and does
        not reach into Tasks 031/032/033/034 services.
        """
        candidate_set, evaluations, consistency_result = (
            self.decision_candidate_set_service.build_for_session_with_inputs(
                db, session_id, candidates
            )
        )
        assessment_set = self.decision_candidate_assessment_service.build(
            candidate_set, evaluations, consistency_result
        )
        return self.build(candidate_set, assessment_set)

    def build(
        self,
        candidate_set: Mapping[str, Any] | None,
        assessment_set: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Package the two upstream contracts into one bundle.

        Pure transformation. Never mutates inputs. Never reranks,
        rescores, filters, deduplicates, or reorders either upstream
        structure.
        """
        cs = self._validate_candidate_set(candidate_set)
        aset = self._validate_assessment_set(assessment_set)

        alignment_complete = self._check_alignment(cs, aset)

        cs_available = cs["available"]
        as_available = aset["available"]
        input_structure_consistent = True

        available = (
            cs_available
            and as_available
            and alignment_complete
            and input_structure_consistent
        )

        candidate_count = len(cs["candidates"]) if available else 0
        order_preserved = cs["candidate_order_preserved"]

        result: dict[str, Any] = {
            "available": available,
            "candidate_set": dict(cs),
            "assessment_set": dict(aset),
            "candidate_count": candidate_count,
            "candidate_order_preserved": order_preserved,
            "candidate_assessment_alignment_complete": alignment_complete,
            "input_structure_consistent": input_structure_consistent,
            "input_source": (
                INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037
            ),
        }
        self._validate_result(result, cs, aset)
        return result

    @staticmethod
    def _validate_candidate_set(
        candidate_set: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if candidate_set is None:
            raise DecisionInputBundleContractError(
                "MISSING_CANDIDATE_SET", "candidate_set is required"
            )
        if not isinstance(candidate_set, Mapping):
            raise DecisionInputBundleContractError(
                "CANDIDATE_SET_TYPE",
                f"candidate_set is not a mapping: "
                f"{type(candidate_set).__name__}",
            )
        for field in _CANDIDATE_SET_REQUIRED_FIELDS:
            if field not in candidate_set:
                raise DecisionInputBundleContractError(
                    "MISSING_CANDIDATE_SET_FIELD",
                    f"candidate_set has no {field}",
                )
        for field in _CANDIDATE_SET_BOOLEAN_FIELDS:
            if not isinstance(candidate_set[field], bool):
                raise DecisionInputBundleContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {candidate_set[field]!r}",
                )
        count = candidate_set["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionInputBundleContractError(
                "CANDIDATE_SET_COUNT_TYPE",
                f"candidate_count is not an int: {count!r}",
            )
        if count < 0:
            raise DecisionInputBundleContractError(
                "CANDIDATE_SET_COUNT_NEGATIVE",
                f"candidate_count is negative: {count!r}",
            )
        candidates = candidate_set["candidates"]
        if not isinstance(candidates, list):
            raise DecisionInputBundleContractError(
                "CANDIDATES_TYPE",
                f"candidates is not a list: {type(candidates).__name__}",
            )
        if count != len(candidates):
            raise DecisionInputBundleContractError(
                "CANDIDATE_SET_COUNT_MISMATCH",
                f"candidate_count {count} != len(candidates) {len(candidates)}",
            )
        for entry in candidates:
            if not isinstance(entry, Mapping):
                raise DecisionInputBundleContractError(
                    "MALFORMED_CANDIDATE",
                    f"candidate is not a mapping: {type(entry).__name__}",
                )
            for field in _CANDIDATE_FIELDS:
                if field not in entry:
                    raise DecisionInputBundleContractError(
                        "MISSING_CANDIDATE_FIELD",
                        f"candidate has no {field}",
                    )
        if candidate_set["candidate_set_source"] != _CANDIDATE_SET_SOURCE:
            raise DecisionInputBundleContractError(
                "INVALID_CANDIDATE_SET_SOURCE",
                "candidate_set_source is not the Task 035 identifier: "
                f"{candidate_set['candidate_set_source']!r}",
            )
        if candidate_set["candidate_order_preserved"] is not True:
            raise DecisionInputBundleContractError(
                "UPSTREAM_ORDER_NOT_PRESERVED",
                "candidate_set.candidate_order_preserved must be True",
            )
        if candidate_set["candidate_set_complete"] != candidate_set["available"]:
            raise DecisionInputBundleContractError(
                "CANDIDATE_SET_COMPLETE_MISMATCH",
                "candidate_set_complete does not match available: "
                f"{candidate_set['candidate_set_complete']!r} != "
                f"{candidate_set['available']!r}",
            )
        return candidate_set

    @staticmethod
    def _validate_assessment_set(
        assessment_set: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if assessment_set is None:
            raise DecisionInputBundleContractError(
                "MISSING_ASSESSMENT_SET", "assessment_set is required"
            )
        if not isinstance(assessment_set, Mapping):
            raise DecisionInputBundleContractError(
                "ASSESSMENT_SET_TYPE",
                f"assessment_set is not a mapping: "
                f"{type(assessment_set).__name__}",
            )
        for field in _ASSESSMENT_SET_REQUIRED_FIELDS:
            if field not in assessment_set:
                raise DecisionInputBundleContractError(
                    "MISSING_ASSESSMENT_SET_FIELD",
                    f"assessment_set has no {field}",
                )
        for field in _ASSESSMENT_SET_BOOLEAN_FIELDS:
            if not isinstance(assessment_set[field], bool):
                raise DecisionInputBundleContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {assessment_set[field]!r}",
                )
        count = assessment_set["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionInputBundleContractError(
                "ASSESSMENT_SET_COUNT_TYPE",
                f"candidate_count is not an int: {count!r}",
            )
        if count < 0:
            raise DecisionInputBundleContractError(
                "ASSESSMENT_SET_COUNT_NEGATIVE",
                f"candidate_count is negative: {count!r}",
            )
        assessments = assessment_set["assessments"]
        if not isinstance(assessments, list):
            raise DecisionInputBundleContractError(
                "ASSESSMENTS_TYPE",
                f"assessments is not a list: {type(assessments).__name__}",
            )
        if count != len(assessments):
            raise DecisionInputBundleContractError(
                "ASSESSMENT_SET_COUNT_MISMATCH",
                f"candidate_count {count} != len(assessments) "
                f"{len(assessments)}",
            )
        for entry in assessments:
            if not isinstance(entry, Mapping):
                raise DecisionInputBundleContractError(
                    "MALFORMED_ASSESSMENT",
                    f"assessment is not a mapping: {type(entry).__name__}",
                )
            for field in _CANDIDATE_FIELDS:
                if field not in entry:
                    raise DecisionInputBundleContractError(
                        "MISSING_ASSESSMENT_FIELD",
                        f"assessment has no {field}",
                    )
        if assessment_set["assessment_source"] != _ASSESSMENT_SET_SOURCE:
            raise DecisionInputBundleContractError(
                "INVALID_ASSESSMENT_SET_SOURCE",
                "assessment_source is not the Task 036 identifier: "
                f"{assessment_set['assessment_source']!r}",
            )
        if assessment_set["candidate_order_preserved"] is not True:
            raise DecisionInputBundleContractError(
                "ASSESSMENT_ORDER_NOT_PRESERVED",
                "assessment_set.candidate_order_preserved must be True",
            )
        if assessment_set["available"]:
            if not assessment_set["evaluation_coverage_complete"]:
                raise DecisionInputBundleContractError(
                    "ASSESSMENT_AVAILABILITY_INCONSISTENT",
                    "assessment_set.available is True but "
                    "evaluation_coverage_complete is False",
                )
            if not assessment_set["assessment_structure_consistent"]:
                raise DecisionInputBundleContractError(
                    "ASSESSMENT_AVAILABILITY_INCONSISTENT",
                    "assessment_set.available is True but "
                    "assessment_structure_consistent is False",
                )
        return assessment_set

    @staticmethod
    def _check_alignment(
        candidate_set: Mapping[str, Any],
        assessment_set: Mapping[str, Any],
    ) -> bool:
        cs_available = candidate_set["available"]
        as_available = assessment_set["available"]
        if not cs_available and not as_available:
            return True
        if cs_available != as_available:
            return False
        candidates = candidate_set["candidates"]
        assessments = assessment_set["assessments"]
        if len(candidates) != len(assessments):
            raise DecisionInputBundleContractError(
                "CANDIDATE_COUNT_MISMATCH",
                f"candidate count {len(candidates)} != assessment count "
                f"{len(assessments)}",
            )
        for i, (c, a) in enumerate(
            zip(candidates, assessments, strict=True)
        ):
            if c["hypothesis_id"] != a["hypothesis_id"]:
                raise DecisionInputBundleContractError(
                    "ID_MISMATCH", f"position {i}: hypothesis_id differs"
                )
            if c["hypothesis_name"] != a["hypothesis_name"]:
                raise DecisionInputBundleContractError(
                    "NAME_MISMATCH", f"position {i}: hypothesis_name differs"
                )
            if c["rank"] != a["rank"]:
                raise DecisionInputBundleContractError(
                    "RANK_MISMATCH", f"position {i}: rank differs"
                )
            if c["score"] != a["score"]:
                raise DecisionInputBundleContractError(
                    "SCORE_MISMATCH", f"position {i}: score differs"
                )
            if c["is_tied"] != a["is_tied"]:
                raise DecisionInputBundleContractError(
                    "IS_TIED_MISMATCH", f"position {i}: is_tied differs"
                )
            if c["tie_group_size"] != a["tie_group_size"]:
                raise DecisionInputBundleContractError(
                    "TIE_GROUP_SIZE_MISMATCH",
                    f"position {i}: tie_group_size differs",
                )
            if c["score_gap_to_next_higher"] != a["score_gap_to_next_higher"]:
                raise DecisionInputBundleContractError(
                    "GAP_HIGHER_MISMATCH",
                    f"position {i}: score_gap_to_next_higher differs",
                )
            if c["score_gap_to_next_lower"] != a["score_gap_to_next_lower"]:
                raise DecisionInputBundleContractError(
                    "GAP_LOWER_MISMATCH",
                    f"position {i}: score_gap_to_next_lower differs",
                )
        return True

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        candidate_set: Mapping[str, Any],
        assessment_set: Mapping[str, Any],
    ) -> None:
        for field in (
            "available",
            "candidate_order_preserved",
            "candidate_assessment_alignment_complete",
            "input_structure_consistent",
        ):
            if not isinstance(result[field], bool):
                raise DecisionInputBundleContractError(
                    "RESULT_FIELD_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )
        count = result["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionInputBundleContractError(
                "RESULT_COUNT_TYPE", f"count is not int: {count!r}"
            )
        if count < 0:
            raise DecisionInputBundleContractError(
                "RESULT_COUNT_NEGATIVE", f"count is negative: {count!r}"
            )
        if not isinstance(result["candidate_set"], Mapping):
            raise DecisionInputBundleContractError(
                "RESULT_CANDIDATE_SET_TYPE",
                f"candidate_set is not a mapping: "
                f"{type(result['candidate_set']).__name__}",
            )
        if not isinstance(result["assessment_set"], Mapping):
            raise DecisionInputBundleContractError(
                "RESULT_ASSESSMENT_SET_TYPE",
                f"assessment_set is not a mapping: "
                f"{type(result['assessment_set']).__name__}",
            )
        if (
            result["candidate_order_preserved"]
            != candidate_set["candidate_order_preserved"]
        ):
            raise DecisionInputBundleContractError(
                "RESULT_ORDER_MISMATCH",
                "candidate_order_preserved does not match upstream: "
                f"{result['candidate_order_preserved']!r} != "
                f"{candidate_set['candidate_order_preserved']!r}",
            )
        expected_available = (
            candidate_set["available"]
            and assessment_set["available"]
            and result["candidate_assessment_alignment_complete"]
            and result["input_structure_consistent"]
        )
        if result["available"] != expected_available:
            raise DecisionInputBundleContractError(
                "RESULT_AVAILABLE_MISMATCH",
                "available does not match the recomputed packaging rule: "
                f"{result['available']!r} != {expected_available!r}",
            )
        if result["available"]:
            if count != len(candidate_set["candidates"]):
                raise DecisionInputBundleContractError(
                    "RESULT_COUNT_MISMATCH",
                    f"count {count} != candidate count "
                    f"{len(candidate_set['candidates'])}",
                )
            if count != len(assessment_set["assessments"]):
                raise DecisionInputBundleContractError(
                    "RESULT_COUNT_MISMATCH",
                    f"count {count} != assessment count "
                    f"{len(assessment_set['assessments'])}",
                )
        if (
            result["input_source"]
            != INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037
        ):
            raise DecisionInputBundleContractError(
                "INVALID_INPUT_SOURCE",
                "input_source is not the Task 037 identifier: "
                f"{result['input_source']!r}",
            )

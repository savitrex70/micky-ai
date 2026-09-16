from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_context import DecisionContextService
from rop.services.evidence_aggregation import (
    CONSISTENCY_CONTRADICTION_ONLY,
    CONSISTENCY_MIXED,
    CONSISTENCY_NO_EVIDENCE,
)

_CONTRADICTING_EVIDENCE_CONSISTENCY_VALUES = frozenset(
    {CONSISTENCY_CONTRADICTION_ONLY, CONSISTENCY_MIXED}
)
"""Task 022 ``evidence_consistency`` values that mean contradicting
evidence is present, independent of ``total_contradiction_contribution``.

Task 022 already separates *whether* contradicting evidence exists
(``has_contradicting_evidence`` / ``contradicting_evidence_count``) from
*how much* it contributes (``total_contradiction_contribution``):
contradicting evidence can exist with zero contribution, and zero
contribution does not imply zero contradicting evidence. The
``evidence_consistency`` classification (which is derived from the
count, not the contribution total, and is the field that actually
survives into the Task 031 decision context) is the correct signal for
this criterion.
"""

EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032 = (
    "DECISION_CANDIDATE_EVALUATION_TASK_032"
)
"""Fixed structural-contract identifier for Task 032 evaluations.

Names *which* contract produced the evaluation. It is not a score, a
probability, a confidence, or a recommendation, and it never changes
per candidate or per criterion.
"""

_REQUIRED_RANKED_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "evidence_consistency",
    "total_support_contribution",
    "total_contradiction_contribution",
    "evidence_coverage_ratio",
    "is_tied",
    "tie_group_size",
)

_REQUIRED_CONTEXT_FIELDS = (
    "differential",
    "differential_summary",
    "differential_consistency",
    "decision_readiness",
)

_CRITERION_RESULT_FIELDS = (
    "criterion_id",
    "criterion_name",
    "satisfied",
    "required",
    "reason",
)


class CriterionType(StrEnum):
    """Task 032: the constrained set of supported criterion types.

    Deliberately closed — no speculative types are added ahead of a
    demonstrated need.
    """

    SUPPORT = "SUPPORT"
    CONTRADICTION = "CONTRADICTION"
    EVIDENCE_COVERAGE = "EVIDENCE_COVERAGE"
    CONSISTENCY = "CONSISTENCY"
    SEPARATION = "SEPARATION"
    READINESS = "READINESS"


@dataclass(frozen=True)
class DecisionCriterion:
    """Task 032: a typed, immutable decision-evaluation criterion definition.

    Criteria are declared once, in ``DEFAULT_CRITERIA`` below, and
    never accepted from a caller or the API — Task 032 does not allow
    arbitrary criteria injection yet.
    """

    criterion_id: str
    name: str
    description: str
    criterion_type: CriterionType
    required: bool
    source: str = EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032


DEFAULT_CRITERIA: tuple[DecisionCriterion, ...] = (
    DecisionCriterion(
        criterion_id="support",
        name="Supporting evidence present",
        description=(
            "Satisfied when the candidate has positive supporting evidence "
            "according to the Task 031 decision context."
        ),
        criterion_type=CriterionType.SUPPORT,
        required=True,
    ),
    DecisionCriterion(
        criterion_id="contradiction",
        name="No contradiction present",
        description=(
            "Satisfied when the candidate has no contradiction conflict "
            "according to the Task 031 decision context."
        ),
        criterion_type=CriterionType.CONTRADICTION,
        required=True,
    ),
    DecisionCriterion(
        criterion_id="evidence_coverage",
        name="Evidence coverage",
        description=(
            "Satisfied according to the existing evidence-coverage ratio "
            "already computed upstream; introduces no new formula."
        ),
        criterion_type=CriterionType.EVIDENCE_COVERAGE,
        required=False,
    ),
    DecisionCriterion(
        criterion_id="consistency",
        name="Differential consistency verified",
        description=(
            "Satisfied only when the Task 029 differential-consistency "
            "result reports the differential as consistent."
        ),
        criterion_type=CriterionType.CONSISTENCY,
        required=True,
    ),
    DecisionCriterion(
        criterion_id="separation",
        name="Score separation from other candidates",
        description=(
            "Descriptive only: satisfied when the candidate's score is not "
            "tied with any other candidate's score, per the Task 027 "
            "separation metadata. Never implies a separated candidate is "
            "the winner."
        ),
        criterion_type=CriterionType.SEPARATION,
        required=False,
    ),
    DecisionCriterion(
        criterion_id="readiness",
        name="Decision readiness",
        description=(
            "Reflects the Task 030 decision-readiness verdict verbatim; "
            "never independently redefines readiness."
        ),
        criterion_type=CriterionType.READINESS,
        required=True,
    ),
)

_DEFAULT_CRITERION_IDS = frozenset(c.criterion_id for c in DEFAULT_CRITERIA)


class DecisionCandidateEvaluationContractError(Exception):
    """Task 032: malformed or internally contradictory evaluation data.

    Raised for a missing/malformed Task 031 decision context, a
    malformed criterion result, a duplicate criterion or candidate id,
    an invalid boolean/integer field, or a count that does not match
    what was actually evaluated. Like the Task 025-031 contract errors,
    this must never be exposed verbatim to API clients; the API layer
    converts it to a generic 500.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionCandidateEvaluationService:
    """Task 032: deterministic, auditable candidate evaluation layer.

    Consumes the Task 031 ``DecisionContext`` exclusively — it never
    reaches directly into evidence, scoring, or ranking services, and
    duplicates no logic already owned by Tasks 020-031. For each
    candidate in the context's differential, every declared criterion
    in ``DEFAULT_CRITERIA`` is evaluated deterministically against the
    context's already-validated fields.

    This answers "how does each candidate perform against the defined
    decision criteria?" — never "which candidate is correct?". There is
    no winner, selected candidate, decision, diagnosis, probability, or
    weighted/utility score anywhere in this service. Read-only
    throughout: nothing is persisted, and the context is defensively
    deep-copied rather than mutated in place.
    """

    def __init__(
        self,
        decision_context_service: DecisionContextService | None = None,
    ) -> None:
        self.decision_context_service = (
            decision_context_service or DecisionContextService()
        )

    def evaluate_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> list[dict[str, Any]]:
        """Build the Task 031 decision context and evaluate every candidate.

        Walks the established dependency chain rather than bypassing
        it: the decision context comes from ``DecisionContextService``,
        which in turn walks Tasks 027-030. Read-only: no database
        writes, no persistence.
        """
        context = self.decision_context_service.build_for_session(
            db, session_id, candidates
        )
        return self.evaluate(context)

    def evaluate(self, context: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        """Evaluate every candidate in an already-built decision context.

        Kept separate from ``evaluate_session`` so evaluation can be
        exercised directly against a hand-built ``DecisionContext``,
        without going through the full pipeline. Never mutates
        ``context`` or anything nested inside it.
        """
        self._validate_context_presence(context)

        differential = copy.deepcopy(context["differential"])  # type: ignore[index]
        summary = copy.deepcopy(dict(context["differential_summary"]))  # type: ignore[index]
        consistency = copy.deepcopy(dict(context["differential_consistency"]))  # type: ignore[index]
        readiness = copy.deepcopy(dict(context["decision_readiness"]))  # type: ignore[index]

        results = [
            self._evaluate_candidate(entry, summary, consistency, readiness)
            for entry in differential
        ]

        self._validate_output(results)
        return results

    # ------------------------------------------------------------------
    # Per-candidate evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_candidate(
        entry: Mapping[str, Any],
        summary: Mapping[str, Any],
        consistency: Mapping[str, Any],
        readiness: Mapping[str, Any],
    ) -> dict[str, Any]:
        criteria_results = [
            DecisionCandidateEvaluationService._evaluate_criterion(
                criterion, entry, summary, consistency, readiness
            )
            for criterion in DEFAULT_CRITERIA
        ]

        criteria_satisfied = sum(1 for c in criteria_results if c["satisfied"])
        criteria_unsatisfied = len(criteria_results) - criteria_satisfied

        required_results = [c for c in criteria_results if c["required"]]
        required_satisfied = sum(1 for c in required_results if c["satisfied"])
        required_unsatisfied = len(required_results) - required_satisfied

        return {
            "hypothesis_id": entry["hypothesis_id"],
            "hypothesis_name": entry["hypothesis_name"],
            "criteria": criteria_results,
            "criterion_count": len(criteria_results),
            "criteria_satisfied": criteria_satisfied,
            "criteria_unsatisfied": criteria_unsatisfied,
            "required_criteria_satisfied": required_satisfied,
            "required_criteria_unsatisfied": required_unsatisfied,
            "evaluation_complete": len(criteria_results) == len(DEFAULT_CRITERIA),
            "evaluation_source": (
                EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032
            ),
        }

    @staticmethod
    def _evaluate_criterion(
        criterion: DecisionCriterion,
        entry: Mapping[str, Any],
        summary: Mapping[str, Any],
        consistency: Mapping[str, Any],
        readiness: Mapping[str, Any],
    ) -> dict[str, Any]:
        evaluators = {
            CriterionType.SUPPORT: DecisionCandidateEvaluationService._evaluate_support,
            CriterionType.CONTRADICTION: (
                DecisionCandidateEvaluationService._evaluate_contradiction
            ),
            CriterionType.EVIDENCE_COVERAGE: (
                DecisionCandidateEvaluationService._evaluate_evidence_coverage
            ),
        }

        if criterion.criterion_type in evaluators:
            satisfied, reason = evaluators[criterion.criterion_type](entry)
        elif criterion.criterion_type is CriterionType.CONSISTENCY:
            satisfied, reason = (
                DecisionCandidateEvaluationService._evaluate_consistency(consistency)
            )
        elif criterion.criterion_type is CriterionType.SEPARATION:
            satisfied, reason = DecisionCandidateEvaluationService._evaluate_separation(
                entry
            )
        elif criterion.criterion_type is CriterionType.READINESS:
            satisfied, reason = DecisionCandidateEvaluationService._evaluate_readiness(
                readiness
            )
        else:  # pragma: no cover - CriterionType is a constrained enum
            raise DecisionCandidateEvaluationContractError(
                "UNKNOWN_CRITERION_TYPE",
                f"unrecognized criterion type: {criterion.criterion_type!r}",
            )

        return {
            "criterion_id": criterion.criterion_id,
            "criterion_name": criterion.name,
            "satisfied": satisfied,
            "required": criterion.required,
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # Criterion semantics — each reads only already-approved context
    # fields and fabricates nothing.
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_support(entry: Mapping[str, Any]) -> tuple[bool, str]:
        if entry.get("evidence_consistency") == CONSISTENCY_NO_EVIDENCE:
            return False, (
                "criterion could not be established from the available "
                "context: no evidence has been evaluated for this candidate"
            )
        total_support = entry.get("total_support_contribution", 0.0)
        if total_support > 0:
            return True, (
                "positive supporting evidence contribution recorded "
                f"(total_support_contribution={total_support})"
            )
        return False, (
            "no positive supporting evidence contribution recorded "
            f"(total_support_contribution={total_support})"
        )

    @staticmethod
    def _evaluate_contradiction(entry: Mapping[str, Any]) -> tuple[bool, str]:
        evidence_consistency = entry.get("evidence_consistency")
        if evidence_consistency == CONSISTENCY_NO_EVIDENCE:
            # Missing information must never be silently treated as
            # support (i.e. as a confirmed absence of contradiction).
            return False, (
                "criterion could not be established from the available "
                "context: no evidence has been evaluated for this candidate"
            )
        # Task 022 distinguishes whether contradicting evidence exists
        # from its contribution magnitude: contradicting evidence can
        # exist with zero contribution, and zero contribution does not
        # imply zero contradicting evidence. So this criterion is
        # decided from the evidence-consistency classification, not
        # from ``total_contradiction_contribution``.
        if evidence_consistency in _CONTRADICTING_EVIDENCE_CONSISTENCY_VALUES:
            return False, (
                "contradicting evidence is present according to the "
                "Task 022 evidence-consistency classification "
                f"(evidence_consistency={evidence_consistency})"
            )
        return True, (
            "no contradicting evidence is present according to the "
            "Task 022 evidence-consistency classification "
            f"(evidence_consistency={evidence_consistency})"
        )

    @staticmethod
    def _evaluate_evidence_coverage(entry: Mapping[str, Any]) -> tuple[bool, str]:
        coverage_ratio = entry.get("evidence_coverage_ratio", 0.0)
        if coverage_ratio > 0:
            return True, f"evidence coverage ratio is {coverage_ratio}"
        return False, (
            f"evidence coverage ratio is {coverage_ratio}; no evidence has "
            "been evaluated for this candidate"
        )

    @staticmethod
    def _evaluate_consistency(consistency: Mapping[str, Any]) -> tuple[bool, str]:
        if consistency.get("consistent") is True:
            return True, (
                "the Task 029 differential-consistency result reports the "
                "differential as consistent"
            )
        return False, (
            "the Task 029 differential-consistency result reports the "
            "differential as not consistent"
        )

    @staticmethod
    def _evaluate_separation(entry: Mapping[str, Any]) -> tuple[bool, str]:
        is_tied = entry.get("is_tied")
        tie_group_size = entry.get("tie_group_size", 1)
        if is_tied is False:
            return True, (
                "this candidate's score is not tied with any other "
                f"candidate (tie_group_size={tie_group_size})"
            )
        other_tied = max(tie_group_size - 1, 0)
        return False, (
            f"this candidate is tied with {other_tied} other candidate(s) "
            "at the same score"
        )

    @staticmethod
    def _evaluate_readiness(readiness: Mapping[str, Any]) -> tuple[bool, str]:
        if readiness.get("ready") is True:
            return True, (
                "the Task 030 decision-readiness result reports the "
                "differential as ready"
            )
        return False, (
            "the Task 030 decision-readiness result reports the "
            "differential as not ready"
        )

    # ------------------------------------------------------------------
    # Input contract: the Task 031 DecisionContext
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_context_presence(context: Mapping[str, Any] | None) -> None:
        if context is None:
            raise DecisionCandidateEvaluationContractError(
                "MISSING_CONTEXT", "decision context is required"
            )
        if not isinstance(context, Mapping):
            raise DecisionCandidateEvaluationContractError(
                "CONTEXT_TYPE",
                f"decision context is not a mapping: {type(context).__name__}",
            )
        for field in _REQUIRED_CONTEXT_FIELDS:
            if field not in context:
                raise DecisionCandidateEvaluationContractError(
                    "MISSING_CONTEXT_FIELD", f"decision context has no {field}"
                )

        differential = context["differential"]
        if differential is None or not isinstance(differential, list):
            raise DecisionCandidateEvaluationContractError(
                "DIFFERENTIAL_TYPE",
                f"differential is not a list: {type(differential).__name__}",
            )
        for entry in differential:
            if not isinstance(entry, Mapping):
                raise DecisionCandidateEvaluationContractError(
                    "RANKED_ENTRY_TYPE",
                    f"ranked entry is not a mapping: {type(entry).__name__}",
                )
            for field in _REQUIRED_RANKED_FIELDS:
                if field not in entry:
                    raise DecisionCandidateEvaluationContractError(
                        "MISSING_RANKED_FIELD", f"ranked entry has no {field}"
                    )

        summary = context["differential_summary"]
        if not isinstance(summary, Mapping):
            raise DecisionCandidateEvaluationContractError(
                "SUMMARY_TYPE",
                f"differential_summary is not a mapping: {type(summary).__name__}",
            )

        consistency = context["differential_consistency"]
        if not isinstance(consistency, Mapping) or "consistent" not in consistency:
            raise DecisionCandidateEvaluationContractError(
                "MISSING_CONSISTENCY_FIELD",
                "differential_consistency has no consistent field",
            )

        readiness = context["decision_readiness"]
        if not isinstance(readiness, Mapping) or "ready" not in readiness:
            raise DecisionCandidateEvaluationContractError(
                "MISSING_READINESS_FIELD", "decision_readiness has no ready field"
            )

    # ------------------------------------------------------------------
    # Output contract: the evaluation results themselves
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_output(results: list[dict[str, Any]]) -> None:
        """Verify the assembled evaluation output invariants.

        Never repairs a value; raises
        ``DecisionCandidateEvaluationContractError`` naming the
        violated invariant. Checks, per candidate: every criterion
        result has all required fields and no duplicate criterion id;
        ``satisfied``/``required`` are actual booleans; every count
        field is an actual int and matches what was actually computed
        from the criteria list; ``evaluation_complete`` matches whether
        every declared default criterion was evaluated exactly once;
        ``evaluation_source`` is the exact Task 032 identifier. Across
        candidates: no duplicate ``hypothesis_id``.
        """
        seen_candidate_ids: set[Any] = set()

        for candidate in results:
            hypothesis_id = candidate.get("hypothesis_id")
            if hypothesis_id in seen_candidate_ids:
                raise DecisionCandidateEvaluationContractError(
                    "DUPLICATE_CANDIDATE_ID",
                    f"duplicate hypothesis_id: {hypothesis_id!r}",
                )
            seen_candidate_ids.add(hypothesis_id)

            criteria = candidate.get("criteria")
            if criteria is None or not isinstance(criteria, list):
                raise DecisionCandidateEvaluationContractError(
                    "MISSING_CRITERIA", "candidate evaluation has no criteria list"
                )

            seen_criterion_ids: set[Any] = set()
            satisfied_count = 0
            required_total = 0
            required_satisfied_count = 0

            for criterion_result in criteria:
                if not isinstance(criterion_result, Mapping):
                    raise DecisionCandidateEvaluationContractError(
                        "MALFORMED_CRITERION",
                        f"criterion result is not a mapping: "
                        f"{type(criterion_result).__name__}",
                    )
                for field in _CRITERION_RESULT_FIELDS:
                    if field not in criterion_result:
                        raise DecisionCandidateEvaluationContractError(
                            "MISSING_CRITERION_FIELD",
                            f"criterion result has no {field}",
                        )

                criterion_id = criterion_result["criterion_id"]
                if criterion_id in seen_criterion_ids:
                    raise DecisionCandidateEvaluationContractError(
                        "DUPLICATE_CRITERION_ID",
                        f"duplicate criterion_id: {criterion_id!r}",
                    )
                seen_criterion_ids.add(criterion_id)

                satisfied = criterion_result["satisfied"]
                required = criterion_result["required"]
                if not isinstance(satisfied, bool):
                    raise DecisionCandidateEvaluationContractError(
                        "SATISFIED_TYPE", f"satisfied is not boolean: {satisfied!r}"
                    )
                if not isinstance(required, bool):
                    raise DecisionCandidateEvaluationContractError(
                        "REQUIRED_TYPE", f"required is not boolean: {required!r}"
                    )

                if satisfied:
                    satisfied_count += 1
                if required:
                    required_total += 1
                    if satisfied:
                        required_satisfied_count += 1

            criterion_count = candidate.get("criterion_count")
            DecisionCandidateEvaluationService._require_int(
                criterion_count, "criterion_count"
            )
            if criterion_count != len(criteria):
                raise DecisionCandidateEvaluationContractError(
                    "CRITERION_COUNT_MISMATCH",
                    f"criterion_count ({criterion_count}) != "
                    f"len(criteria) ({len(criteria)})",
                )

            criteria_satisfied = candidate.get("criteria_satisfied")
            criteria_unsatisfied = candidate.get("criteria_unsatisfied")
            required_criteria_satisfied = candidate.get("required_criteria_satisfied")
            required_criteria_unsatisfied = candidate.get(
                "required_criteria_unsatisfied"
            )
            for name, value in (
                ("criteria_satisfied", criteria_satisfied),
                ("criteria_unsatisfied", criteria_unsatisfied),
                ("required_criteria_satisfied", required_criteria_satisfied),
                ("required_criteria_unsatisfied", required_criteria_unsatisfied),
            ):
                DecisionCandidateEvaluationService._require_int(value, name)

            if criteria_satisfied != satisfied_count:
                raise DecisionCandidateEvaluationContractError(
                    "SATISFIED_COUNT_MISMATCH",
                    f"criteria_satisfied ({criteria_satisfied}) does not match "
                    f"the number of satisfied criteria ({satisfied_count})",
                )
            if criteria_unsatisfied != criterion_count - satisfied_count:
                raise DecisionCandidateEvaluationContractError(
                    "UNSATISFIED_COUNT_MISMATCH",
                    f"criteria_unsatisfied ({criteria_unsatisfied}) does not "
                    f"match criterion_count - criteria_satisfied "
                    f"({criterion_count - satisfied_count})",
                )
            if required_criteria_satisfied != required_satisfied_count:
                raise DecisionCandidateEvaluationContractError(
                    "REQUIRED_SATISFIED_MISMATCH",
                    f"required_criteria_satisfied "
                    f"({required_criteria_satisfied}) does not match the "
                    f"number of satisfied required criteria "
                    f"({required_satisfied_count})",
                )
            if required_criteria_unsatisfied != (
                required_total - required_satisfied_count
            ):
                raise DecisionCandidateEvaluationContractError(
                    "REQUIRED_UNSATISFIED_MISMATCH",
                    f"required_criteria_unsatisfied "
                    f"({required_criteria_unsatisfied}) does not match "
                    f"required_total - required_satisfied "
                    f"({required_total - required_satisfied_count})",
                )

            evaluation_complete = candidate.get("evaluation_complete")
            if not isinstance(evaluation_complete, bool):
                raise DecisionCandidateEvaluationContractError(
                    "EVALUATION_COMPLETE_TYPE",
                    f"evaluation_complete is not boolean: {evaluation_complete!r}",
                )
            expected_complete = (
                criterion_count == len(DEFAULT_CRITERIA)
                and seen_criterion_ids == _DEFAULT_CRITERION_IDS
            )
            if evaluation_complete != expected_complete:
                raise DecisionCandidateEvaluationContractError(
                    "EVALUATION_COMPLETE_MISMATCH",
                    f"evaluation_complete ({evaluation_complete}) does not "
                    f"match its derivation ({expected_complete})",
                )

            source = candidate.get("evaluation_source")
            if source != EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032:
                raise DecisionCandidateEvaluationContractError(
                    "EVALUATION_SOURCE",
                    f"evaluation_source is not the Task 032 identifier: {source!r}",
                )

    @staticmethod
    def _require_int(value: Any, field_name: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise DecisionCandidateEvaluationContractError(
                f"{field_name.upper()}_TYPE",
                f"{field_name} is not an int: {value!r}",
            )

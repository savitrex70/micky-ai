from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_candidate_assessment import (
    ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036,
    DecisionCandidateAssessmentService,
)
from rop.services.decision_candidate_evaluation import (
    EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032,
    DecisionCandidateEvaluationService,
)
from rop.services.decision_candidate_set import (
    CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035,
    DecisionCandidateSetService,
)
from rop.services.decision_context import (
    CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031,
    DecisionContextService,
)
from rop.services.decision_evaluation_consistency import (
    CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033,
    DecisionEvaluationConsistencyService,
)
from rop.services.decision_execution import (
    DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039,
    DecisionExecutionService,
)
from rop.services.decision_execution_consistency import (
    DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040,
    DecisionExecutionConsistencyService,
)
from rop.services.decision_input_bundle import (
    INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037,
    DecisionInputBundleService,
)
from rop.services.decision_input_eligibility import (
    ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
    DecisionInputEligibilityService,
)
from rop.services.decision_policy import (
    POLICY_SOURCE_DECISION_POLICY_TASK_038,
    DecisionPolicyService,
)

PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041 = "REASONING_PIPELINE_TASK_041"
"""Fixed structural-contract identifier for Task 041 results."""

_RESULT_FIELDS = (
    "available",
    "pipeline_consistent",
    "pipeline_complete",
    "stage_count",
    "completed_stage_count",
    "stages",
    "final_execution",
    "final_execution_consistency",
    "pipeline_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "pipeline_consistent",
    "pipeline_complete",
)

_RESULT_INTEGER_FIELDS = ("stage_count", "completed_stage_count")

_STAGE_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "available",
    "consistent",
    "complete",
)

_STAGE_BOOLEAN_FIELDS = ("available", "consistent", "complete")

_MAPPING_INPUTS = (
    "context",
    "consistency",
    "eligibility",
    "candidate_set",
    "assessment",
    "bundle",
    "policy",
    "execution",
    "audit",
)


class ReasoningPipelineContractError(Exception):
    """Task 041: malformed upstream result or internally inconsistent bundle.

    Raised only when one of the composed Task 031-040 results is not
    shaped like its own established contract, when Task 039's execution
    or Task 040's audit fails its own validator, or when Task 041's own
    assembled pipeline structure violates its own invariants. It is
    never raised for a valid downstream outcome -- INPUT_UNAVAILABLE
    and INPUT_INCONSISTENT are valid Task 039 outcomes and are
    represented faithfully through ``final_execution``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningPipelineService:
    """Task 041: deterministic end-to-end reasoning pipeline composition.

    Composes the established decision-pipeline boundaries (Tasks
    031-040) into one inspectable view. Walks the chain exactly once,
    calling each stage's own established service method -- the same
    single-pass walk the upstream boundaries already perform
    internally, extended here so that every intermediate result can be
    captured for the stage list. It introduces no new reasoning, no
    re-selection, no policy override, and no mutation of any upstream
    result.
    """

    def __init__(self) -> None:
        # Wire the chain exactly the way ``sessions.py`` wires it, so
        # Task 041 composes the same service instances downstream
        # callers would use.
        self.decision_context_service = DecisionContextService()
        self.decision_candidate_evaluation_service = (
            DecisionCandidateEvaluationService(self.decision_context_service)
        )
        self.decision_evaluation_consistency_service = (
            DecisionEvaluationConsistencyService(
                self.decision_candidate_evaluation_service
            )
        )
        self.decision_input_eligibility_service = (
            DecisionInputEligibilityService(
                self.decision_evaluation_consistency_service
            )
        )
        self.decision_candidate_set_service = DecisionCandidateSetService(
            self.decision_input_eligibility_service
        )
        self.decision_candidate_assessment_service = (
            DecisionCandidateAssessmentService(
                self.decision_candidate_set_service
            )
        )
        self.decision_input_bundle_service = DecisionInputBundleService(
            self.decision_candidate_set_service,
            self.decision_candidate_assessment_service,
        )
        self.decision_policy_service = DecisionPolicyService(
            self.decision_input_bundle_service
        )
        self.decision_execution_service = DecisionExecutionService(
            self.decision_input_bundle_service,
            self.decision_policy_service,
        )
        self.decision_execution_consistency_service = (
            DecisionExecutionConsistencyService(
                self.decision_input_bundle_service,
                self.decision_policy_service,
                self.decision_execution_service,
            )
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Walk the established chain exactly once, then compose.

        Each call below invokes the owning stage's own established
        service method -- no algorithm is reimplemented here. Capturing
        the intermediate results is what lets Task 041 expose a
        stage-by-stage view; no existing single boundary returns them
        all at once.
        """
        context = self.decision_context_service.build_for_session(
            db, session_id, candidates
        )
        expected_candidate_ids = [
            entry["hypothesis_id"] for entry in context["differential"]
        ]
        evaluations = self.decision_candidate_evaluation_service.evaluate(context)
        consistency = self.decision_evaluation_consistency_service.check(
            evaluations, expected_candidate_ids
        )
        eligibility = self.decision_input_eligibility_service.build(
            context, consistency
        )
        candidate_set = self.decision_candidate_set_service.build(
            context, eligibility
        )
        assessment = self.decision_candidate_assessment_service.build(
            candidate_set, evaluations, consistency
        )
        bundle = self.decision_input_bundle_service.build(
            candidate_set, assessment
        )
        policy = self.decision_policy_service.build()
        execution = self.decision_execution_service.build(bundle, policy)
        audit = self.decision_execution_consistency_service.build(
            bundle, policy, execution
        )
        return self.build(
            context=context,
            evaluations=evaluations,
            consistency=consistency,
            eligibility=eligibility,
            candidate_set=candidate_set,
            assessment=assessment,
            bundle=bundle,
            policy=policy,
            execution=execution,
            audit=audit,
        )


    def build(
        self,
        *,
        context: Mapping[str, Any] | None = None,
        evaluations: list[Mapping[str, Any]] | None = None,
        consistency: Mapping[str, Any] | None = None,
        eligibility: Mapping[str, Any] | None = None,
        candidate_set: Mapping[str, Any] | None = None,
        assessment: Mapping[str, Any] | None = None,
        bundle: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
        execution: Mapping[str, Any] | None = None,
        audit: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compose the stage list and pipeline-level flags. Pure.

        Each stage descriptor maps the corresponding upstream result's
        own established fields to Task 041's available/consistent/
        complete triple. No new semantics are invented.
        """
        inputs: dict[str, Any] = {
            "context": context,
            "evaluations": evaluations,
            "consistency": consistency,
            "eligibility": eligibility,
            "candidate_set": candidate_set,
            "assessment": assessment,
            "bundle": bundle,
            "policy": policy,
            "execution": execution,
            "audit": audit,
        }
        for name, value in inputs.items():
            if value is None:
                raise ReasoningPipelineContractError(
                    "MISSING_" + name.upper(), name + " is required"
                )
        if not isinstance(evaluations, list):
            raise ReasoningPipelineContractError(
                "EVALUATIONS_TYPE",
                "evaluations is not a list: " + type(evaluations).__name__,
            )
        for name in _MAPPING_INPUTS:
            if not isinstance(inputs[name], Mapping):
                raise ReasoningPipelineContractError(
                    name.upper() + "_TYPE",
                    name + " is not a mapping: " + type(inputs[name]).__name__,
                )

        # Every composed stage must carry its own established source
        # identifier -- Task 041 never substitutes its own identifier
        # for an upstream one, and it never accepts a wrong source.
        expected_sources: tuple[tuple[str, str, str], ...] = (
            ("context", "context_source", CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031),
            (
                "consistency",
                "consistency_source",
                CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033,
            ),
            (
                "eligibility",
                "eligibility_source",
                ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
            ),
            (
                "candidate_set",
                "candidate_set_source",
                CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035,
            ),
            (
                "assessment",
                "assessment_source",
                ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036,
            ),
            (
                "bundle",
                "input_source",
                INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037,
            ),
            (
                "policy",
                "policy_source",
                POLICY_SOURCE_DECISION_POLICY_TASK_038,
            ),
            (
                "execution",
                "decision_execution_source",
                DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039,
            ),
            (
                "audit",
                "execution_source",
                DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040,
            ),
        )
        for input_name, source_field, expected_source in expected_sources:
            container = inputs[input_name]
            actual = container.get(source_field)
            if actual != expected_source:
                raise ReasoningPipelineContractError(
                    "INVALID_" + input_name.upper() + "_SOURCE",
                    input_name + "." + source_field + " is not the "
                    "established identifier: " + repr(actual),
                )

        for entry in evaluations:
            if not isinstance(entry, Mapping):
                raise ReasoningPipelineContractError(
                    "EVALUATION_ENTRY_TYPE",
                    "evaluation entry is not a mapping: "
                    + type(entry).__name__,
                )
            entry_source = entry.get("evaluation_source")
            if (
                entry_source
                != EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032
            ):
                raise ReasoningPipelineContractError(
                    "INVALID_EVALUATION_SOURCE",
                    "evaluation_source is not the Task 032 identifier: "
                    + repr(entry_source),
                )

        def _f(container: Mapping[str, Any], key: str, label: str) -> Any:
            if key not in container:
                raise ReasoningPipelineContractError(
                    "MISSING_" + label.upper() + "_" + key.upper(),
                    label + " has no " + key,
                )
            return container[key]

        stages = [
            self._make_stage(
                "031_DECISION_CONTEXT",
                1,
                CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031,
                _f(context, "context_available", "context"),
                _f(context, "consistency_verified", "context"),
                True,
            ),
            self._make_stage(
                "032_DECISION_CANDIDATE_EVALUATION",
                2,
                EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032,
                True,
                True,
                all(
                    _f(e, "evaluation_complete", "evaluation")
                    for e in evaluations
                ),
            ),
            self._make_stage(
                "033_DECISION_EVALUATION_CONSISTENCY",
                3,
                CONSISTENCY_SOURCE_DECISION_EVALUATION_CONSISTENCY_TASK_033,
                True,
                _f(consistency, "consistent", "consistency"),
                (
                    _f(consistency, "all_candidates_evaluated", "consistency")
                    and _f(consistency, "all_criteria_evaluated", "consistency")
                ),
            ),
            self._make_stage(
                "034_DECISION_INPUT_ELIGIBILITY",
                4,
                ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
                True,
                _f(eligibility, "evaluation_consistent", "eligibility"),
                True,
            ),
            self._make_stage(
                "035_DECISION_CANDIDATE_SET",
                5,
                CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035,
                _f(candidate_set, "available", "candidate_set"),
                _f(candidate_set, "candidate_order_preserved", "candidate_set"),
                _f(candidate_set, "candidate_set_complete", "candidate_set"),
            ),
            self._make_stage(
                "036_DECISION_CANDIDATE_ASSESSMENT",
                6,
                ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036,
                _f(assessment, "available", "assessment"),
                _f(assessment, "assessment_structure_consistent", "assessment"),
                _f(assessment, "evaluation_coverage_complete", "assessment"),
            ),
            self._make_stage(
                "037_DECISION_INPUT_BUNDLE",
                7,
                INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037,
                _f(bundle, "available", "bundle"),
                _f(bundle, "input_structure_consistent", "bundle"),
                _f(bundle, "candidate_assessment_alignment_complete", "bundle"),
            ),
            self._make_stage(
                "038_DECISION_POLICY",
                8,
                POLICY_SOURCE_DECISION_POLICY_TASK_038,
                True,
                True,
                True,
            ),
            self._make_stage(
                "039_DECISION_EXECUTION",
                9,
                DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039,
                _f(execution, "available", "execution"),
                True,
                True,
            ),
            self._make_stage(
                "040_DECISION_EXECUTION_CONSISTENCY",
                10,
                DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040,
                _f(audit, "available", "audit"),
                _f(audit, "execution_consistent", "audit"),
                True,
            ),
        ]

        stage_count = len(stages)
        completed_stage_count = sum(1 for s in stages if s["complete"])
        pipeline_complete = all(s["complete"] for s in stages)
        pipeline_consistent = all(s["consistent"] for s in stages)

        result: dict[str, Any] = {
            "available": True,
            "pipeline_consistent": pipeline_consistent,
            "pipeline_complete": pipeline_complete,
            "stage_count": stage_count,
            "completed_stage_count": completed_stage_count,
            "stages": stages,
            "final_execution": dict(execution),
            "final_execution_consistency": dict(audit),
            "pipeline_source": PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041,
        }
        self._validate_result(result, bundle, policy)
        return result


    @staticmethod
    def _make_stage(
        stage_id: str,
        stage_order: int,
        stage_source: str,
        available: Any,
        consistent: Any,
        complete: Any,
    ) -> dict[str, Any]:
        for name, value in (
            ("available", available),
            ("consistent", consistent),
            ("complete", complete),
        ):
            if not isinstance(value, bool):
                raise ReasoningPipelineContractError(
                    "STAGE_" + name.upper() + "_TYPE",
                    stage_id + "." + name + " is not boolean: " + repr(value),
                )
        return {
            "stage_id": stage_id,
            "stage_order": stage_order,
            "stage_source": stage_source,
            "available": available,
            "consistent": consistent,
            "complete": complete,
        }

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        bundle: Mapping[str, Any],
        policy: Mapping[str, Any],
    ) -> None:
        for field in _RESULT_FIELDS:
            if field not in result:
                raise ReasoningPipelineContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningPipelineContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        for field in _RESULT_INTEGER_FIELDS:
            value = result[field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise ReasoningPipelineContractError(
                    field.upper() + "_TYPE",
                    field + " is not an int: " + repr(value),
                )
            if value < 0:
                raise ReasoningPipelineContractError(
                    field.upper() + "_NEGATIVE",
                    field + " is negative: " + repr(value),
                )
        if result["completed_stage_count"] > result["stage_count"]:
            raise ReasoningPipelineContractError(
                "COMPLETED_EXCEEDS_TOTAL",
                "completed_stage_count exceeds stage_count",
            )

        stages = result["stages"]
        if not isinstance(stages, list):
            raise ReasoningPipelineContractError(
                "STAGES_TYPE",
                "stages is not a list: " + type(stages).__name__,
            )
        if result["stage_count"] != len(stages):
            raise ReasoningPipelineContractError(
                "STAGE_COUNT_MISMATCH",
                "stage_count " + repr(result["stage_count"])
                + " != len(stages) " + repr(len(stages)),
            )
        seen_ids: set[str] = set()
        expected_order = 1
        for s in stages:
            if not isinstance(s, Mapping):
                raise ReasoningPipelineContractError(
                    "STAGE_TYPE",
                    "stage is not a mapping: " + type(s).__name__,
                )
            for field in _STAGE_FIELDS:
                if field not in s:
                    raise ReasoningPipelineContractError(
                        "MISSING_STAGE_FIELD", "stage has no " + field
                    )
            if not isinstance(s["stage_id"], str) or not s["stage_id"]:
                raise ReasoningPipelineContractError(
                    "STAGE_ID_TYPE",
                    "stage_id is not a non-empty string: " + repr(s["stage_id"]),
                )
            if not isinstance(s["stage_source"], str) or not s["stage_source"]:
                raise ReasoningPipelineContractError(
                    "STAGE_SOURCE_TYPE",
                    "stage_source is not a non-empty string: "
                    + repr(s["stage_source"]),
                )
            if s["stage_id"] in seen_ids:
                raise ReasoningPipelineContractError(
                    "DUPLICATE_STAGE_ID",
                    "duplicate stage_id: " + s["stage_id"],
                )
            seen_ids.add(s["stage_id"])
            if s["stage_order"] != expected_order:
                raise ReasoningPipelineContractError(
                    "STAGE_ORDER_MISMATCH",
                    "stage_order " + repr(s["stage_order"])
                    + " != expected " + repr(expected_order),
                )
            expected_order += 1
            for field in _STAGE_BOOLEAN_FIELDS:
                if not isinstance(s[field], bool):
                    raise ReasoningPipelineContractError(
                        "STAGE_" + field.upper() + "_TYPE",
                        s["stage_id"] + "." + field + " is not boolean: "
                        + repr(s[field]),
                    )

        expected_completed = sum(1 for s in stages if s["complete"])
        if result["completed_stage_count"] != expected_completed:
            raise ReasoningPipelineContractError(
                "COMPLETED_COUNT_MISMATCH",
                "completed_stage_count " + repr(result["completed_stage_count"])
                + " != actual " + repr(expected_completed),
            )
        expected_complete = all(s["complete"] for s in stages)
        if result["pipeline_complete"] != expected_complete:
            raise ReasoningPipelineContractError(
                "PIPELINE_COMPLETE_MISMATCH",
                "pipeline_complete does not match stage completeness",
            )
        expected_consistent = all(s["consistent"] for s in stages)
        if result["pipeline_consistent"] != expected_consistent:
            raise ReasoningPipelineContractError(
                "PIPELINE_CONSISTENT_MISMATCH",
                "pipeline_consistent does not match stage consistency",
            )
        if (
            result["pipeline_source"]
            != PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041
        ):
            raise ReasoningPipelineContractError(
                "INVALID_PIPELINE_SOURCE",
                "pipeline_source is not the Task 041 identifier: "
                + repr(result["pipeline_source"]),
            )

        # Reuse Task 039's own full semantic validator for
        # final_execution. A lightweight shape check is not enough:
        # Task 041 must reject an execution whose basic shape is valid
        # but whose fields violate Task 039's contract (e.g. SELECTED
        # with no selected_candidate, or a selected candidate that is
        # not in the eligible set). Task 039's _validate_result and
        # _compute_eligible are instance methods, so we build the same
        # service instance Task 041 already composes.
        try:
            execution_service = DecisionExecutionService()
            assessments = bundle["assessment_set"]["assessments"]
            eligible = execution_service._compute_eligible(assessments)
            execution_service._validate_result(
                result["final_execution"],
                bundle,
                policy,
                assessments,
                eligible,
            )
        except ReasoningPipelineContractError:
            raise
        except Exception as exc:
            raise ReasoningPipelineContractError(
                "INVALID_FINAL_EXECUTION",
                "final_execution failed the Task 039 validator: "
                + str(exc),
            ) from exc

        # Reuse Task 040's output validator for final_execution_consistency.
        try:
            DecisionExecutionConsistencyService._validate_result(
                result["final_execution_consistency"]
            )
        except ReasoningPipelineContractError:
            raise
        except Exception as exc:
            raise ReasoningPipelineContractError(
                "INVALID_FINAL_AUDIT",
                "final_execution_consistency failed its own validator: "
                + str(exc),
            ) from exc

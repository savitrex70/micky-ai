from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.candidate_generation import CandidateGenerationService
from rop.services.entity import EntityService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.reasoning_pipeline import (
    ReasoningPipelineContractError,
    ReasoningPipelineService,
)
from rop.services.reasoning_run import (
    REASONING_RUN_SOURCE_TASK_042,
    ReasoningRunContractError,
    ReasoningRunService,
)
from rop.services.reasoning_session import ReasoningSessionService
from rop.services.template_match import TemplateMatchService

REASONING_RUN_CONSISTENCY_SOURCE_TASK_043 = (
    "REASONING_RUN_CONSISTENCY_TASK_043"
)
"""Fixed structural-contract identifier for Task 043 results."""

_EXPECTED_STAGE_IDS = (
    "SESSION_INPUT",
    "OBSERVATIONS",
    "ENTITIES",
    "MISSING_INFORMATION",
    "TEMPLATE_CONTEXT",
    "CANDIDATE_GENERATION",
    "REASONING_PIPELINE",
)

_EXPECTED_STAGE_SOURCES = {
    "SESSION_INPUT": "REASONING_RUN_STAGE_SESSION_INPUT_TASK_042",
    "OBSERVATIONS": "REASONING_RUN_STAGE_OBSERVATIONS_TASK_042",
    "ENTITIES": "REASONING_RUN_STAGE_ENTITIES_TASK_042",
    "MISSING_INFORMATION": "REASONING_RUN_STAGE_MISSING_INFORMATION_TASK_042",
    "TEMPLATE_CONTEXT": "REASONING_RUN_STAGE_TEMPLATE_CONTEXT_TASK_042",
    "CANDIDATE_GENERATION": "REASONING_RUN_STAGE_CANDIDATE_GENERATION_TASK_042",
    "REASONING_PIPELINE": "REASONING_PIPELINE_TASK_041",
}

_STAGE_REQUIRED_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "available",
    "consistent",
    "complete",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "run_consistent",
    "session_consistent",
    "observations_consistent",
    "entities_consistent",
    "missing_information_consistent",
    "template_context_consistent",
    "candidate_state_consistent",
    "candidate_count_consistent",
    "candidate_generation_consistent",
    "pipeline_consistent",
    "stage_structure_consistent",
    "source_consistency",
    "metadata_consistency",
    "consistency_issues",
    "run_consistency_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "run_consistent",
    "session_consistent",
    "observations_consistent",
    "entities_consistent",
    "missing_information_consistent",
    "template_context_consistent",
    "candidate_state_consistent",
    "candidate_count_consistent",
    "candidate_generation_consistent",
    "pipeline_consistent",
    "stage_structure_consistent",
    "source_consistency",
    "metadata_consistency",
)

# Deterministic ordering for consistency_issues.
_ISSUE_ORDER = (
    "RUN_SOURCE_MISMATCH",
    "STAGE_COUNT_MISMATCH",
    "STAGE_ORDER_MISMATCH",
    "DUPLICATE_STAGE_ID",
    "STAGE_MISSING",
    "STAGE_SOURCE_MISMATCH",
    "STAGE_FIELD_MISSING",
    "CANDIDATE_COUNT_MISMATCH",
    "CANDIDATE_GENERATION_AVAILABILITY_MISMATCH",
    "CANDIDATE_GENERATION_STAGE_MISMATCH",
    "TEMPLATE_STAGE_MISMATCH",
    "PIPELINE_SOURCE_MISMATCH",
    "PIPELINE_STRUCTURE_INCONSISTENT",
    "COMPLETED_STAGE_COUNT_MISMATCH",
    "RUN_COMPLETE_MISMATCH",
    "RUN_CONSISTENCY_MISMATCH",
)

_CANDIDATE_PAGE_SIZE = 100
_STATE_PAGE_SIZE = 1000

# Fields the audit needs on the Task 042 run in order to run at all.
# Missing any of these means the run is too malformed to audit.
_AUDIT_INPUT_REQUIRED_FIELDS = (
    "run_source",
    "stage_count",
    "stages",
    "candidate_count",
    "candidate_generation_available",
    "completed_stage_count",
    "run_complete",
    "run_consistent",
    "reasoning_pipeline",
)


class ReasoningRunConsistencyContractError(Exception):
    """Task 043: malformed upstream state or an internal audit bug.

    Raised only when the session does not exist, the composed Task 042
    result is not shaped like its own established contract, or this
    service's own assembled audit result violates its own invariants.
    It is never raised for a valid but inconsistent run state -- an
    incomplete run, a missing candidate set, or a valid downstream
    outcome such as INPUT_UNAVAILABLE are all faithfully represented
    through the consistency flags and issues list.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunConsistencyService:
    """Task 043: deterministic audit of a Task 042 reasoning run.

    Independently re-derives the expected run representation from the
    session's actual state, then compares it field by field against the
    Task 042 composition. Introduces no new reasoning, no
    re-selection, no policy override, and no mutation of any upstream
    result. Read-only throughout.
    """

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        reasoning_run_service: ReasoningRunService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.reasoning_run_service = (
            reasoning_run_service or ReasoningRunService()
        )
        self.observation_service = observation_service or ObservationService()
        self.entity_service = entity_service or EntityService()
        self.missing_information_service = (
            missing_information_service or MissingInformationService()
        )
        self.template_match_service = (
            template_match_service or TemplateMatchService()
        )
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )

    @staticmethod
    def _paginate(fetch_page: Any) -> list[Any]:
        results: list[Any] = []
        offset = 0
        while True:
            page = fetch_page(offset)
            results.extend(page)
            if len(page) < _STATE_PAGE_SIZE:
                break
            offset += _STATE_PAGE_SIZE
        return results

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Read session state, compose Task 042, then audit. Read-only."""
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningRunConsistencyContractError(
                "MISSING_SESSION", "session does not exist"
            )

        try:
            run, bundle, policy = (
                self.reasoning_run_service.build_for_session_with_inputs(
                    db, session_id
                )
            )
        except ReasoningRunContractError as exc:
            raise ReasoningRunConsistencyContractError(
                "INVALID_REASONING_RUN",
                "Task 042 run failed its own composition: " + str(exc),
            ) from exc

        observations = self._paginate(
            lambda off: self.observation_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            )
        )
        entities = self._paginate(
            lambda off: self.entity_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            )
        )
        missing_information = (
            self.missing_information_service.list_by_session(db, session_id)
        )
        template_matches = self.template_match_service.list_by_session(
            db, session_id
        )

        candidates: list[Any] = []
        page_offset = 0
        while True:
            page = self.candidate_generation_service.list_by_session(
                db,
                session_id,
                offset=page_offset,
                limit=_CANDIDATE_PAGE_SIZE,
            )
            candidates.extend(page)
            if len(page) < _CANDIDATE_PAGE_SIZE:
                break
            page_offset += _CANDIDATE_PAGE_SIZE

        return self.build(
            run=run,
            observations=observations,
            entities=entities,
            missing_information=missing_information,
            template_matches=template_matches,
            candidates=candidates,
            bundle=bundle,
            policy=policy,
        )


    def build(
        self,
        *,
        run: Mapping[str, Any] | None = None,
        observations: list[Any] | None = None,
        entities: list[Any] | None = None,
        missing_information: list[Any] | None = None,
        template_matches: list[Any] | None = None,
        candidates: list[Any] | None = None,
        bundle: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit the Task 042 run against actual state. Pure.

        Never mutates inputs. Every flag is derived independently from
        the supplied state; Task 042's own flags are never trusted
        without cross-checks.
        """
        if run is None:
            raise ReasoningRunConsistencyContractError(
                "MISSING_RUN", "run is required"
            )
        if not isinstance(run, Mapping):
            raise ReasoningRunConsistencyContractError(
                "RUN_TYPE",
                "run is not a mapping: " + type(run).__name__,
            )
        for name, value in (
            ("observations", observations),
            ("entities", entities),
            ("missing_information", missing_information),
            ("template_matches", template_matches),
            ("candidates", candidates),
        ):
            if not isinstance(value, list):
                raise ReasoningRunConsistencyContractError(
                    name.upper() + "_TYPE",
                    name + " is not a list: " + type(value).__name__,
                )
        if not isinstance(bundle, Mapping):
            raise ReasoningRunConsistencyContractError(
                "BUNDLE_TYPE",
                "bundle is not a mapping: " + type(bundle).__name__,
            )
        if not isinstance(policy, Mapping):
            raise ReasoningRunConsistencyContractError(
                "POLICY_TYPE",
                "policy is not a mapping: " + type(policy).__name__,
            )

        # Lightweight precondition: the run must be shaped enough to
        # audit at all. Task 043's own audit checks (below) are what
        # report semantic disagreement (wrong source, wrong stage
        # order, wrong counts, wrong flags) as consistency_issues --
        # those are not raised as exceptions. Only a run so malformed
        # that the audit cannot proceed raises INVALID_REASONING_RUN.
        for required_field in _AUDIT_INPUT_REQUIRED_FIELDS:
            if required_field not in run:
                raise ReasoningRunConsistencyContractError(
                    "INVALID_REASONING_RUN",
                    "Task 042 run is missing required field: "
                    + required_field,
                )
        if not isinstance(run.get("stages"), list):
            raise ReasoningRunConsistencyContractError(
                "INVALID_REASONING_RUN",
                "Task 042 run stages is not a list",
            )

        issues: list[str] = []

        actual_candidate_count = len(candidates)
        actual_template_present = len(template_matches) > 0

        # --- Run-level source check ---
        if run.get("run_source") != REASONING_RUN_SOURCE_TASK_042:
            issues.append("RUN_SOURCE_MISMATCH")

        # --- Stage structure checks ---
        stages = run.get("stages")
        if not isinstance(stages, list):
            issues.append("STAGE_MISSING")
            stages = []
        stage_by_id = {}
        seen_ids: set[str] = set()
        for idx, stage in enumerate(stages):
            if not isinstance(stage, Mapping):
                issues.append("STAGE_FIELD_MISSING")
                continue
            sid = stage.get("stage_id")
            if not isinstance(sid, str) or not sid:
                issues.append("STAGE_FIELD_MISSING")
                continue
            if sid in seen_ids:
                if "DUPLICATE_STAGE_ID" not in issues:
                    issues.append("DUPLICATE_STAGE_ID")
            seen_ids.add(sid)
            if stage.get("stage_order") != idx + 1:
                if "STAGE_ORDER_MISMATCH" not in issues:
                    issues.append("STAGE_ORDER_MISMATCH")
            expected_source = _EXPECTED_STAGE_SOURCES.get(sid)
            if expected_source is not None and stage.get(
                "stage_source"
            ) != expected_source:
                if "STAGE_SOURCE_MISMATCH" not in issues:
                    issues.append("STAGE_SOURCE_MISMATCH")
            for field in _STAGE_REQUIRED_FIELDS:
                if field not in stage:
                    if "STAGE_FIELD_MISSING" not in issues:
                        issues.append("STAGE_FIELD_MISSING")
            stage_by_id[sid] = stage

        if run.get("stage_count") != len(stages):
            issues.append("STAGE_COUNT_MISMATCH")
        if len(stages) != len(_EXPECTED_STAGE_IDS):
            if "STAGE_COUNT_MISMATCH" not in issues:
                issues.append("STAGE_COUNT_MISMATCH")
        for expected_id in _EXPECTED_STAGE_IDS:
            if expected_id not in stage_by_id:
                if "STAGE_MISSING" not in issues:
                    issues.append("STAGE_MISSING")

        # --- Candidate count check ---
        if run.get("candidate_count") != actual_candidate_count:
            issues.append("CANDIDATE_COUNT_MISMATCH")

        # --- Candidate generation availability check ---
        expected_gen_available = actual_candidate_count > 0
        if run.get("candidate_generation_available") != expected_gen_available:
            issues.append("CANDIDATE_GENERATION_AVAILABILITY_MISMATCH")

        # --- CANDIDATE_GENERATION stage check ---
        gen_stage = stage_by_id.get("CANDIDATE_GENERATION")
        if gen_stage is None:
            issues.append("CANDIDATE_GENERATION_STAGE_MISMATCH")
        else:
            expected_avail = expected_gen_available
            expected_complete = expected_gen_available
            if (
                gen_stage.get("available") != expected_avail
                or gen_stage.get("complete") != expected_complete
                or gen_stage.get("consistent") is not True
            ):
                issues.append("CANDIDATE_GENERATION_STAGE_MISMATCH")

        # --- TEMPLATE_CONTEXT stage check ---
        tmpl_stage = stage_by_id.get("TEMPLATE_CONTEXT")
        if tmpl_stage is None:
            issues.append("TEMPLATE_STAGE_MISMATCH")
        else:
            # Per Task 042 approved semantics: available reflects
            # actual template presence; complete is always True.
            if tmpl_stage.get("available") != actual_template_present:
                issues.append("TEMPLATE_STAGE_MISMATCH")

        # --- Nested pipeline checks ---
        # Reuse Task 041's own full validator via the bundle/policy
        # intermediates that Task 042 now returns alongside the run.
        # Deep structural mismatches (e.g. a malformed nested
        # final_execution) are reported as PIPELINE_STRUCTURE_INCONSISTENT
        # rather than raising, so the audit still returns an available
        # result with an explicit issue list.
        pipeline = run.get("reasoning_pipeline")
        if not isinstance(pipeline, Mapping):
            issues.append("PIPELINE_STRUCTURE_INCONSISTENT")
        else:
            if pipeline.get("pipeline_source") != "REASONING_PIPELINE_TASK_041":
                issues.append("PIPELINE_SOURCE_MISMATCH")
            try:
                ReasoningPipelineService._validate_result(
                    dict(pipeline), bundle, policy
                )
            except ReasoningPipelineContractError:
                if "PIPELINE_STRUCTURE_INCONSISTENT" not in issues:
                    issues.append("PIPELINE_STRUCTURE_INCONSISTENT")
            except Exception:
                if "PIPELINE_STRUCTURE_INCONSISTENT" not in issues:
                    issues.append("PIPELINE_STRUCTURE_INCONSISTENT")

        # --- Metadata / run-level flag checks ---
        expected_completed = sum(
            1
            for s in stages
            if isinstance(s, Mapping) and s.get("complete") is True
        )
        if run.get("completed_stage_count") != expected_completed:
            issues.append("COMPLETED_STAGE_COUNT_MISMATCH")

        expected_run_complete = all(
            isinstance(s, Mapping) and s.get("complete") is True
            for s in stages
        ) and len(stages) > 0
        if run.get("run_complete") != expected_run_complete:
            issues.append("RUN_COMPLETE_MISMATCH")

        expected_run_consistent = all(
            isinstance(s, Mapping) and s.get("consistent") is True
            for s in stages
        ) and len(stages) > 0
        if run.get("run_consistent") != expected_run_consistent:
            issues.append("RUN_CONSISTENCY_MISMATCH")

        # --- Deterministic issue ordering, dedupe ---
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # --- Derive flags ---
        source_consistency = "RUN_SOURCE_MISMATCH" not in unique_issues

        stage_structure_consistent = not any(
            i in unique_issues
            for i in (
                "STAGE_COUNT_MISMATCH",
                "STAGE_ORDER_MISMATCH",
                "DUPLICATE_STAGE_ID",
                "STAGE_MISSING",
                "STAGE_SOURCE_MISMATCH",
                "STAGE_FIELD_MISSING",
            )
        )

        candidate_count_consistent = (
            "CANDIDATE_COUNT_MISMATCH" not in unique_issues
        )
        candidate_generation_consistent = (
            "CANDIDATE_GENERATION_AVAILABILITY_MISMATCH" not in unique_issues
            and "CANDIDATE_GENERATION_STAGE_MISMATCH" not in unique_issues
        )
        candidate_state_consistent = (
            candidate_count_consistent and candidate_generation_consistent
        )
        template_context_consistent = (
            "TEMPLATE_STAGE_MISMATCH" not in unique_issues
        )
        pipeline_consistent = not any(
            i in unique_issues
            for i in (
                "PIPELINE_SOURCE_MISMATCH",
                "PIPELINE_STRUCTURE_INCONSISTENT",
            )
        )
        metadata_consistency = (
            candidate_count_consistent
            and candidate_generation_consistent
            and "COMPLETED_STAGE_COUNT_MISMATCH" not in unique_issues
        )

        # Session, observations, entities, missing-information stages are
        # structural only: their presence and source were checked above.
        session_consistent = True
        observations_consistent = (
            "OBSERVATIONS" in stage_by_id
            and "STAGE_MISSING" not in unique_issues
        )
        entities_consistent = (
            "ENTITIES" in stage_by_id
            and "STAGE_MISSING" not in unique_issues
        )
        missing_information_consistent = (
            "MISSING_INFORMATION" in stage_by_id
            and "STAGE_MISSING" not in unique_issues
        )

        run_consistent = not ordered_issues

        result: dict[str, Any] = {
            "available": True,
            "run_consistent": run_consistent,
            "session_consistent": session_consistent,
            "observations_consistent": observations_consistent,
            "entities_consistent": entities_consistent,
            "missing_information_consistent": missing_information_consistent,
            "template_context_consistent": template_context_consistent,
            "candidate_state_consistent": candidate_state_consistent,
            "candidate_count_consistent": candidate_count_consistent,
            "candidate_generation_consistent": candidate_generation_consistent,
            "pipeline_consistent": pipeline_consistent,
            "stage_structure_consistent": stage_structure_consistent,
            "source_consistency": source_consistency,
            "metadata_consistency": metadata_consistency,
            "consistency_issues": ordered_issues,
            "run_consistency_source": (
                REASONING_RUN_CONSISTENCY_SOURCE_TASK_043
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunConsistencyContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunConsistencyContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningRunConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: "
                + type(issues).__name__,
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise ReasoningRunConsistencyContractError(
                    "ISSUE_TYPE",
                    "issue is not a non-empty string: " + repr(issue),
                )
        if len(set(issues)) != len(issues):
            raise ReasoningRunConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningRunConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if (
            result["run_consistency_source"]
            != REASONING_RUN_CONSISTENCY_SOURCE_TASK_043
        ):
            raise ReasoningRunConsistencyContractError(
                "INVALID_SOURCE",
                "run_consistency_source is not the Task 043 identifier: "
                + repr(result["run_consistency_source"]),
            )
        # run_consistent must equal (no issues).
        if result["run_consistent"] != (len(issues) == 0):
            raise ReasoningRunConsistencyContractError(
                "RUN_CONSISTENT_MISMATCH",
                "run_consistent does not match consistency_issues",
            )

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.entity import EntityService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.reasoning_pipeline import (
    PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041,
    ReasoningPipelineContractError,
    ReasoningPipelineService,
)
from rop.services.reasoning_session import ReasoningSessionService
from rop.services.template_match import TemplateMatchService

REASONING_RUN_SOURCE_TASK_042 = "REASONING_RUN_TASK_042"

STAGE_SOURCE_SESSION_INPUT = "REASONING_RUN_STAGE_SESSION_INPUT_TASK_042"
STAGE_SOURCE_OBSERVATIONS = "REASONING_RUN_STAGE_OBSERVATIONS_TASK_042"
STAGE_SOURCE_ENTITIES = "REASONING_RUN_STAGE_ENTITIES_TASK_042"
STAGE_SOURCE_MISSING_INFORMATION = (
    "REASONING_RUN_STAGE_MISSING_INFORMATION_TASK_042"
)
STAGE_SOURCE_TEMPLATE_CONTEXT = "REASONING_RUN_STAGE_TEMPLATE_CONTEXT_TASK_042"
STAGE_SOURCE_CANDIDATE_GENERATION = (
    "REASONING_RUN_STAGE_CANDIDATE_GENERATION_TASK_042"
)

_CANDIDATE_PAGE_SIZE = 100
_STATE_PAGE_SIZE = 1000

_RESULT_FIELDS = (
    "available",
    "run_consistent",
    "run_complete",
    "stage_count",
    "completed_stage_count",
    "stages",
    "candidate_count",
    "candidate_generation_available",
    "reasoning_pipeline",
    "run_source",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "run_consistent",
    "run_complete",
    "candidate_generation_available",
)

_RESULT_INTEGER_FIELDS = (
    "stage_count",
    "completed_stage_count",
    "candidate_count",
)

_STAGE_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "available",
    "consistent",
    "complete",
)

_STAGE_BOOLEAN_FIELDS = ("available", "consistent", "complete")


class ReasoningRunContractError(Exception):
    """Task 042: malformed upstream state or an internal composition bug.

    Raised only when the session state, an upstream service result, or
    the composed Task 041 pipeline output is not shaped like its own
    established contract, or when this service's own assembled run
    structure violates its own invariants. It is never raised for a
    valid downstream state -- an empty candidate set, missing template
    context, or a valid INPUT_UNAVAILABLE / INPUT_INCONSISTENT
    downstream outcome are all faithfully represented through the stage
    list and nested Task 041 result.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunService:
    """Task 042: deterministic full ROP reasoning-run composition.

    Bridges the session's own upstream state (observations, entities,
    missing information, template context, existing candidates) into
    the approved Task 041 reasoning pipeline, producing one coherent
    end-to-end ROP run representation. Read-only: candidate generation
    is never re-invoked from this service, so a GET never mutates
    session state. Introduces no new reasoning; performs no
    persistence; mutates no input.
    """

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        reasoning_pipeline_service: ReasoningPipelineService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
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
        self.reasoning_pipeline_service = (
            reasoning_pipeline_service or ReasoningPipelineService()
        )

    @staticmethod
    def _paginate(fetch_page: Any) -> list[Any]:
        """Read every page from a paginated list_by_session boundary.

        Uses _STATE_PAGE_SIZE pages and stops when a page is shorter
        than the page size, matching the pattern already established
        for candidates.
        """
        results: list[Any] = []
        offset = 0
        while True:
            page = fetch_page(offset)
            results.extend(page)
            if len(page) < _STATE_PAGE_SIZE:
                break
            offset += _STATE_PAGE_SIZE
        return results

    def build_for_session_with_inputs(
        self,
        db: Session,
        session_id: UUID,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Read state, compose run, and return the intermediates.

        Returns ``(run_result, pipeline_bundle, pipeline_policy)``.
        Downstream audit layers (e.g. Task 043) can use the bundle and
        policy to re-validate the nested Task 041 pipeline against its
        own full validator without re-walking the chain.

        Read-only throughout: candidates are only listed, never
        regenerated. If the session does not exist,
        ReasoningRunContractError is raised with MISSING_SESSION.
        """
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningRunContractError(
                "MISSING_SESSION", "session does not exist"
            )

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

        candidates: list[CandidateHypothesis] = []
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

        pipeline_result, bundle, policy = (
            self.reasoning_pipeline_service.build_for_session_with_inputs(
                db, session_id, candidates
            )
        )

        result = self.build(
            session=session,
            observations=observations,
            entities=entities,
            missing_information=missing_information,
            template_matches=template_matches,
            candidates=candidates,
            pipeline_result=pipeline_result,
            bundle=bundle,
            policy=policy,
        )
        return result, dict(bundle), dict(policy)

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return only the composed run.

        Convenience wrapper around ``build_for_session_with_inputs`` for
        callers that do not need the intermediate bundle/policy.
        """
        result, _, _ = self.build_for_session_with_inputs(
            db, session_id
        )
        return result


    def build(
        self,
        *,
        session: object | None = None,
        observations: list[object] | None = None,
        entities: list[object] | None = None,
        missing_information: list[object] | None = None,
        template_matches: list[object] | None = None,
        candidates: list[object] | None = None,
        pipeline_result: Mapping[str, Any] | None = None,
        bundle: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compose the full ROP run view. Pure; never mutates inputs."""
        if session is None:
            raise ReasoningRunContractError(
                "MISSING_SESSION", "session is required"
            )
        for name, value in (
            ("observations", observations),
            ("entities", entities),
            ("missing_information", missing_information),
            ("template_matches", template_matches),
            ("candidates", candidates),
        ):
            if not isinstance(value, list):
                raise ReasoningRunContractError(
                    name.upper() + "_TYPE",
                    name + " is not a list: " + type(value).__name__,
                )
        if not isinstance(pipeline_result, Mapping):
            raise ReasoningRunContractError(
                "PIPELINE_RESULT_TYPE",
                "pipeline_result is not a mapping: "
                + type(pipeline_result).__name__,
            )
        if not isinstance(bundle, Mapping):
            raise ReasoningRunContractError(
                "BUNDLE_TYPE",
                "bundle is not a mapping: " + type(bundle).__name__,
            )
        if not isinstance(policy, Mapping):
            raise ReasoningRunContractError(
                "POLICY_TYPE",
                "policy is not a mapping: " + type(policy).__name__,
            )

        # Reuse Task 041's own validator against the nested pipeline
        # result, rather than trusting its pipeline_complete /
        # pipeline_consistent flags directly.
        try:
            ReasoningPipelineService._validate_result(
                dict(pipeline_result), bundle, policy
            )
        except ReasoningPipelineContractError as exc:
            raise ReasoningRunContractError(
                "INVALID_REASONING_PIPELINE",
                "nested Task 041 result failed its own validator: "
                + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningRunContractError(
                "INVALID_REASONING_PIPELINE",
                "nested Task 041 result failed its own validator: "
                + str(exc),
            ) from exc

        has_template = len(template_matches) > 0
        has_candidates = len(candidates) > 0
        pipeline_available = bool(
            pipeline_result.get("available", False)
        )
        pipeline_consistent = bool(
            pipeline_result.get("pipeline_consistent", False)
        )
        pipeline_complete = bool(
            pipeline_result.get("pipeline_complete", False)
        )

        stages = [
            self._make_stage(
                "SESSION_INPUT",
                1,
                STAGE_SOURCE_SESSION_INPUT,
                True,
                True,
                True,
            ),
            self._make_stage(
                "OBSERVATIONS",
                2,
                STAGE_SOURCE_OBSERVATIONS,
                True,
                True,
                True,
            ),
            self._make_stage(
                "ENTITIES",
                3,
                STAGE_SOURCE_ENTITIES,
                True,
                True,
                True,
            ),
            self._make_stage(
                "MISSING_INFORMATION",
                4,
                STAGE_SOURCE_MISSING_INFORMATION,
                True,
                True,
                True,
            ),
            self._make_stage(
                "TEMPLATE_CONTEXT",
                5,
                STAGE_SOURCE_TEMPLATE_CONTEXT,
                has_template,
                True,
                True,
            ),
            self._make_stage(
                "CANDIDATE_GENERATION",
                6,
                STAGE_SOURCE_CANDIDATE_GENERATION,
                has_candidates,
                True,
                has_candidates,
            ),
            self._make_stage(
                "REASONING_PIPELINE",
                7,
                PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041,
                pipeline_available,
                pipeline_consistent,
                pipeline_complete,
            ),
        ]

        stage_count = len(stages)
        completed_stage_count = sum(1 for s in stages if s["complete"])
        run_complete = all(s["complete"] for s in stages)
        run_consistent = all(s["consistent"] for s in stages)

        result: dict[str, Any] = {
            "available": True,
            "run_consistent": run_consistent,
            "run_complete": run_complete,
            "stage_count": stage_count,
            "completed_stage_count": completed_stage_count,
            "stages": stages,
            "candidate_count": len(candidates),
            "candidate_generation_available": len(candidates) > 0,
            "reasoning_pipeline": dict(pipeline_result),
            "run_source": REASONING_RUN_SOURCE_TASK_042,
        }
        self._validate_result(result)
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
                raise ReasoningRunContractError(
                    "STAGE_" + name.upper() + "_TYPE",
                    stage_id + "." + name + " is not boolean: "
                    + repr(value),
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
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_FIELDS:
            if field not in result:
                raise ReasoningRunContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningRunContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        for field in _RESULT_INTEGER_FIELDS:
            value = result[field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise ReasoningRunContractError(
                    field.upper() + "_TYPE",
                    field + " is not an int: " + repr(value),
                )
            if value < 0:
                raise ReasoningRunContractError(
                    field.upper() + "_NEGATIVE",
                    field + " is negative: " + repr(value),
                )

        # candidate_generation_available must equal (candidate_count > 0).
        expected_generation_available = result["candidate_count"] > 0
        if (
            result["candidate_generation_available"]
            != expected_generation_available
        ):
            raise ReasoningRunContractError(
                "CANDIDATE_GENERATION_AVAILABLE_MISMATCH",
                "candidate_generation_available does not match "
                "candidate_count > 0",
            )

        stages = result["stages"]
        if not isinstance(stages, list):
            raise ReasoningRunContractError(
                "STAGES_TYPE",
                "stages is not a list: " + type(stages).__name__,
            )
        if result["stage_count"] != len(stages):
            raise ReasoningRunContractError(
                "STAGE_COUNT_MISMATCH",
                "stage_count " + repr(result["stage_count"])
                + " != len(stages) " + repr(len(stages)),
            )
        seen_ids: set[str] = set()
        expected_order = 1
        for s in stages:
            if not isinstance(s, Mapping):
                raise ReasoningRunContractError(
                    "STAGE_TYPE",
                    "stage is not a mapping: " + type(s).__name__,
                )
            for field in _STAGE_FIELDS:
                if field not in s:
                    raise ReasoningRunContractError(
                        "MISSING_STAGE_FIELD", "stage has no " + field
                    )
            if not isinstance(s["stage_id"], str) or not s["stage_id"]:
                raise ReasoningRunContractError(
                    "STAGE_ID_TYPE",
                    "stage_id is not a non-empty string: "
                    + repr(s["stage_id"]),
                )
            if not isinstance(s["stage_source"], str) or not s["stage_source"]:
                raise ReasoningRunContractError(
                    "STAGE_SOURCE_TYPE",
                    "stage_source is not a non-empty string: "
                    + repr(s["stage_source"]),
                )
            if s["stage_id"] in seen_ids:
                raise ReasoningRunContractError(
                    "DUPLICATE_STAGE_ID",
                    "duplicate stage_id: " + s["stage_id"],
                )
            seen_ids.add(s["stage_id"])
            if s["stage_order"] != expected_order:
                raise ReasoningRunContractError(
                    "STAGE_ORDER_MISMATCH",
                    "stage_order " + repr(s["stage_order"])
                    + " != expected " + repr(expected_order),
                )
            expected_order += 1
            for field in _STAGE_BOOLEAN_FIELDS:
                if not isinstance(s[field], bool):
                    raise ReasoningRunContractError(
                        "STAGE_" + field.upper() + "_TYPE",
                        s["stage_id"] + "." + field + " is not boolean: "
                        + repr(s[field]),
                    )

        expected_completed = sum(1 for s in stages if s["complete"])
        if result["completed_stage_count"] != expected_completed:
            raise ReasoningRunContractError(
                "COMPLETED_COUNT_MISMATCH",
                "completed_stage_count "
                + repr(result["completed_stage_count"])
                + " != actual " + repr(expected_completed),
            )
        expected_complete = all(s["complete"] for s in stages)
        if result["run_complete"] != expected_complete:
            raise ReasoningRunContractError(
                "RUN_COMPLETE_MISMATCH",
                "run_complete does not match stage completeness",
            )
        expected_consistent = all(s["consistent"] for s in stages)
        if result["run_consistent"] != expected_consistent:
            raise ReasoningRunContractError(
                "RUN_CONSISTENT_MISMATCH",
                "run_consistent does not match stage consistency",
            )
        if result["run_source"] != REASONING_RUN_SOURCE_TASK_042:
            raise ReasoningRunContractError(
                "INVALID_RUN_SOURCE",
                "run_source is not the Task 042 identifier: "
                + repr(result["run_source"]),
            )

        pipeline = result["reasoning_pipeline"]
        if not isinstance(pipeline, Mapping):
            raise ReasoningRunContractError(
                "PIPELINE_TYPE",
                "reasoning_pipeline is not a mapping: "
                + type(pipeline).__name__,
            )

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.candidate_generation import CandidateGenerationService
from rop.services.entity import EntityService
from rop.services.evidence_evaluation import EvidenceEvaluationService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.observation_extraction import ObservationExtractionService
from rop.services.reasoning_run import (
    ReasoningRunContractError,
    ReasoningRunService,
)
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyContractError,
    ReasoningRunConsistencyService,
)
from rop.services.reasoning_session import ReasoningSessionService
from rop.services.template_match import TemplateMatchService

REASONING_RUN_EXECUTION_SOURCE_TASK_044 = "REASONING_RUN_EXECUTION_TASK_044"

OUTCOME_COMPLETED = "COMPLETED"
OUTCOME_FAILED = "FAILED"
OUTCOME_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"

_STATUS_COMPLETED = "COMPLETED"
_STATUS_FAILED = "FAILED"

_EXECUTION_STAGE_IDS = (
    "SESSION_VERIFIED",
    "OBSERVATION_EXTRACTION",
    "MISSING_INFORMATION",
    "TEMPLATE_MATCHING",
    "CANDIDATE_GENERATION",
    "EVIDENCE_EVALUATION",
    "REASONING_RUN",
    "REASONING_RUN_CONSISTENCY",
)

_STAGE_SOURCES = {
    "SESSION_VERIFIED":
        "REASONING_RUN_EXECUTION_STAGE_SESSION_VERIFIED_TASK_044",
    "OBSERVATION_EXTRACTION":
        "REASONING_RUN_EXECUTION_STAGE_OBSERVATION_EXTRACTION_TASK_044",
    "MISSING_INFORMATION":
        "REASONING_RUN_EXECUTION_STAGE_MISSING_INFORMATION_TASK_044",
    "TEMPLATE_MATCHING":
        "REASONING_RUN_EXECUTION_STAGE_TEMPLATE_MATCHING_TASK_044",
    "CANDIDATE_GENERATION":
        "REASONING_RUN_EXECUTION_STAGE_CANDIDATE_GENERATION_TASK_044",
    "EVIDENCE_EVALUATION":
        "REASONING_RUN_EXECUTION_STAGE_EVIDENCE_EVALUATION_TASK_044",
    "REASONING_RUN":
        "REASONING_RUN_EXECUTION_STAGE_REASONING_RUN_TASK_044",
    "REASONING_RUN_CONSISTENCY":
        "REASONING_RUN_EXECUTION_STAGE_REASONING_RUN_CONSISTENCY_TASK_044",
}

_RESULT_REQUIRED_FIELDS = (
    "available",
    "outcome",
    "execution_consistent",
    "session_id",
    "completed_stage_count",
    "stage_count",
    "stages",
    "reasoning_run",
    "reasoning_run_consistency",
    "execution_source",
)

_STAGE_REQUIRED_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "status",
)

_CANDIDATE_PAGE_SIZE = 100
_STATE_PAGE_SIZE = 1000


class ReasoningRunExecutionContractError(Exception):
    """Task 044: a stage of the execution orchestrator failed.

    Raised when a required stage of the orchestrated reasoning
    workflow fails, when a required session or prerequisite is
    missing, or when a delegated service returns a result that
    violates its own contract. It is never converted into a
    successful-but-empty execution result.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionService:
    """Task 044: deterministic reasoning-run execution orchestrator.

    The first write-side composition layer. Runs the established
    deterministic reasoning workflow in order by delegating to the
    existing services -- no reasoning, scoring, ranking, or decision
    logic is reimplemented here. Any stage failure raises an explicit
    ReasoningRunExecutionContractError; downstream stages never run
    after a required earlier stage fails.
    """

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        observation_extraction_service: (
            ObservationExtractionService | None
        ) = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        evidence_evaluation_service: EvidenceEvaluationService | None = None,
        reasoning_run_service: ReasoningRunService | None = None,
        reasoning_run_consistency_service: (
            ReasoningRunConsistencyService | None
        ) = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.observation_service = observation_service or ObservationService()
        self.entity_service = entity_service or EntityService()
        self.observation_extraction_service = (
            observation_extraction_service or ObservationExtractionService()
        )
        self.missing_information_service = (
            missing_information_service or MissingInformationService()
        )
        self.template_match_service = (
            template_match_service or TemplateMatchService()
        )
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )
        self.evidence_evaluation_service = (
            evidence_evaluation_service or EvidenceEvaluationService()
        )
        self.reasoning_run_service = (
            reasoning_run_service or ReasoningRunService()
        )
        self.reasoning_run_consistency_service = (
            reasoning_run_consistency_service
            or ReasoningRunConsistencyService()
        )

    def execute_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Run the deterministic reasoning workflow end-to-end.

        Every stage delegates to the established service that owns it.
        A stage failure raises ReasoningRunExecutionContractError and
        no further stages run.
        """
        # 1. Session verification.
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningRunExecutionContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )

        # 2. Observation extraction from the session's user_input.
        try:
            self.observation_extraction_service.extract_and_store(
                db, session_id, session.user_input
            )
        except Exception as exc:
            raise ReasoningRunExecutionContractError(
                "OBSERVATION_EXTRACTION_FAILED",
                "observation extraction failed: " + str(exc),
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

        # 3. Missing-information detection.
        try:
            self.missing_information_service.detect_and_store(
                db, session_id, observations
            )
        except Exception as exc:
            raise ReasoningRunExecutionContractError(
                "MISSING_INFORMATION_FAILED",
                "missing-information detection failed: " + str(exc),
            ) from exc

        # 4. Template matching.
        try:
            self.template_match_service.match(
                db, session_id, observations, entities
            )
        except Exception as exc:
            raise ReasoningRunExecutionContractError(
                "TEMPLATE_MATCHING_FAILED",
                "template matching failed: " + str(exc),
            ) from exc

        template_matches = self.template_match_service.list_by_session(
            db, session_id
        )

        # 5. Candidate generation -- reuses the same template lookup
        # already established in the /generate-candidates endpoint.
        from rop.templates import load_templates

        template = None
        if template_matches:
            latest = template_matches[-1]
            templates = load_templates()
            template = next(
                (t for t in templates if t.name == latest.template_name),
                None,
            )

        missing_information = (
            self.missing_information_service.list_by_session(db, session_id)
        )

        try:
            self.candidate_generation_service.generate(
                db=db,
                session_id=session_id,
                observations=observations,
                entities=entities,
                template=template,
                missing_information=missing_information,
            )
        except Exception as exc:
            raise ReasoningRunExecutionContractError(
                "CANDIDATE_GENERATION_FAILED",
                "candidate generation failed: " + str(exc),
            ) from exc

        # 6. Evidence evaluation.
        candidates = self._paginate(
            lambda off: self.candidate_generation_service.list_by_session(
                db, session_id, offset=off, limit=_CANDIDATE_PAGE_SIZE
            )
        )

        try:
            self.evidence_evaluation_service.evaluate_session(
                db=db,
                session_id=session_id,
                candidates=candidates,
                observations=observations,
                entities=entities,
            )
        except Exception as exc:
            raise ReasoningRunExecutionContractError(
                "EVIDENCE_EVALUATION_FAILED",
                "evidence evaluation failed: " + str(exc),
            ) from exc

        # 7. Compose the Task 042 reasoning run.
        try:
            run = self.reasoning_run_service.build_for_session(
                db, session_id
            )
        except ReasoningRunContractError as exc:
            raise ReasoningRunExecutionContractError(
                "REASONING_RUN_FAILED",
                "Task 042 composition failed: " + str(exc),
            ) from exc

        # 8. Audit the run via Task 043.
        try:
            audit = (
                self.reasoning_run_consistency_service.build_for_session(
                    db, session_id
                )
            )
        except ReasoningRunConsistencyContractError as exc:
            raise ReasoningRunExecutionContractError(
                "REASONING_RUN_CONSISTENCY_FAILED",
                "Task 043 audit failed: " + str(exc),
            ) from exc

        return self._build_result(
            session_id=session_id,
            run=run,
            audit=audit,
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

    @staticmethod
    def _build_result(
        *,
        session_id: UUID,
        run: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        stages = [
            {
                "stage_id": sid,
                "stage_order": i + 1,
                "stage_source": _STAGE_SOURCES[sid],
                "status": _STATUS_COMPLETED,
            }
            for i, sid in enumerate(_EXECUTION_STAGE_IDS)
        ]
        completed_stage_count = sum(
            1 for s in stages if s["status"] == _STATUS_COMPLETED
        )
        result: dict[str, Any] = {
            "available": True,
            "outcome": OUTCOME_COMPLETED,
            "execution_consistent": bool(
                audit.get("run_consistent", False)
            ),
            "session_id": session_id,
            "completed_stage_count": completed_stage_count,
            "stage_count": len(stages),
            "stages": stages,
            "reasoning_run": dict(run),
            "reasoning_run_consistency": dict(audit),
            "execution_source": REASONING_RUN_EXECUTION_SOURCE_TASK_044,
        }
        ReasoningRunExecutionService._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningRunExecutionContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        if not isinstance(result["available"], bool):
            raise ReasoningRunExecutionContractError(
                "AVAILABLE_TYPE",
                "available is not boolean: " + repr(result["available"]),
            )
        if not isinstance(result["execution_consistent"], bool):
            raise ReasoningRunExecutionContractError(
                "EXECUTION_CONSISTENT_TYPE",
                "execution_consistent is not boolean: "
                + repr(result["execution_consistent"]),
            )
        if result["outcome"] not in (
            OUTCOME_COMPLETED,
            OUTCOME_FAILED,
            OUTCOME_SESSION_NOT_FOUND,
        ):
            raise ReasoningRunExecutionContractError(
                "INVALID_OUTCOME",
                "outcome is not a known identifier: "
                + repr(result["outcome"]),
            )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningRunExecutionContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: "
                + type(result["session_id"]).__name__,
            )
        for field in ("completed_stage_count", "stage_count"):
            value = result[field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise ReasoningRunExecutionContractError(
                    field.upper() + "_TYPE",
                    field + " is not an int: " + repr(value),
                )
            if value < 0:
                raise ReasoningRunExecutionContractError(
                    field.upper() + "_NEGATIVE",
                    field + " is negative: " + repr(value),
                )
        if result["completed_stage_count"] > result["stage_count"]:
            raise ReasoningRunExecutionContractError(
                "COMPLETED_EXCEEDS_TOTAL",
                "completed_stage_count exceeds stage_count",
            )
        stages = result["stages"]
        if not isinstance(stages, list):
            raise ReasoningRunExecutionContractError(
                "STAGES_TYPE",
                "stages is not a list: " + type(stages).__name__,
            )
        if len(stages) != result["stage_count"]:
            raise ReasoningRunExecutionContractError(
                "STAGE_COUNT_MISMATCH",
                "stage_count " + repr(result["stage_count"])
                + " != len(stages) " + repr(len(stages)),
            )
        seen_ids: set[str] = set()
        expected_order = 1
        for s in stages:
            if not isinstance(s, dict):
                raise ReasoningRunExecutionContractError(
                    "STAGE_TYPE",
                    "stage is not a dict: " + type(s).__name__,
                )
            for field in _STAGE_REQUIRED_FIELDS:
                if field not in s:
                    raise ReasoningRunExecutionContractError(
                        "MISSING_STAGE_FIELD", "stage has no " + field
                    )
            if s["stage_id"] in seen_ids:
                raise ReasoningRunExecutionContractError(
                    "DUPLICATE_STAGE_ID", "duplicate stage_id: "
                    + str(s["stage_id"]),
                )
            seen_ids.add(s["stage_id"])
            if s["stage_order"] != expected_order:
                raise ReasoningRunExecutionContractError(
                    "STAGE_ORDER_MISMATCH",
                    "stage_order " + repr(s["stage_order"])
                    + " != expected " + repr(expected_order),
                )
            expected_order += 1
            if s["status"] not in (_STATUS_COMPLETED, _STATUS_FAILED):
                raise ReasoningRunExecutionContractError(
                    "INVALID_STAGE_STATUS",
                    "stage status is not a known identifier: "
                    + repr(s["status"]),
                )
        completed = sum(1 for s in stages if s["status"] == _STATUS_COMPLETED)
        if result["completed_stage_count"] != completed:
            raise ReasoningRunExecutionContractError(
                "COMPLETED_COUNT_MISMATCH",
                "completed_stage_count "
                + repr(result["completed_stage_count"])
                + " != actual " + repr(completed),
            )
        if not isinstance(result["reasoning_run"], dict):
            raise ReasoningRunExecutionContractError(
                "REASONING_RUN_TYPE",
                "reasoning_run is not a dict: "
                + type(result["reasoning_run"]).__name__,
            )
        if not isinstance(result["reasoning_run_consistency"], dict):
            raise ReasoningRunExecutionContractError(
                "REASONING_RUN_CONSISTENCY_TYPE",
                "reasoning_run_consistency is not a dict: "
                + type(result["reasoning_run_consistency"]).__name__,
            )
        if (
            result["execution_source"]
            != REASONING_RUN_EXECUTION_SOURCE_TASK_044
        ):
            raise ReasoningRunExecutionContractError(
                "INVALID_EXECUTION_SOURCE",
                "execution_source is not the Task 044 identifier: "
                + repr(result["execution_source"]),
            )

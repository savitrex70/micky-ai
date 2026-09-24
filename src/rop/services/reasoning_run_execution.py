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
from rop.services.reasoning_run import ReasoningRunService
from rop.services.reasoning_run_consistency import (
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
_STATUS_SKIPPED = "SKIPPED"

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
    "SESSION_VERIFIED": "REASONING_RUN_EXECUTION_STAGE_SESSION_VERIFIED_TASK_044",
    "OBSERVATION_EXTRACTION": (
        "REASONING_RUN_EXECUTION_STAGE_OBSERVATION_EXTRACTION_TASK_044"
    ),
    "MISSING_INFORMATION": "REASONING_RUN_EXECUTION_STAGE_MISSING_INFORMATION_TASK_044",
    "TEMPLATE_MATCHING": "REASONING_RUN_EXECUTION_STAGE_TEMPLATE_MATCHING_TASK_044",
    "CANDIDATE_GENERATION": (
        "REASONING_RUN_EXECUTION_STAGE_CANDIDATE_GENERATION_TASK_044"
    ),
    "EVIDENCE_EVALUATION": "REASONING_RUN_EXECUTION_STAGE_EVIDENCE_EVALUATION_TASK_044",
    "REASONING_RUN": "REASONING_RUN_EXECUTION_STAGE_REASONING_RUN_TASK_044",
    "REASONING_RUN_CONSISTENCY": (
        "REASONING_RUN_EXECUTION_STAGE_REASONING_RUN_CONSISTENCY_TASK_044"
    ),
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

# Public aliases for downstream audit layers (e.g. Task 045) that must
# treat Task 044 as the source of truth for stage identity and sources
# rather than copying divergent values.
EXECUTION_STAGE_IDS = _EXECUTION_STAGE_IDS
EXECUTION_STAGE_SOURCES = _STAGE_SOURCES


class ReasoningRunExecutionContractError(Exception):
    """Task 044: an infrastructure or contract failure.

    Raised only when the session does not exist, or when an
    unexpected internal error prevents the orchestrator from producing
    a valid ReasoningRunExecutionRead at all. Stage failures inside
    the orchestrated workflow are represented as a FAILED execution
    result (returned normally), not raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunExecutionService:
    """Task 044: deterministic reasoning-run execution orchestrator.

    The first write-side composition layer. Runs the established
    deterministic reasoning workflow in order by delegating to the
    existing services -- no reasoning, scoring, ranking, or decision
    logic is reimplemented here. Stage failures are represented as a
    FAILED execution result with partial stage status; downstream
    stages never run after a required earlier stage fails.
    """

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        observation_extraction_service: ObservationExtractionService | None = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        evidence_evaluation_service: EvidenceEvaluationService | None = None,
        reasoning_run_service: ReasoningRunService | None = None,
        reasoning_run_consistency_service: ReasoningRunConsistencyService | None = None,
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
        self.template_match_service = template_match_service or TemplateMatchService()
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )
        self.evidence_evaluation_service = (
            evidence_evaluation_service or EvidenceEvaluationService()
        )
        self.reasoning_run_service = reasoning_run_service or ReasoningRunService()
        self.reasoning_run_consistency_service = (
            reasoning_run_consistency_service or ReasoningRunConsistencyService()
        )

    def execute_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Run the deterministic reasoning workflow end-to-end.

        Every stage delegates to the established service that owns it.
        A stage failure is caught and represented as a FAILED execution
        result: the failing stage is marked FAILED, subsequent stages
        are marked SKIPPED, and ``reasoning_run`` /
        ``reasoning_run_consistency`` stay None. Only a missing session
        raises ReasoningRunExecutionContractError.
        """
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningRunExecutionContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )

        state: dict[str, Any] = {}
        completed_ids: list[str] = ["SESSION_VERIFIED"]
        failed_id: str | None = None

        stages = (
            ("OBSERVATION_EXTRACTION", self._stage_observations),
            ("MISSING_INFORMATION", self._stage_missing_information),
            ("TEMPLATE_MATCHING", self._stage_template_matching),
            ("CANDIDATE_GENERATION", self._stage_candidate_generation),
            ("EVIDENCE_EVALUATION", self._stage_evidence_evaluation),
            ("REASONING_RUN", self._stage_reasoning_run),
            ("REASONING_RUN_CONSISTENCY", self._stage_reasoning_run_consistency),
        )

        for stage_id, method in stages:
            try:
                method(db, session, session_id, state)
            except Exception:
                failed_id = stage_id
                break
            completed_ids.append(stage_id)

        return self._build_result(
            session_id=session_id,
            completed_ids=completed_ids,
            failed_id=failed_id,
            run=state.get("run"),
            audit=state.get("audit"),
        )

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage_observations(self, db, session, session_id, state):
        existing = self._paginate(
            lambda off: self.observation_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            )
        )
        # Reuse existing observation state on repeat execution; only
        # extract when none exists yet.
        if not existing:
            self.observation_extraction_service.extract_and_store(
                db, session_id, session.user_input
            )
        state["observations"] = self._paginate(
            lambda off: self.observation_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            )
        )
        state["entities"] = self._paginate(
            lambda off: self.entity_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            )
        )

    def _stage_missing_information(self, db, session, session_id, state):
        self.missing_information_service.detect_and_store(
            db, session_id, state["observations"]
        )

    def _stage_template_matching(self, db, session, session_id, state):
        existing = self.template_match_service.list_by_session(db, session_id)
        # Same idempotency rule as observations -- do not append a
        # second template match when one already exists.
        if not existing:
            self.template_match_service.match(
                db, session_id, state["observations"], state["entities"]
            )
        state["template_matches"] = self.template_match_service.list_by_session(
            db, session_id
        )

    def _stage_candidate_generation(self, db, session, session_id, state):
        template = self._resolve_template(state.get("template_matches", []))
        missing_information = self.missing_information_service.list_by_session(
            db, session_id
        )
        self.candidate_generation_service.generate(
            db=db,
            session_id=session_id,
            observations=state["observations"],
            entities=state["entities"],
            template=template,
            missing_information=missing_information,
        )
        state["candidates"] = self._paginate(
            lambda off: self.candidate_generation_service.list_by_session(
                db, session_id, offset=off, limit=_CANDIDATE_PAGE_SIZE
            )
        )

    def _stage_evidence_evaluation(self, db, session, session_id, state):
        self.evidence_evaluation_service.evaluate_session(
            db=db,
            session_id=session_id,
            candidates=state["candidates"],
            observations=state["observations"],
            entities=state["entities"],
        )

    def _stage_reasoning_run(self, db, session, session_id, state):
        state["run"] = self.reasoning_run_service.build_for_session(db, session_id)

    def _stage_reasoning_run_consistency(self, db, session, session_id, state):
        state["audit"] = self.reasoning_run_consistency_service.build_for_session(
            db, session_id
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
    def _resolve_template(template_matches: list[Any]) -> Any:
        if not template_matches:
            return None
        from rop.templates import load_templates

        latest = template_matches[-1]
        templates = load_templates()
        return next(
            (t for t in templates if t.name == latest.template_name),
            None,
        )

    @staticmethod
    def _build_result(
        *,
        session_id: UUID,
        completed_ids: list[str],
        failed_id: str | None,
        run: dict[str, Any] | None,
        audit: dict[str, Any] | None,
    ) -> dict[str, Any]:
        completed_set = set(completed_ids)
        stages = []
        for i, sid in enumerate(_EXECUTION_STAGE_IDS):
            if sid in completed_set:
                status = _STATUS_COMPLETED
            elif sid == failed_id:
                status = _STATUS_FAILED
            else:
                status = _STATUS_SKIPPED
            stages.append(
                {
                    "stage_id": sid,
                    "stage_order": i + 1,
                    "stage_source": _STAGE_SOURCES[sid],
                    "status": status,
                }
            )
        completed_stage_count = sum(
            1 for s in stages if s["status"] == _STATUS_COMPLETED
        )
        if failed_id is None:
            outcome = OUTCOME_COMPLETED
            available = True
        else:
            outcome = OUTCOME_FAILED
            available = False
            # Per the Task 044 FAILED contract, both nested results
            # must be absent on any stage failure -- including when a
            # later stage failed after the reasoning run was already
            # composed earlier in the same execution.
            run = None
            audit = None
        execution_consistent = (
            bool(audit.get("run_consistent", False)) if audit is not None else False
        )
        result: dict[str, Any] = {
            "available": available,
            "outcome": outcome,
            "execution_consistent": execution_consistent,
            "session_id": session_id,
            "completed_stage_count": completed_stage_count,
            "stage_count": len(stages),
            "stages": stages,
            "reasoning_run": run,
            "reasoning_run_consistency": audit,
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
                "outcome is not a known identifier: " + repr(result["outcome"]),
            )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningRunExecutionContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
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
                "stage_count "
                + repr(result["stage_count"])
                + " != len(stages) "
                + repr(len(stages)),
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
                    "DUPLICATE_STAGE_ID",
                    "duplicate stage_id: " + str(s["stage_id"]),
                )
            seen_ids.add(s["stage_id"])
            if s["stage_order"] != expected_order:
                raise ReasoningRunExecutionContractError(
                    "STAGE_ORDER_MISMATCH",
                    "stage_order "
                    + repr(s["stage_order"])
                    + " != expected "
                    + repr(expected_order),
                )
            expected_order += 1
            if s["status"] not in (
                _STATUS_COMPLETED,
                _STATUS_FAILED,
                _STATUS_SKIPPED,
            ):
                raise ReasoningRunExecutionContractError(
                    "INVALID_STAGE_STATUS",
                    "stage status is not a known identifier: " + repr(s["status"]),
                )
        completed = sum(1 for s in stages if s["status"] == _STATUS_COMPLETED)
        if result["completed_stage_count"] != completed:
            raise ReasoningRunExecutionContractError(
                "COMPLETED_COUNT_MISMATCH",
                "completed_stage_count "
                + repr(result["completed_stage_count"])
                + " != actual "
                + repr(completed),
            )
        # Stage IDs must match the declared Task 044 stage list in
        # exact order, and each stage_source must match its canonical
        # _STAGE_SOURCES entry.
        actual_ids = tuple(s["stage_id"] for s in stages)
        if actual_ids != _EXECUTION_STAGE_IDS:
            raise ReasoningRunExecutionContractError(
                "STAGE_IDS_MISMATCH",
                "stage_ids "
                + repr(actual_ids)
                + " != declared "
                + repr(_EXECUTION_STAGE_IDS),
            )
        for s in stages:
            expected_source = _STAGE_SOURCES.get(s["stage_id"])
            if s["stage_source"] != expected_source:
                raise ReasoningRunExecutionContractError(
                    "STAGE_SOURCE_MISMATCH",
                    "stage_id "
                    + repr(s["stage_id"])
                    + " has stage_source "
                    + repr(s["stage_source"])
                    + ", expected "
                    + repr(expected_source),
                )
        # reasoning_run / reasoning_run_consistency are nullable.
        if result["reasoning_run"] is not None and not isinstance(
            result["reasoning_run"], dict
        ):
            raise ReasoningRunExecutionContractError(
                "REASONING_RUN_TYPE",
                "reasoning_run is not a dict or None: "
                + type(result["reasoning_run"]).__name__,
            )
        if result["reasoning_run_consistency"] is not None and not isinstance(
            result["reasoning_run_consistency"], dict
        ):
            raise ReasoningRunExecutionContractError(
                "REASONING_RUN_CONSISTENCY_TYPE",
                "reasoning_run_consistency is not a dict or None: "
                + type(result["reasoning_run_consistency"]).__name__,
            )
        if result["outcome"] == OUTCOME_COMPLETED:
            if result["reasoning_run"] is None:
                raise ReasoningRunExecutionContractError(
                    "COMPLETED_WITHOUT_RUN",
                    "COMPLETED outcome requires a reasoning_run",
                )
            if result["reasoning_run_consistency"] is None:
                raise ReasoningRunExecutionContractError(
                    "COMPLETED_WITHOUT_AUDIT",
                    "COMPLETED outcome requires a " "reasoning_run_consistency",
                )
        if result["outcome"] == OUTCOME_FAILED:
            if result["available"] is not False:
                raise ReasoningRunExecutionContractError(
                    "FAILED_MUST_BE_UNAVAILABLE",
                    "FAILED outcome requires available=False",
                )
        if result["execution_source"] != REASONING_RUN_EXECUTION_SOURCE_TASK_044:
            raise ReasoningRunExecutionContractError(
                "INVALID_EXECUTION_SOURCE",
                "execution_source is not the Task 044 identifier: "
                + repr(result["execution_source"]),
            )

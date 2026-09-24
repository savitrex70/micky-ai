from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.candidate_generation import CandidateGenerationService
from rop.services.entity import EntityService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
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

REASONING_CONTEXT_SOURCE_TASK_055 = "REASONING_CONTEXT_TASK_055"

_STATE_PAGE_SIZE = 1000
_CANDIDATE_PAGE_SIZE = 100

_RESULT_REQUIRED_FIELDS = (
    "available",
    "context_consistent",
    "session_id",
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
    "reasoning_pipeline",
    "reasoning_run_consistency",
    "context_source",
)

_RESULT_BOOLEAN_FIELDS = ("available", "context_consistent")

_RESULT_LIST_FIELDS = (
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
)


def _coerce_session_id(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError):
            return None
    return None


class ReasoningContextContractError(Exception):
    """Task 055: the supplied reasoning state cannot be assembled into
    a valid ReasoningContextRead.

    Raised when a required input is malformed, when the nested Task 042
    or Task 043 structure violates its own contract, or when the
    session does not exist. It is never raised for a normal reasoning
    state -- an incomplete or inconsistent run is faithfully preserved
    through the nested structures.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningContextService:
    """Task 055: canonical reasoning-context assembly.

    Pure assembly only. Does not generate candidates, rank, score,
    filter, select, diagnose, recommend, call an LLM, or touch the
    database from its pure ``build`` path. Delegates its session-level
    state reads to the established per-session services.
    """

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        reasoning_run_service: ReasoningRunService | None = None,
        reasoning_run_consistency_service: ReasoningRunConsistencyService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.observation_service = observation_service or ObservationService()
        self.entity_service = entity_service or EntityService()
        self.missing_information_service = (
            missing_information_service or MissingInformationService()
        )
        self.template_match_service = template_match_service or TemplateMatchService()
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )
        self.reasoning_run_service = reasoning_run_service or ReasoningRunService()
        self.reasoning_run_consistency_service = (
            reasoning_run_consistency_service or ReasoningRunConsistencyService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Read the session's reasoning state and assemble a context."""
        if self.reasoning_session_service.get(db, session_id) is None:
            raise ReasoningContextContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )
        observations = self._paginate(
            lambda off: self.observation_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            ),
            _STATE_PAGE_SIZE,
        )
        entities = self._paginate(
            lambda off: self.entity_service.list_by_session(
                db, session_id, offset=off, limit=_STATE_PAGE_SIZE
            ),
            _STATE_PAGE_SIZE,
        )
        missing_information = self.missing_information_service.list_by_session(
            db, session_id
        )
        template_matches = self.template_match_service.list_by_session(db, session_id)
        candidates = self._paginate(
            lambda off: self.candidate_generation_service.list_by_session(
                db, session_id, offset=off, limit=_CANDIDATE_PAGE_SIZE
            ),
            _CANDIDATE_PAGE_SIZE,
        )
        # Build Task 042 exactly once and reuse its intermediates so
        # Task 043 audits the exact run being packaged, rather than
        # independently rebuilding a second Task 042 run.
        try:
            run, bundle, policy = (
                self.reasoning_run_service.build_for_session_with_inputs(db, session_id)
            )
        except ReasoningRunContractError as exc:
            raise ReasoningContextContractError(
                "REASONING_RUN_FAILED",
                "Task 042 composition failed: " + str(exc),
            ) from exc
        try:
            audit = self.reasoning_run_consistency_service.build(
                run=run,
                observations=observations,
                entities=entities,
                missing_information=missing_information,
                template_matches=template_matches,
                candidates=candidates,
                bundle=bundle,
                policy=policy,
            )
        except ReasoningRunConsistencyContractError as exc:
            raise ReasoningContextContractError(
                "REASONING_RUN_CONSISTENCY_FAILED",
                "Task 043 audit failed: " + str(exc),
            ) from exc
        return self.build(
            session_id=session_id,
            observations=observations,
            entities=entities,
            missing_information=missing_information,
            template_context=template_matches,
            candidate_state=candidates,
            reasoning_run=run,
            reasoning_run_consistency=audit,
        )

    def build(
        self,
        *,
        session_id: Any = None,
        observations: list[Any] | None = None,
        entities: list[Any] | None = None,
        missing_information: list[Any] | None = None,
        template_context: list[Any] | None = None,
        candidate_state: list[Any] | None = None,
        reasoning_run: Mapping[str, Any] | None = None,
        reasoning_run_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the context. Pure; never mutates inputs."""
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningContextContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        for name, value in (
            ("observations", observations),
            ("entities", entities),
            ("missing_information", missing_information),
            ("template_context", template_context),
            ("candidate_state", candidate_state),
        ):
            if not isinstance(value, list):
                raise ReasoningContextContractError(
                    name.upper() + "_TYPE",
                    name + " is not a list: " + type(value).__name__,
                )
        if not isinstance(reasoning_run, Mapping):
            raise ReasoningContextContractError(
                "MISSING_REASONING_RUN",
                "reasoning_run is required and must be a mapping",
            )
        if not isinstance(reasoning_run_consistency, Mapping):
            raise ReasoningContextContractError(
                "MISSING_REASONING_RUN_CONSISTENCY",
                "reasoning_run_consistency is required and must be a " "mapping",
            )

        # Validate the nested Task 042 and Task 043 contracts using
        # their own single-argument validators.
        try:
            ReasoningRunService._validate_result(dict(reasoning_run))
        except ReasoningRunContractError as exc:
            raise ReasoningContextContractError(
                "INVALID_REASONING_RUN",
                "Task 042 run failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningContextContractError(
                "INVALID_REASONING_RUN",
                "Task 042 run failed its own validator: " + str(exc),
            ) from exc

        try:
            ReasoningRunConsistencyService._validate_result(
                dict(reasoning_run_consistency)
            )
        except ReasoningRunConsistencyContractError as exc:
            raise ReasoningContextContractError(
                "INVALID_REASONING_RUN_CONSISTENCY",
                "Task 043 audit failed its own validator: " + str(exc),
            ) from exc
        except Exception as exc:
            raise ReasoningContextContractError(
                "INVALID_REASONING_RUN_CONSISTENCY",
                "Task 043 audit failed its own validator: " + str(exc),
            ) from exc

        # Prove the Task 043 audit corresponds to this exact Task 042
        # run. Recompute the run fingerprint with Task 043's own
        # staticmethod (delegated, not reimplemented) and require an
        # exact match against the audit's provenance field.
        try:
            expected_fingerprint = ReasoningRunConsistencyService._run_fingerprint(
                reasoning_run
            )
        except Exception as exc:
            raise ReasoningContextContractError(
                "AUDIT_RUN_FINGERPRINT_COMPUTE_FAILED",
                "could not compute the Task 042 run fingerprint: " + str(exc),
            ) from exc
        if (
            reasoning_run_consistency.get("audited_run_fingerprint")
            != expected_fingerprint
        ):
            raise ReasoningContextContractError(
                "AUDIT_RUN_MISMATCH",
                "reasoning_run_consistency.audited_run_fingerprint does "
                "not match the supplied Task 042 run",
            )

        available = bool(reasoning_run.get("available")) and bool(
            reasoning_run_consistency.get("available")
        )

        run_candidate_count = reasoning_run.get("candidate_count")
        context_consistent = (
            isinstance(run_candidate_count, int)
            and not isinstance(run_candidate_count, bool)
            and run_candidate_count == len(candidate_state)
        )

        result: dict[str, Any] = {
            "available": available,
            "context_consistent": context_consistent,
            "session_id": sid,
            "observations": observations,
            "entities": entities,
            "missing_information": missing_information,
            "template_context": template_context,
            "candidate_state": candidate_state,
            "reasoning_pipeline": dict(reasoning_run),
            "reasoning_run_consistency": dict(reasoning_run_consistency),
            "context_source": REASONING_CONTEXT_SOURCE_TASK_055,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _paginate(
        fetch_page: Callable[[int], list[Any]],
        page_size: int,
    ) -> list[Any]:
        results: list[Any] = []
        offset = 0
        while True:
            page = fetch_page(offset)
            results.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return results

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESULT_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningContextContractError(
                    "MISSING_RESULT_FIELD", "result has no " + field
                )
        for field in _RESULT_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningContextContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningContextContractError(
                "SESSION_ID_TYPE",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        for field in _RESULT_LIST_FIELDS:
            if not isinstance(result[field], list):
                raise ReasoningContextContractError(
                    field.upper() + "_TYPE",
                    field + " is not a list: " + type(result[field]).__name__,
                )
        if not isinstance(result["reasoning_pipeline"], Mapping):
            raise ReasoningContextContractError(
                "REASONING_PIPELINE_TYPE",
                "reasoning_pipeline is not a mapping: "
                + type(result["reasoning_pipeline"]).__name__,
            )
        if not isinstance(result["reasoning_run_consistency"], Mapping):
            raise ReasoningContextContractError(
                "REASONING_RUN_CONSISTENCY_TYPE",
                "reasoning_run_consistency is not a mapping: "
                + type(result["reasoning_run_consistency"]).__name__,
            )
        try:
            ReasoningRunService._validate_result(dict(result["reasoning_pipeline"]))
        except Exception as exc:
            raise ReasoningContextContractError(
                "INVALID_REASONING_RUN",
                "nested Task 042 run failed its own validator: " + str(exc),
            ) from exc
        try:
            ReasoningRunConsistencyService._validate_result(
                dict(result["reasoning_run_consistency"])
            )
        except Exception as exc:
            raise ReasoningContextContractError(
                "INVALID_REASONING_RUN_CONSISTENCY",
                "nested Task 043 audit failed its own validator: " + str(exc),
            ) from exc
        if result["context_source"] != REASONING_CONTEXT_SOURCE_TASK_055:
            raise ReasoningContextContractError(
                "INVALID_CONTEXT_SOURCE",
                "context_source is not the Task 055 identifier: "
                + repr(result["context_source"]),
            )

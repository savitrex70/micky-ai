"""Task 124: canonical deterministic reasoning-run input snapshot.

Reads every reasoning-run input collection exactly once, deep-freezes
the values into JSON-safe data, and validates the frozen shape through
the strict snapshot schema. Later database mutations cannot alter a
snapshot that has already been taken.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_input_snapshot import (
    ReasoningRunInputSnapshotRead,
)
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.entity import EntityService
from rop.services.evidence_evaluation import EvidenceEvaluationService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.reasoning_session import ReasoningSessionService
from rop.services.template_match import TemplateMatchService

REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124 = "REASONING_RUN_INPUT_SNAPSHOT_TASK_124"

_SNAPSHOT_PAGE_SIZE = 1000


class ReasoningRunInputSnapshotContractError(Exception):
    """Task 124: the input snapshot could not be established."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunInputSnapshotService:
    """Builds one frozen snapshot of all reasoning-run inputs."""

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        evidence_evaluation_service: EvidenceEvaluationService | None = None,
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
        self.evidence_evaluation_service = (
            evidence_evaluation_service or EvidenceEvaluationService()
        )

    def build_snapshot(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Read every input collection once and return the frozen snapshot.

        Each collection is read exactly once from the database and then
        validated through the strict snapshot schema, so the returned
        dict is fully detached JSON-safe data: later database mutations
        cannot alter it.
        """
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningRunInputSnapshotContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )
        try:
            observations = self._paginate(
                lambda off: self.observation_service.list_by_session(
                    db, session_id, offset=off, limit=_SNAPSHOT_PAGE_SIZE
                )
            )
            entities = self._paginate(
                lambda off: self.entity_service.list_by_session(
                    db, session_id, offset=off, limit=_SNAPSHOT_PAGE_SIZE
                )
            )
            missing_information = self.missing_information_service.list_by_session(
                db, session_id
            )
            template_matches = self.template_match_service.list_by_session(
                db, session_id
            )
            candidates = self._paginate(
                lambda off: self.candidate_generation_service.list_by_session(
                    db, session_id, offset=off, limit=_SNAPSHOT_PAGE_SIZE
                )
            )
            evidence = self._paginate(
                lambda off: self.evidence_evaluation_service.list_by_session(
                    db, session_id, offset=off, limit=_SNAPSHOT_PAGE_SIZE
                )
            )
            snapshot = ReasoningRunInputSnapshotRead.model_validate(
                {
                    "session_id": session_id,
                    "user_input": session.user_input,
                    "observations": observations,
                    "entities": entities,
                    "missing_information": missing_information,
                    "template_matches": template_matches,
                    "candidates": candidates,
                    "evidence": evidence,
                    "candidate_order": [str(c.id) for c in candidates],
                    "evidence_order": [str(e.id) for e in evidence],
                    "snapshot_source": (REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124),
                }
            )
        except ReasoningRunInputSnapshotContractError:
            raise
        except Exception as exc:
            raise ReasoningRunInputSnapshotContractError(
                "SNAPSHOT_BUILD_FAILED",
                "input snapshot could not be established: " + type(exc).__name__,
            ) from exc
        return snapshot.model_dump(mode="json")

    @staticmethod
    def _paginate(fetch_page: Any) -> list[Any]:
        results: list[Any] = []
        offset = 0
        while True:
            page = fetch_page(offset)
            results.extend(page)
            if len(page) < _SNAPSHOT_PAGE_SIZE:
                break
            offset += _SNAPSHOT_PAGE_SIZE
        return results

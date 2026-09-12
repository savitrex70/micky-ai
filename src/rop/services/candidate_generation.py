from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.candidates import CandidateGenerator, load_hypothesis_rules
from rop.candidates.models import HypothesisRule
from rop.models import CandidateHypothesis, Entity, Observation
from rop.repositories import CandidateHypothesisRepository
from rop.schemas import MissingInformationRead
from rop.templates import ClinicalTemplate


class CandidateGenerationService:
    """Generate candidate hypotheses from observations and rules."""

    def __init__(
        self,
        rules: tuple[HypothesisRule, ...] | None = None,
        repository: CandidateHypothesisRepository | None = None,
    ) -> None:
        self.rules = rules or load_hypothesis_rules()
        self.repository = repository or CandidateHypothesisRepository()
        self.generator = CandidateGenerator(rules=self.rules)

    def generate(
        self,
        db: Session,
        session_id: UUID,
        observations: list[Observation],
        entities: list[Entity],
        template: ClinicalTemplate | None = None,
        missing_information: (
            list[MissingInformationRead] | list[dict[str, Any]] | None
        ) = None,
    ) -> list[CandidateHypothesis]:
        self.repository.delete_by_session(db, session_id)

        candidates = self.generator.generate(
            session_id=session_id,
            observations=observations,
            entities=entities,
            template=template,
            missing_information=missing_information,
        )

        if not candidates:
            return []

        return self.repository.create_many(db, session_id, candidates)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[CandidateHypothesis]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

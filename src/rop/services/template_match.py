from rop.models import Entity, Observation, TemplateMatch
from rop.repositories import TemplateMatchRepository
from rop.templates import (
    ClinicalTemplate,
    load_templates,
    match_template,
)


class TemplateMatchService:
    """Match the most appropriate clinical template for a reasoning session."""

    def __init__(
        self,
        templates: tuple[ClinicalTemplate, ...] | None = None,
        repository: TemplateMatchRepository | None = None,
    ) -> None:
        self.templates = templates or load_templates()
        self.repository = repository or TemplateMatchRepository()

    def match(
        self,
        db: object,
        session_id: object,
        observations: list[Observation],
        entities: list[Entity],
    ) -> TemplateMatch:
        from sqlalchemy.orm import Session

        if not isinstance(db, Session):
            raise TypeError("db must be a sqlalchemy.orm.Session")

        from uuid import UUID

        if not isinstance(session_id, UUID):
            raise TypeError("session_id must be a UUID")

        result = match_template(self.templates, observations, entities)

        candidate_payloads = []
        for candidate in result.candidates:
            candidate_payloads.append(
                {
                    "template_name": candidate.template.name,
                    "score": candidate.score,
                    "matched_observation_count": candidate.matched_observation_count,
                    "matched_entity_count": candidate.matched_entity_count,
                    "matched_rule_categories": candidate.matched_rule_categories,
                    "total_rule_categories": candidate.total_rule_categories,
                    "matched_observation_texts": list(
                        candidate.matched_observation_texts
                    ),
                    "matched_entity_names": list(candidate.matched_entity_names),
                }
            )

        record = TemplateMatch(
            session_id=session_id,
            template_name=result.selected_template.name,
            confidence=result.confidence,
            matched_observations=list(result.matched_observations),
            matched_entities=list(result.matched_entities),
            reason=result.reason,
            candidates=candidate_payloads,
        )

        return self.repository.create(db, record)

    def list_by_session(
        self, db: object, session_id: object
    ) -> list[TemplateMatch]:
        from uuid import UUID

        from sqlalchemy.orm import Session

        if not isinstance(db, Session):
            raise TypeError("db must be a sqlalchemy.orm.Session")
        if not isinstance(session_id, UUID):
            raise TypeError("session_id must be a UUID")

        return self.repository.list_by_session(db, session_id)

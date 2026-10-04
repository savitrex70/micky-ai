from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base
from rop.models import TemplateMatch
from rop.schemas import (
    EntityCreate,
    ObservationCreate,
    ReasoningSessionCreate,
)
from rop.services import (
    EntityService,
    ObservationService,
    ReasoningSessionService,
    TemplateMatchService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_template_match_model_has_required_columns() -> None:
    columns = {column.name for column in TemplateMatch.__table__.columns}

    assert columns == {
        "id",
        "session_id",
        "template_name",
        "confidence",
        "matched_observations",
        "matched_entities",
        "reason",
        "candidates",
        "created_at",
    }


def test_service_creates_template_match() -> None:
    with TestingSessionLocal() as db:
        session_service = ReasoningSessionService()
        observation_service = ObservationService()
        entity_service = EntityService()
        template_match_service = TemplateMatchService()

        reasoning_session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="clinical",
                user_input="Chest pain patient",
                current_stage="initial",
            ),
        )

        observations = [
            observation_service.create(
                db,
                ObservationCreate(
                    session_id=reasoning_session.id,
                    text="Symptom = Chest pain",
                    type="symptom",
                    confidence=0.95,
                    source="rule_based",
                ),
            ),
            observation_service.create(
                db,
                ObservationCreate(
                    session_id=reasoning_session.id,
                    text="Radiation = Left arm",
                    type="body_location",
                    confidence=0.92,
                    source="rule_based",
                ),
            ),
        ]

        entities = [
            entity_service.create(
                db,
                EntityCreate(
                    session_id=reasoning_session.id,
                    name="Left arm",
                    category="body_location",
                    confidence=0.9,
                    source="rule_based",
                ),
            ),
        ]

        match = template_match_service.match(
            db, reasoning_session.id, observations, entities
        )

        assert match.session_id == reasoning_session.id
        assert match.template_name == "acute_coronary_syndrome"
        assert match.confidence > 0.0
        assert "Symptom = Chest pain" in match.matched_observations
        assert "Left arm" in match.matched_entities
        assert match.reason != ""
        assert len(match.candidates) > 0


def test_service_lists_matches_by_session() -> None:
    with TestingSessionLocal() as db:
        session_service = ReasoningSessionService()
        observation_service = ObservationService()
        template_match_service = TemplateMatchService()

        reasoning_session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="clinical",
                user_input="Headache patient",
                current_stage="initial",
            ),
        )

        observation_service.create(
            db,
            ObservationCreate(
                session_id=reasoning_session.id,
                text="Symptom = Headache",
                type="symptom",
                confidence=0.9,
                source="rule_based",
            ),
        )

        match = template_match_service.match(db, reasoning_session.id, [], [])

        matches = template_match_service.list_by_session(db, reasoning_session.id)
        assert len(matches) == 1
        assert matches[0].id == match.id

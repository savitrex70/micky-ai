from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rop.database import Base
from rop.models import Observation
from rop.schemas import (
    ObservationCreate,
    ObservationRead,
    ObservationUpdate,
    ReasoningSessionCreate,
)
from rop.services import ObservationService, ReasoningSessionService

engine = create_engine("sqlite+pysqlite:///:memory:")
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_observation_crud_and_session_relationship() -> None:
    session_service = ReasoningSessionService()
    observation_service = ObservationService()

    with TestingSessionLocal() as db:
        reasoning_session = session_service.create(
            db,
            data=ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )
        data = ObservationCreate(
            session_id=reasoning_session.id,
            text="A factual observation",
            type="fact",
            confidence=0.85,
            source="unit-test",
        )

        observation = observation_service.create(db, data)

        assert observation.session_id == reasoning_session.id
        assert observation.session is reasoning_session
        assert reasoning_session.observations == [observation]
        assert observation_service.get(db, observation.id) is observation
        assert observation_service.list_by_session(db, reasoning_session.id) == [
            observation
        ]

        updated = observation_service.update(
            db,
            observation.id,
            ObservationUpdate(confidence=0.95),
        )
        assert updated is not None
        assert updated.confidence == 0.95
        assert ObservationRead.model_validate(updated).text == "A factual observation"

        assert observation_service.delete(db, observation.id) is True
        assert observation_service.get(db, observation.id) is None
        assert observation_service.delete(db, observation.id) is False


def test_observation_requires_confidence_between_zero_and_one() -> None:
    values = {
        "session_id": uuid4(),
        "text": "An observation",
        "type": "fact",
        "source": "unit-test",
    }

    with pytest.raises(ValidationError):
        ObservationCreate(confidence=1.1, **values)

    with pytest.raises(ValidationError):
        ObservationCreate(confidence=-0.1, **values)


def test_observation_table_has_required_columns() -> None:
    columns = {column.name for column in Observation.__table__.columns}

    assert columns == {
        "id",
        "session_id",
        "text",
        "type",
        "confidence",
        "source",
        "timestamp",
    }

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rop.database import Base
from rop.models import Entity
from rop.schemas import EntityCreate, EntityRead, EntityUpdate, ReasoningSessionCreate
from rop.services import EntityService, ReasoningSessionService

engine = create_engine("sqlite+pysqlite:///:memory:")
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_entity_crud_and_session_relationship() -> None:
    session_service = ReasoningSessionService()
    entity_service = EntityService()

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
        data = EntityCreate(
            session_id=reasoning_session.id,
            name="Ada Lovelace",
            category="person",
            confidence=0.9,
            source="unit-test",
        )

        entity = entity_service.create(db, data)

        assert entity.session_id == reasoning_session.id
        assert entity.session is reasoning_session
        assert reasoning_session.entities == [entity]
        assert entity_service.get(db, entity.id) is entity
        assert entity_service.list_by_session(db, reasoning_session.id) == [entity]

        updated = entity_service.update(
            db,
            entity.id,
            EntityUpdate(category="historical-person", confidence=0.95),
        )
        assert updated is not None
        assert updated.category == "historical-person"
        assert EntityRead.model_validate(updated).name == "Ada Lovelace"

        assert entity_service.delete(db, entity.id) is True
        assert entity_service.get(db, entity.id) is None
        assert entity_service.delete(db, entity.id) is False


def test_entity_requires_confidence_between_zero_and_one() -> None:
    values = {
        "session_id": uuid4(),
        "name": "An entity",
        "category": "concept",
        "source": "unit-test",
    }

    with pytest.raises(ValidationError):
        EntityCreate(confidence=1.1, **values)

    with pytest.raises(ValidationError):
        EntityCreate(confidence=-0.1, **values)


def test_entity_table_has_required_columns() -> None:
    columns = {column.name for column in Entity.__table__.columns}

    assert columns == {
        "id",
        "session_id",
        "name",
        "category",
        "confidence",
        "source",
    }

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rop.database import Base
from rop.models import ReasoningSession
from rop.repositories import ReasoningSessionRepository
from rop.schemas import (
    ReasoningSessionCreate,
    ReasoningSessionRead,
    ReasoningSessionUpdate,
)
from rop.services import ReasoningSessionService

engine = create_engine("sqlite+pysqlite:///:memory:")
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_reasoning_session_crud() -> None:
    repository = ReasoningSessionRepository()
    service = ReasoningSessionService(repository)
    data = ReasoningSessionCreate(
        status="created",
        domain="testing",
        user_input="A test input",
        current_stage="initial",
        metadata={"source": "unit-test"},
    )

    with TestingSessionLocal() as db:
        created = service.create(db, data)
        session_id = created.id

        assert isinstance(session_id, type(uuid4()))
        assert created.metadata_ == {"source": "unit-test"}
        assert service.get(db, session_id) is created
        assert len(service.list(db)) == 1

        updated = service.update(
            db,
            session_id,
            ReasoningSessionUpdate(notes="Added during the test"),
        )
        assert updated is not None
        assert updated.notes == "Added during the test"

        serialized = ReasoningSessionRead.model_validate(updated)
        assert serialized.metadata == {"source": "unit-test"}
        assert service.delete(db, session_id) is True
        assert service.get(db, session_id) is None
        assert service.delete(db, session_id) is False


def test_reasoning_session_table_has_required_columns() -> None:
    columns = {column.name for column in ReasoningSession.__table__.columns}

    assert columns == {
        "id",
        "created_at",
        "updated_at",
        "status",
        "domain",
        "user_input",
        "current_stage",
        "notes",
        "metadata",
    }

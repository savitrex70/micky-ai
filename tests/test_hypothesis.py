from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rop.database import Base
from rop.models import Hypothesis
from rop.models.hypothesis import HypothesisStatus
from rop.schemas import (
    HypothesisCreate,
    HypothesisRead,
    HypothesisUpdate,
    ReasoningSessionCreate,
)
from rop.services import HypothesisService, ReasoningSessionService

engine = create_engine("sqlite+pysqlite:///:memory:")
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_hypothesis_crud_and_session_relationship() -> None:
    session_service = ReasoningSessionService()
    hypothesis_service = HypothesisService()

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
        data = HypothesisCreate(
            session_id=reasoning_session.id,
            title="The system is available",
            description="The service responds successfully to health checks.",
            category="system",
            status=HypothesisStatus.ACTIVE,
            likelihood_score=0.8,
            rank=2,
            reason="Initial hypothesis",
        )

        hypothesis = hypothesis_service.create(db, data)

        assert hypothesis.session_id == reasoning_session.id
        assert hypothesis.session is reasoning_session
        assert reasoning_session.hypotheses == [hypothesis]
        assert hypothesis_service.get(db, hypothesis.id) is hypothesis
        assert hypothesis_service.list_by_session(db, reasoning_session.id) == [
            hypothesis
        ]

        updated = hypothesis_service.update(
            db,
            hypothesis.id,
            HypothesisUpdate(rank=1, status=HypothesisStatus.SUPPORTED),
        )
        assert updated is not None
        assert updated.rank == 1
        assert updated.status == HypothesisStatus.SUPPORTED
        assert HypothesisRead.model_validate(updated).title == (
            "The system is available"
        )

        assert hypothesis_service.delete(db, hypothesis.id) is True
        assert hypothesis_service.get(db, hypothesis.id) is None
        assert hypothesis_service.delete(db, hypothesis.id) is False


def test_hypothesis_requires_valid_likelihood_and_rank() -> None:
    values = {
        "session_id": uuid4(),
        "title": "A hypothesis",
        "description": "A test description",
        "category": "system",
        "status": HypothesisStatus.PENDING,
    }

    with pytest.raises(ValidationError):
        HypothesisCreate(likelihood_score=1.1, rank=1, **values)

    with pytest.raises(ValidationError):
        HypothesisCreate(likelihood_score=0.5, rank=-1, **values)


def test_hypothesis_status_enum() -> None:
    valid_statuses = {
        HypothesisStatus.PENDING,
        HypothesisStatus.ACTIVE,
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.CONTRADICTED,
        HypothesisStatus.REJECTED,
        HypothesisStatus.CONFIRMED,
    }

    with TestingSessionLocal() as db:
        session_service = ReasoningSessionService()
        hypothesis_service = HypothesisService()

        reasoning_session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )

        for status in valid_statuses:
            hypothesis = hypothesis_service.create(
                db,
                HypothesisCreate(
                    session_id=reasoning_session.id,
                    title=f"Hypothesis {status.value}",
                    description="Test",
                    category="system",
                    status=status,
                    likelihood_score=0.5,
                    rank=1,
                ),
            )
            assert hypothesis.status == status


def test_hypothesis_table_has_required_columns() -> None:
    columns = {column.name for column in Hypothesis.__table__.columns}

    assert columns == {
        "id",
        "session_id",
        "title",
        "description",
        "category",
        "status",
        "likelihood_score",
        "rank",
        "reason",
        "created_at",
        "updated_at",
    }


def test_service_filters_by_status() -> None:
    with TestingSessionLocal() as db:
        session_service = ReasoningSessionService()
        hypothesis_service = HypothesisService()

        reasoning_session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )

        for status in [HypothesisStatus.PENDING, HypothesisStatus.ACTIVE]:
            hypothesis_service.create(
                db,
                HypothesisCreate(
                    session_id=reasoning_session.id,
                    title=f"Hypothesis {status.value}",
                    description="Test",
                    category="system",
                    status=status,
                    likelihood_score=0.5,
                    rank=1,
                ),
            )

        pending = hypothesis_service.list_by_status(
            db, reasoning_session.id, HypothesisStatus.PENDING
        )
        assert len(pending) == 1
        assert pending[0].status == HypothesisStatus.PENDING

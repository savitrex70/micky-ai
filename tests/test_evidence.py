from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rop.database import Base
from rop.models import Evidence
from rop.models.evidence import EvidenceStrength, EvidenceType
from rop.schemas import (
    EvidenceCreate,
    EvidenceRead,
    EvidenceUpdate,
    HypothesisCreate,
    ReasoningSessionCreate,
)
from rop.services import EvidenceService, HypothesisService, ReasoningSessionService

engine = create_engine("sqlite+pysqlite:///:memory:")
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def test_evidence_crud_and_hypothesis_relationship() -> None:
    session_service = ReasoningSessionService()
    hypothesis_service = HypothesisService()
    evidence_service = EvidenceService()

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
        hypothesis = hypothesis_service.create(
            db,
            data=HypothesisCreate(
                session_id=reasoning_session.id,
                title="The service is available",
                description="The service responds to requests.",
                category="system",
                status="active",
                likelihood_score=0.8,
                rank=1,
            ),
        )
        data = EvidenceCreate(
            hypothesis_id=hypothesis.id,
            session_id=reasoning_session.id,
            type=EvidenceType.SUPPORTING,
            text="The health endpoint returned a successful response.",
            source="unit-test",
            confidence=0.95,
            strength=EvidenceStrength.STRONG,
        )

        evidence = evidence_service.create(db, data)

        assert evidence.hypothesis_id == hypothesis.id
        assert evidence.session_id == reasoning_session.id
        assert evidence.hypothesis is hypothesis
        assert hypothesis.evidence == [evidence]
        assert evidence_service.get(db, evidence.id) is evidence
        assert evidence_service.list_by_hypothesis(db, hypothesis.id) == [evidence]
        assert evidence_service.list_by_session(db, reasoning_session.id) == [evidence]

        updated = evidence_service.update(
            db,
            evidence.id,
            EvidenceUpdate(
                type=EvidenceType.CONTRADICTING,
                confidence=0.4,
                strength=EvidenceStrength.WEAK,
            ),
        )
        assert updated is not None
        assert updated.type == EvidenceType.CONTRADICTING
        assert updated.confidence == 0.4
        assert updated.strength == EvidenceStrength.WEAK
        assert EvidenceRead.model_validate(updated).text.startswith("The health")

        assert evidence_service.delete(db, evidence.id) is True
        assert evidence_service.get(db, evidence.id) is None
        assert evidence_service.delete(db, evidence.id) is False


def test_evidence_requires_valid_type_and_confidence() -> None:
    values = {
        "hypothesis_id": uuid4(),
        "session_id": uuid4(),
        "text": "A piece of evidence",
        "source": "unit-test",
    }

    with pytest.raises(ValidationError):
        EvidenceCreate(type="uncertain", confidence=0.5, **values)

    with pytest.raises(ValidationError):
        EvidenceCreate(type=EvidenceType.SUPPORTING, confidence=1.1, **values)


def test_evidence_requires_valid_strength() -> None:
    values = {
        "hypothesis_id": uuid4(),
        "session_id": uuid4(),
        "type": EvidenceType.SUPPORTING,
        "text": "A piece of evidence",
        "source": "unit-test",
        "confidence": 0.5,
    }

    with pytest.raises(ValidationError):
        EvidenceCreate(strength="invalid_strength", **values)


def test_evidence_table_has_required_columns() -> None:
    columns = {column.name for column in Evidence.__table__.columns}

    assert columns == {
        "id",
        "hypothesis_id",
        "session_id",
        "type",
        "source",
        "text",
        "confidence",
        "strength",
        "created_at",
    }


def test_service_filters_evidence_by_session() -> None:
    with TestingSessionLocal() as db:
        session_service = ReasoningSessionService()
        hypothesis_service = HypothesisService()
        evidence_service = EvidenceService()

        reasoning_session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="testing",
                user_input="A test input",
                current_stage="initial",
            ),
        )
        hypothesis = hypothesis_service.create(
            db,
            HypothesisCreate(
                session_id=reasoning_session.id,
                title="Hypothesis",
                description="Test",
                category="system",
                status="active",
                likelihood_score=0.5,
                rank=1,
            ),
        )

        evidence_service.create(
            db,
            EvidenceCreate(
                hypothesis_id=hypothesis.id,
                session_id=reasoning_session.id,
                type=EvidenceType.SUPPORTING,
                text="Evidence 1",
                source="unit-test",
                confidence=0.9,
                strength=EvidenceStrength.STRONG,
            ),
        )

        results = evidence_service.list_by_session(db, reasoning_session.id)
        assert len(results) == 1
        assert results[0].session_id == reasoning_session.id

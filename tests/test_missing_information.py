from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base
from rop.missing_information import (
    ClinicalProfile,
    ClinicalProfileRequirement,
    MissingInformationDetector,
)
from rop.models import Observation, ReasoningSession
from rop.schemas import ReasoningSessionCreate
from rop.services import MissingInformationService, ReasoningSessionService

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def observation(text: str, type_: str) -> Observation:
    return Observation(
        session_id=uuid4(),
        text=text,
        type=type_,
        confidence=0.9,
        source="rule_based",
    )


def test_chest_pain_template_reports_missing_information() -> None:
    observations = [
        observation("Symptom = Chest pain", "symptom"),
        observation("Radiation = Left arm", "radiation"),
    ]

    missing = MissingInformationDetector().detect(observations)

    assert [(item.key, item.label) for item in missing] == [
        ("age", "Age"),
        ("sex", "Sex"),
        ("blood_pressure", "Blood pressure"),
        ("ecg", "ECG"),
        ("troponin", "Troponin"),
        ("past_cardiac_history", "Past cardiac history"),
    ]
    assert {item.template for item in missing} == {"chest_pain"}


def test_detector_removes_observed_requirements() -> None:
    observations = [
        observation("Symptom = Chest pain", "symptom"),
        observation("Age = 56", "age"),
        observation("Sex = Male", "sex"),
        observation("Blood pressure = 120/80 mmHg", "measurement"),
        observation("ECG = Normal", "sign"),
        observation("Troponin = Negative", "measurement"),
        observation("Past cardiac history = None", "history"),
    ]

    missing = MissingInformationDetector().detect(observations)

    assert missing == []


def test_detector_accepts_custom_templates() -> None:
    profile = ClinicalProfile(
        name="custom",
        trigger_types=frozenset({"symptom"}),
        trigger_aliases=frozenset({"headache"}),
        requirements=(
            ClinicalProfileRequirement("onset", "Onset time", frozenset({"duration"})),
        ),
    )

    missing = MissingInformationDetector((profile,)).detect(
        [observation("Symptom = Headache", "symptom")]
    )

    assert [(item.key, item.label) for item in missing] == [("onset", "Onset time")]


def test_service_stores_missing_information_on_session() -> None:
    with TestingSessionLocal() as db:
        session = ReasoningSessionService().create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="clinical",
                user_input="Chest pain radiating to the left arm.",
                current_stage="initial",
            ),
        )
        observations = [
            observation("Symptom = Chest pain", "symptom"),
            observation("Radiation = Left arm", "radiation"),
        ]
        for item in observations:
            item.session_id = session.id
            db.add(item)
        db.commit()

        records = MissingInformationService().detect_and_store(
            db, session.id, observations
        )

        assert len(records) == 6
        assert {record.session_id for record in records} == {session.id}
        assert {record.item for record in session.missing_information} == {
            "Age",
            "Sex",
            "Blood pressure",
            "ECG",
            "Troponin",
            "Past cardiac history",
        }
        assert db.query(ReasoningSession).one().missing_information == records

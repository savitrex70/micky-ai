from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base
from rop.extraction import ObservationExtractor
from rop.models import ReasoningSession
from rop.schemas import ReasoningSessionCreate
from rop.services import ObservationExtractionService, ReasoningSessionService

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


EXAMPLE_TEXT = (
    "A 56-year-old male presents with severe chest pain "
    "radiating to the left arm for 30 minutes."
)


def test_extractor_parses_clinical_example() -> None:
    observations = ObservationExtractor().extract(EXAMPLE_TEXT)

    assert [(item.type, item.text) for item in observations] == [
        ("age", "Age = 56"),
        ("sex", "Sex = Male"),
        ("symptom", "Symptom = Chest pain"),
        ("severity", "Severity = Severe"),
        ("radiation", "Radiation = Left arm"),
        ("duration", "Duration = 30 minutes"),
    ]
    assert all(item.source == "rule_based" for item in observations)
    assert all(0.0 <= item.confidence <= 1.0 for item in observations)


def test_extractor_returns_no_observations_for_unknown_text() -> None:
    assert ObservationExtractor().extract("The patient was seen today.") == []


def test_extraction_service_stores_observations_on_session() -> None:
    session_service = ReasoningSessionService()
    extraction_service = ObservationExtractionService()

    with TestingSessionLocal() as db:
        session = session_service.create(
            db,
            ReasoningSessionCreate(
                status="created",
                domain="clinical",
                user_input=EXAMPLE_TEXT,
                current_stage="initial",
            ),
        )

        observations = extraction_service.extract_and_store(
            db, session.id, EXAMPLE_TEXT
        )

        assert len(observations) == 6
        assert {observation.session_id for observation in observations} == {session.id}
        assert db.query(ReasoningSession).one().observations == observations

def test_extractor_handles_symptom_without_severity() -> None:
    """Regression: a symptom that matches without an optional severity
    prefix (e.g. plain "chest pain") must not crash the extractor. The
    _SYMPTOM_PATTERN's severity group is optional, so match.group must
    be None-checked before calling .strip()."""
    from rop.extraction import ObservationExtractor

    observations = ObservationExtractor().extract("Patient reports chest pain")
    symptom_values = [o.text for o in observations if o.type == "symptom"]
    assert "Symptom = Chest pain" in symptom_values
    # And no severity observation is produced for this input.
    severity_values = [o.text for o in observations if o.type == "severity"]
    assert severity_values == []


from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Session:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def create_session() -> dict[str, object]:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "clinical",
            "user_input": "Chest pain patient",
            "current_stage": "initial",
            "metadata": {},
        },
    )
    assert response.status_code == 201
    return response.json()


def add_observations(session_id: str, observations: list[dict[str, object]]) -> None:
    for obs in observations:
        response = client.post(
            f"/sessions/{session_id}/observations",
            json=obs,
        )
        assert response.status_code == 201


def test_match_template_single_match() -> None:
    session = create_session()
    session_id = session["id"]

    add_observations(
        session_id,
        [
            {
                "text": "Symptom = Chest pain",
                "type": "symptom",
                "confidence": 0.95,
                "source": "rule_based",
            },
            {
                "text": "Radiation = Left arm",
                "type": "body_location",
                "confidence": 0.92,
                "source": "rule_based",
            },
        ],
    )

    response = client.post(f"/sessions/{session_id}/match-template")
    assert response.status_code == 201

    data = response.json()
    assert data["template_name"] == "acute_coronary_syndrome"
    assert data["confidence"] > 0.0
    assert len(data["matched_observations"]) == 2
    assert "Symptom = Chest pain" in data["matched_observations"]
    assert "Radiation = Left arm" in data["matched_observations"]
    assert data["reason"].startswith("Selected 'acute_coronary_syndrome'")


def test_match_template_no_match_falls_back() -> None:
    session = create_session()
    session_id = session["id"]

    add_observations(
        session_id,
        [
            {
                "text": "Symptom = Headache",
                "type": "symptom",
                "confidence": 0.9,
                "source": "rule_based",
            },
        ],
    )

    response = client.post(f"/sessions/{session_id}/match-template")
    assert response.status_code == 201

    data = response.json()
    assert data["template_name"] == "general_assessment"
    assert data["confidence"] == 0.1


def test_match_template_rejects_missing_session() -> None:
    response = client.post(f"/sessions/{uuid4()}/match-template")
    assert response.status_code == 404


def test_match_template_stores_candidates() -> None:
    session = create_session()
    session_id = session["id"]

    add_observations(
        session_id,
        [
            {
                "text": "Symptom = Chest pain",
                "type": "symptom",
                "confidence": 0.95,
                "source": "rule_based",
            },
        ],
    )

    response = client.post(f"/sessions/{session_id}/match-template")
    assert response.status_code == 201

    data = response.json()
    assert len(data["candidates"]) > 0
    assert any(
        c["template_name"] == "acute_coronary_syndrome" for c in data["candidates"]
    )


def test_match_template_openapi_documented() -> None:
    paths = app.openapi()["paths"]
    assert "/sessions/{session_id}/match-template" in paths

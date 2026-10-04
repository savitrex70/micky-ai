from collections.abc import Generator
from uuid import UUID, uuid4

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


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def create_session() -> dict[str, object]:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "A test input",
            "current_stage": "initial",
            "metadata": {"source": "api-test"},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_session_endpoints() -> None:
    created = create_session()
    session_id = created["id"]

    assert UUID(session_id)
    assert client.get("/sessions").json()[0]["id"] == session_id
    assert client.get(f"/sessions/{session_id}").json() == created

    assert client.delete(f"/sessions/{session_id}").status_code == 204
    assert client.get(f"/sessions/{session_id}").status_code == 404
    assert client.delete(f"/sessions/{session_id}").status_code == 404


def test_observation_endpoints() -> None:
    session = create_session()
    session_id = session["id"]

    response = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": "The endpoint responded successfully.",
            "type": "fact",
            "confidence": 0.9,
            "source": "api-test",
        },
    )
    assert response.status_code == 201
    observation = response.json()
    assert observation["session_id"] == session_id

    observations = client.get(f"/sessions/{session_id}/observations")
    assert observations.status_code == 200
    assert observations.json() == [observation]

    missing_session_id = uuid4()
    assert client.get(f"/sessions/{missing_session_id}/observations").status_code == 404
    assert (
        client.post(
            f"/sessions/{missing_session_id}/observations",
            json={
                "text": "Orphan observation",
                "type": "fact",
                "confidence": 0.5,
                "source": "api-test",
            },
        ).status_code
        == 404
    )


def test_observation_extraction_endpoint() -> None:
    session = create_session()
    session_id = session["id"]

    response = client.post(
        f"/sessions/{session_id}/extract-observations",
        json={
            "text": (
                "A 56-year-old male presents with severe chest pain "
                "radiating to the left arm for 30 minutes."
            )
        },
    )

    assert response.status_code == 201
    observations = response.json()["observations"]
    assert [observation["text"] for observation in observations] == [
        "Age = 56",
        "Sex = Male",
        "Symptom = Chest pain",
        "Severity = Severe",
        "Radiation = Left arm",
        "Duration = 30 minutes",
    ]
    assert {observation["session_id"] for observation in observations} == {session_id}


def test_observation_extraction_rejects_missing_session() -> None:
    response = client.post(
        f"/sessions/{uuid4()}/extract-observations",
        json={"text": "A 56-year-old male has chest pain."},
    )

    assert response.status_code == 404


def test_missing_information_endpoint_stores_template_results() -> None:
    session = create_session()
    session_id = session["id"]

    for payload in [
        {
            "text": "Symptom = Chest pain",
            "type": "symptom",
            "confidence": 0.95,
            "source": "rule_based",
        },
        {
            "text": "Radiation = Left arm",
            "type": "radiation",
            "confidence": 0.92,
            "source": "rule_based",
        },
    ]:
        assert (
            client.post(
                f"/sessions/{session_id}/observations", json=payload
            ).status_code
            == 201
        )

    response = client.post(f"/sessions/{session_id}/detect-missing-information")

    assert response.status_code == 201
    assert [item["item"] for item in response.json()] == [
        "Age",
        "Sex",
        "Blood pressure",
        "ECG",
        "Troponin",
        "Past cardiac history",
    ]
    assert {item["session_id"] for item in response.json()} == {session_id}

    rerun = client.post(f"/sessions/{session_id}/detect-missing-information")
    assert len(rerun.json()) == 6


def test_openapi_documents_requested_paths() -> None:
    paths = app.openapi()["paths"]

    assert "/sessions" in paths
    assert "/sessions/{session_id}" in paths
    assert "/sessions/{session_id}/observations" in paths
    assert "/sessions/{session_id}/extract-observations" in paths
    assert "/sessions/{session_id}/detect-missing-information" in paths
    assert "/sessions/{session_id}/match-template" in paths
    assert "/sessions/{session_id}/hypotheses" in paths
    assert "/sessions/{session_id}/hypotheses/{hypothesis_id}" in paths
    assert "/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence" in paths
    assert "/sessions/{session_id}/evidence" in paths
    assert "/sessions/{session_id}/steps" in paths
    assert "/sessions/{session_id}/replay" in paths
    assert "/sessions/{session_id}/generate-candidates" in paths


def test_evidence_endpoints() -> None:
    session = create_session()
    session_id = session["id"]

    hypothesis_response = client.post(
        f"/sessions/{session_id}/hypotheses",
        json={
            "title": "Test hypothesis",
            "description": "A test description",
            "category": "system",
            "status": "pending",
            "likelihood_score": 0.7,
            "rank": 1,
        },
    )
    assert hypothesis_response.status_code == 201
    hypothesis_id = hypothesis_response.json()["id"]

    response = client.post(
        f"/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence",
        json={
            "type": "supporting",
            "source": "unit-test",
            "text": "Supporting evidence text",
            "confidence": 0.9,
            "strength": "strong",
        },
    )
    assert response.status_code == 201
    evidence = response.json()
    evidence_id = evidence["id"]

    assert evidence["hypothesis_id"] == hypothesis_id
    assert evidence["session_id"] == session_id
    assert evidence["type"] == "supporting"
    assert evidence["strength"] == "strong"
    assert evidence["confidence"] == 0.9

    evidence_list = client.get(
        f"/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence"
    )
    assert evidence_list.status_code == 200
    assert evidence_list.json() == [evidence]

    session_evidence_list = client.get(f"/sessions/{session_id}/evidence")
    assert session_evidence_list.status_code == 200
    assert session_evidence_list.json() == [evidence]

    evidence_detail = client.get(
        f"/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}"
    )
    assert evidence_detail.status_code == 200
    assert evidence_detail.json() == evidence

    updated = client.put(
        f"/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}",
        json={
            "type": "contradicting",
            "confidence": 0.4,
            "strength": "weak",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["type"] == "contradicting"
    assert updated.json()["confidence"] == 0.4
    assert updated.json()["strength"] == "weak"

    assert (
        client.delete(
            f"/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}"
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/sessions/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}"
        ).status_code
        == 404
    )


def test_evidence_endpoints_reject_missing_session() -> None:
    response = client.post(
        f"/sessions/{uuid4()}/hypotheses/{uuid4()}/evidence",
        json={
            "type": "supporting",
            "source": "unit-test",
            "text": "Evidence",
            "confidence": 0.9,
            "strength": "strong",
        },
    )
    assert response.status_code == 404


def test_evidence_endpoints_reject_missing_hypothesis() -> None:
    session = create_session()
    session_id = session["id"]

    response = client.post(
        f"/sessions/{session_id}/hypotheses/{uuid4()}/evidence",
        json={
            "type": "supporting",
            "source": "unit-test",
            "text": "Evidence",
            "confidence": 0.9,
            "strength": "strong",
        },
    )
    assert response.status_code == 404


def test_reasoning_step_endpoints() -> None:
    session = create_session()
    session_id = session["id"]

    response = client.post(
        f"/sessions/{session_id}/steps",
        json={
            "step_type": "input",
            "input_data": {"text": "user input"},
            "output_data": {"status": "received"},
            "confidence": 0.9,
            "duration_ms": 100,
            "status": "completed",
        },
    )
    assert response.status_code == 201
    step = response.json()
    step_id = step["id"]

    assert step["session_id"] == session_id
    assert step["step_type"] == "input"
    assert step["step_number"] == 1

    response2 = client.post(
        f"/sessions/{session_id}/steps",
        json={
            "step_type": "observation_extraction",
            "input_data": {},
            "output_data": {"observations": []},
            "confidence": 0.8,
            "duration_ms": 200,
            "status": "completed",
        },
    )
    assert response2.status_code == 201
    assert response2.json()["step_number"] == 2

    steps = client.get(f"/sessions/{session_id}/steps")
    assert steps.status_code == 200
    assert len(steps.json()) == 2

    step_detail = client.get(f"/sessions/{session_id}/steps/{step_id}")
    assert step_detail.status_code == 200
    assert step_detail.json() == step

    replay = client.get(f"/sessions/{session_id}/replay")
    assert replay.status_code == 200
    assert len(replay.json()) == 2
    assert replay.json()[0]["step_type"] == "input"
    assert replay.json()[1]["step_type"] == "observation_extraction"


def test_generate_candidates_endpoint() -> None:
    session = create_session()
    session_id = session["id"]

    client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.95,
            "source": "rule_based",
        },
    )

    client.post(
        f"/sessions/{session_id}/match-template",
    )

    response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert response.status_code == 201

    candidates = response.json()
    assert len(candidates) > 0
    for candidate in candidates:
        assert "id" in candidate
        assert "name" in candidate
        assert "category" in candidate
        assert "trigger_reason" in candidate
        assert "initial_score" in candidate
        assert "confidence" in candidate
        assert "supporting_observations" in candidate
        assert "contradicting_observations" in candidate
        assert "missing_information" in candidate
        assert "status" in candidate
        assert "created_at" in candidate


def test_generate_candidates_rejects_missing_session() -> None:
    response = client.post(f"/sessions/{uuid4()}/generate-candidates")
    assert response.status_code == 404


def test_reasoning_step_rejects_missing_session() -> None:
    response = client.post(
        f"/sessions/{uuid4()}/steps",
        json={
            "step_type": "input",
            "input_data": {},
            "output_data": {},
            "confidence": 0.9,
            "duration_ms": 100,
            "status": "completed",
        },
    )
    assert response.status_code == 404
    session = create_session()
    session_id = session["id"]

    response = client.post(
        f"/sessions/{session_id}/hypotheses",
        json={
            "title": "Test hypothesis",
            "description": "A test description",
            "category": "system",
            "status": "pending",
            "likelihood_score": 0.7,
            "rank": 1,
            "reason": "Initial hypothesis",
        },
    )
    assert response.status_code == 201
    hypothesis = response.json()
    hypothesis_id = hypothesis["id"]

    assert hypothesis["session_id"] == session_id
    assert hypothesis["title"] == "Test hypothesis"
    assert hypothesis["status"] == "pending"
    assert hypothesis["rank"] == 1

    hypotheses = client.get(f"/sessions/{session_id}/hypotheses")
    assert hypotheses.status_code == 200
    assert hypotheses.json() == [hypothesis]

    hypothesis_detail = client.get(f"/sessions/{session_id}/hypotheses/{hypothesis_id}")
    assert hypothesis_detail.status_code == 200
    assert hypothesis_detail.json() == hypothesis

    updated = client.put(
        f"/sessions/{session_id}/hypotheses/{hypothesis_id}",
        json={
            "status": "active",
            "rank": 2,
            "reason": "Updated reason",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "active"
    assert updated.json()["rank"] == 2

    assert (
        client.delete(f"/sessions/{session_id}/hypotheses/{hypothesis_id}").status_code
        == 204
    )
    assert (
        client.get(f"/sessions/{session_id}/hypotheses/{hypothesis_id}").status_code
        == 404
    )


def test_hypothesis_endpoints_reject_missing_session() -> None:
    response = client.post(
        f"/sessions/{uuid4()}/hypotheses",
        json={
            "title": "Test hypothesis",
            "description": "A test description",
            "category": "system",
            "status": "pending",
            "likelihood_score": 0.7,
            "rank": 1,
        },
    )
    assert response.status_code == 404


def test_decision_candidate_evaluations_evaluates_every_candidate_beyond_one_page() -> (
    None
):
    # Task 032's contract requires every candidate to receive an
    # evaluation. Regression guard: with more than one page's worth of
    # persisted candidates, the endpoint must retrieve and evaluate all
    # of them, not silently truncate to the first page.
    from rop.models import CandidateHypothesis as CandidateHypothesisModel

    session = create_session()
    session_id = session["id"]

    # Use the DB session the app is *currently* configured to use
    # (via its active dependency override) rather than this module's
    # own ``TestingSessionLocal`` directly: other test modules in the
    # suite also override ``get_db`` on the same shared ``app``
    # object, and whichever override was applied last is the one in
    # effect by the time tests run.
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        candidate_count = 130
        for i in range(candidate_count):
            db.add(
                CandidateHypothesisModel(
                    session_id=UUID(session_id),
                    name=f"Candidate {i}",
                    category="testing",
                    trigger_reason="seeded for pagination test",
                    initial_score=float(i),
                    confidence=0.5,
                    supporting_observations=[],
                    contradicting_observations=[],
                    missing_information=[],
                )
            )
        db.commit()
    finally:
        db_generator.close()

    response = client.get(f"/sessions/{session_id}/decision-candidate-evaluations")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == candidate_count
    assert {r["hypothesis_name"] for r in results} == {
        f"Candidate {i}" for i in range(candidate_count)
    }


def test_decision_evaluation_consistency_covers_every_candidate_beyond_one_page() -> (
    None
):
    # Task 033's contract requires every candidate's evaluation to be
    # checked for structural consistency. Regression guard: with more
    # than one page's worth of persisted candidates, the endpoint must
    # retrieve and check all of them, not silently truncate to the
    # first page (mirrors Task 032's own pagination fix above).
    from rop.models import CandidateHypothesis as CandidateHypothesisModel

    session = create_session()
    session_id = session["id"]

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        candidate_count = 130
        for i in range(candidate_count):
            db.add(
                CandidateHypothesisModel(
                    session_id=UUID(session_id),
                    name=f"Candidate {i}",
                    category="testing",
                    trigger_reason="seeded for pagination test",
                    initial_score=float(i),
                    confidence=0.5,
                    supporting_observations=[],
                    contradicting_observations=[],
                    missing_information=[],
                )
            )
        db.commit()
    finally:
        db_generator.close()

    response = client.get(f"/sessions/{session_id}/decision-evaluation-consistency")
    assert response.status_code == 200
    result = response.json()
    assert result["evaluation_count"] == candidate_count
    assert result["expected_candidate_count"] == candidate_count
    assert result["candidate_count_matches"] is True
    assert result["all_candidates_evaluated"] is True
    assert result["has_missing_candidate_evaluation"] is False
    assert result["consistent"] is True

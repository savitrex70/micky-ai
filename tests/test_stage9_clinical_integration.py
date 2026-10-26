"""End-to-end boundary tests for Stage 9's clinical workflow integration."""

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop.database import Base, get_db
from rop.main import app

LOCAL_HEADERS = {
    "origin": "http://127.0.0.1:8000",
    "content-type": "application/json",
}


def test_clinical_audited_workflow_is_separate_from_personal_conversations() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    previous = app.dependency_overrides.get(get_db)

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    clinical_marker = "CLINICAL_ONLY_PRIVATE_MARKER_2397"
    try:
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            conversation_response = client.post(
                "/api/assistant/conversations",
                headers=LOCAL_HEADERS,
                json={"title": "Personal conversation"},
            )
            assert conversation_response.status_code == 201
            conversation_id = conversation_response.json()["id"]

            clinical_response = client.post(
                "/sessions",
                json={
                    "status": "created",
                    "domain": "testing",
                    "user_input": clinical_marker,
                    "current_stage": "initial",
                    "metadata": {"source": "stage-9-acceptance"},
                },
            )
            assert clinical_response.status_code == 201
            clinical_session_id = clinical_response.json()["id"]
            assert clinical_session_id != conversation_id

            audited = client.post(
                f"/sessions/{clinical_session_id}/reasoning-run/execute-fully-audited"
            )
            assert audited.status_code == 200
            package = audited.json()
            assert package["session_id"] == clinical_session_id
            assert isinstance(package["available"], bool)
            assert isinstance(package["package_consistent"], bool)
            assert "execution_bundle" in package
            assert "bundle_consistency" in package

            # A conversation UUID must not be accepted as a clinical session ID.
            wrong_domain = client.post(
                f"/sessions/{conversation_id}/reasoning-run/execute-fully-audited"
            )
            assert wrong_domain.status_code == 404

            export_response = client.get("/api/assistant/personal-data/export")
            assert export_response.status_code == 200
            exported = export_response.json()
            assert exported["complete"] is True
            assert exported["counts"]["conversations"] == 1
            assert exported["counts"]["messages"] == 0
            assert exported["counts"]["workspace_items"] == 0
            assert {row["record_type"] for row in exported["records"]} == {
                "conversation"
            }
            assert clinical_marker not in export_response.text

            page = client.get("/")
            javascript = client.get("/static/workspace.js")
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()

    assert page.status_code == javascript.status_code == 200
    assert 'id="clinical-run-reasoning"' in page.text
    assert 'id="clinical-reasoning-result"' in page.text
    assert "/reasoning-run/execute-fully-audited" in javascript.text
    assert "result.package_consistent === true" in javascript.text
    assert "clinicalReasoningResult.textContent = JSON.stringify(result, null, 2)" in (
        javascript.text
    )
    assert "not a validated diagnosis or treatment recommendation" in page.text
    assert "separate from assistant conversations" in page.text.lower()

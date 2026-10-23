"""End-to-end tests for confirmation-gated personal workspace mutations."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop import database as database_module
from rop.database import Base, get_db
from rop.main import app
from rop.services import workspace_executor

ORIGIN = "http://127.0.0.1:8000"
ORIGIN_HEADERS = {
    "origin": ORIGIN,
    "content-type": "application/json",
}


@pytest.fixture
def client(monkeypatch) -> Generator[TestClient, None, None]:
    """Give direct-session routes and dependency-injected routes one isolated DB."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database_module, "SessionLocal", testing_session_local)
    # The workspace executor imports SessionLocal directly, unlike the APIs.
    monkeypatch.setattr(workspace_executor, "SessionLocal", testing_session_local)

    previous_override = app.dependency_overrides.get(get_db)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    http_client = TestClient(app, base_url=ORIGIN)
    try:
        yield http_client
    finally:
        http_client.close()
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _prepare_note(
    client: TestClient,
    *,
    idempotency_key: UUID,
    title: str = "Ward revision",
) -> dict:
    response = client.post(
        "/api/assistant/workspace/changes",
        headers=ORIGIN_HEADERS,
        json={
            "kind": "note",
            "action": "create",
            "idempotency_key": str(idempotency_key),
            "title": title,
            "content": "Local integration test content",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _decide(
    client: TestClient,
    challenge: dict,
    *,
    decision: str,
    display_code: str | None = None,
):
    body = {"decision": decision}
    if display_code is not None:
        body["display_code"] = display_code
    return client.post(
        "/api/assistant/confirmations/" + challenge["challenge_id"] + "/decision",
        headers=ORIGIN_HEADERS,
        json=body,
    )


def _notes(client: TestClient) -> list[dict]:
    response = client.get(
        "/api/assistant/workspace/items?kind=note",
        headers=ORIGIN_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _receipt(client: TestClient, key: UUID) -> dict:
    response = client.get(
        f"/api/assistant/workspace/receipts/{key}",
        headers=ORIGIN_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_confirmed_note_is_committed_once_and_receipt_replays_safely(
    client: TestClient,
) -> None:
    key = uuid4()
    prepared = _prepare_note(client, idempotency_key=key)

    assert prepared["status"] == "confirmation-required"
    assert "challenge" in prepared
    assert _notes(client) == []
    assert _receipt(client, key)["status"] == "unknown"

    decided = _decide(
        client,
        prepared["challenge"],
        decision="confirm",
        display_code=prepared["challenge"]["display_code"],
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "executed"
    assert decided.json()["executed"] is True

    notes = _notes(client)
    assert len(notes) == 1
    assert notes[0]["title"] == "Ward revision"
    assert _receipt(client, key)["status"] == "succeeded"

    replay = _prepare_note(client, idempotency_key=key)
    assert replay["status"] == "success"
    assert "challenge" not in replay
    assert len(_notes(client)) == 1


def test_cancelled_note_does_not_mutate_and_receipt_can_be_abandoned(
    client: TestClient,
) -> None:
    key = uuid4()
    prepared = _prepare_note(client, idempotency_key=key)
    assert prepared["status"] == "confirmation-required"

    cancelled = _decide(
        client,
        prepared["challenge"],
        decision="cancel",
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["executed"] is False
    assert _notes(client) == []

    abandoned = client.request(
        "DELETE",
        f"/api/assistant/workspace/receipts/{key}",
        headers=ORIGIN_HEADERS,
        json={},
    )
    assert abandoned.status_code == 204
    assert _receipt(client, key)["status"] == "not-found"


def test_wrong_display_code_refuses_execution_and_keeps_active_reservation(
    client: TestClient,
) -> None:
    key = uuid4()
    prepared = _prepare_note(client, idempotency_key=key)
    challenge = prepared["challenge"]

    wrong_code = _decide(
        client,
        challenge,
        decision="confirm",
        display_code="WRONG-CODE",
    )
    assert wrong_code.status_code == 200, wrong_code.text
    assert wrong_code.json()["status"] == "refused"
    assert wrong_code.json()["executed"] is False
    assert _notes(client) == []

    abandoned_while_active = client.request(
        "DELETE",
        f"/api/assistant/workspace/receipts/{key}",
        headers=ORIGIN_HEADERS,
        json={},
    )
    assert abandoned_while_active.status_code == 409

    cancelled = _decide(client, challenge, decision="cancel")
    assert cancelled.json()["status"] == "cancelled"
    abandoned = client.delete(
        f"/api/assistant/workspace/receipts/{key}",
        headers=ORIGIN_HEADERS,
        json={},
    )
    assert abandoned.status_code == 204
    assert _notes(client) == []


def test_explicit_chat_command_uses_the_same_confirmation_and_receipt_flow(
    client: TestClient,
) -> None:
    conversation = client.post(
        "/api/assistant/conversations",
        headers=ORIGIN_HEADERS,
        json={"title": "Workspace integration"},
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = UUID(conversation.json()["id"])
    key = uuid4()

    response = client.post(
        "/api/assistant/requests",
        headers=ORIGIN_HEADERS,
        json={
            "message": "workspace add note: Created from chat",
            "conversation_id": str(conversation_id),
            "idempotency_key": str(key),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "confirmation-required"
    assert body["challenge"]["summary"]
    assert _notes(client) == []

    decided = _decide(
        client,
        body["challenge"],
        decision="confirm",
        display_code=body["challenge"]["display_code"],
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "executed"
    assert decided.json()["executed"] is True

    notes = _notes(client)
    assert len(notes) == 1
    assert notes[0]["title"] == "Created from chat"
    assert _receipt(client, key)["status"] == "succeeded"

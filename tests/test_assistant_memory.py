"""API and persistence tests for user-controlled memory."""
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop.database import Base, get_db
from rop.main import app

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"origin": ORIGIN, "content-type": "application/json"}




@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    previous = app.dependency_overrides.get(get_db)

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    http_client = TestClient(app, base_url=ORIGIN)
    try:
        yield http_client
    finally:
        http_client.close()
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def create_entry(client: TestClient, title: str, content: str):
    return client.post(
        "/api/assistant/memories",
        headers=HEADERS,
        json={"entry_type": "memory", "title": title, "content": content},
    )


def test_create_list_search_update_and_delete(client: TestClient) -> None:
    created = create_entry(client, "Study preference", "Use concise explanations.")
    assert created.status_code == 201, created.text
    entry = created.json()
    assert created.headers["cache-control"].startswith("no-store")

    listing = client.get("/api/assistant/memories?limit=10")
    assert listing.status_code == 200
    assert listing.headers["x-content-type-options"] == "nosniff"
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == entry["id"]

    search = client.get("/api/assistant/memories?q=concise")
    assert search.json()["total"] == 1

    updated = client.patch(
        "/api/assistant/memories/" + entry["id"],
        headers=HEADERS,
        json={"entry_type": "preference", "title": "Answer style"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Answer style"
    assert updated.json()["entry_type"] == "preference"
    assert updated.json()["content"] == "Use concise explanations."

    # A separate request-scoped database session can read the committed row.
    assert client.get("/api/assistant/memories").json()["items"][0]["id"] == entry["id"]
    deleted = client.delete(
        "/api/assistant/memories/" + entry["id"], headers=HEADERS
    )
    assert deleted.status_code == 204
    assert client.get("/api/assistant/memories").json()["total"] == 0


def test_chat_does_not_implicitly_create_memory(client: TestClient) -> None:
    result = client.post(
        "/api/assistant/requests", json={"message": "remember this private sentence"}
    )
    assert result.status_code == 200
    assert result.json()["status"] == "unsupported-capability"
    assert client.get("/api/assistant/memories").json()["total"] == 0


def test_memory_write_rejects_cross_origin_request(client: TestClient) -> None:
    response = client.post(
        "/api/assistant/memories",
        headers={"origin": "https://attacker.invalid", "content-type": "application/json"},
        json={"title": "Entry", "content": "Content"},
    )
    assert response.status_code == 403
    assert client.get("/api/assistant/memories").json()["total"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"title": " ", "content": "nonblank"},
        {"title": "Valid", "content": " "},
        {"title": "Valid", "content": "content", "conversation_id": "forged"},
    ],
)
def test_memory_create_rejects_invalid_values(
    client: TestClient, body: dict[str, object]
) -> None:
    response = client.post("/api/assistant/memories", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert client.get("/api/assistant/memories").json()["total"] == 0


def test_clear_all_requires_exact_confirmation(client: TestClient) -> None:
    assert create_entry(client, "First", "One").status_code == 201
    assert create_entry(client, "Second", "Two").status_code == 201
    wrong = client.post(
        "/api/assistant/memories/clear",
        headers=HEADERS,
        json={"confirmation_phrase": "clear everything"},
    )
    assert wrong.status_code == 422
    assert client.get("/api/assistant/memories").json()["total"] == 2

    cleared = client.post(
        "/api/assistant/memories/clear",
        headers=HEADERS,
        json={"confirmation_phrase": "CLEAR ALL SAVED MEMORY"},
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"status": "success", "deleted_count": 2}
    assert client.get("/api/assistant/memories").json()["total"] == 0

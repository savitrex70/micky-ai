"""Regression tests for the configured local Host boundary."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop import database as database_module
from rop.database import Base, get_db
from rop.main import app

TRUSTED_ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def trusted_client(monkeypatch) -> Generator[TestClient, None, None]:
    """Provide a real trusted-authority client backed by an isolated SQLite DB."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    previous = app.dependency_overrides.get(get_db)

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, base_url=TRUSTED_ORIGIN)
    try:
        yield client
    finally:
        client.close()
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_configured_host_can_read_private_api_and_serve_local_ui(
    trusted_client: TestClient,
) -> None:
    save = trusted_client.post(
        "/api/assistant/memories",
        headers={"origin": TRUSTED_ORIGIN},
        json={
            "idempotency_key": str(uuid4()),
            "entry_type": "memory",
            "title": "private-host-boundary-marker",
            "content": "trusted loopback host private data",
        },
    )
    assert save.status_code == 201, save.text

    root = trusted_client.get("/")
    asset = trusted_client.get("/static/app.js")
    memories = trusted_client.get("/api/assistant/memories?limit=10")
    export = trusted_client.get("/api/assistant/personal-data/export")

    assert root.status_code == 200
    assert asset.status_code == 200
    assert memories.status_code == 200
    assert memories.json()["total"] == 1
    assert memories.json()["items"][0]["title"] == "private-host-boundary-marker"
    assert memories.headers["cache-control"].startswith("no-store")
    assert export.status_code == 200
    assert export.json()["total_records"] == 1
    assert "private-host-boundary-marker" in export.text
    assert export.headers["cache-control"].startswith("no-store")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/app.js",
        "/api/assistant/memories",
        "/api/assistant/personal-data/export",
        "/api/assistant/workspace/items",
        "/api/assistant/workspace/retrieval-roots",
        "/api/assistant/conversations",
        "/api/assistant/confirmation-records",
        (
            "/api/assistant/clarifications?"
            "conversation_id=00000000-0000-4000-8000-000000000001"
        ),
        "/sessions",
        "/docs",
        "/openapi.json",
    ],
)
def test_untrusted_host_is_rejected_before_private_route_or_asset(
    trusted_client: TestClient,
    path: str,
) -> None:
    response = trusted_client.get(path, headers={"host": "rebinding.attacker.invalid"})

    assert response.status_code == 403
    assert response.json() == {"detail": "This request was refused."}
    assert "rebinding.attacker.invalid" not in response.text


def test_untrusted_host_is_rejected_before_database_access(monkeypatch) -> None:
    def forbidden_session_factory(*args, **kwargs):
        raise AssertionError("untrusted Host reached a private-data handler")

    monkeypatch.setattr(database_module, "SessionLocal", forbidden_session_factory)
    with TestClient(app, base_url=TRUSTED_ORIGIN) as client:
        for path in (
            "/api/assistant/memories",
            "/api/assistant/personal-data/export",
            "/api/assistant/workspace/items",
            "/api/assistant/conversations",
            "/api/assistant/confirmation-records",
        ):
            response = client.get(path, headers={"host": "attacker.invalid"})
            assert response.status_code == 403, path


def test_nonconfigured_loopback_port_is_not_trusted() -> None:
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get(
            "/api/assistant/memories",
            headers={"host": "127.0.0.1:9999"},
        )

    assert response.status_code == 403


def test_untrusted_host_cannot_read_seeded_private_memory_or_export(
    trusted_client: TestClient,
) -> None:
    save = trusted_client.post(
        "/api/assistant/memories",
        headers={"origin": TRUSTED_ORIGIN},
        json={
            "idempotency_key": str(uuid4()),
            "entry_type": "memory",
            "title": "host-secret-marker",
            "content": "this must not be disclosed to a hostile host header",
        },
    )
    assert save.status_code == 201, save.text
    assert "host-secret-marker" in trusted_client.get("/api/assistant/memories").text

    headers = {"host": "attacker.invalid"}
    for path in (
        "/api/assistant/memories",
        "/api/assistant/personal-data/export",
    ):
        response = trusted_client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert "host-secret-marker" not in response.text
        assert "must not be disclosed" not in response.text

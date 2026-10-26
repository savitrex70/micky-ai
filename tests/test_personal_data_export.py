"""Contract and persistence tests for the bounded personal-data export."""

from collections.abc import Generator
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import rop.models  # noqa: F401
from rop.database import Base, get_db
from rop.main import app
from rop.models.assistant_conversation import AssistantConversation
from rop.models.assistant_item import AssistantItem
from rop.models.assistant_message import AssistantMessage

ORIGIN = "http://127.0.0.1:8000"


def _seed(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        first = AssistantConversation(title="First saved conversation")
        second = AssistantConversation(title="Second saved conversation")
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                AssistantMessage(
                    conversation_id=first.id,
                    role="user",
                    content="private user message",
                    sequence=0,
                ),
                AssistantMessage(
                    conversation_id=first.id,
                    role="assistant",
                    content="local assistant reply",
                    sequence=1,
                ),
                AssistantMessage(
                    conversation_id=second.id,
                    role="user",
                    content="second conversation message",
                    sequence=0,
                ),
            ]
        )
        session.add_all(
            [
                AssistantItem(
                    kind="note",
                    title="Revision notes",
                    content="Keep this export on my device.",
                    completed=False,
                ),
                AssistantItem(
                    kind="reminder",
                    title="Review appointment",
                    content="",
                    due_at=datetime(2026, 10, 27, 9, 0, tzinfo=UTC),
                    timezone="Europe/Amsterdam",
                    completed=False,
                ),
            ]
        )
        session.commit()


def test_personal_data_export_is_versioned_bounded_and_complete(monkeypatch) -> None:
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
    try:
        _seed(factory)
        with TestClient(app, base_url=ORIGIN) as client:
            page_one = client.get("/api/assistant/personal-data/export?offset=0&limit=3")
            page_two = client.get("/api/assistant/personal-data/export?offset=3&limit=3")
            page_three = client.get(
                "/api/assistant/personal-data/export?offset=6&limit=3"
            )
            too_large = client.get(
                "/api/assistant/personal-data/export?offset=0&limit=501"
            )
            negative = client.get(
                "/api/assistant/personal-data/export?offset=-1&limit=10"
            )
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()

    assert page_one.status_code == page_two.status_code == page_three.status_code == 200
    first = page_one.json()
    second = page_two.json()
    third = page_three.json()
    assert first["export_format"] == "micky-ai-personal-data"
    assert first["schema_version"] == 1
    assert first["total_records"] == 7
    assert first["counts"] == {
        "conversations": 2,
        "messages": 3,
        "workspace_items": 2,
    }
    assert first["offset"] == 0 and first["limit"] == 3
    assert first["next_offset"] == 3 and first["complete"] is False
    assert second["offset"] == 3 and second["next_offset"] == 6
    assert second["complete"] is False
    assert third["offset"] == 6 and third["next_offset"] is None
    assert third["complete"] is True

    records = first["records"] + second["records"] + third["records"]
    assert len(records) == first["total_records"]
    assert [record["record_type"] for record in records] == [
        "conversation",
        "conversation",
        "message",
        "message",
        "message",
        "workspace_item",
        "workspace_item",
    ]
    assert "private user message" in {
        record.get("content")
        for record in records
        if record["record_type"] == "message"
    }
    reminder = next(
        record
        for record in records
        if record["record_type"] == "workspace_item"
        and record["kind"] == "reminder"
    )
    assert reminder["timezone"] == "Europe/Amsterdam"
    assert reminder["due_at"] is not None
    allowed_fields = {
        "record_type", "id", "title", "created_at", "updated_at",
        "conversation_id", "role", "content", "sequence", "kind",
        "due_at", "timezone", "completed",
    }
    assert all(set(record).issubset(allowed_fields) for record in records)
    assert {record["record_type"] for record in records}.issubset(
        {"conversation", "message", "workspace_item"}
    )
    assert too_large.status_code == 422
    assert negative.status_code == 422


def test_personal_data_export_ui_discloses_scope_and_uses_local_api() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        javascript = client.get("/static/workspace.js")

    assert page.status_code == 200
    assert 'id="personal-data-export"' in page.text
    assert "conversations, their messages," in page.text
    assert javascript.status_code == 200
    assert "/api/assistant/personal-data/export" in javascript.text
    assert "schema_version" in javascript.text
    assert "Do not silently treat an incomplete export as complete" in javascript.text

"""Task 230: assistant-request persistence tests (conversation-aware).

PostgreSQL-backed where the DB semantics matter. Tests skip unless
``ROP_TEST_DATABASE_URL`` names a PostgreSQL database ending in ``_test``.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from rop import database as database_module
from rop.database import get_db
from rop.main import app
from rop.models import (
    AssistantConversation,
    AssistantMessage,
)
from rop.repositories.assistant_conversation import ConversationRepository

TEST_DATABASE_URL = os.environ.get("ROP_TEST_DATABASE_URL", "")
ORIGIN = "http://127.0.0.1:8000"
ORIGIN_HEADERS = {"origin": ORIGIN, "content-type": "application/json"}


def _config_problem() -> str | None:
    if not TEST_DATABASE_URL:
        return None  # absence -> skip, not fail
    try:
        url = make_url(TEST_DATABASE_URL)
    except Exception:
        return "ROP_TEST_DATABASE_URL is not a valid database URL"
    if url.get_backend_name() != "postgresql":
        return f"ROP_TEST_DATABASE_URL must be PostgreSQL; got {url.drivername}"
    if not (url.database or "").endswith("_test"):
        return "ROP_TEST_DATABASE_URL database name must end with '_test'"
    return None


@pytest.fixture(scope="session")
def pg_engine():
    if not TEST_DATABASE_URL:
        pytest.skip(
            "ROP_TEST_DATABASE_URL is not set; " "persistence tests require PostgreSQL"
        )
    problem = _config_problem()
    if problem is not None:
        pytest.fail(problem)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:
        engine.dispose()
        pytest.fail(
            f"PostgreSQL test DB configured but unreachable ({type(exc).__name__})"
        )
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(pg_engine):
    with Session(pg_engine) as session:
        session.execute(
            text(
                "TRUNCATE assistant_messages, assistant_conversations "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
    yield


@pytest.fixture
def real_db(pg_engine, clean_database):
    testing_session = sessionmaker(bind=pg_engine)

    def override():
        with testing_session() as session:
            yield session

    # Replace BOTH the FastAPI dependency AND the module-level SessionLocal
    # used inside the persistence helpers.
    previous_override = app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides[get_db] = override
    previous_session_local = database_module.SessionLocal
    database_module.SessionLocal = testing_session
    # Also patch inside assistant module which imported via `from rop import
    # database as database_module` — same module object, so this is one patch.
    try:
        yield pg_engine
    finally:
        database_module.SessionLocal = previous_session_local
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(real_db):
    return TestClient(app, base_url=ORIGIN)


def _create_conv(client, title: str = "chat") -> str:
    r = client.post(
        "/api/assistant/conversations",
        headers=ORIGIN_HEADERS,
        json={"title": title},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _submit(client, message: str, conversation_id: str | None = None):
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/api/assistant/requests", headers=ORIGIN_HEADERS, json=body)


# ============================================================================
# No conversation_id — historical behaviour
# ============================================================================


def test_no_conversation_does_not_touch_db(client, real_db) -> None:
    """Without a conversation_id, no conversation table is touched."""
    with Session(real_db) as check:
        conv_before = check.scalar(
            select(func.count()).select_from(AssistantConversation)
        )
        msg_before = check.scalar(select(func.count()).select_from(AssistantMessage))
    r = _submit(client, "help")
    assert r.status_code == 200
    with Session(real_db) as check:
        conv_after = check.scalar(
            select(func.count()).select_from(AssistantConversation)
        )
        msg_after = check.scalar(select(func.count()).select_from(AssistantMessage))
    assert conv_before == conv_after
    assert msg_before == msg_after


# ============================================================================
# Successful persistence
# ============================================================================


def test_help_success_persists_user_and_assistant_pair(client, real_db) -> None:
    conv = _create_conv(client)
    r = _submit(client, "help", conv)
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "success"
    assistant_text = payload["message"]

    with Session(real_db) as check:
        messages = check.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == UUID(conv))
            .order_by(AssistantMessage.sequence)
        ).all()
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "help"
    assert messages[0].sequence == 0
    assert messages[1].role == "assistant"
    assert messages[1].content == assistant_text
    assert messages[1].sequence == 1


def test_success_response_envelope_unchanged_when_persisting(client, real_db) -> None:
    """The response the client sees is the same envelope as without a
    conversation; the persist path is transparent to the caller.
    """
    conv = _create_conv(client)
    without = _submit(client, "help")
    with_conv = _submit(client, "help", conv)
    assert without.json() == with_conv.json()


def test_updated_at_advances_after_success(client, real_db) -> None:
    conv = _create_conv(client)
    with Session(real_db) as check:
        before = check.get(AssistantConversation, UUID(conv)).updated_at
    _submit(client, "help", conv)
    with Session(real_db) as check:
        after = check.get(AssistantConversation, UUID(conv)).updated_at
    assert after > before


def test_two_turns_get_consecutive_sequences(client, real_db) -> None:
    conv = _create_conv(client)
    _submit(client, "help", conv)
    _submit(client, "what can you do", conv)
    with Session(real_db) as check:
        seqs = check.scalars(
            select(AssistantMessage.sequence)
            .where(AssistantMessage.conversation_id == UUID(conv))
            .order_by(AssistantMessage.sequence)
        ).all()
    assert seqs == [0, 1, 2, 3]


# ============================================================================
# Missing / malformed conversation_id
# ============================================================================


def test_unknown_conversation_returns_404_without_creating(client, real_db) -> None:
    r = _submit(client, "help", str(uuid4()))
    assert r.status_code == 404
    with Session(real_db) as check:
        assert (
            check.scalar(select(func.count()).select_from(AssistantConversation)) == 0
        )


def test_malformed_conversation_id_returns_422(client, real_db) -> None:
    r = client.post(
        "/api/assistant/requests",
        headers=ORIGIN_HEADERS,
        json={"message": "help", "conversation_id": "not-a-uuid"},
    )
    assert r.status_code == 422


# ============================================================================
# Non-success outcomes are not persisted
# ============================================================================


def test_unsupported_request_with_conv_id_persists_nothing(client, real_db) -> None:
    conv = _create_conv(client)
    r = _submit(client, "what is the weather today", conv)
    assert r.status_code == 200
    assert r.json()["status"] == "unsupported-capability"
    with Session(real_db) as check:
        count = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == UUID(conv))
        )
    assert count == 0


def test_unsupported_request_still_404s_on_missing_conversation(
    client, real_db
) -> None:
    """Origin and conversation verification happen before dispatch, so a
    missing conversation is 404 even when the request would be unsupported.
    """
    r = _submit(client, "what is the weather today", str(uuid4()))
    assert r.status_code == 404


# ============================================================================
# Schema strictness
# ============================================================================


def test_unexpected_field_with_conv_id_rejected(client, real_db) -> None:
    conv = _create_conv(client)
    r = client.post(
        "/api/assistant/requests",
        headers=ORIGIN_HEADERS,
        json={"message": "help", "conversation_id": conv, "role": "assistant"},
    )
    assert r.status_code == 422
    with Session(real_db) as check:
        assert check.scalar(select(func.count()).select_from(AssistantMessage)) == 0


# ============================================================================
# Origin enforcement (only when conversation_id is supplied)
# ============================================================================


def test_persist_path_requires_origin(client, real_db) -> None:
    conv = _create_conv(client)
    r = client.post(
        "/api/assistant/requests",
        headers={"content-type": "application/json"},
        json={"message": "help", "conversation_id": conv},
    )
    assert r.status_code == 403
    with Session(real_db) as check:
        assert check.scalar(select(func.count()).select_from(AssistantMessage)) == 0


def test_no_conversation_path_does_not_require_origin(client, real_db) -> None:
    """Historical no-conversation path is database-free and unguarded."""
    r = client.post(
        "/api/assistant/requests",
        headers={"content-type": "application/json"},
        json={"message": "help"},
    )
    # 200 if policy allows help; the point is it's not 403 for missing origin
    assert r.status_code == 200


# ============================================================================
# Persistence failure → rollback, no partial save, sanitized response
# ============================================================================


def test_second_append_failure_rolls_back_pair(client, real_db, monkeypatch) -> None:
    """If the second append raises, no message from this turn is stored."""
    conv = _create_conv(client)

    call_count = {"n": 0}
    real_append = ConversationRepository.append_message

    def boom_second(self, session, cid, data):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated second-append failure")
        return real_append(self, session, cid, data)

    monkeypatch.setattr(ConversationRepository, "append_message", boom_second)

    r = _submit(client, "help", conv)
    assert r.status_code == 503
    # Sanitized text
    assert "simulated" not in r.text.lower()
    assert "runtimeerror" not in r.text.lower()

    with Session(real_db) as check:
        count = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == UUID(conv))
        )
    assert count == 0


def test_sequence_conflict_returns_409(client, real_db, monkeypatch) -> None:
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError as _IE

    conv = _create_conv(client)

    def boom_sequence(self, session, cid, data):
        exc = _IE("stmt", {}, Exception("synthetic"))
        exc.orig = SimpleNamespace(
            diag=SimpleNamespace(
                constraint_name="uq_assistant_messages_conversation_sequence"
            )
        )
        raise exc

    monkeypatch.setattr(ConversationRepository, "append_message", boom_sequence)
    r = _submit(client, "help", conv)
    assert r.status_code == 409
    assert "reload" in r.json()["detail"].lower()


def test_other_integrity_error_returns_503_not_409(
    client, real_db, monkeypatch
) -> None:
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError as _IE

    conv = _create_conv(client)

    def boom_other(self, session, cid, data):
        exc = _IE("stmt", {}, Exception("synthetic"))
        exc.orig = SimpleNamespace(
            diag=SimpleNamespace(constraint_name="some_other_constraint")
        )
        raise exc

    monkeypatch.setattr(ConversationRepository, "append_message", boom_other)
    r = _submit(client, "help", conv)
    assert r.status_code == 503
    assert "sequence" not in r.json()["detail"].lower()
    assert "concurrent" not in r.json()["detail"].lower()


# ============================================================================
# No clinical touch
# ============================================================================


def test_persistence_does_not_touch_reasoning_sessions(client, real_db) -> None:
    with Session(real_db) as check:
        before = check.scalar(text("select count(*) from reasoning_sessions"))
    conv = _create_conv(client)
    _submit(client, "help", conv)
    with Session(real_db) as check:
        after = check.scalar(text("select count(*) from reasoning_sessions"))
    assert before == after

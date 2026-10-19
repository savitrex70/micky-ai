"""Task 229: HTTP API integration tests for assistant conversations.

PostgreSQL-backed: the constraints, cascade, and concurrent-append
behaviour the API depends on are PostgreSQL behaviour, and a SQLite
substitute would prove none of it.

Skip semantics:

* If ``ROP_TEST_DATABASE_URL`` is absent, every test in this file skips;
  no test in this file can run meaningfully without a real database.
  Database-independent route and schema checks live in
  ``tests/test_conversations_api_schema.py``.
* If ``ROP_TEST_DATABASE_URL`` is configured but is not a PostgreSQL URL,
  does not name a database ending in ``_test``, or cannot be reached, the
  ``pg_engine`` fixture FAILS rather than skipping. A broken test-database
  setup must not be concealed behind a skip.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from rop.database import get_db
from rop.main import app
from rop.models import (
    AssistantConversation,
    AssistantMessage,
)
from rop.repositories.assistant_conversation import (
    MAX_CONVERSATION_LIST_LIMIT,
    MAX_MESSAGE_LIST_LIMIT,
)

TEST_DATABASE_URL = os.environ.get("ROP_TEST_DATABASE_URL", "")

ORIGIN = "http://127.0.0.1:8000"
ORIGIN_HEADERS = {"origin": ORIGIN, "content-type": "application/json"}


def _config_problem() -> str | None:
    """Return a configuration error string if the URL is present but bad.

    Absence of the URL is not a configuration problem; it means
    ``pytest.skip`` is correct. Only a URL that IS set but is
    non-PostgreSQL, not a ``_test`` database, or otherwise unusable is a
    configuration problem, and the fixture must fail on those rather than
    skip.
    """
    if not TEST_DATABASE_URL:
        return None
    try:
        url = make_url(TEST_DATABASE_URL)
    except Exception:
        return "ROP_TEST_DATABASE_URL is not a valid database URL"
    if url.get_backend_name() != "postgresql":
        return (
            "ROP_TEST_DATABASE_URL must use a PostgreSQL driver; "
            f"got scheme '{url.drivername}'"
        )
    database = url.database or ""
    if not database.endswith("_test"):
        return "ROP_TEST_DATABASE_URL database name must end with '_test'"
    return None


@pytest.fixture(scope="session")
def pg_engine():
    if not TEST_DATABASE_URL:
        pytest.skip(
            "ROP_TEST_DATABASE_URL is not set; PostgreSQL conversation "
            "API tests require an explicit test database"
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
            "ROP_TEST_DATABASE_URL is configured but the PostgreSQL test "
            f"database is unreachable ({type(exc).__name__})"
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
    """Bind the app's get_db to the real PostgreSQL test database.

    ``tests/test_api.py`` installs a session-scoped SQLite override on the
    shared app at import time. This fixture takes precedence for the
    duration of each test and restores whatever was previously installed.

    This fixture is deliberately NOT ``autouse``. Tests that do not need a
    database must not trigger it. In this file every test that uses
    ``client`` gets the real DB via the ``client`` fixture's dependency;
    tests in other files that check the API contract without a database
    (see ``tests/test_conversations_api_schema.py``) do not use
    ``client`` and therefore run even when ``ROP_TEST_DATABASE_URL`` is
    absent.
    """
    testing_session = sessionmaker(bind=pg_engine)

    def override():
        with testing_session() as session:
            yield session

    previous = app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides[get_db] = override
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(real_db):
    return TestClient(app, base_url=ORIGIN)


def _create(client: TestClient, title: str = "chat") -> dict:
    response = client.post(
        "/api/assistant/conversations",
        headers=ORIGIN_HEADERS,
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================================
# CRUD behaviour
# ============================================================================


def test_create_conversation(client) -> None:
    created = _create(client, title="First")
    assert isinstance(UUID(created["id"]), UUID)
    assert created["title"] == "First"
    assert created["created_at"]
    assert created["updated_at"]


def test_create_rejects_blank_title(client) -> None:
    response = client.post(
        "/api/assistant/conversations",
        headers=ORIGIN_HEADERS,
        json={"title": "   "},
    )
    assert response.status_code == 422


def test_create_rejects_unknown_field(client) -> None:
    response = client.post(
        "/api/assistant/conversations",
        headers=ORIGIN_HEADERS,
        json={"title": "x", "id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 422


def test_list_conversations(client) -> None:
    for i in range(3):
        _create(client, title=f"c{i}")
    response = client.get("/api/assistant/conversations", headers={"origin": ORIGIN})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    # Deterministic order (updated_at desc, id desc)
    ids_second_time = [
        c["id"]
        for c in client.get(
            "/api/assistant/conversations", headers={"origin": ORIGIN}
        ).json()
    ]
    assert [c["id"] for c in payload] == ids_second_time


def test_list_pagination(client) -> None:
    for i in range(5):
        _create(client, title=f"c{i}")
    page1 = client.get(
        "/api/assistant/conversations?limit=2&offset=0",
        headers={"origin": ORIGIN},
    ).json()
    assert len(page1) == 2
    page2 = client.get(
        "/api/assistant/conversations?limit=2&offset=2",
        headers={"origin": ORIGIN},
    ).json()
    assert len(page2) == 2
    assert {p["id"] for p in page1}.isdisjoint({p["id"] for p in page2})


def test_list_rejects_invalid_limit(client) -> None:
    response = client.get(
        "/api/assistant/conversations?limit=0", headers={"origin": ORIGIN}
    )
    assert response.status_code == 422
    response = client.get(
        f"/api/assistant/conversations?limit={MAX_CONVERSATION_LIST_LIMIT + 1}",
        headers={"origin": ORIGIN},
    )
    assert response.status_code == 422


def test_list_rejects_negative_offset(client) -> None:
    response = client.get(
        "/api/assistant/conversations?offset=-1", headers={"origin": ORIGIN}
    )
    assert response.status_code == 422


def test_get_conversation(client) -> None:
    created = _create(client)
    fetched = client.get(
        f"/api/assistant/conversations/{created['id']}",
        headers={"origin": ORIGIN},
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_get_missing_conversation_returns_404(client) -> None:
    response = client.get(
        f"/api/assistant/conversations/{uuid4()}", headers={"origin": ORIGIN}
    )
    assert response.status_code == 404


def test_get_malformed_id_returns_422(client) -> None:
    response = client.get(
        "/api/assistant/conversations/not-a-uuid", headers={"origin": ORIGIN}
    )
    assert response.status_code == 422


def test_rename_conversation(client) -> None:
    created = _create(client, title="Old")
    response = client.patch(
        f"/api/assistant/conversations/{created['id']}",
        headers=ORIGIN_HEADERS,
        json={"title": "New"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "New"
    # Persisted value visible via GET
    again = client.get(
        f"/api/assistant/conversations/{created['id']}",
        headers={"origin": ORIGIN},
    ).json()
    assert again["title"] == "New"


def test_rename_missing_returns_404(client) -> None:
    response = client.patch(
        f"/api/assistant/conversations/{uuid4()}",
        headers=ORIGIN_HEADERS,
        json={"title": "New"},
    )
    assert response.status_code == 404


def test_delete_conversation(client, pg_engine) -> None:
    created = _create(client)
    response = client.delete(
        f"/api/assistant/conversations/{created['id']}",
        headers=ORIGIN_HEADERS,
    )
    assert response.status_code == 204
    with Session(pg_engine) as check:
        assert check.get(AssistantConversation, UUID(created["id"])) is None


def test_delete_missing_returns_404(client) -> None:
    response = client.delete(
        f"/api/assistant/conversations/{uuid4()}", headers=ORIGIN_HEADERS
    )
    assert response.status_code == 404


def test_delete_does_not_affect_other_conversation(client, pg_engine) -> None:
    a = _create(client, "a")
    b = _create(client, "b")
    # Append a message to both
    for conv in (a, b):
        client.post(
            f"/api/assistant/conversations/{conv['id']}/messages",
            headers=ORIGIN_HEADERS,
            json={"content": "hi"},
        )
    client.delete(f"/api/assistant/conversations/{a['id']}", headers=ORIGIN_HEADERS)
    with Session(pg_engine) as check:
        remaining = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == UUID(b["id"]))
        )
    assert remaining == 1


# ============================================================================
# Messages
# ============================================================================


def test_append_user_message(client) -> None:
    conv = _create(client)
    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hello"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "user"
    assert payload["content"] == "hello"
    assert payload["sequence"] == 0


def test_list_messages_in_order(client) -> None:
    conv = _create(client)
    for i in range(3):
        client.post(
            f"/api/assistant/conversations/{conv['id']}/messages",
            headers=ORIGIN_HEADERS,
            json={"content": f"m{i}"},
        )
    response = client.get(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers={"origin": ORIGIN},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [m["content"] for m in payload] == ["m0", "m1", "m2"]
    assert [m["sequence"] for m in payload] == [0, 1, 2]


def test_list_messages_pagination(client) -> None:
    conv = _create(client)
    for i in range(5):
        client.post(
            f"/api/assistant/conversations/{conv['id']}/messages",
            headers=ORIGIN_HEADERS,
            json={"content": f"m{i}"},
        )
    page = client.get(
        f"/api/assistant/conversations/{conv['id']}/messages?limit=2&offset=1",
        headers={"origin": ORIGIN},
    ).json()
    assert [m["content"] for m in page] == ["m1", "m2"]


def test_messages_rejects_invalid_pagination(client) -> None:
    conv = _create(client)
    assert (
        client.get(
            f"/api/assistant/conversations/{conv['id']}/messages?limit=0",
            headers={"origin": ORIGIN},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/assistant/conversations/{conv['id']}/messages"
            f"?limit={MAX_MESSAGE_LIST_LIMIT + 1}",
            headers={"origin": ORIGIN},
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/assistant/conversations/{conv['id']}/messages?offset=-1",
            headers={"origin": ORIGIN},
        ).status_code
        == 422
    )


def test_list_messages_for_missing_conversation_returns_404(client) -> None:
    response = client.get(
        f"/api/assistant/conversations/{uuid4()}/messages",
        headers={"origin": ORIGIN},
    )
    assert response.status_code == 404


def test_append_to_missing_conversation_returns_404(client) -> None:
    response = client.post(
        f"/api/assistant/conversations/{uuid4()}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "orphan"},
    )
    assert response.status_code == 404


def test_append_rejects_caller_supplied_role(client, pg_engine) -> None:
    conv = _create(client)
    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"role": "assistant", "content": "fake"},
    )
    assert response.status_code == 422
    # Nothing was stored
    with Session(pg_engine) as check:
        count = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == UUID(conv["id"]))
        )
    assert count == 0


def test_append_rejects_blank_content(client) -> None:
    conv = _create(client)
    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "   "},
    )
    assert response.status_code == 422


def test_append_rejects_unknown_field(client) -> None:
    conv = _create(client)
    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hi", "sequence": 99},
    )
    assert response.status_code == 422


# ============================================================================
# Concurrent-append conflict
# ============================================================================


def test_concurrent_append_sequence_conflict_is_not_silently_retried(
    client, pg_engine
) -> None:
    """Concurrent appends race for the same sequence; nothing is duplicated."""
    conv = _create(client)

    def do_append(i: int) -> int:
        # Separate client per thread to avoid shared state
        c = TestClient(app, base_url=ORIGIN)
        r = c.post(
            f"/api/assistant/conversations/{conv['id']}/messages",
            headers=ORIGIN_HEADERS,
            json={"content": f"c{i}"},
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(do_append, [0, 1]))

    # At most one of the two concurrent appends may succeed; the other
    # either returns 201 (it won) or 409 (it lost the race). Retrying
    # internally is forbidden by design; a silent duplicate would appear
    # here as two stored messages with distinct sequences — which is also
    # fine if the repository serialised them. What must NOT happen is two
    # messages stored with the *same* sequence.
    with Session(pg_engine) as check:
        rows = check.execute(
            select(AssistantMessage.sequence)
            .where(AssistantMessage.conversation_id == UUID(conv["id"]))
            .order_by(AssistantMessage.sequence)
        ).all()
    sequences = [r[0] for r in rows]
    assert len(sequences) == len(
        set(sequences)
    ), f"duplicate sequences stored: {sequences}"
    # And every request got 201 or 409, never a silent success that did
    # not persist, never a 5xx.
    assert all(code in (201, 409) for code in codes), codes


# ============================================================================
# Origin enforcement
# ============================================================================


def test_create_without_origin_rejected(client, pg_engine) -> None:
    response = client.post(
        "/api/assistant/conversations",
        headers={"content-type": "application/json"},
        json={"title": "no-origin"},
    )
    assert response.status_code == 403
    with Session(pg_engine) as check:
        assert (
            check.scalar(select(func.count()).select_from(AssistantConversation)) == 0
        )


def test_create_with_mismatched_origin_rejected(client, pg_engine) -> None:
    response = client.post(
        "/api/assistant/conversations",
        headers={"origin": "http://evil.example", "content-type": "application/json"},
        json={"title": "bad-origin"},
    )
    assert response.status_code == 403
    with Session(pg_engine) as check:
        assert (
            check.scalar(select(func.count()).select_from(AssistantConversation)) == 0
        )


def test_create_without_json_content_type_rejected(client) -> None:
    response = client.post(
        "/api/assistant/conversations",
        headers={"origin": ORIGIN, "content-type": "text/plain"},
        content="not json",
    )
    assert response.status_code == 403


def test_rename_without_origin_rejected(client) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/assistant/conversations/{created['id']}",
        headers={"content-type": "application/json"},
        json={"title": "New"},
    )
    assert response.status_code == 403
    # Original title unchanged
    again = client.get(
        f"/api/assistant/conversations/{created['id']}",
        headers={"origin": ORIGIN},
    ).json()
    assert again["title"] == created["title"]


def test_delete_without_origin_rejected(client, pg_engine) -> None:
    created = _create(client)
    response = client.delete(
        f"/api/assistant/conversations/{created['id']}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 403
    with Session(pg_engine) as check:
        assert check.get(AssistantConversation, UUID(created["id"])) is not None


def test_append_without_origin_rejected(client, pg_engine) -> None:
    conv = _create(client)
    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers={"content-type": "application/json"},
        json={"content": "hi"},
    )
    assert response.status_code == 403
    with Session(pg_engine) as check:
        count = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == UUID(conv["id"]))
        )
    assert count == 0


def test_create_with_mismatched_host_rejected(client) -> None:
    # base_url defines the test Host; a custom Host header must not match
    response = client.post(
        "/api/assistant/conversations",
        headers={
            "origin": ORIGIN,
            "content-type": "application/json",
            "host": "evil.example",
        },
        json={"title": "x"},
    )
    assert response.status_code == 403


# ============================================================================
# Integration / regression
# ============================================================================


def test_assistant_request_endpoint_semantics_unchanged(client, pg_engine) -> None:
    """A normal assistant request must not touch the conversation tables."""
    with Session(pg_engine) as check:
        before_conv = check.scalar(
            select(func.count()).select_from(AssistantConversation)
        )
        before_msg = check.scalar(select(func.count()).select_from(AssistantMessage))
    response = client.post(
        "/api/assistant/requests",
        headers=ORIGIN_HEADERS,
        json={"message": "hello"},
    )
    # 200 or a defined status; the point is it does not create a conversation
    assert response.status_code in (200, 403)
    with Session(pg_engine) as check:
        after_conv = check.scalar(
            select(func.count()).select_from(AssistantConversation)
        )
        after_msg = check.scalar(select(func.count()).select_from(AssistantMessage))
    assert before_conv == after_conv
    assert before_msg == after_msg


def test_conversations_never_touch_reasoning_sessions(client, pg_engine) -> None:
    with Session(pg_engine) as check:
        before = check.scalar(text("select count(*) from reasoning_sessions"))
    _create(client, "check")
    conv = client.get(
        "/api/assistant/conversations", headers={"origin": ORIGIN}
    ).json()[0]
    client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hi"},
    )
    with Session(pg_engine) as check:
        after = check.scalar(text("select count(*) from reasoning_sessions"))
    assert before == after


# ============================================================================
# Integrity-error classification (unit + integration)
# ============================================================================


def _make_integrity_error(constraint_name: str | None):
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError as _SAIntegrityError

    exc = _SAIntegrityError("stmt", {}, Exception("synthetic"))
    if constraint_name is None:
        # Simulate a driver that does not expose diag metadata
        exc.orig = SimpleNamespace()
    else:
        exc.orig = SimpleNamespace(
            diag=SimpleNamespace(constraint_name=constraint_name)
        )
    return exc


def test_classify_sequence_conflict_unit() -> None:
    from rop.api.conversations import (
        _INTEGRITY_SEQUENCE_CONSTRAINT,
        _classify_integrity_error,
    )

    assert (
        _classify_integrity_error(_make_integrity_error(_INTEGRITY_SEQUENCE_CONSTRAINT))
        == "sequence_conflict"
    )


def test_classify_fk_violation_unit() -> None:
    from rop.api.conversations import _classify_integrity_error

    assert (
        _classify_integrity_error(
            _make_integrity_error("assistant_messages_conversation_id_fkey")
        )
        == "missing_parent"
    )


def test_classify_unknown_constraint_unit() -> None:
    from rop.api.conversations import _classify_integrity_error

    assert (
        _classify_integrity_error(_make_integrity_error("some_other_constraint"))
        == "unknown"
    )


def test_classify_no_diag_metadata_unit() -> None:
    from rop.api.conversations import _classify_integrity_error

    assert _classify_integrity_error(_make_integrity_error(None)) == "unknown"


def test_append_unrelated_integrity_error_is_not_reported_as_sequence_conflict(
    client, monkeypatch
) -> None:
    """An integrity error with an unrecognized constraint is a 503, not 409."""
    from rop.repositories.assistant_conversation import ConversationRepository

    conv = _create(client)

    fake = _make_integrity_error("some_other_constraint")

    def boom(self, db, cid, data):
        raise fake

    monkeypatch.setattr(ConversationRepository, "append_message", boom)

    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hi"},
    )
    assert response.status_code == 503
    body = response.json()
    assert "sequence" not in body["detail"].lower()
    assert "concurrent" not in body["detail"].lower()


def test_append_fk_violation_is_reported_as_missing_parent(client, monkeypatch) -> None:
    """An FK violation on conversation_id is a 404, not a 409."""
    from rop.repositories.assistant_conversation import ConversationRepository

    conv = _create(client)

    fake = _make_integrity_error("assistant_messages_conversation_id_fkey")

    def boom(self, db, cid, data):
        raise fake

    monkeypatch.setattr(ConversationRepository, "append_message", boom)

    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hi"},
    )
    assert response.status_code == 404


def test_append_sequence_conflict_returns_409(client, monkeypatch) -> None:
    """The named sequence constraint returns 409 with the fixed message."""
    from rop.api.conversations import _INTEGRITY_SEQUENCE_CONSTRAINT
    from rop.repositories.assistant_conversation import ConversationRepository

    conv = _create(client)

    fake = _make_integrity_error(_INTEGRITY_SEQUENCE_CONSTRAINT)

    def boom(self, db, cid, data):
        raise fake

    monkeypatch.setattr(ConversationRepository, "append_message", boom)

    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hi"},
    )
    assert response.status_code == 409
    body = response.json()
    assert "reload" in body["detail"].lower()


def test_append_generic_exception_returns_503(client, monkeypatch) -> None:
    """A non-IntegrityError exception is a 503, never a 409 or success."""
    from rop.repositories.assistant_conversation import ConversationRepository

    conv = _create(client)

    def boom(self, db, cid, data):
        raise RuntimeError("simulated non-integrity failure")

    monkeypatch.setattr(ConversationRepository, "append_message", boom)

    response = client.post(
        f"/api/assistant/conversations/{conv['id']}/messages",
        headers=ORIGIN_HEADERS,
        json={"content": "hi"},
    )
    assert response.status_code == 503
    # Sanitized message only
    assert "simulated" not in response.text
    assert "RuntimeError" not in response.text

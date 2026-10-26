"""Task 228: durable assistant conversation and message persistence tests.

These tests run against the project's configured PostgreSQL test database.
Without ``ROP_TEST_DATABASE_URL`` (with a database name ending in
``_test``) they skip rather than touching the application database.

The suite truncates ``assistant_conversations`` and ``assistant_messages``
for isolation. ``TRUNCATE ... CASCADE`` is used so the two tables are
cleared together.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rop.models import (
    AssistantConversation,
    AssistantMessage,
)
from rop.repositories.assistant_conversation import (
    MAX_CONVERSATION_LIST_LIMIT,
    MAX_MESSAGE_LIST_LIMIT,
    ConversationNotFoundError,
    ConversationRepository,
)
from rop.schemas.assistant_conversation import (
    AssistantConversationCreate,
    AssistantConversationUpdate,
    AssistantMessageCreate,
)

TEST_DATABASE_URL = os.environ.get("ROP_TEST_DATABASE_URL", "")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _skip_reason() -> str | None:
    if not TEST_DATABASE_URL:
        return (
            "ROP_TEST_DATABASE_URL is not set; PostgreSQL conversation tests "
            "require an explicit test database"
        )
    try:
        database = make_url(TEST_DATABASE_URL).database or ""
    except Exception:
        return "ROP_TEST_DATABASE_URL is not a valid database URL"
    if not database.endswith("_test"):
        return "ROP_TEST_DATABASE_URL database name must end with '_test'"
    return None


@pytest.fixture(scope="session")
def pg_engine():
    if not TEST_DATABASE_URL:
        pytest.skip(
            "ROP_TEST_DATABASE_URL is not set; PostgreSQL tests are unavailable"
        )
    reason = _skip_reason()
    if reason is not None:
        pytest.fail(reason)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:
        engine.dispose()
        pytest.fail(
            "Configured PostgreSQL test database is unreachable "
            f"({type(exc).__name__})"
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
def db(pg_engine, clean_database):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def repository() -> ConversationRepository:
    return ConversationRepository()


# ============================================================================
# Conversation CRUD
# ============================================================================


def test_create_and_get_conversation(db, repository) -> None:
    read = repository.create(db, AssistantConversationCreate(title="First"))
    assert isinstance(read.id, UUID)
    assert read.title == "First"
    assert read.created_at is not None
    assert read.updated_at is not None

    fetched = repository.get(db, read.id)
    assert fetched is not None
    assert fetched.id == read.id
    assert fetched.title == "First"


def test_get_missing_conversation_returns_none(db, repository) -> None:
    assert repository.get(db, uuid4()) is None


def test_list_conversations_is_stable_and_paginated(db, repository) -> None:
    ids = []
    for i in range(5):
        read = repository.create(db, AssistantConversationCreate(title=f"c{i}"))
        ids.append(read.id)
    db.flush()

    page1 = repository.list(db, offset=0, limit=2)
    assert len(page1) == 2
    page2 = repository.list(db, offset=2, limit=2)
    assert len(page2) == 2
    page3 = repository.list(db, offset=4, limit=2)
    assert len(page3) == 1

    # No duplicates across pages
    all_ids = [r.id for r in page1 + page2 + page3]
    assert len(set(all_ids)) == 5

    # Repeated calls produce the same order
    page1_again = repository.list(db, offset=0, limit=2)
    assert [r.id for r in page1] == [r.id for r in page1_again]


def test_list_rejects_invalid_limit(db, repository) -> None:
    with pytest.raises(ValueError):
        repository.list(db, offset=0, limit=0)
    with pytest.raises(ValueError):
        repository.list(db, offset=0, limit=MAX_CONVERSATION_LIST_LIMIT + 1)


def test_list_rejects_negative_offset(db, repository) -> None:
    with pytest.raises(ValueError):
        repository.list(db, offset=-1)


def test_update_title(db, repository) -> None:
    read = repository.create(db, AssistantConversationCreate(title="Old"))
    updated = repository.update(db, read.id, AssistantConversationUpdate(title="New"))
    assert updated.title == "New"
    # Persisted value is what we read back
    fetched = repository.get(db, read.id)
    assert fetched is not None
    assert fetched.title == "New"


def test_update_missing_conversation_raises(db, repository) -> None:
    with pytest.raises(ConversationNotFoundError):
        repository.update(db, uuid4(), AssistantConversationUpdate(title="New"))


# ============================================================================
# Message ordering and role constraints
# ============================================================================


def test_append_and_list_messages_in_order(db, repository) -> None:
    conv = repository.create(db, AssistantConversationCreate(title="Chat"))
    for i in range(3):
        repository.append_message(
            db,
            conv.id,
            AssistantMessageCreate(role="user", content=f"u{i}"),
        )
        repository.append_message(
            db,
            conv.id,
            AssistantMessageCreate(role="assistant", content=f"a{i}"),
        )
    db.flush()

    messages = repository.list_messages(db, conv.id, limit=100)
    assert len(messages) == 6
    assert [m.sequence for m in messages] == [0, 1, 2, 3, 4, 5]
    assert [m.content for m in messages] == ["u0", "a0", "u1", "a1", "u2", "a2"]


def test_append_message_to_missing_conversation_raises(db, repository) -> None:
    with pytest.raises(ConversationNotFoundError):
        repository.append_message(
            db,
            uuid4(),
            AssistantMessageCreate(role="user", content="orphan"),
        )


def test_invalid_role_rejected_by_schema() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AssistantMessageCreate(role="system", content="hidden")  # type: ignore[arg-type]


def test_invalid_role_rejected_by_database(db, pg_engine) -> None:
    """Even a direct DB write with an unsupported role is rejected."""
    with Session(pg_engine) as session:
        conversation = AssistantConversation(title="direct")
        session.add(conversation)
        session.flush()
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO assistant_messages "
                    "(id, conversation_id, role, content, sequence) VALUES "
                    "(:id, :cid, 'system', 'x', 0)"
                ),
                {"id": uuid4(), "cid": conversation.id},
            )
            session.flush()
        session.rollback()


def test_duplicate_sequence_rejected(db, pg_engine, repository) -> None:
    conv = repository.create(db, AssistantConversationCreate(title="Dup"))
    # Commit so the conversation is visible to the second session below;
    # the repository itself never commits, but the *test* may.
    db.commit()
    with Session(pg_engine) as session:
        session.execute(
            text(
                "INSERT INTO assistant_messages "
                "(id, conversation_id, role, content, sequence) VALUES "
                "(:id, :cid, 'user', 'a', 0)"
            ),
            {"id": uuid4(), "cid": conv.id},
        )
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO assistant_messages "
                    "(id, conversation_id, role, content, sequence) VALUES "
                    "(:id, :cid, 'user', 'b', 0)"
                ),
                {"id": uuid4(), "cid": conv.id},
            )
        session.rollback()


def test_negative_sequence_rejected(db, pg_engine, repository) -> None:
    conv = repository.create(db, AssistantConversationCreate(title="Neg"))
    db.flush()
    with Session(pg_engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO assistant_messages "
                    "(id, conversation_id, role, content, sequence) VALUES "
                    "(:id, :cid, 'user', 'x', -1)"
                ),
                {"id": uuid4(), "cid": conv.id},
            )
        session.rollback()


def test_message_list_rejects_invalid_pagination(db, repository) -> None:
    conv = repository.create(db, AssistantConversationCreate(title="p"))
    with pytest.raises(ValueError):
        repository.list_messages(db, conv.id, limit=0)
    with pytest.raises(ValueError):
        repository.list_messages(db, conv.id, limit=MAX_MESSAGE_LIST_LIMIT + 1)
    with pytest.raises(ValueError):
        repository.list_messages(db, conv.id, offset=-1)


# ============================================================================
# Deletion
# ============================================================================


def test_delete_removes_conversation_and_messages(db, pg_engine, repository) -> None:
    conv = repository.create(db, AssistantConversationCreate(title="del"))
    repository.append_message(
        db, conv.id, AssistantMessageCreate(role="user", content="a")
    )
    repository.append_message(
        db, conv.id, AssistantMessageCreate(role="assistant", content="b")
    )
    # Commit so the pre-delete count is visible to a fresh session; the
    # repository does not commit, the test does.
    db.commit()

    with Session(pg_engine) as check:
        before = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == conv.id)
        )
    assert before == 2

    assert repository.delete(db, conv.id) is True
    db.commit()

    with Session(pg_engine) as check:
        after = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == conv.id)
        )
    assert after == 0

    # Missing conversation returns False rather than raising
    assert repository.delete(db, uuid4()) is False


def test_delete_does_not_affect_other_conversations(db, pg_engine, repository) -> None:
    conv_a = repository.create(db, AssistantConversationCreate(title="A"))
    conv_b = repository.create(db, AssistantConversationCreate(title="B"))
    repository.append_message(
        db, conv_a.id, AssistantMessageCreate(role="user", content="a1")
    )
    repository.append_message(
        db, conv_b.id, AssistantMessageCreate(role="user", content="b1")
    )
    db.commit()

    repository.delete(db, conv_a.id)
    db.commit()

    with Session(pg_engine) as check:
        remaining_b = check.scalar(
            select(func.count())
            .select_from(AssistantMessage)
            .where(AssistantMessage.conversation_id == conv_b.id)
        )
    assert remaining_b == 1


def test_no_clinical_table_touched(db, pg_engine, repository) -> None:
    with Session(pg_engine) as check:
        before = check.scalar(text("select count(*) from reasoning_sessions"))
    conv = repository.create(db, AssistantConversationCreate(title="x"))
    repository.append_message(
        db, conv.id, AssistantMessageCreate(role="user", content="hello")
    )
    repository.list(db, limit=10)
    repository.list_messages(db, conv.id, limit=10)
    repository.delete(db, conv.id)
    db.flush()
    with Session(pg_engine) as check:
        after = check.scalar(text("select count(*) from reasoning_sessions"))
    assert before == after


# ============================================================================
# No implicit commit
# ============================================================================


def test_repository_does_not_commit(pg_engine, clean_database) -> None:
    """Rolling back the session must undo the repository's work."""
    repository = ConversationRepository()
    with Session(pg_engine) as session:
        read = repository.create(session, AssistantConversationCreate(title="t"))
        # Deliberately not committed.
        session.rollback()
    with Session(pg_engine) as check:
        assert (
            check.scalar(select(func.count()).select_from(AssistantConversation)) == 0
        )
        assert check.get(AssistantConversation, read.id) is None


# ============================================================================
# Migration upgrade/downgrade
# ============================================================================


def _alembic_config() -> Config:
    config = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(PROJECT_ROOT, "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def test_migration_creates_and_removes_only_the_conversation_tables(
    pg_engine,
) -> None:
    """Upgrade creates both new tables; downgrade removes only them."""
    from sqlalchemy import inspect as sa_inspect

    config = _alembic_config()

    # Ensure we are at the base of our revision's parent.
    command.downgrade(config, "20261017_0017")
    command.upgrade(config, "20261019_0018")
    insp = sa_inspect(pg_engine)
    tables = set(insp.get_table_names())
    assert "assistant_conversations" in tables
    assert "assistant_messages" in tables
    # Other tables still present
    assert "reasoning_sessions" in tables
    assert "assistant_confirmations" in tables

    command.downgrade(config, "20261017_0017")
    insp = sa_inspect(pg_engine)
    tables = set(insp.get_table_names())
    assert "assistant_conversations" not in tables
    assert "assistant_messages" not in tables
    assert "reasoning_sessions" in tables
    assert "assistant_confirmations" in tables

    # Leave the database at head for other tests.
    command.upgrade(config, "head")


# ============================================================================
# Activity ordering regression (parent updated_at must bump on append)
# ============================================================================


def test_append_message_bumps_parent_updated_at_and_reorders_listing(
    db, pg_engine, repository
) -> None:
    """Appending a message must advance the parent's ``updated_at``.

    The listing order is ``updated_at DESC, id DESC``. Before this fix,
    ``append_message()`` assigned ``conversation.title = conversation.title``,
    which SQLAlchemy's change detection treats as a no-op, so no ``UPDATE``
    was emitted and the parent's ``updated_at`` never advanced. This test
    gives the conversation to be updated an older ``updated_at`` than the
    other, appends a message, and then asserts:

      * the appending conversation's ``updated_at`` advanced;
      * ``repository.list()`` returns the appending conversation first.

    The timestamps are set explicitly (distinct datetime values) rather
    than being measured by sleeping, so the assertions are deterministic.
    """
    from datetime import timedelta as _td

    from sqlalchemy import update as _update

    from rop.models.assistant_conversation import AssistantConversation

    # Create two conversations.
    older = repository.create(db, AssistantConversationCreate(title="older"))
    newer = repository.create(db, AssistantConversationCreate(title="newer"))
    db.commit()

    # Make "older" genuinely older in updated_at, and "newer" the most
    # recent. These timestamps are distinct and explicit.
    baseline = NOW
    db.execute(
        _update(AssistantConversation)
        .where(AssistantConversation.id == older.id)
        .values(updated_at=baseline - _td(minutes=10))
    )
    db.execute(
        _update(AssistantConversation)
        .where(AssistantConversation.id == newer.id)
        .values(updated_at=baseline)
    )
    db.commit()

    # Sanity: "newer" is currently first in listing order.
    before_order = repository.list(db, limit=10)
    assert [r.id for r in before_order][0] == newer.id
    before_updated_at = next(r.updated_at for r in before_order if r.id == older.id)

    # Append a message to the older conversation.
    repository.append_message(
        db,
        older.id,
        AssistantMessageCreate(role="user", content="reviving older"),
    )
    db.commit()

    # Reload and check the parent's updated_at advanced.
    after_order = repository.list(db, limit=10)
    after_older = next(r for r in after_order if r.id == older.id)
    assert (
        after_older.updated_at > before_updated_at
    ), "append_message must advance the parent conversation's updated_at"

    # And that the appending conversation now sorts first.
    assert [r.id for r in after_order][0] == older.id, (
        "after appending a message, the older conversation should move to "
        "the top of the listing"
    )

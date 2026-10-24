"""Bounded startup cleanup for expired pending assistant clarifications."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop.database import Base
from rop.models.assistant_conversation import AssistantConversation
from rop.models.assistant_pending_clarification import AssistantPendingClarification
from rop.repositories.assistant_pending_clarification import (
    AssistantPendingClarificationRepository,
)
from rop.services.clarification_recovery import (
    CLARIFICATION_RECOVERY_BATCH_LIMIT,
    recover_pending_clarification_state,
)


def _session_factory():
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
    return engine, factory


def _seed_expired_clarifications(factory, count: int) -> list[UUID]:
    ids: list[UUID] = []
    now = datetime.now(UTC)
    with factory() as session:
        conversation = AssistantConversation(title="clarification cleanup test")
        session.add(conversation)
        session.flush()
        for index in range(count):
            row_id = uuid4()
            ids.append(row_id)
            session.add(
                AssistantPendingClarification(
                    id=row_id,
                    clarification_id=uuid4(),
                    conversation_id=conversation.id,
                    capability_identifier="workspace-command",
                    original_message=f"PRIVATE_ORIGINAL_{index}",
                    partial_operation={"title": f"PRIVATE_TITLE_{index}"},
                    missing_fields=["title"],
                    question="What title should I use?",
                    expires_at=now - timedelta(minutes=11),
                    status="PENDING",
                )
            )
        session.commit()
    return ids


def test_startup_recovery_deletes_expired_clarifications_and_keeps_active() -> None:
    engine, factory = _session_factory()
    try:
        expired_ids = _seed_expired_clarifications(factory, 2)
        cleanup_now = datetime.now(UTC)
        active_id = uuid4()
        with factory() as session:
            conversation_id = session.scalar(select(AssistantConversation.id))
            session.add(
                AssistantPendingClarification(
                    id=active_id,
                    clarification_id=uuid4(),
                    conversation_id=conversation_id,
                    capability_identifier="workspace-command",
                    original_message="PRIVATE_ACTIVE_MESSAGE",
                    partial_operation={"title": "PRIVATE_ACTIVE_TITLE"},
                    missing_fields=["title"],
                    question="What title should I use?",
                    expires_at=cleanup_now + timedelta(minutes=5),
                    status="PENDING",
                )
            )
            session.commit()

        recovered = recover_pending_clarification_state(
            session_factory=factory,
            now=cleanup_now,
        )

        assert recovered is True
        with factory() as session:
            remaining_expired = session.scalar(
                select(func.count())
                .select_from(AssistantPendingClarification)
                .where(AssistantPendingClarification.id.in_(expired_ids))
            )
            active = session.get(AssistantPendingClarification, active_id)
        assert remaining_expired == 0
        assert active is not None
        assert active.status == "PENDING"
        assert active.original_message == "PRIVATE_ACTIVE_MESSAGE"
        assert active.partial_operation == {"title": "PRIVATE_ACTIVE_TITLE"}
    finally:
        engine.dispose()


def test_startup_cleanup_drains_backlog_in_bounded_transactions() -> None:
    engine, factory = _session_factory()
    try:
        total = CLARIFICATION_RECOVERY_BATCH_LIMIT + 5
        ids = _seed_expired_clarifications(factory, total)

        recovered = recover_pending_clarification_state(
            session_factory=factory,
            batch_limit=total,
            now=datetime.now(UTC),
        )

        assert recovered is True
        with factory() as session:
            remaining = session.scalar(
                select(func.count())
                .select_from(AssistantPendingClarification)
                .where(AssistantPendingClarification.id.in_(ids))
            )
        assert remaining == 0
    finally:
        engine.dispose()


def test_consumed_clarification_is_redacted_then_deleted() -> None:
    engine, factory = _session_factory()
    repository = AssistantPendingClarificationRepository()
    try:
        ids = _seed_expired_clarifications(factory, 1)
        with factory() as session:
            row = session.get(AssistantPendingClarification, ids[0])
            assert row is not None
            repository.consume_and_clear(session, row, now=datetime.now(UTC))
            session.commit()

        with factory() as session:
            redacted = session.get(AssistantPendingClarification, ids[0])
            assert redacted is not None
            assert redacted.status == "CONSUMED"
            assert redacted.original_message == ""
            assert redacted.partial_operation == {}
            assert redacted.missing_fields == []
            assert redacted.question == ""

            deleted = repository.delete_expired(session, now=datetime.now(UTC))
            session.commit()
        assert deleted == 1

        with factory() as session:
            assert session.get(AssistantPendingClarification, ids[0]) is None
    finally:
        engine.dispose()

class _FakeSession:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self) -> None:
        if self.commit_error:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


class _FakeRepository:
    def __init__(
        self,
        error: Exception | None = None,
        deleted_counts: list[int] | None = None,
    ) -> None:
        self.error = error
        self.deleted_counts = list(deleted_counts) if deleted_counts is not None else [1]
        self.limits: list[int] = []

    def delete_expired(self, session, *, now=None, limit=100) -> int:
        self.limits.append(limit)
        if self.error:
            raise self.error
        return self.deleted_counts.pop(0) if self.deleted_counts else 0


def test_recovery_caps_configured_batch_limit() -> None:
    session = _FakeSession()
    repository = _FakeRepository()

    assert recover_pending_clarification_state(
        session_factory=lambda: session,
        repository=repository,
        batch_limit=CLARIFICATION_RECOVERY_BATCH_LIMIT + 10,
    )
    assert repository.limits == [CLARIFICATION_RECOVERY_BATCH_LIMIT]
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


def test_recovery_repeats_full_batches_in_separate_transactions() -> None:
    sessions: list[_FakeSession] = []

    def session_factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    repository = _FakeRepository(
        deleted_counts=[CLARIFICATION_RECOVERY_BATCH_LIMIT, 3]
    )
    assert recover_pending_clarification_state(
        session_factory=session_factory,
        repository=repository,
        now=datetime.now(UTC),
    )

    assert repository.limits == [
        CLARIFICATION_RECOVERY_BATCH_LIMIT,
        CLARIFICATION_RECOVERY_BATCH_LIMIT,
    ]
    assert len(sessions) == 2
    assert [
        (session.commits, session.rollbacks, session.closes) for session in sessions
    ] == [(1, 0, 1), (1, 0, 1)]


def test_cleanup_failure_rolls_back_and_returns_false() -> None:
    session = _FakeSession()
    repository = _FakeRepository(error=RuntimeError("sensitive database detail"))

    recovered = recover_pending_clarification_state(
        session_factory=lambda: session,
        repository=repository,
    )

    assert recovered is False
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_commit_failure_rolls_back_and_returns_false() -> None:
    session = _FakeSession(commit_error=RuntimeError("sensitive database detail"))

    recovered = recover_pending_clarification_state(
        session_factory=lambda: session,
        repository=_FakeRepository(),
    )

    assert recovered is False
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_session_creation_failure_returns_false() -> None:
    def unavailable_database():
        raise RuntimeError("sensitive connection detail")

    assert (
        recover_pending_clarification_state(session_factory=unavailable_database)
        is False
    )


def test_invalid_cleanup_batch_is_rejected_without_opening_session() -> None:
    called = False

    def forbidden_factory():
        nonlocal called
        called = True
        raise AssertionError("session should not be opened")

    assert (
        recover_pending_clarification_state(
            session_factory=forbidden_factory,
            batch_limit=0,
        )
        is False
    )
    assert called is False

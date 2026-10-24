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


def test_startup_recovery_deletes_expired_clarification_values() -> None:
    engine, factory = _session_factory()
    try:
        ids = _seed_expired_clarifications(factory, 2)
        recovered = recover_pending_clarification_state(
            session_factory=factory,
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


def test_startup_cleanup_processes_only_one_bounded_batch() -> None:
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
            remaining_ids = set(
                session.scalars(
                    select(AssistantPendingClarification.id).where(
                        AssistantPendingClarification.id.in_(ids)
                    )
                ).all()
            )
        assert len(remaining_ids) == 5

        assert recover_pending_clarification_state(
            session_factory=factory,
            now=datetime.now(UTC),
        )
        with factory() as session:
            remaining = session.scalar(
                select(func.count())
                .select_from(AssistantPendingClarification)
                .where(AssistantPendingClarification.id.in_(ids))
            )
        assert remaining == 0
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
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.limits: list[int] = []

    def delete_expired(self, session, *, now=None, limit=100) -> int:
        self.limits.append(limit)
        if self.error:
            raise self.error
        return 1


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

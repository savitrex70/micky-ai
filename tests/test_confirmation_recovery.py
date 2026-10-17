from __future__ import annotations

import asyncio

import rop.main as main_module
from rop.services.confirmation_recovery import (
    RECOVERY_BATCH_LIMIT,
    recover_confirmation_state,
)


class FakeSession:
    def __init__(self, *, commit_error: Exception | None = None):
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self):
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class FakeRepository:
    def __init__(self, *, expire_error: Exception | None = None):
        self.expire_error = expire_error
        self.mark_limits: list[int] = []
        self.expire_limits: list[int] = []

    def mark_unestablished_outcomes(self, session, *, limit):
        self.mark_limits.append(limit)
        return 1

    def expire_overdue(self, session, *, limit, now=None):
        self.expire_limits.append(limit)
        if self.expire_error is not None:
            raise self.expire_error
        return 1


def test_recovery_commits_one_bounded_transaction() -> None:
    session = FakeSession()
    repository = FakeRepository()

    recovered = recover_confirmation_state(
        session_factory=lambda: session,
        repository=repository,
    )

    assert recovered is True
    assert repository.mark_limits == [RECOVERY_BATCH_LIMIT]
    assert repository.expire_limits == [RECOVERY_BATCH_LIMIT]
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


def test_recovery_rolls_back_if_a_sweep_fails() -> None:
    session = FakeSession()
    repository = FakeRepository(expire_error=RuntimeError("sensitive db details"))

    recovered = recover_confirmation_state(
        session_factory=lambda: session,
        repository=repository,
    )

    assert recovered is False
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_recovery_does_not_claim_success_if_commit_fails() -> None:
    session = FakeSession(commit_error=RuntimeError("sensitive db details"))

    recovered = recover_confirmation_state(
        session_factory=lambda: session,
        repository=FakeRepository(),
    )

    assert recovered is False
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_recovery_handles_session_creation_failure() -> None:
    def unavailable_database():
        raise RuntimeError("sensitive connection details")

    assert recover_confirmation_state(session_factory=unavailable_database) is False


def test_lifespan_still_starts_when_database_recovery_is_unavailable(
    monkeypatch,
) -> None:
    started: list[bool] = []
    monkeypatch.setattr(main_module, "configure_logging", lambda level: None)
    monkeypatch.setattr(main_module, "recover_confirmation_state", lambda: False)

    async def exercise_lifespan() -> None:
        async with main_module.lifespan(main_module.app):
            started.append(True)

    asyncio.run(exercise_lifespan())
    assert started == [True]

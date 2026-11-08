"""End-to-end tests for conversational workspace management (Task 249).

Natural-language requests such as "Mark the Ward revision task as
complete" must resolve to one exact existing record, keep every
existing confirmation / idempotency guarantee, and fail closed when the
target is missing, ambiguous, or changed. Read-only pending listings
never require confirmation.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop import database as database_module
from rop.database import Base, get_db
from rop.main import app
from rop.services import workspace_executor
from rop.services.workspace_selector import (
    bind_resolved_target,
    item_version_token,
    normalize_selector_title,
    resolve_selector_title,
    verify_disambiguated_target,
)

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


def _seed_item(
    *,
    kind: str,
    title: str,
    content: str = "",
    completed: bool = False,
    due_at: datetime | None = None,
    timezone: str | None = None,
) -> UUID:
    """Insert one workspace item directly so tests control exact titles."""
    if kind == "reminder":
        assert due_at is not None and timezone is not None
    with database_module.SessionLocal() as session:
        from rop.models.assistant_item import AssistantItem

        item = AssistantItem(
            kind=kind,
            title=title,
            content=content,
            completed=completed,
            due_at=due_at,
            timezone=timezone,
        )
        session.add(item)
        session.commit()
        return item.id


def _items(client: TestClient, kind: str) -> list[dict]:
    response = client.get(
        f"/api/assistant/workspace/items?kind={kind}",
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


def _item_by_id(client: TestClient, kind: str, item_id: str) -> dict | None:
    for item in _items(client, kind):
        if item["id"] == item_id:
            return item
    return None


def _item_by_title(client: TestClient, kind: str, title: str) -> dict | None:
    for item in _items(client, kind):
        if item["title"] == title:
            return item
    return None


def _new_conversation(client: TestClient) -> str:
    created = client.post(
        "/api/assistant/conversations",
        headers=ORIGIN_HEADERS,
        json={"title": "Conversational workspace"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _send(
    client: TestClient,
    conversation_id: str,
    message: str,
    *,
    key: UUID | None = None,
    clarification_id: str | None = None,
) -> dict:
    payload: dict = {
        "message": message,
        "conversation_id": conversation_id,
        "idempotency_key": str(key or uuid4()),
    }
    if clarification_id is not None:
        payload["clarification_id"] = clarification_id
    response = client.post(
        "/api/assistant/requests",
        headers=ORIGIN_HEADERS,
        json=payload,
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


def _confirm_and_execute(client: TestClient, prepared: dict) -> dict:
    decided = _decide(
        client,
        prepared["challenge"],
        decision="confirm",
        display_code=prepared["challenge"]["display_code"],
    )
    assert decided.status_code == 200, decided.text
    return decided.json()


def _expire_confirmation(challenge: dict) -> None:
    with database_module.SessionLocal() as session:
        from rop.models.assistant_confirmation import AssistantConfirmation

        record = session.scalar(
            select(AssistantConfirmation).where(
                AssistantConfirmation.challenge_id == challenge["challenge_id"]
            )
        )
        assert record is not None
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()


def _expire_clarification(clarification_id: str) -> None:
    with database_module.SessionLocal() as session:
        from rop.models.assistant_pending_clarification import (
            AssistantPendingClarification,
        )

        record = session.scalar(
            select(AssistantPendingClarification).where(
                AssistantPendingClarification.clarification_id == UUID(clarification_id)
            )
        )
        assert record is not None
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()


def _install_uncertain_commit(monkeypatch: pytest.MonkeyPatch):
    """Commit the effect but force receipt recovery to report an unknown result."""
    real_factory = workspace_executor.SessionLocal
    real_recovery = workspace_executor._recover_receipt

    class _CommitThenLoseAcknowledgement:
        def __init__(self, inner) -> None:
            self.inner = inner
            self.first_commit = True

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self) -> None:
            self.inner.commit()
            if self.first_commit:
                self.first_commit = False
                raise RuntimeError("simulated lost commit acknowledgement")

    def wrapped_factory():
        return _CommitThenLoseAcknowledgement(real_factory())

    def unavailable_receipt_recovery(*args, **kwargs):
        from rop.services.workspace_executor import ExecutorInterrupted

        raise ExecutorInterrupted("receipt lookup temporarily unavailable")

    monkeypatch.setattr(workspace_executor, "SessionLocal", wrapped_factory)
    monkeypatch.setattr(
        workspace_executor, "_recover_receipt", unavailable_receipt_recovery
    )
    return real_factory, real_recovery


PAST_DUE = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Read-only pending listings
# ---------------------------------------------------------------------------


def test_pending_task_listing_phrases_are_read_only(client: TestClient) -> None:
    _seed_item(kind="task", title="Ward revision")
    _seed_item(kind="task", title="Lab follow-up", completed=True)
    conversation_id = _new_conversation(client)

    for phrase in (
        "Show my pending tasks",
        "List incomplete tasks",
        "What tasks do I still have to finish?",
    ):
        body = _send(client, conversation_id, phrase)
        assert body["status"] == "success", body
        assert "challenge" not in body
        assert "Found 1 pending tasks" in body["message"]
        assert "Ward revision [task, open," in body["message"]
        assert "Lab follow-up" not in body["message"]
        assert _receipt(client, uuid4())["status"] == "not-found"

    # Nothing was mutated by any listing request.
    titles = {item["title"] for item in _items(client, "task")}
    assert titles == {"Ward revision", "Lab follow-up"}


def test_pending_listing_empty_and_legacy_all_listing(client: TestClient) -> None:
    _seed_item(kind="note", title="Discharge summary", completed=True)
    conversation_id = _new_conversation(client)

    body = _send(client, conversation_id, "Show my pending notes")
    assert body["status"] == "success", body
    assert "No pending notes were found." == body["message"]

    body = _send(client, conversation_id, "Show my pending reminders")
    assert body["status"] == "success", body
    assert "No pending reminder were found." == body["message"]

    body = _send(client, conversation_id, "Mark the quiet hour task as done")
    assert body["status"] == "refused", body
    assert "no task" in body["message"].casefold()

    body = _send(client, conversation_id, "workspace list all")
    assert body["status"] == "success", body
    assert "Discharge summary [note, completed," in body["message"]


# ---------------------------------------------------------------------------
# Complete / reopen a task by exact title
# ---------------------------------------------------------------------------


def test_complete_task_by_title_requires_confirmation_then_executes(
    client: TestClient,
) -> None:
    task_id = str(_seed_item(kind="task", title="Ward revision"))
    _seed_item(kind="note", title="Ward revision", content="Same title, other kind")
    conversation_id = _new_conversation(client)
    key = uuid4()

    prepared = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
        key=key,
    )
    assert prepared["status"] == "confirmation-required", prepared
    assert "I found exactly one task titled 'Ward revision'" in prepared["message"]
    assert "has not run" in prepared["message"]
    assert prepared["challenge"]["summary"]
    # Nothing may change before the explicit confirmation decision.
    assert _item_by_id(client, "task", task_id)["completed"] is False
    assert _item_by_title(client, "note", "Ward revision") is not None

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    assert _item_by_id(client, "task", task_id)["completed"] is True
    assert _receipt(client, key)["status"] == "succeeded"

    replay = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
        key=key,
    )
    assert replay["status"] == "success", replay
    assert "No duplicate change was applied." in replay["message"]
    assert len(_items(client, "task")) == 1
    assert _item_by_title(client, "note", "Ward revision") is not None


def test_reopen_completed_task_by_title(client: TestClient) -> None:
    task_id = str(_seed_item(kind="task", title="Ward revision", completed=True))
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Reopen the Ward revision task",
    )
    assert prepared["status"] == "confirmation-required", prepared
    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    assert _item_by_id(client, "task", task_id)["completed"] is False


def test_unknown_title_refuses_without_receipt_or_challenge(
    client: TestClient,
) -> None:
    conversation_id = _new_conversation(client)
    key = uuid4()

    body = _send(
        client,
        conversation_id,
        "Mark the Missing report task as complete",
        key=key,
    )
    assert body["status"] == "refused", body
    assert "No task titled 'Missing report' was found" in body["message"]
    assert "challenge" not in body
    assert _receipt(client, key)["status"] == "not-found"


# ---------------------------------------------------------------------------
# Ambiguous titles are never silently chosen
# ---------------------------------------------------------------------------


def test_duplicate_titles_ask_for_item_id_and_only_one_changes(
    client: TestClient,
) -> None:
    first_id = str(_seed_item(kind="task", title="Ward revision"))
    second_id = str(_seed_item(kind="task", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Mark the Ward revision task as complete")
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert prompt["missing_fields"] == ["target"]
    assert first_id in prompt["question"]
    assert second_id in prompt["question"]
    assert "Reply with the item ID" in prompt["question"]
    assert _item_by_id(client, "task", first_id)["completed"] is False

    try_id = _send(
        client,
        conversation_id,
        "not-a-uuid",
        clarification_id=prompt["clarification_id"],
    )
    assert try_id["status"] == "clarification-required", try_id
    assert "Enter the item ID shown" in try_id["clarification_prompt"]["question"]

    renewed = try_id["clarification_prompt"]
    bound = _send(
        client,
        conversation_id,
        second_id,
        clarification_id=renewed["clarification_id"],
    )
    assert bound["status"] == "confirmation-required", bound
    assert bound["challenge"]["summary"]
    assert "has not run" in bound["message"]

    result = _confirm_and_execute(client, bound)
    assert result["status"] == "executed"
    assert _item_by_id(client, "task", second_id)["completed"] is True
    assert _item_by_id(client, "task", first_id)["completed"] is False


def test_disambiguation_answer_for_different_kind_is_refused(
    client: TestClient,
) -> None:
    _seed_item(kind="note", title="Ward revision")
    _seed_item(kind="note", title="Ward revision")
    task_id = str(_seed_item(kind="task", title="Unrelated report"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Delete my note titled Ward revision")
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]

    answered = _send(
        client,
        conversation_id,
        task_id,
        clarification_id=prompt["clarification_id"],
    )
    assert answered["status"] == "refused", answered
    assert "nothing was changed" in answered["message"].casefold()
    # Both notes survive; the refused task is untouched.
    assert len(_items(client, "note")) == 2
    assert _item_by_id(client, "task", task_id) is not None


def test_disambiguation_target_renamed_after_offer_is_refused(
    client: TestClient,
) -> None:
    first_id = _seed_item(kind="task", title="Ward revision")
    dragged_id = str(_seed_item(kind="task", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Complete the Ward revision task")
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]

    with database_module.SessionLocal() as session:
        from rop.models.assistant_item import AssistantItem

        item = session.get(AssistantItem, UUID(dragged_id))
        assert item is not None
        item.title = "Renamed while asking"
        session.commit()

    answered = _send(
        client,
        conversation_id,
        dragged_id,
        clarification_id=prompt["clarification_id"],
    )
    assert answered["status"] == "refused", answered
    assert "changed after it was offered" in answered["message"]
    for item in _items(client, "task"):
        assert item["completed"] is False
    assert _item_by_id(client, "task", str(first_id)) is not None


def test_expired_disambiguation_clarification_refuses(client: TestClient) -> None:
    _seed_item(kind="task", title="Ward revision")
    _seed_item(kind="task", title="Ward revision")
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Complete the Ward revision task")
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    _expire_clarification(prompt["clarification_id"])

    answered = _send(
        client,
        conversation_id,
        str(_items(client, "task")[0]["id"]),
        clarification_id=prompt["clarification_id"],
    )
    assert answered["status"] == "refused", answered
    assert "expired" in answered["message"].casefold()
    for item in _items(client, "task"):
        assert item["completed"] is False


def test_deleted_duplicate_after_offer_is_refused_without_mutation(
    client: TestClient,
) -> None:
    first_id = _seed_item(kind="task", title="Ward revision")
    gone_id = str(_seed_item(kind="task", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Complete the Ward revision task")
    prompt = prepared["clarification_prompt"]

    with database_module.SessionLocal() as session:
        from rop.models.assistant_item import AssistantItem

        item = session.get(AssistantItem, UUID(gone_id))
        assert item is not None
        session.delete(item)
        session.commit()

    answered = _send(
        client,
        conversation_id,
        gone_id,
        clarification_id=prompt["clarification_id"],
    )
    assert answered["status"] == "refused", answered
    assert "no longer exists" in answered["message"].casefold()
    assert _item_by_id(client, "task", str(first_id)) is not None


def test_disambiguated_delete_executes_for_the_chosen_note(
    client: TestClient,
) -> None:
    first_id = str(_seed_item(kind="note", title="Ward revision"))
    second_id = str(_seed_item(kind="note", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Delete my note titled Ward revision")
    prompt = prepared["clarification_prompt"]
    bound = _send(
        client,
        conversation_id,
        second_id,
        clarification_id=prompt["clarification_id"],
    )
    assert bound["status"] == "confirmation-required", bound
    result = _confirm_and_execute(client, bound)
    assert result["status"] == "executed"
    assert _item_by_id(client, "note", second_id) is None
    assert _item_by_id(client, "note", first_id) is not None


# ---------------------------------------------------------------------------
# Rename and content updates by exact title
# ---------------------------------------------------------------------------


def test_rename_note_by_title_flow(client: TestClient) -> None:
    note_id = str(_seed_item(kind="note", title="Ward revision", content="Keep me"))
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Rename my note titled Ward revision to Ward revision two",
    )
    assert prepared["status"] == "confirmation-required", prepared
    assert _item_by_id(client, "note", note_id)["title"] == "Ward revision"
    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    renamed = _item_by_id(client, "note", note_id)
    assert renamed["title"] == "Ward revision two"
    assert renamed["content"] == "Keep me"


def test_update_note_content_by_title_flow(client: TestClient) -> None:
    note_id = str(_seed_item(kind="note", title="Ward revision", content="Old body"))
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Update the content of the note titled Ward revision with New recovery notes",
    )
    assert prepared["status"] == "confirmation-required", prepared
    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "note", note_id)
    assert updated["content"] == "New recovery notes"
    assert updated["title"] == "Ward revision"


def test_bare_update_phrase_asks_for_exact_change(client: TestClient) -> None:
    _seed_item(kind="note", title="Ward revision", content="Old body")
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Update my note titled Ward revision")
    assert prepared["status"] == "unsupported-capability", prepared
    assert "'title: ...'" in prepared["message"]
    assert "'content: ...'" in prepared["message"]
    updated = _item_by_title(client, "note", "Ward revision")
    assert updated["content"] == "Old body"


def test_update_selector_without_field_clarifies_then_binds_content(
    client: TestClient,
) -> None:
    note_id = str(_seed_item(kind="note", title="Ward revision", content="Old body"))
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "workspace update note titled: Ward revision",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert set(prompt["missing_fields"]) == {"title", "content"}
    assert "title: New title" in prompt["question"]
    assert "content: New content" in prompt["question"]

    continued = _send(
        client,
        conversation_id,
        "content: Updated plan",
        clarification_id=prompt["clarification_id"],
    )
    assert continued["status"] == "confirmation-required", continued
    result = _confirm_and_execute(client, continued)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "note", note_id)
    assert updated["content"] == "Updated plan"
    # The update keeps the existing title when only content was supplied.
    assert updated["title"] == "Ward revision"


# ---------------------------------------------------------------------------
# Staleness: fail closed when the target changed or disappeared
# ---------------------------------------------------------------------------


def test_changed_target_is_rejected_at_execution_and_retry_succeeds(
    client: TestClient,
) -> None:
    task_id = str(_seed_item(kind="task", title="Ward revision"))
    conversation_id = _new_conversation(client)
    key = uuid4()

    prepared = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
        key=key,
    )
    assert prepared["status"] == "confirmation-required", prepared

    with database_module.SessionLocal() as session:
        from rop.models.assistant_item import AssistantItem

        item = session.get(AssistantItem, UUID(task_id))
        assert item is not None
        item.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        session.commit()

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "failed", result
    assert _item_by_id(client, "task", task_id)["completed"] is False
    assert _receipt(client, key)["status"] == "unknown"

    retry = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
    )
    assert retry["status"] == "confirmation-required", retry
    retry_result = _confirm_and_execute(client, retry)
    assert retry_result["status"] == "executed"
    assert _item_by_id(client, "task", task_id)["completed"] is True


def test_deleted_target_is_rejected_at_execution(client: TestClient) -> None:
    note_id = str(_seed_item(kind="note", title="Ward revision", content="Keep me"))
    conversation_id = _new_conversation(client)
    key = uuid4()

    prepared = _send(
        client,
        conversation_id,
        "Delete my note titled Ward revision",
        key=key,
    )
    assert prepared["status"] == "confirmation-required", prepared

    with database_module.SessionLocal() as session:
        from rop.models.assistant_item import AssistantItem

        item = session.get(AssistantItem, UUID(note_id))
        assert item is not None
        session.delete(item)
        session.commit()

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "failed", result
    assert _receipt(client, key)["status"] == "unknown"
    assert _item_by_id(client, "note", note_id) is None


# ---------------------------------------------------------------------------
# Confirmation contract on selector-driven challenges
# ---------------------------------------------------------------------------


def test_wrong_display_code_refuses_then_correct_code_executes(
    client: TestClient,
) -> None:
    task_id = str(_seed_item(kind="task", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
    )
    assert prepared["status"] == "confirmation-required", prepared
    refused = _decide(
        client,
        prepared["challenge"],
        decision="confirm",
        display_code="WRONG-CODE",
    )
    assert refused.status_code == 200, refused.text
    assert refused.json()["status"] == "refused", refused.json()
    assert _item_by_id(client, "task", task_id)["completed"] is False

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    assert _item_by_id(client, "task", task_id)["completed"] is True


def test_cancelled_selector_command_does_not_mutate(client: TestClient) -> None:
    note_id = str(_seed_item(kind="note", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Delete my note titled Ward revision")
    assert prepared["status"] == "confirmation-required", prepared
    cancelled = _decide(client, prepared["challenge"], decision="cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert _item_by_id(client, "note", note_id) is not None


def test_expired_confirmation_challenge_refuses(client: TestClient) -> None:
    note_id = str(_seed_item(kind="note", title="Ward revision"))
    conversation_id = _new_conversation(client)

    prepared = _send(client, conversation_id, "Delete my note titled Ward revision")
    assert prepared["status"] == "confirmation-required", prepared
    _expire_confirmation(prepared["challenge"])

    decided = _decide(
        client,
        prepared["challenge"],
        decision="confirm",
        display_code=prepared["challenge"]["display_code"],
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "refused"
    assert _item_by_id(client, "note", note_id) is not None


def test_conflicting_idempotency_key_refuses_new_material(client: TestClient) -> None:
    _seed_item(kind="task", title="Ward revision")
    _seed_item(kind="task", title="Different report")
    conversation_id = _new_conversation(client)
    key = uuid4()

    prepared = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
        key=key,
    )
    assert prepared["status"] == "confirmation-required", prepared

    conflict = _send(
        client,
        conversation_id,
        "Mark the Different report task as complete",
        key=key,
    )
    assert conflict["status"] == "refused", conflict
    assert "already bound to a different change" in conflict["message"]

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    assert _item_by_title(client, "task", "Ward revision")["completed"] is True
    assert _item_by_title(client, "task", "Different report")["completed"] is False
    assert _receipt(client, key)["status"] == "succeeded"


def test_uncertain_commit_reports_unknown_then_receipt_recovers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = str(_seed_item(kind="task", title="Ward revision"))
    conversation_id = _new_conversation(client)
    key = uuid4()

    prepared = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
        key=key,
    )
    assert prepared["status"] == "confirmation-required", prepared

    real_factory, real_recovery = _install_uncertain_commit(monkeypatch)
    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "unknown", result
    assert _item_by_id(client, "task", task_id)["completed"] is True
    assert _receipt(client, key)["status"] == "succeeded"
    # Restore the executor's real session factory and receipt recovery.
    monkeypatch.setattr(workspace_executor, "SessionLocal", real_factory)
    monkeypatch.setattr(workspace_executor, "_recover_receipt", real_recovery)

    replay = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
        key=key,
    )
    assert replay["status"] in {"success", "confirmation-required"}, replay
    replayed = _confirm_and_execute(client, replay) if "challenge" in replay else replay
    assert replayed["status"] == "success", replayed
    assert len(_items(client, "task")) == 1
    assert _item_by_id(client, "task", task_id)["completed"] is True
    assert _receipt(client, key)["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Reminder rescheduling by exact title
# ---------------------------------------------------------------------------


def _seed_reminder(title: str) -> str:
    return str(
        _seed_item(
            kind="reminder",
            title=title,
            due_at=PAST_DUE,
            timezone="Europe/Amsterdam",
        )
    )


def test_reschedule_by_title_with_explicit_time_and_zone(
    client: TestClient,
) -> None:
    reminder_id = _seed_reminder("Check mail")
    task_id = str(_seed_item(kind="task", title="Check mail"))
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to "
        "2026-11-12T14:00 in Europe/Amsterdam",
    )
    assert prepared["status"] == "confirmation-required", prepared
    assert "I found exactly one reminder titled 'Check mail'" in prepared["message"]
    assert _item_by_id(client, "reminder", reminder_id)["due_at"].startswith(
        "2026-09-01"
    )

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    assert updated["due_at"].startswith("2026-11-12T13:00:00")  # CET = UTC+1
    assert updated["timezone"] == "Europe/Amsterdam"
    assert updated["title"] == "Check mail"
    # Kind scoping: the identically titled task is untouched.
    assert _item_by_id(client, "task", task_id) is not None
    assert _item_by_id(client, "task", task_id)["title"] == "Check mail"


def test_reschedule_by_title_missing_timezone_asks_then_executes(
    client: TestClient,
) -> None:
    reminder_id = _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to 2026-11-12T14:00",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert prompt["missing_fields"] == ["timezone"]

    continued = _send(
        client,
        conversation_id,
        "Europe/Amsterdam",
        clarification_id=prompt["clarification_id"],
    )
    assert continued["status"] == "confirmation-required", continued
    result = _confirm_and_execute(client, continued)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    assert updated["due_at"].startswith("2026-11-12T13:00:00")
    assert updated["timezone"] == "Europe/Amsterdam"


def test_reschedule_by_title_invalid_timezone_repeats_the_question(
    client: TestClient,
) -> None:
    _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "workspace update reminder titled: Check mail | "
        "due: 2026-11-12T14:00 | tz: Mars/Colony",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert prompt["missing_fields"] == ["timezone"]
    assert "IANA" in prompt["question"] or "time zone" in prompt["question"].casefold()
    assert _receipt(client, uuid4())["status"] == "not-found"


def test_relative_reschedule_with_clock_needs_timezone(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.capabilities import workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    reminder_id = _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to tomorrow at 09:00",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert set(prompt["missing_fields"]) == {"due_at", "timezone"}

    continued = _send(
        client,
        conversation_id,
        "09:00 | Europe/Amsterdam",
        clarification_id=prompt["clarification_id"],
    )
    assert continued["status"] == "confirmation-required", continued
    result = _confirm_and_execute(client, continued)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    # 09:00 Amsterdam (CET, UTC+1 after the DST change) = 08:00 UTC.
    assert updated["due_at"].startswith("2026-10-30T08:00:00")
    assert updated["timezone"] == "Europe/Amsterdam"


def test_relative_reschedule_without_clock_asks_both_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.capabilities import workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    reminder_id = _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to tomorrow",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert set(prompt["missing_fields"]) == {"due_at", "timezone"}

    continued = _send(
        client,
        conversation_id,
        "09:00 | Europe/Amsterdam",
        clarification_id=prompt["clarification_id"],
    )
    assert continued["status"] == "confirmation-required", continued
    result = _confirm_and_execute(client, continued)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    assert updated["due_at"].startswith("2026-10-30T08:00:00")


def test_relative_reschedule_anchor_survives_midnight(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.capabilities import workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    reminder_id = _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to tomorrow",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]

    # The user answers after local midnight; the anchored "tomorrow" must
    # still mean 2026-10-30, not the shifted original date's tomorrow.
    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 23, 30, tzinfo=UTC),
    )
    continued = _send(
        client,
        conversation_id,
        "09:00 | Europe/Amsterdam",
        clarification_id=prompt["clarification_id"],
    )
    assert continued["status"] == "confirmation-required", continued
    result = _confirm_and_execute(client, continued)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    assert updated["due_at"].startswith("2026-10-30T08:00:00")


def test_dst_nonexistent_local_time_fails_closed(client: TestClient) -> None:
    _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "workspace update reminder titled: Check mail | "
        "due: 2026-03-08T02:30 | tz: America/New_York",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert "does not exist" in prompt["question"].casefold()
    assert prompt["missing_fields"] == ["due_at"]
    assert _receipt(client, uuid4())["status"] == "not-found"


def test_dst_ambiguous_local_time_asks_offset_then_executes(
    client: TestClient,
) -> None:
    reminder_id = _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)

    prepared = _send(
        client,
        conversation_id,
        "workspace update reminder titled: Check mail | "
        "due: 2026-10-25T03:30 | tz: Europe/Bucharest",
    )
    assert prepared["status"] == "clarification-required", prepared
    prompt = prepared["clarification_prompt"]
    assert "occurs twice" in prompt["question"].casefold()
    assert "+03:00" in prompt["question"]

    continued = _send(
        client,
        conversation_id,
        "2026-10-25T03:30+03:00",
        clarification_id=prompt["clarification_id"],
    )
    assert continued["status"] == "confirmation-required", continued
    result = _confirm_and_execute(client, continued)
    assert result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    assert updated["due_at"].startswith("2026-10-25T00:30:00")  # 03:30+03:00
    assert updated["timezone"] == "Europe/Bucharest"


def test_failed_reschedule_then_new_request_recovers(client: TestClient) -> None:
    reminder_id = _seed_reminder("Check mail")
    conversation_id = _new_conversation(client)
    key = uuid4()

    prepared = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to "
        "2026-11-12T14:00 in Europe/Amsterdam",
        key=key,
    )
    assert prepared["status"] == "confirmation-required", prepared

    with database_module.SessionLocal() as session:
        from rop.models.assistant_item import AssistantItem

        item = session.get(AssistantItem, UUID(reminder_id))
        assert item is not None
        item.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        session.commit()

    result = _confirm_and_execute(client, prepared)
    assert result["status"] == "failed", result
    assert _item_by_id(client, "reminder", reminder_id)["due_at"].startswith(
        "2026-09-01"
    )

    retry = _send(
        client,
        conversation_id,
        "Reschedule my reminder titled Check mail to "
        "2026-11-12T14:00 in Europe/Amsterdam",
    )
    assert retry["status"] == "confirmation-required", retry
    retry_result = _confirm_and_execute(client, retry)
    assert retry_result["status"] == "executed"
    updated = _item_by_id(client, "reminder", reminder_id)
    assert updated["due_at"].startswith("2026-11-12T13:00:00")


# ---------------------------------------------------------------------------
# Unit tests for the read-only selector resolution boundary
# ---------------------------------------------------------------------------


@pytest.fixture
def selector_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make(session: Session, kind: str, title: str):
    from rop.models.assistant_item import AssistantItem

    item = AssistantItem(kind=kind, title=title, content="")
    if kind == "reminder":
        item.due_at = PAST_DUE
        item.timezone = "UTC"
    session.add(item)
    session.commit()
    return item


def test_normalize_selector_title_is_whitespace_and_case_stable() -> None:
    assert normalize_selector_title("  Ward  \t revision ") == "ward revision"
    assert normalize_selector_title("ward REVISION") == "ward revision"
    assert normalize_selector_title(None) == ""
    assert normalize_selector_title(123) == ""


def test_resolve_selector_title_outcomes(selector_session: Session) -> None:
    _make(selector_session, "task", "Ward revision")
    match = _make(selector_session, "note", "  WARD revision  ")
    match.updated_at = datetime(2030, 1, 1, tzinfo=UTC)  # deterministic newest
    selector_session.commit()

    resolution = resolve_selector_title(
        selector_session, kind="note", title="ward revision"
    )
    assert resolution.status == "unique"
    assert [str(item.id) for item in resolution.matches] == [str(match.id)]

    missing = resolve_selector_title(
        selector_session, kind="reminder", title="Ward revision"
    )
    assert missing.status == "not_found"
    assert missing.matches == ()

    _make(selector_session, "task", "Ward revision")
    ambiguous = resolve_selector_title(
        selector_session, kind="task", title="Ward revision"
    )
    assert ambiguous.status == "ambiguous"
    assert len(ambiguous.matches) == 2


def test_resolve_selector_title_rejects_partial_and_similar_matches(
    selector_session: Session,
) -> None:
    _make(selector_session, "task", "Ward revision plan")

    partial = resolve_selector_title(
        selector_session, kind="task", title="Ward revision"
    )
    assert partial.status == "not_found"

    superset = resolve_selector_title(
        selector_session, kind="task", title="Ward revision plan extended"
    )
    assert superset.status == "not_found"


def test_resolve_selector_title_rejects_invalid_input(
    selector_session: Session,
) -> None:
    with pytest.raises(ValueError):
        resolve_selector_title(selector_session, kind="journal", title="Ward")
    with pytest.raises(ValueError):
        resolve_selector_title(selector_session, kind="note", title="   ")
    with pytest.raises(ValueError):
        resolve_selector_title(selector_session, kind="note", title=123)


def test_bind_resolved_target_drops_selector_and_versions_the_row(
    selector_session: Session,
) -> None:
    from rop.schemas.authorization import ProposedOperation

    item = _make(selector_session, "task", "Ward revision")
    operation = ProposedOperation(
        operation_id="workspace_task_complete",
        parameters={"idempotency_key": "k", "selector_title": "Ward revision"},
    )
    bound = bind_resolved_target(operation, item)
    assert bound.target == str(item.id)
    assert "selector_title" not in bound.parameters
    assert bound.parameters["target_updated_at"] == item_version_token(item)


def test_verify_disambiguated_target_validates_kind() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        from rop.schemas.authorization import ProposedOperation

        note = _make(session, "note", "Ward revision")
        other = _make(session, "note", "Ward revision")
        operation = ProposedOperation(
            operation_id="workspace_note_delete",
            target=str(other.id),
            parameters={
                "idempotency_key": "k",
                "selector_title": "Ward revision",
            },
        )
        verified = verify_disambiguated_target(session, operation, kind="note")
        assert verified is not None and verified.id == other.id

        # Wrong kind is refused even when the title matches.
        wrong_kind = verify_disambiguated_target(session, operation, kind="task")
        assert wrong_kind is None

        # A renamed record no longer matches the offered title.
        renamed = _make(session, "note", "Other title")
        renamed_operation = ProposedOperation(
            operation_id="workspace_note_delete",
            target=str(renamed.id),
            parameters={"idempotency_key": "k", "selector_title": "Ward revision"},
        )
        assert (
            verify_disambiguated_target(session, renamed_operation, kind="note") is None
        )

        # A missing or invalid target always fails closed.
        no_target = ProposedOperation(
            operation_id="workspace_note_delete",
            parameters={"idempotency_key": "k", "selector_title": "Ward revision"},
        )
        assert verify_disambiguated_target(session, no_target, kind="note") is None
        invalid_target = ProposedOperation(
            operation_id="workspace_note_delete",
            target="not-a-uuid",
            parameters={"idempotency_key": "k", "selector_title": "Ward revision"},
        )
        assert verify_disambiguated_target(session, invalid_target, kind="note") is None
        assert session.get(type(note), note.id) is not None
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# UI contract: the served conversations UI must accept Task 249 responses
# ---------------------------------------------------------------------------

# Field names this feature introduces; the served app.js must not hard-code
# or whitelist them anywhere (its validators are generic by design).
_TASK249_UI_FIELD_NAMES = (
    "selector_title",
    "relative_date_hint",
    "relative_clock_time",
    "relative_anchor_utc",
)


def test_served_chat_ui_renders_task249_statuses_and_generic_fields(
    client: TestClient,
) -> None:
    page = client.get("/")
    assert page.status_code == 200
    script = client.get("/static/app.js")
    assert script.status_code == 200
    js = script.text

    # Every Task 249 response status is handled by the existing dispatcher.
    for status in (
        "success",
        "unsupported-capability",
        "clarification-required",
        "confirmation-required",
        "refused",
    ):
        assert f'"{status}"' in js, status

    # The clarification validator accepts any string-array missing_fields, so
    # Task 249 prompts (missing_fields such as ["target"]) render without UI
    # changes and without a loophole for unvalidated field names.
    assert "Array.isArray(value.missing_fields)" in js
    assert 'value.missing_fields.every((item) => typeof item === "string")' in js
    for name in _TASK249_UI_FIELD_NAMES:
        assert name not in js, f"{name} must not be special-cased in the UI"

    # Clarification prompts and confirmation challenges stay on the served
    # surfaces the chat UI already binds to.
    assert 'getElementById("clarification-panel")' in js
    assert 'getElementById("clarification-question")' in js


def test_task249_live_payloads_satisfy_served_ui_envelope(client: TestClient) -> None:
    conversation_id = _new_conversation(client)

    # Read-only success listing: exactly the fields the chat UI allow-lists.
    listing = _send(client, conversation_id, "Show my pending tasks.")
    assert listing["status"] == "success"
    assert set(listing) == {"status", "message"}
    assert isinstance(listing["message"], str)

    # Unsupported capability: same envelope, no invented fields.
    unsupported = _send(
        client,
        conversation_id,
        "Show my pending items",
    )
    assert unsupported["status"] == "unsupported-capability"
    assert set(unsupported) == {"status", "message"}

    # Disambiguation clarification: the exact shape served app.js validates.
    _seed_item(kind="task", title="Ward revision")
    _seed_item(kind="task", title="Ward revision")
    prepared = _send(
        client,
        conversation_id,
        "Mark the Ward revision task as complete",
    )
    assert prepared["status"] == "clarification-required", prepared
    assert set(prepared) <= {"status", "message", "clarification_prompt"}
    prompt = prepared["clarification_prompt"]
    assert set(prompt) == {
        "clarification_id",
        "capability_identifier",
        "question",
        "missing_fields",
    }
    assert isinstance(prompt["clarification_id"], str) and prompt["clarification_id"]
    assert prompt["capability_identifier"]
    assert prompt["question"]
    assert prompt["missing_fields"] == ["target"]
    assert all(isinstance(field, str) and field for field in prompt["missing_fields"])

    # Confirmation challenge: the same challenge shape the UI already renders.
    other_id = str(_seed_item(kind="note", title="Legacy note"))
    prepared_delete = _send(
        client,
        conversation_id,
        "Delete my note titled Legacy note",
    )
    assert prepared_delete["status"] == "confirmation-required", prepared_delete
    challenge = prepared_delete["challenge"]
    for field in ("challenge_id", "summary", "display_code", "expires_at"):
        assert field in challenge, field

    # Cancellation keeps the envelope: nothing mutates and nothing new appears.
    _decide(client, challenge, decision="cancel")
    assert _item_by_id(client, "note", other_id) is not None

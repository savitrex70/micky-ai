"""End-to-end lifecycle matrix for notes, tasks, and reminders."""

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import rop.models  # noqa: F401
from rop import database as database_module
from rop.api import workspace as workspace_api
from rop.authorization.executors import ExecutorError, ExecutorInterrupted
from rop.database import Base, get_db
from rop.main import app, settings
from rop.models.assistant_confirmation import AssistantConfirmation
from rop.schemas.authorization import AuthorizationPolicy
from rop.services import workspace_executor

ORIGIN = "http://127.0.0.1:8000"
ORIGIN_HEADERS = {"origin": ORIGIN, "content-type": "application/json"}
WORKSPACE = "/api/assistant/workspace"
FIXED_NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
FUTURE_DUE = "2026-10-25T16:00"
OVERDUE_DUE = "2026-10-23T11:00"
UPDATED_FUTURE_DUE = "2026-10-26T11:00"


@pytest.fixture
def workspace_test_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[Callable[[], TestClient], sessionmaker[Session]], None, None]:
    """Use a file-backed SQLite DB so separate TestClient lifespans share data."""
    database_path = tmp_path / "workspace-lifecycle.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database_module, "SessionLocal", sessions)
    monkeypatch.setattr(workspace_executor, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "startup_recovery_enabled", False)

    previous_override = app.dependency_overrides.get(get_db)

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    def make_client() -> TestClient:
        return TestClient(app, base_url=ORIGIN)

    try:
        yield make_client, sessions
    finally:
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _items(
    client: TestClient,
    kind: str | None = None,
    *,
    include_completed: bool = True,
) -> list[dict[str, Any]]:
    params: dict[str, str | bool] = {"include_completed": include_completed}
    if kind is not None:
        params["kind"] = kind
    response = client.get(f"{WORKSPACE}/items", params=params, headers=ORIGIN_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _body(
    kind: str,
    action: str,
    key: UUID,
    *,
    item_id: str | None = None,
    title: str | None = None,
    content: str | None = None,
    clear_content: bool = False,
    completed: bool | None = None,
    due_local: str = FUTURE_DUE,
    timezone: str = "Europe/Bucharest",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "action": action,
        "idempotency_key": str(key),
    }
    if item_id is not None:
        payload["item_id"] = item_id
    if action in {"create", "update"}:
        payload["title"] = title or (
            "Updated item" if action == "update" else "Initial item"
        )
        if content is not None:
            payload["content"] = content
        if clear_content:
            payload["clear_content"] = True
        if kind == "reminder":
            payload["due_local"] = due_local
            payload["timezone"] = timezone
    if action == "complete":
        payload["completed"] = completed
    return payload


def _prepare(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"{WORKSPACE}/changes", headers=ORIGIN_HEADERS, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _decide(
    client: TestClient,
    challenge: dict[str, Any],
    *,
    decision: str = "confirm",
    display_code: str | None = None,
):
    payload: dict[str, str] = {"decision": decision}
    if display_code is not None:
        payload["display_code"] = display_code
    return client.post(
        f"/api/assistant/confirmations/{challenge['challenge_id']}/decision",
        headers=ORIGIN_HEADERS,
        json=payload,
    )


def _confirm(client: TestClient, prepared: dict[str, Any]) -> dict[str, Any]:
    assert prepared["status"] == "confirmation-required", prepared
    challenge = prepared["challenge"]
    response = _decide(
        client, challenge, display_code=challenge["display_code"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_item(
    client: TestClient,
    kind: str,
    *,
    title: str = "Initial item",
    content: str = "Initial content",
    due_local: str = FUTURE_DUE,
) -> dict[str, Any]:
    body = _body(
        kind,
        "create",
        uuid4(),
        title=title,
        content=content,
        due_local=due_local,
    )
    result = _confirm(client, _prepare(client, body))
    assert result["status"] == "executed", result
    matching = [item for item in _items(client, kind) if item["title"] == title]
    assert len(matching) == 1
    return matching[0]


def _receipt(client: TestClient, key: UUID) -> dict[str, Any]:
    response = client.get(f"{WORKSPACE}/receipts/{key}")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("kind", "action", "completed"),
    [
        ("note", "create", None),
        ("note", "update", None),
        ("note", "delete", None),
        ("task", "create", None),
        ("task", "update", None),
        ("task", "delete", None),
        ("task", "complete", True),
        ("task", "complete", False),
        ("reminder", "create", None),
        ("reminder", "update", None),
        ("reminder", "delete", None),
    ],
    ids=[
        "note-create",
        "note-update",
        "note-delete",
        "task-create",
        "task-update",
        "task-delete",
        "task-complete",
        "task-reopen",
        "reminder-create",
        "reminder-update",
        "reminder-delete",
    ],
)
def test_supported_workspace_operation_lifecycle_matrix(
    workspace_test_env, kind: str, action: str, completed: bool | None
) -> None:
    """Every registered item mutation requires confirmation and persists once."""
    make_client, _ = workspace_test_env
    with make_client() as client:
        target_id: str | None = None
        if action != "create":
            initial = _create_item(client, kind)
            target_id = initial["id"]
            if action == "complete" and completed is False:
                marked = _confirm(
                    client,
                    _prepare(
                        client,
                        _body(
                            "task",
                            "complete",
                            uuid4(),
                            item_id=target_id,
                            completed=True,
                        ),
                    ),
                )
                assert marked["status"] == "executed", marked

        before = _items(client, kind)
        key = uuid4()
        body = _body(
            kind,
            action,
            key,
            item_id=target_id,
            title="Updated item" if action == "update" else None,
            content="Updated content" if action == "update" else (
                "Initial content" if action == "create" else None
            ),
            completed=completed,
            due_local=UPDATED_FUTURE_DUE if action == "update" else FUTURE_DUE,
        )
        prepared = _prepare(client, body)
        assert prepared["status"] == "confirmation-required", prepared
        assert _items(client, kind) == before, (
            f"{kind}/{action} mutated workspace data before confirmation"
        )

        outcome = _confirm(client, prepared)
        assert outcome["status"] == "executed", outcome
        assert outcome["executed"] is True
        after = _items(client, kind)
        assert _receipt(client, key)["status"] == "succeeded"

        if action == "create":
            assert len(after) == len(before) + 1
            before_ids = {item["id"] for item in before}
            created = next(item for item in after if item["id"] not in before_ids)
            assert created["title"] == "Initial item"
            if kind == "reminder":
                assert created["timezone"] == "Europe/Bucharest"
                assert created["due_at"] is not None
        elif action == "update":
            updated = next(item for item in after if item["id"] == target_id)
            assert updated["title"] == "Updated item"
            assert updated["content"] == "Updated content"
            if kind == "reminder":
                assert updated["timezone"] == "Europe/Bucharest"
        elif action == "delete":
            assert all(item["id"] != target_id for item in after)
            assert len(after) == len(before) - 1
        else:
            changed = next(item for item in after if item["id"] == target_id)
            assert changed["completed"] is completed
            open_items = _items(client, "task", include_completed=False)
            open_ids = {item["id"] for item in open_items}
            assert (target_id in open_ids) is (not completed)


@pytest.mark.parametrize("kind", ["note", "task", "reminder"])
def test_same_key_replay_and_conflicting_material_are_safe(
    workspace_test_env, kind: str
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        key = uuid4()
        body = _body(kind, "create", key, title=f"{kind} original")
        prepared = _prepare(client, body)
        assert prepared["status"] == "confirmation-required"

        identical_while_pending = _prepare(client, body)
        assert identical_while_pending["status"] == "unknown"
        assert "challenge" not in identical_while_pending

        conflict = _body(kind, "create", key, title=f"{kind} conflict")
        conflict_response = client.post(
            f"{WORKSPACE}/changes", headers=ORIGIN_HEADERS, json=conflict
        )
        assert conflict_response.status_code == 409
        assert _items(client, kind) == []

        outcome = _confirm(client, prepared)
        assert outcome["status"] == "executed"
        replay = _prepare(client, body)
        assert replay["status"] == "success"
        assert "challenge" not in replay
        assert len(_items(client, kind)) == 1
        assert _items(client, kind)[0]["title"] == f"{kind} original"


@pytest.mark.parametrize("kind", ["note", "task", "reminder"])
def test_wrong_code_cancel_and_replay_do_not_mutate(
    workspace_test_env, kind: str
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        key = uuid4()
        prepared = _prepare(client, _body(kind, "create", key))
        challenge = prepared["challenge"]

        wrong = _decide(
            client, challenge, display_code="WRONG-CODE", decision="confirm"
        )
        assert wrong.status_code == 200
        assert wrong.json()["status"] == "refused"
        assert wrong.json()["executed"] is False
        assert _items(client, kind) == []

        cancelled = _decide(client, challenge, decision="cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["executed"] is False
        replay = _decide(
            client, challenge, display_code=challenge["display_code"]
        )
        assert replay.json()["status"] == "refused"
        assert replay.json()["executed"] is False
        assert _items(client, kind) == []
        assert _receipt(client, key)["status"] == "unknown"


@pytest.mark.parametrize("kind", ["note", "task", "reminder"])
def test_expired_challenge_is_refused_and_cannot_be_replayed(
    workspace_test_env, kind: str
) -> None:
    make_client, sessions = workspace_test_env
    with make_client() as client:
        key = uuid4()
        prepared = _prepare(client, _body(kind, "create", key))
        challenge = prepared["challenge"]
        with sessions() as session:
            record = session.scalar(
                select(AssistantConfirmation).where(
                    AssistantConfirmation.challenge_id == challenge["challenge_id"]
                )
            )
            assert record is not None
            record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            session.commit()

        first = _decide(
            client, challenge, display_code=challenge["display_code"]
        )
        assert first.status_code == 200
        assert first.json()["status"] == "refused"
        assert first.json()["executed"] is False
        second = _decide(
            client, challenge, display_code=challenge["display_code"]
        )
        assert second.json()["status"] == "refused"
        assert _items(client, kind) == []
        assert _receipt(client, key)["status"] == "unknown"


@pytest.mark.parametrize(
    "kind,action",
    [
        ("note", "update"),
        ("task", "complete"),
        ("reminder", "delete"),
    ],
    ids=[
        "missing-note-update-target",
        "missing-task-completion-target",
        "deleted-reminder-target",
    ],
)
def test_nonexistent_targets_fail_without_creating_items(
    workspace_test_env, kind: str, action: str
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        target_id = str(uuid4())
        body = _body(
            kind,
            action,
            uuid4(),
            item_id=target_id,
            title="Must not appear" if action == "update" else None,
            completed=True if action == "complete" else None,
        )
        prepared = _prepare(client, body)
        assert prepared["status"] == "confirmation-required"
        assert _items(client, kind) == []

        failed = _confirm(client, prepared)
        assert failed["status"] == "failed"
        assert failed["executed"] is True
        assert _items(client, kind) == []




@pytest.mark.parametrize(
    ("kind", "action"),
    [
        ("note", "update"),
        ("task", "complete"),
        ("reminder", "delete"),
    ],
    ids=["deleted-note-update", "deleted-task-complete", "deleted-reminder-delete"],
)
def test_already_deleted_targets_cannot_be_mutated_again(
    workspace_test_env, kind: str, action: str
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        item = _create_item(client, kind)
        item_id = item["id"]
        deleted = _confirm(
            client, _prepare(client, _body(kind, "delete", uuid4(), item_id=item_id))
        )
        assert deleted["status"] == "executed"
        assert _items(client, kind) == []

        body = _body(
            kind,
            action,
            uuid4(),
            item_id=item_id,
            title="Must not resurrect" if action == "update" else None,
            completed=True if action == "complete" else None,
        )
        failed = _confirm(client, _prepare(client, body))
        assert failed["status"] == "failed"
        assert _items(client, kind) == []


def test_list_filters_item_kind_and_completed_tasks_without_item_detail_route(
    workspace_test_env,
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        note = _create_item(client, "note")
        task = _create_item(client, "task")
        reminder = _create_item(client, "reminder")
        completed = _confirm(
            client,
            _prepare(
                client,
                _body("task", "complete", uuid4(), item_id=task["id"], completed=True),
            ),
        )
        assert completed["status"] == "executed"

        all_items = _items(client)
        assert {item["id"] for item in all_items} == {
            note["id"], task["id"], reminder["id"]
        }
        assert {item["kind"] for item in all_items} == {"note", "task", "reminder"}
        for kind in ("note", "task", "reminder"):
            assert all(item["kind"] == kind for item in _items(client, kind))

        open_items = _items(client, include_completed=False)
        assert task["id"] not in {item["id"] for item in open_items}
        assert note["id"] in {item["id"] for item in open_items}
        assert reminder["id"] in {item["id"] for item in open_items}

        missing_detail = client.get(f"{WORKSPACE}/items/{note['id']}")
        assert missing_detail.status_code == 404

def test_clear_content_update_is_bound_and_only_applied_after_confirmation(
    workspace_test_env,
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        original = _create_item(client, "note", content="Sensitive note body")
        key = uuid4()
        body = _body(
            "note",
            "update",
            key,
            item_id=original["id"],
            title="Initial item",
            clear_content=True,
        )
        prepared = _prepare(client, body)
        assert prepared["status"] == "confirmation-required"
        before = next(
            item for item in _items(client, "note") if item["id"] == original["id"]
        )
        assert before["content"] == "Sensitive note body"

        result = _confirm(client, prepared)
        assert result["status"] == "executed"
        after = next(
            item for item in _items(client, "note") if item["id"] == original["id"]
        )
        assert after["content"] == ""


def test_workspace_validation_origin_and_policy_refusals_are_non_mutating(
    workspace_test_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        key = uuid4()
        body = _body("note", "create", key)
        no_origin = client.post(f"{WORKSPACE}/changes", json=body)
        assert no_origin.status_code == 403
        assert _receipt(client, key)["status"] == "not-found"
        assert _items(client, "note") == []

        original_policy = workspace_api._POLICY
        denied_rules = tuple(
            rule.model_copy(update={"prohibited": True})
            if rule.operation_id == "workspace_note_create"
            else rule
            for rule in original_policy.rules
        )
        monkeypatch.setattr(
            workspace_api, "_POLICY", AuthorizationPolicy(rules=denied_rules)
        )
        denied_key = uuid4()
        denied = client.post(
            f"{WORKSPACE}/changes",
            headers=ORIGIN_HEADERS,
            json=_body("note", "create", denied_key),
        )
        assert denied.status_code == 200
        assert denied.json()["status"] == "refused"
        assert "challenge" not in denied.json()
        assert _receipt(client, denied_key)["status"] == "not-found"
        assert _items(client, "note") == []


def test_invalid_fields_malformed_ids_and_unsupported_actions_are_rejected(
    workspace_test_env,
) -> None:
    make_client, _ = workspace_test_env
    malformed = [
        {
            "kind": "note",
            "action": "create",
            "idempotency_key": str(uuid4()),
        },
        _body(
            "note", "update", uuid4(), item_id="not-a-uuid", title="Invalid target"
        ),
        {
            "kind": "note",
            "action": "update",
            "idempotency_key": str(uuid4()),
            "title": "Missing target",
        },
        {
            "kind": "reminder",
            "action": "complete",
            "idempotency_key": str(uuid4()),
            "item_id": str(uuid4()),
            "completed": True,
        },
        {
            "kind": "reminder",
            "action": "create",
            "idempotency_key": str(uuid4()),
            "title": "Missing due time",
        },
    ]
    with make_client() as client:
        for body in malformed:
            response = client.post(
                f"{WORKSPACE}/changes", headers=ORIGIN_HEADERS, json=body
            )
            assert response.status_code == 422, (body, response.text)
        assert _items(client) == []


def test_completed_task_can_be_recompleted_updated_and_deleted(
    workspace_test_env,
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        task = _create_item(client, "task")
        target = task["id"]
        completed = _confirm(
            client,
            _prepare(
                client,
                _body("task", "complete", uuid4(), item_id=target, completed=True),
            ),
        )
        assert completed["status"] == "executed"

        repeated = _confirm(
            client,
            _prepare(
                client,
                _body("task", "complete", uuid4(), item_id=target, completed=True),
            ),
        )
        assert repeated["status"] == "executed"
        rows = _items(client, "task")
        assert len(rows) == 1
        assert rows[0]["completed"] is True

        updated = _confirm(
            client,
            _prepare(
                client,
                _body(
                    "task", "update", uuid4(), item_id=target, title="Completed task"
                ),
            ),
        )
        assert updated["status"] == "executed"
        rows = _items(client, "task")
        assert rows[0]["title"] == "Completed task"
        assert rows[0]["completed"] is True

        deleted = _confirm(
            client,
            _prepare(client, _body("task", "delete", uuid4(), item_id=target)),
        )
        assert deleted["status"] == "executed"
        assert _items(client, "task") == []


@pytest.mark.parametrize(
    "due_local,timezone",
    [
        ("2024-03-10T02:30", "America/Toronto"),
        ("2024-11-03T01:30", "America/Toronto"),
        ("2026-10-25T03:30", "Europe/Bucharest"),
    ],
    ids=["nonexistent-dst-time", "ambiguous-dst-time", "ambiguous-bucharest-time"],
)
def test_reminder_dst_values_are_rejected_at_the_api(
    workspace_test_env, due_local: str, timezone: str
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        body = _body(
            "reminder",
            "create",
            uuid4(),
            title="DST must be resolved",
            due_local=due_local,
            timezone=timezone,
        )
        response = client.post(
            f"{WORKSPACE}/changes", headers=ORIGIN_HEADERS, json=body
        )
        assert response.status_code == 422
        assert _items(client, "reminder") == []


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return (
        parsed.replace(tzinfo=UTC)
        if parsed.tzinfo is None
        else parsed.astimezone(UTC)
    )


def test_reminders_persist_update_and_delete_across_api_restarts(
    workspace_test_env,
) -> None:
    make_client, _ = workspace_test_env
    with make_client() as client:
        future = _create_item(
            client, "reminder", title="Future reminder", due_local=FUTURE_DUE
        )
        overdue = _create_item(
            client, "reminder", title="Overdue reminder", due_local=OVERDUE_DUE
        )
        assert _utc_datetime(future["due_at"]) > FIXED_NOW
        assert _utc_datetime(overdue["due_at"]) < FIXED_NOW

    with make_client() as restarted:
        persisted = _items(restarted, "reminder")
        assert {item["id"] for item in persisted} == {future["id"], overdue["id"]}
        assert len(persisted) == 2
        persisted_overdue = next(
            item for item in persisted if item["id"] == overdue["id"]
        )
        assert persisted_overdue["title"] == "Overdue reminder"
        assert _utc_datetime(persisted_overdue["due_at"]) < FIXED_NOW

        update_body = _body(
            "reminder",
            "update",
            uuid4(),
            item_id=overdue["id"],
            title="Moved reminder",
            due_local=UPDATED_FUTURE_DUE,
        )
        prepared = _prepare(restarted, update_body)
        assert prepared["status"] == "confirmation-required"
        unchanged = next(
            item
            for item in _items(restarted, "reminder")
            if item["id"] == overdue["id"]
        )
        assert unchanged["title"] == "Overdue reminder"
        assert _utc_datetime(unchanged["due_at"]) < FIXED_NOW
        outcome = _confirm(restarted, prepared)
        assert outcome["status"] == "executed"

    with make_client() as restarted_again:
        items = _items(restarted_again, "reminder")
        assert len(items) == 2
        moved = next(item for item in items if item["id"] == overdue["id"])
        assert moved["title"] == "Moved reminder"
        assert moved["timezone"] == "Europe/Bucharest"
        assert _utc_datetime(moved["due_at"]) > FIXED_NOW

        deleted = _confirm(
            restarted_again,
            _prepare(
                restarted_again,
                _body("reminder", "delete", uuid4(), item_id=moved["id"]),
            ),
        )
        assert deleted["status"] == "executed"
        remaining = _items(restarted_again, "reminder")
        assert len(remaining) == 1
        assert remaining[0]["id"] == future["id"]


def test_overdue_reminder_ui_uses_persisted_due_time_and_refreshes() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "rop"
        / "web"
        / "static"
        / "workspace.js"
    ).read_text(encoding="utf-8")
    assert 'item.kind === "reminder" && !item.completed' in source
    assert "new Date(item.due_at).getTime() <= now" in source
    assert "window.setInterval(refreshItems, 60000)" in source


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [(ExecutorError, "failed"), (ExecutorInterrupted, "unknown")],
    ids=["known-failure", "uncertain-outcome"],
)
def test_failure_and_uncertainty_are_distinguished(
    workspace_test_env,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    expected_status: str,
) -> None:
    make_client, _ = workspace_test_env

    def fail_before_mutation(session, operation) -> None:
        raise error_type("simulated private executor failure")

    monkeypatch.setattr(workspace_executor, "_apply_item", fail_before_mutation)
    with make_client() as client:
        key = uuid4()
        prepared = _prepare(client, _body("note", "create", key))
        result = _confirm(client, prepared)
        assert result["status"] == expected_status
        assert result["executed"] is True
        assert _items(client, "note") == []
        assert _receipt(client, key)["status"] == "unknown"
        assert "simulated private executor failure" not in result["message"]


def test_unknown_confirmation_result_recovers_original_receipt_without_duplicate(
    workspace_test_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_client, sessions = workspace_test_env
    real_factory = workspace_executor.SessionLocal

    class CommitThenLoseAcknowledgement:
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
        return CommitThenLoseAcknowledgement(real_factory())

    def unavailable_receipt_recovery(*args, **kwargs):
        raise ExecutorInterrupted("receipt lookup temporarily unavailable")

    with make_client() as client:
        key = uuid4()
        body = _body("note", "create", key, title="Commit ambiguity")
        prepared = _prepare(client, body)
        monkeypatch.setattr(workspace_executor, "SessionLocal", wrapped_factory)
        monkeypatch.setattr(
            workspace_executor, "_recover_receipt", unavailable_receipt_recovery
        )

        result = _confirm(client, prepared)
        assert result["status"] == "unknown"
        assert result["executed"] is True
        assert len(_items(client, "note")) == 1
        assert _receipt(client, key)["status"] == "succeeded"

    monkeypatch.setattr(workspace_executor, "SessionLocal", real_factory)
    with make_client() as restarted:
        replay = _prepare(restarted, body)
        assert replay["status"] == "success"
        assert "challenge" not in replay
        assert len(_items(restarted, "note")) == 1
        assert _receipt(restarted, key)["status"] == "succeeded"

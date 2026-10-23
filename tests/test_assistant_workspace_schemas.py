"""Validation and timezone tests for the local workspace contract."""

from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from rop.api.workspace import _is_network_path, _parse_local_due
from rop.schemas.workspace import WorkspaceChangeRequest


def _change(**overrides):
    body = {
        "kind": "note",
        "action": "create",
        "idempotency_key": "97f0dabb-bbf2-431e-90fb-1fdc862d93cc",
        "title": "Read pathology",
    }
    body.update(overrides)
    return WorkspaceChangeRequest.model_validate(body)


def test_workspace_change_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _change(confirmed=True)


def test_create_cannot_target_existing_item() -> None:
    with pytest.raises(ValidationError):
        _change(item_id="b1d855f9-fbc8-465e-a449-ce2cf251a973")


def test_reminder_requires_due_time_and_timezone() -> None:
    with pytest.raises(ValidationError):
        _change(kind="reminder")


def test_non_reminders_cannot_carry_due_time() -> None:
    with pytest.raises(ValidationError):
        _change(due_local="2026-10-23T13:00", timezone="America/Toronto")


def test_task_completion_requires_an_explicit_boolean() -> None:
    with pytest.raises(ValidationError):
        _change(
            kind="task",
            action="complete",
            item_id="b1d855f9-fbc8-465e-a449-ce2cf251a973",
        )


def test_clear_content_is_update_only() -> None:
    with pytest.raises(ValidationError):
        _change(clear_content=True)
    valid = _change(
        action="update",
        item_id="b1d855f9-fbc8-465e-a449-ce2cf251a973",
        clear_content=True,
    )
    assert valid.clear_content is True


def test_workspace_mutations_require_consequential_confirmation() -> None:
    from rop.services.workspace_executor import build_workspace_policy

    policy = build_workspace_policy()
    for operation_id in (
        "workspace_note_create",
        "workspace_note_delete",
        "workspace_task_complete",
        "workspace_reminder_create",
        "workspace_root_add",
    ):
        rule = policy.rule(operation_id)
        assert rule is not None
        assert rule.risk is not None
        assert str(rule.risk) == "CONSEQUENTIAL"


def test_nonexistent_dst_wall_time_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _parse_local_due("2024-03-10T02:30", "America/Toronto")
    assert exc.value.status_code == 422


def test_ambiguous_dst_wall_time_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _parse_local_due("2024-11-03T01:30", "America/Toronto")
    assert exc.value.status_code == 422


def test_normal_local_wall_time_converts_to_utc() -> None:
    parsed = _parse_local_due("2026-01-15T09:30", "America/Toronto")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_unc_paths_are_rejected_for_retrieval() -> None:
    assert _is_network_path(Path("//server/share")) is True


def test_retrieval_root_add_rejects_an_item_id() -> None:
    with pytest.raises(ValidationError):
        _change(kind="retrieval_root", action="add", path="C:/Documents",
                item_id="b1d855f9-fbc8-465e-a449-ce2cf251a973", title=None)


def test_retrieval_root_remove_rejects_a_path() -> None:
    with pytest.raises(ValidationError):
        _change(kind="retrieval_root", action="remove",
                item_id="b1d855f9-fbc8-465e-a449-ce2cf251a973",
                path="C:/Documents", title=None)

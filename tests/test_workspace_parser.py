"""Unit tests for deterministic assistant workspace command parsing."""

from uuid import uuid4

import pytest

from rop.capabilities.parser import CapabilityParseError
from rop.capabilities.workspace_parser import WorkspaceCommandParser


def test_parser_only_matches_explicit_workspace_commands() -> None:
    parser = WorkspaceCommandParser()
    assert parser.matches("workspace list notes")
    assert parser.matches("WORKSPACE search files: blood pressure")
    assert not parser.matches("help")
    assert not parser.matches("please add a reminder for tomorrow")


def test_list_notes_has_exact_low_risk_operation_shape() -> None:
    operation = WorkspaceCommandParser().parse("workspace list notes")
    assert operation.operation_id == "workspace_list_items"
    assert operation.parameters == {"kind": "note"}
    assert operation.target is None


def test_add_note_requires_title_and_returns_partial_operation() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace add note:", idempotency_key=key)
    error = caught.value
    assert error.field_name == "title"
    assert error.missing_fields == ["title"]
    assert error.partial_operation is not None
    assert error.partial_operation.operation_id == "workspace_note_create"
    assert error.partial_operation.parameters["idempotency_key"] == key


def test_clarification_can_complete_note_creation() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace add note:", idempotency_key=key)
    partial = caught.value.partial_operation
    assert partial is not None
    operation = parser.parse(
        "Review the respiratory notes",
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": ["title"],
        },
    )
    assert operation.operation_id == "workspace_note_create"
    assert operation.parameters["title"] == "Review the respiratory notes"
    assert operation.parameters["idempotency_key"] == key


def test_reminder_requires_explicit_local_time_and_timezone() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace add reminder: Call clinic",
            idempotency_key=str(uuid4()),
        )
    error = caught.value
    assert error.field_name == "due_at"
    assert set(error.missing_fields) == {"due_at", "timezone"}
    assert error.partial_operation is not None


def test_reminder_clarification_requires_both_values() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace add reminder: Call clinic", idempotency_key=key)
    partial = caught.value.partial_operation
    assert partial is not None
    operation = parser.parse(
        "2026-10-24T09:30 | Europe/Bucharest",
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": ["due_at", "timezone"],
        },
    )
    assert operation.operation_id == "workspace_reminder_create"
    assert operation.parameters["due_at"] == "2026-10-24T09:30"
    assert operation.parameters["timezone"] == "Europe/Bucharest"
    assert operation.parameters["idempotency_key"] == key


def test_uuid_target_is_required_for_delete() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace delete note", idempotency_key=str(uuid4()))
    assert caught.value.field_name == "target"
    assert caught.value.partial_operation is not None

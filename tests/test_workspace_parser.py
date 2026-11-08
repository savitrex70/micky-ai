"""Unit tests for deterministic assistant workspace command parsing."""

from datetime import UTC, datetime
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
    assert operation.parameters["due_at"] == "2026-10-24T06:30:00+00:00"
    assert operation.parameters["timezone"] == "Europe/Bucharest"
    assert operation.parameters["idempotency_key"] == key


def test_uuid_target_is_required_for_delete() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace delete note", idempotency_key=str(uuid4()))
    assert caught.value.field_name == "target"
    assert caught.value.partial_operation is not None


def test_reminder_normalizes_named_local_time_to_utc() -> None:
    operation = WorkspaceCommandParser().parse(
        "workspace add reminder: Call clinic | 2026-06-10T09:30 | Europe/Bucharest",
        idempotency_key=str(uuid4()),
    )
    assert operation.parameters["due_at"] == "2026-06-10T06:30:00+00:00"
    assert operation.parameters["timezone"] == "Europe/Bucharest"


def test_ambiguous_daylight_saving_time_requires_explicit_offset() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace add reminder: Call clinic | 2026-10-25T03:30 | Europe/Bucharest",
            idempotency_key=str(uuid4()),
        )
    assert caught.value.field_name == "due_at"
    assert caught.value.partial_operation is not None
    assert "occurs twice" in caught.value.question


@pytest.mark.parametrize(
    ("due_at", "expected_utc"),
    [
        ("2026-10-25T03:30+03:00", "2026-10-25T00:30:00+00:00"),
        ("2026-10-25T03:30+02:00", "2026-10-25T01:30:00+00:00"),
    ],
)
def test_explicit_offset_disambiguates_repeated_local_time(
    due_at: str, expected_utc: str
) -> None:
    operation = WorkspaceCommandParser().parse(
        f"workspace add reminder: Call clinic | {due_at} | Europe/Bucharest",
        idempotency_key=str(uuid4()),
    )
    assert operation.parameters["due_at"] == expected_utc


def test_nonexistent_daylight_saving_time_requires_correction() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace add reminder: Call clinic | 2026-03-29T03:30 | Europe/Bucharest",
            idempotency_key=str(uuid4()),
        )
    assert caught.value.field_name == "due_at"
    assert "does not exist" in caught.value.question


def test_invalid_timezone_clarification_updates_timezone_not_due_time() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace add reminder: Call clinic | 2026-06-10T09:30 | Not/AZone",
            idempotency_key=key,
        )
    error = caught.value
    assert error.field_name == "timezone"
    assert error.partial_operation is not None
    operation = parser.parse(
        "Europe/Bucharest",
        pending_context={
            "partial_operation": error.partial_operation.model_dump(mode="json"),
            "missing_fields": ["timezone"],
        },
    )
    assert operation.parameters["timezone"] == "Europe/Bucharest"
    assert operation.parameters["due_at"] == "2026-06-10T06:30:00+00:00"


def test_clarification_updates_search_query_not_title() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace search files:")
    error = caught.value
    assert error.partial_operation is not None
    operation = parser.parse(
        "hypertension",
        pending_context={
            "partial_operation": error.partial_operation.model_dump(mode="json"),
            "missing_fields": ["query"],
        },
    )
    assert operation.operation_id == "workspace_search_files"
    assert operation.parameters["query"] == "hypertension"
    assert "title" not in operation.parameters


def test_update_preserves_material_values_when_target_needs_clarification() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace update note not-a-uuid: Revised title | Revised body",
            idempotency_key=key,
        )
    error = caught.value
    assert error.field_name == "target"
    assert error.missing_fields == ["target"]
    partial = error.partial_operation
    assert partial is not None
    assert partial.parameters == {
        "idempotency_key": key,
        "title": "Revised title",
        "content": "Revised body",
    }

    target = str(uuid4())
    completed = parser.parse(
        target,
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": error.missing_fields,
        },
    )
    assert completed.operation_id == "workspace_note_update"
    assert completed.target == target
    assert completed.parameters["title"] == "Revised title"
    assert completed.parameters["content"] == "Revised body"
    assert completed.parameters["idempotency_key"] == key


def test_reminder_update_preserves_timezone_values_while_target_is_missing() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace update reminder not-a-uuid: Call clinic | bring notes | "
            "2026-10-24T09:30 | Europe/Bucharest",
            idempotency_key=key,
        )
    error = caught.value
    assert error.field_name == "target"
    partial = error.partial_operation
    assert partial is not None
    target = str(uuid4())
    completed = parser.parse(
        target,
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": error.missing_fields,
        },
    )
    assert completed.operation_id == "workspace_reminder_update"
    assert completed.target == target
    assert completed.parameters["title"] == "Call clinic"
    assert completed.parameters["content"] == "bring notes"
    assert completed.parameters["due_at"] == "2026-10-24T06:30:00+00:00"
    assert completed.parameters["timezone"] == "Europe/Bucharest"


def _relative_reminder_pending(
    parser: WorkspaceCommandParser,
    hint: str,
    time_text: str | None = None,
):
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace add reminder: Review my notes",
            idempotency_key=str(uuid4()),
            relative_date_hint=hint,
            relative_clock_time=time_text,
        )
    error = caught.value
    assert error.partial_operation is not None
    return error


def _continue_relative_reminder(parser: WorkspaceCommandParser, error, answer: str):
    assert error.partial_operation is not None
    return parser.parse(
        answer,
        pending_context={
            "partial_operation": error.partial_operation.model_dump(mode="json"),
            "missing_fields": list(error.missing_fields),
        },
    )


def test_relative_tomorrow_date_survives_clarification_and_uses_selected_timezone(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "tomorrow")
    assert pending.missing_fields == ["due_at", "timezone"]
    assert pending.partial_operation.parameters["relative_date_hint"] == "tomorrow"
    assert "tomorrow" not in pending.partial_operation.parameters["title"]

    completed = _continue_relative_reminder(parser, pending, "09:00 | Europe/Amsterdam")
    assert completed.operation_id == "workspace_reminder_create"
    assert completed.parameters["title"] == "Review my notes"
    assert completed.parameters["timezone"] == "Europe/Amsterdam"
    assert completed.parameters["due_at"] == "2026-10-30T08:00:00+00:00"
    assert "relative_date_hint" not in completed.parameters
    assert "relative_clock_time" not in completed.parameters


@pytest.mark.parametrize(
    ("hint", "clock_time", "expected_utc"),
    [
        ("today", "09:30", "2026-10-29T08:30:00+00:00"),
        ("tomorrow", "09:30", "2026-10-30T08:30:00+00:00"),
        ("tonight", "20:00", "2026-10-29T19:00:00+00:00"),
    ],
)
def test_relative_day_hints_resolve_with_a_timezone_and_clock(
    monkeypatch,
    hint: str,
    clock_time: str,
    expected_utc: str,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, hint, clock_time)
    assert pending.missing_fields == ["timezone"]
    completed = _continue_relative_reminder(parser, pending, "Europe/Amsterdam")
    assert completed.parameters["due_at"] == expected_utc
    assert completed.parameters["timezone"] == "Europe/Amsterdam"


def test_relative_tomorrow_uses_request_anchor_when_clarification_crosses_midnight(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 22, 55, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "tomorrow")
    assert pending.partial_operation is not None
    assert (
        pending.partial_operation.parameters["relative_anchor_utc"]
        == "2026-10-29T22:55:00+00:00"
    )

    # Amsterdam passes midnight while the ten-minute clarification is active.
    # The request was made at 23:55 local on October 29, so "tomorrow" remains
    # October 30 even though the answer arrives after local midnight.
    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 23, 5, tzinfo=UTC),
    )
    completed = _continue_relative_reminder(parser, pending, "09:00 | Europe/Amsterdam")
    assert completed.parameters["due_at"] == "2026-10-30T08:00:00+00:00"
    assert "relative_anchor_utc" not in completed.parameters


def test_relative_reminder_without_original_anchor_fails_closed(monkeypatch) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "tomorrow")
    assert pending.partial_operation is not None
    partial = pending.partial_operation.model_dump(mode="json")
    partial["parameters"].pop("relative_anchor_utc")

    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "09:00 | Europe/Amsterdam",
            pending_context={
                "partial_operation": partial,
                "missing_fields": list(pending.missing_fields),
            },
        )

    assert caught.value.partial_operation is None
    assert "original relative-date reference was not preserved" in caught.value.question
    assert "nothing was saved" in caught.value.question


def test_relative_reminder_reasks_for_timezone_after_invalid_timezone(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "tomorrow", "09:00")
    with pytest.raises(CapabilityParseError) as caught:
        _continue_relative_reminder(parser, pending, "Not/AZone")
    invalid_zone = caught.value
    assert invalid_zone.field_name == "timezone"
    assert invalid_zone.missing_fields == ["timezone"]
    completed = _continue_relative_reminder(parser, invalid_zone, "Europe/Amsterdam")
    assert completed.parameters["due_at"] == "2026-10-30T08:00:00+00:00"


def test_relative_reminder_rejects_invalid_and_past_clock_values(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "today", "09:00")
    with pytest.raises(CapabilityParseError) as caught:
        _continue_relative_reminder(parser, pending, "Europe/Amsterdam")
    assert caught.value.field_name == "due_at"
    assert "already passed" in caught.value.question

    pending_without_clock = _relative_reminder_pending(parser, "today")
    with pytest.raises(CapabilityParseError) as invalid_clock:
        _continue_relative_reminder(
            parser, pending_without_clock, "not-a-time | Europe/Amsterdam"
        )
    assert invalid_clock.value.field_name == "due_at"
    assert "HH:MM" in invalid_clock.value.question


def test_relative_reminder_handles_nonexistent_dst_wall_time(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "tomorrow", "02:30")
    with pytest.raises(CapabilityParseError) as caught:
        _continue_relative_reminder(parser, pending, "America/New_York")
    assert caught.value.field_name == "due_at"
    assert "does not exist" in caught.value.question
    corrected = _continue_relative_reminder(parser, caught.value, "03:30")
    assert corrected.parameters["due_at"] == "2026-03-08T07:30:00+00:00"


def test_relative_reminder_handles_ambiguous_dst_wall_time_without_guessing(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 31, 12, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "tomorrow", "01:30")
    with pytest.raises(CapabilityParseError) as caught:
        _continue_relative_reminder(parser, pending, "America/New_York")
    assert caught.value.field_name == "due_at"
    assert "occurs twice" in caught.value.question


def test_next_week_requires_an_exact_date_inside_the_next_calendar_week(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    pending = _relative_reminder_pending(parser, "next_week")
    next_week_answer = "2026-11-04T09:30 | Europe/Amsterdam"
    completed = _continue_relative_reminder(parser, pending, next_week_answer)
    assert completed.parameters["due_at"] == "2026-11-04T08:30:00+00:00"

    with pytest.raises(CapabilityParseError) as caught:
        _continue_relative_reminder(
            parser, pending, "2026-10-30T09:30 | Europe/Amsterdam"
        )
    assert caught.value.field_name == "due_at"
    assert "next calendar week" in caught.value.question


# ---------------------------------------------------------------------------
# Task 249: title-selector commands and pending listing
# ---------------------------------------------------------------------------


def test_list_pending_tasks_binds_read_only_status() -> None:
    parser = WorkspaceCommandParser()
    for kind, plural in (
        ("note", "notes"),
        ("task", "tasks"),
        ("reminder", "reminders"),
    ):
        operation = parser.parse(f"workspace list pending {plural}")
        assert operation.operation_id == "workspace_list_items"
        assert operation.parameters == {"kind": kind, "status": "pending"}
        assert operation.target is None


def test_list_pending_words_are_interchangeable() -> None:
    parser = WorkspaceCommandParser()
    for word in ("pending", "incomplete", "open", "unfinished"):
        operation = parser.parse(f"workspace list {word} tasks")
        assert operation.parameters == {"kind": "task", "status": "pending"}


def test_list_rejects_unknown_pending_kinds() -> None:
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError):
        parser.parse("workspace list pending items")


def test_selector_commands_carry_the_exact_title_without_a_target() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    operation = parser.parse(
        "workspace delete note titled: Ward revision", idempotency_key=key
    )
    assert operation.operation_id == "workspace_note_delete"
    assert operation.target is None
    assert operation.parameters == {
        "idempotency_key": key,
        "selector_title": "Ward revision",
    }


def test_task_state_selector_carries_completed_flag() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    complete = parser.parse(
        "workspace complete task titled: Submit assignment", idempotency_key=key
    )
    assert complete.operation_id == "workspace_task_complete"
    assert complete.target is None
    assert complete.parameters["selector_title"] == "Submit assignment"
    assert complete.parameters["completed"] == "true"

    reopen = parser.parse(
        "workspace reopen task titled: Submit assignment", idempotency_key=key
    )
    assert reopen.parameters["completed"] == "false"


def test_selector_commands_require_an_exact_title() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())

    with pytest.raises(CapabilityParseError) as caught:
        parser.parse("workspace delete task titled:", idempotency_key=key)
    error = caught.value
    assert error.field_name == "selector_title"
    assert error.missing_fields == ["selector_title"]
    partial = error.partial_operation
    assert partial is not None
    assert partial.operation_id == "workspace_task_delete"
    assert partial.parameters["idempotency_key"] == key
    assert "selector_title" not in partial.parameters

    completed = parser.parse(
        "Ward revision",
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": ["selector_title"],
        },
    )
    assert completed.parameters["selector_title"] == "Ward revision"


def test_selector_commands_refuse_separators_and_unprintable_titles() -> None:
    parser = WorkspaceCommandParser()
    for command in (
        "workspace delete task titled: Ward | rm -rf",
        "workspace delete task titled: Ward\x07 revision",
        "workspace delete task titled: " + "x" * 201,
        "workspace complete task titled: Ward\x1b revision",
        "workspace update note titled: Ward\x1b revision | title: Other",
    ):
        with pytest.raises(CapabilityParseError) as caught:
            parser.parse(command, idempotency_key=str(uuid4()))
        assert caught.value.partial_operation is None
        assert caught.value.field_name in {"selector_title", "update"}


def test_update_selector_binds_rename_and_content_segments() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    renamed = parser.parse(
        "workspace update note titled: Ward revision | title: Ward revision two",
        idempotency_key=key,
    )
    assert renamed.operation_id == "workspace_note_update"
    assert renamed.target is None
    assert renamed.parameters["selector_title"] == "Ward revision"
    assert renamed.parameters["title"] == "Ward revision two"
    assert "content" not in renamed.parameters

    content = parser.parse(
        "workspace update note titled: Ward revision | content: New key points",
        idempotency_key=key,
    )
    assert content.parameters["content"] == "New key points"
    # The executor writes a full title value; an unchanged title keeps the
    # selector value.
    assert content.parameters["title"] == "Ward revision"


def test_update_selector_reminder_resolves_exact_due_time() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    operation = parser.parse(
        "workspace update reminder titled: Call the clinic | "
        "due: 2026-11-12T14:00 | tz: Europe/Amsterdam",
        idempotency_key=key,
    )
    assert operation.operation_id == "workspace_reminder_update"
    assert operation.target is None
    assert operation.parameters["selector_title"] == "Call the clinic"
    assert operation.parameters["due_at"] == "2026-11-12T13:00:00+00:00"
    assert operation.parameters["timezone"] == "Europe/Amsterdam"
    assert operation.parameters["title"] == "Call the clinic"


def test_update_selector_reminder_requires_exact_time() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace update reminder titled: Call the clinic | due: 2026-11-12T14:00",
            idempotency_key=key,
        )
    # The parser asks for the missing timezone through the dedicated field.
    assert caught.value.field_name == "timezone"
    assert caught.value.missing_fields == ["timezone"]
    partial = caught.value.partial_operation
    assert partial is not None
    assert partial.parameters["selector_title"] == "Call the clinic"
    assert partial.parameters["due_at"] == "2026-11-12T14:00"

    with pytest.raises(CapabilityParseError) as missing_time:
        parser.parse(
            "workspace update reminder titled: Call the clinic",
            idempotency_key=str(uuid4()),
        )
    assert set(missing_time.value.missing_fields) == {"due_at", "timezone"}
    partial = missing_time.value.partial_operation
    assert partial is not None
    assert partial.parameters["selector_title"] == "Call the clinic"


def test_update_selector_continues_clarification_by_selector_then_segments(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as first:
        parser.parse("workspace update note titled:", idempotency_key=str(uuid4()))
    assert set(first.value.missing_fields) == {
        "selector_title",
        "title",
        "content",
    }
    partial = first.value.partial_operation
    assert partial is not None

    # The first answer binds the selector; both change fields remain.
    with pytest.raises(CapabilityParseError) as second:
        parser.parse(
            "Ward revision",
            pending_context={
                "partial_operation": partial.model_dump(mode="json"),
                "missing_fields": list(first.value.missing_fields),
            },
        )
    assert set(second.value.missing_fields) == {"title", "content"}
    carried = second.value.partial_operation
    assert carried.parameters["selector_title"] == "Ward revision"
    assert "title" not in carried.parameters
    assert "content" not in carried.parameters

    completed = parser.parse(
        "content: Revised recovery plan",
        pending_context={
            "partial_operation": carried.model_dump(mode="json"),
            "missing_fields": list(second.value.missing_fields),
        },
    )
    assert completed.parameters["title"] == "Ward revision"
    assert completed.parameters["content"] == "Revised recovery plan"
    assert completed.parameters["selector_title"] == "Ward revision"


def test_update_selector_accepts_both_change_segments_in_one_reply(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as first:
        parser.parse("workspace update note titled:", idempotency_key=str(uuid4()))
    partial = first.value.partial_operation
    with pytest.raises(CapabilityParseError) as second:
        parser.parse(
            "Ward revision",
            pending_context={
                "partial_operation": partial.model_dump(mode="json"),
                "missing_fields": list(first.value.missing_fields),
            },
        )
    completed = parser.parse(
        "title: New plan | content: New details",
        pending_context={
            "partial_operation": second.value.partial_operation.model_dump(mode="json"),
            "missing_fields": list(second.value.missing_fields),
        },
    )
    assert completed.parameters["title"] == "New plan"
    assert completed.parameters["content"] == "New details"


def test_update_selector_relative_reschedule_uses_request_anchor(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    key = str(uuid4())

    completed = parser.parse(
        "workspace update reminder titled: Call the clinic | " "tz: Europe/Amsterdam",
        idempotency_key=key,
        relative_date_hint="tomorrow",
        relative_clock_time="09:00",
    )
    assert completed.parameters["selector_title"] == "Call the clinic"
    assert completed.parameters["due_at"] == "2026-10-30T08:00:00+00:00"
    assert completed.parameters["timezone"] == "Europe/Amsterdam"
    assert completed.parameters["title"] == "Call the clinic"
    for relative_name in (
        "relative_date_hint",
        "relative_clock_time",
        "relative_anchor_utc",
    ):
        assert relative_name not in completed.parameters


def test_update_selector_relative_reschedule_without_clock_asks_clock_time(
    monkeypatch,
) -> None:
    import rop.capabilities.workspace_parser as workspace_parser

    monkeypatch.setattr(
        workspace_parser,
        "_current_utc",
        lambda: datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    )
    parser = WorkspaceCommandParser()
    with pytest.raises(CapabilityParseError) as caught:
        parser.parse(
            "workspace update reminder titled: Call the clinic | tz: Europe/Amsterdam",
            idempotency_key=str(uuid4()),
            relative_date_hint="tomorrow",
        )
    assert caught.value.missing_fields == ["due_at"]
    partial = caught.value.partial_operation
    assert partial.parameters["selector_title"] == "Call the clinic"
    assert partial.parameters["timezone"] == "Europe/Amsterdam"
    anchor = partial.parameters["relative_anchor_utc"]
    assert anchor == "2026-10-29T06:00:00+00:00"

    completed = parser.parse(
        "09:00",
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": list(caught.value.missing_fields),
        },
    )
    assert completed.parameters["due_at"] == "2026-10-30T08:00:00+00:00"
    assert completed.parameters["timezone"] == "Europe/Amsterdam"


def test_update_selector_exclusive_dst_times_fail_closed() -> None:
    parser = WorkspaceCommandParser()
    key = str(uuid4())
    with pytest.raises(CapabilityParseError) as missing:
        parser.parse(
            "workspace update reminder titled: Call the clinic | "
            "due: 2026-03-08T02:30 | tz: America/New_York",
            idempotency_key=key,
        )
    assert missing.value.field_name == "due_at"
    assert "does not exist" in missing.value.question
    assert missing.value.missing_fields == ["due_at"]
    partial = missing.value.partial_operation
    assert partial is not None
    assert partial.parameters["selector_title"] == "Call the clinic"

    completed = parser.parse(
        "2026-03-08T03:30",
        pending_context={
            "partial_operation": partial.model_dump(mode="json"),
            "missing_fields": list(missing.value.missing_fields),
        },
    )
    assert completed.parameters["due_at"] == "2026-03-08T07:30:00+00:00"
    assert completed.parameters["timezone"] == "America/New_York"

    with pytest.raises(CapabilityParseError) as ambiguous:
        parser.parse(
            "workspace update reminder titled: Call the clinic | "
            "due: 2026-10-25T03:30 | tz: Europe/Bucharest",
            idempotency_key=str(uuid4()),
        )
    assert "occurs twice" in ambiguous.value.question
    resolved = parser.parse(
        "2026-10-25T03:30+03:00",
        pending_context={
            "partial_operation": ambiguous.value.partial_operation.model_dump(
                mode="json"
            ),
            "missing_fields": list(ambiguous.value.missing_fields),
        },
    )
    assert resolved.parameters["due_at"] == "2026-10-25T00:30:00+00:00"


def test_explicit_command_grammar_still_parses_by_uuid() -> None:
    parser = WorkspaceCommandParser()
    uuid_target = str(uuid4())
    list_operation = parser.parse("workspace list notes")
    assert list_operation.parameters == {"kind": "note"}
    delete_operation = parser.parse(
        f"workspace delete note {uuid_target}", idempotency_key="k"
    )
    assert delete_operation.target == uuid_target
    complete_operation = parser.parse(
        f"workspace complete task {uuid_target}", idempotency_key="k"
    )
    assert complete_operation.target == uuid_target
    update_operation = parser.parse(
        f"workspace update note {uuid_target}: Revised title | Revised body",
        idempotency_key="k",
    )
    assert update_operation.target == uuid_target
    assert update_operation.parameters["title"] == "Revised title"
    assert update_operation.parameters["content"] == "Revised body"

"""Fixed-corpus tests for deterministic natural-language intent interpretation."""

import pytest

from rop.capabilities.intent_interpreter import interpret_request


@pytest.mark.parametrize(
    ("phrase", "intent", "command"),
    [
        ("Help me.", "help", "help"),
        ("What can you do?", "help", "help"),
        ("Show me the commands I can use.", "help", "help"),
        ("Show me my notes.", "workspace", "workspace list notes"),
        ("What tasks do I have?", "workspace", "workspace list tasks"),
        ("Show my reminders.", "workspace", "workspace list reminders"),
        (
            "Find files containing my revision notes.",
            "workspace",
            "workspace search files: my revision notes",
        ),
        (
            "Search my authorized files for pharmacology.",
            "workspace",
            "workspace search files: pharmacology",
        ),
        (
            "Find the document mentioning this topic.",
            "workspace",
            "workspace search files: this topic",
        ),
        (
            "Make a note titled Study Plan.",
            "workspace",
            "workspace add note: Study Plan",
        ),
        ("Save this as a note.", "workspace", "workspace add note:"),
        (
            "Create a task to finish my assignment.",
            "workspace",
            "workspace add task: finish my assignment",
        ),
        (
            "Remind me to review my notes tomorrow.",
            "workspace",
            "workspace add reminder: review my notes",
        ),
        (
            "Remind me to call the dentist on 2026-11-01T10:00 in Europe/Amsterdam",
            "workspace",
            "workspace add reminder: call the dentist | 2026-11-01T10:00 | "
            "Europe/Amsterdam",
        ),
        (
            "workspace list notes",
            "workspace",
            "workspace list notes",
        ),
    ],
)
def test_supported_phrases_map_to_exact_existing_intents(
    phrase: str, intent: str, command: str
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.intent == intent
    assert result.command == command


@pytest.mark.parametrize(
    "phrase",
    [
        "what is the weather today",
        "create an appointment with my doctor",
        "please remember this private string",
        "show me my note",
        "find documents containing pharmacology",
    ],
)
def test_near_misses_and_unsupported_requests_do_not_match(phrase: str) -> None:
    result = interpret_request(phrase)
    assert result.status == "unsupported"
    assert result.command is None


@pytest.mark.parametrize(
    "phrase",
    [
        "show me my notes and tasks",
        "what can you do and save a note",
        "show my reminders then create a task",
    ],
)
def test_conflicting_intents_ask_for_clarification_without_selecting_a_command(
    phrase: str,
) -> None:
    result = interpret_request(phrase)
    assert result.status == "ambiguous"
    assert result.command is None
    assert "Nothing was executed" in (result.message or "")


def test_extracted_command_separator_is_rejected() -> None:
    result = interpret_request(
        "make a note titled Plan | workspace delete note "
        "00000000-0000-0000-0000-000000000001"
    )
    assert result.status == "ambiguous"
    assert result.command is None


def test_explicit_command_is_preserved_without_rewriting() -> None:
    command = "workspace add note: Study Plan | title details"
    result = interpret_request(command)
    assert result.status == "matched"
    assert result.command == command


def test_task_and_reminder_workflow_requires_all_exact_fields() -> None:
    result = interpret_request(
        "Create a task to finish assignment and remind me to review notes "
        "on 2026-11-01T10:00 in Europe/Amsterdam"
    )
    assert result.status == "matched"
    assert result.intent == "workspace"
    assert result.command == (
        "workspace workflow create task-and-reminder: finish assignment | "
        "review notes | 2026-11-01T10:00 | Europe/Amsterdam"
    )


def test_task_and_reminder_workflow_without_date_requests_clarification() -> None:
    result = interpret_request(
        "Create a task to finish assignment and remind me to review notes tomorrow"
    )
    assert result.status == "ambiguous"
    assert result.command is None
    assert "exact local date/time" in (result.message or "")


@pytest.mark.parametrize(
    ("phrase", "command"),
    [
        ("Create a task to", "workspace add task:"),
        ("Remind me to", "workspace add reminder:"),
    ],
)
def test_missing_optional_title_never_adds_trailing_command_whitespace(
    phrase: str, command: str
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.command == command


@pytest.mark.parametrize(
    ("phrase", "expected_command"),
    [
        (
            (
                "Find files containing pharmacology notes and create a task "
                "to revise chapter 3."
            ),
            (
                "workspace workflow search-and-create-item: task | "
                "pharmacology notes | revise chapter 3"
            ),
        ),
        (
            (
                "Search my authorized files for renal physiology and prepare "
                "a note titled Revision key points."
            ),
            (
                "workspace workflow search-and-create-item: note | "
                "renal physiology | Revision key points"
            ),
        ),
    ],
)
def test_search_and_create_workflow_requires_explicit_query_and_title(
    phrase: str, expected_command: str
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.intent == "workspace"
    assert result.command == expected_command


def test_note_with_missing_title_asks_for_clarification() -> None:
    result = interpret_request("Create a note titled")
    assert result.status == "ambiguous"
    assert result.command is None
    assert "note" in (result.message or "")


def test_search_and_create_workflow_with_missing_title_asks_for_clarification() -> None:
    result = interpret_request("Find files containing renal marker and prepare a note")
    assert result.status == "ambiguous"
    assert result.command is None
    assert "item title" in (result.message or "")


def test_search_and_create_workflow_rejects_command_separator() -> None:
    result = interpret_request(
        "Find files containing pharmacology | workspace delete task "
        "00000000-0000-0000-0000-000000000001 and create a task to revise it"
    )
    assert result.status == "ambiguous"
    assert result.command is None


@pytest.mark.parametrize(
    ("phrase", "date_hint", "clock_time"),
    [
        ("Remind me to review my notes today.", "today", None),
        ("Remind me to review my notes tomorrow.", "tomorrow", None),
        ("Remind me to review my notes tomorrow at 09:00.", "tomorrow", "09:00"),
        ("Remind me to review my notes tonight.", "tonight", None),
        ("Remind me to review my notes tonight at 20:00.", "tonight", "20:00"),
        ("Remind me to review my notes this evening at 19:30.", "tonight", "19:30"),
        ("Remind me to review my notes next week.", "next_week", None),
    ],
)
def test_relative_reminder_date_is_preserved_as_structured_metadata(
    phrase: str,
    date_hint: str,
    clock_time: str | None,
) -> None:
    result = interpret_request(phrase)

    assert result.status == "matched"
    assert result.intent == "workspace"
    assert result.command == "workspace add reminder: review my notes"
    assert result.relative_date_hint == date_hint
    assert result.relative_clock_time == clock_time


# ---------------------------------------------------------------------------
# Task 249: conversational workspace management
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "command"),
    [
        ("Show my pending tasks.", "workspace list pending tasks"),
        ("List incomplete tasks.", "workspace list pending tasks"),
        ("What tasks do I still have to finish?", "workspace list pending tasks"),
        ("what tasks do I still have to do", "workspace list pending tasks"),
        ("List open notes.", "workspace list pending notes"),
        ("Show my pending reminders", "workspace list pending reminders"),
        ("List unfinished reminders.", "workspace list pending reminders"),
    ],
)
def test_pending_listing_phrases_map_to_read_only_command(
    phrase: str, command: str
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.intent == "workspace"
    assert result.command == command
    assert result.relative_date_hint is None
    assert result.relative_clock_time is None


@pytest.mark.parametrize(
    ("phrase", "command"),
    [
        (
            "Mark my pharmacology revision task as complete.",
            "workspace complete task titled: pharmacology revision",
        ),
        (
            "Mark the task titled Clinical attachment report as complete.",
            "workspace complete task titled: Clinical attachment report",
        ),
        (
            "Complete the task titled Clinical attachment report.",
            "workspace complete task titled: Clinical attachment report",
        ),
        (
            "Complete my pharmacology revision task.",
            "workspace complete task titled: pharmacology revision",
        ),
        (
            "Finish my lab report task.",
            "workspace complete task titled: lab report",
        ),
        (
            "Reopen my pathology assignment task.",
            "workspace reopen task titled: pathology assignment",
        ),
        (
            "Reopen the task titled Pathology assignment.",
            "workspace reopen task titled: Pathology assignment",
        ),
        (
            "Reopen my Ward revision task again",
            "workspace reopen task titled: Ward revision",
        ),
    ],
)
def test_task_state_phrases_target_tasks_by_exact_title(
    phrase: str, command: str
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.command == command


@pytest.mark.parametrize(
    ("phrase", "command"),
    [
        (
            "Delete my note titled Respiratory revision.",
            "workspace delete note titled: Respiratory revision",
        ),
        (
            "Delete the task titled Submit assignment.",
            "workspace delete task titled: Submit assignment",
        ),
        (
            "Delete my reminder titled Call the clinic.",
            "workspace delete reminder titled: Call the clinic",
        ),
        (
            "Delete the note titled Ward revision",
            "workspace delete note titled: Ward revision",
        ),
        (
            "Delete my Respiratory revision note.",
            "workspace delete note titled: Respiratory revision",
        ),
        (
            "Delete my Call the clinic reminder.",
            "workspace delete reminder titled: Call the clinic",
        ),
    ],
)
def test_delete_phrases_target_one_kind_by_exact_title(
    phrase: str, command: str
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.command == command


@pytest.mark.parametrize(
    ("phrase", "command"),
    [
        (
            "Rename the note titled Respiratory Notes to Respiratory Revision.",
            (
                "workspace update note titled: Respiratory Notes | "
                "title: Respiratory Revision"
            ),
        ),
        (
            "Rename my task titled Clinical Report to Final Clinical Report.",
            (
                "workspace update task titled: Clinical Report | "
                "title: Final Clinical Report"
            ),
        ),
        (
            (
                "Update the content of my note titled Pharmacology Revision "
                "with revised key points."
            ),
            (
                "workspace update note titled: Pharmacology Revision | "
                "content: revised key points"
            ),
        ),
        (
            (
                "Change the content of the task titled Lab checklist to "
                "include consent step."
            ),
            (
                "workspace update task titled: Lab checklist | "
                "content: include consent step"
            ),
        ),
    ],
)
def test_update_phrases_emit_explicit_field_segments(phrase: str, command: str) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.command == command


@pytest.mark.parametrize(
    ("phrase", "command", "date_hint", "clock_time"),
    [
        (
            "Move my clinic appointment reminder to tomorrow at 09:00 in "
            "Africa/Nairobi.",
            (
                "workspace update reminder titled: clinic appointment | "
                "tz: Africa/Nairobi"
            ),
            "tomorrow",
            "09:00",
        ),
        (
            (
                "Move the reminder titled Call the clinic to tomorrow at "
                "09:00 in Africa/Nairobi."
            ),
            (
                "workspace update reminder titled: Call the clinic | "
                "tz: Africa/Nairobi"
            ),
            "tomorrow",
            "09:00",
        ),
        (
            (
                "Reschedule my stdp assignment reminder to tomorrow in "
                "Africa/Nairobi."
            ),
            (
                "workspace update reminder titled: stdp assignment | "
                "tz: Africa/Nairobi"
            ),
            "tomorrow",
            None,
        ),
        (
            (
                "Reschedule the reminder titled Call the clinic to "
                "2026-11-12T14:00 in Africa/Nairobi."
            ),
            (
                "workspace update reminder titled: Call the clinic | "
                "due: 2026-11-12T14:00 | tz: Africa/Nairobi"
            ),
            None,
            None,
        ),
        (
            ("Move my clinic appointment reminder to next week in " "Africa/Nairobi."),
            (
                "workspace update reminder titled: clinic appointment | "
                "tz: Africa/Nairobi"
            ),
            "next_week",
            None,
        ),
        (
            "Move my clinic appointment reminder to tonight at 20:00.",
            "workspace update reminder titled: clinic appointment",
            "tonight",
            "20:00",
        ),
        (
            (
                "Reschedule the reminder titled Follow-up to "
                "2026-11-12T14:00+03:00 | Europe/Bucharest"
            ),
            (
                "workspace update reminder titled: Follow-up | "
                "due: 2026-11-12T14:00+03:00 | tz: Europe/Bucharest"
            ),
            None,
            None,
        ),
    ],
)
def test_reschedule_phrases_return_relative_metadata_separately(
    phrase: str, command: str, date_hint: str | None, clock_time: str | None
) -> None:
    result = interpret_request(phrase)
    assert result.status == "matched"
    assert result.command == command
    assert result.relative_date_hint == date_hint
    assert result.relative_clock_time == clock_time


@pytest.mark.parametrize(
    ("phrase", "snippet"),
    [
        ("Mark the it task as complete", "exact title"),
        ("Mark the this task as complete", "exact title"),
        ("Complete the task titled | separated title", "cannot be safely interpreted"),
        ("Delete my note titled Ward\x7f revision", None),
        ("Rename the task titled A to B and delete the note titled C", None),
        ("Mark my task as complete and delete my note titled Legacy C", None),
        (
            "Show my pending tasks and delete note "
            "00000000-0000-0000-0000-000000000001",
            None,
        ),
    ],
)
def test_selector_phrases_without_exact_titles_never_infer_targets(
    phrase: str, snippet: str | None
) -> None:
    result = interpret_request(phrase)
    assert result.status == "ambiguous", (phrase, result)
    assert result.command is None
    if snippet is not None:
        assert snippet in (result.message or "")
    else:
        assert "Nothing was executed" in (result.message or "")


@pytest.mark.parametrize(
    "phrase",
    [
        "Mark my Ward note as complete",
        "Reopen my pathology reminder",
        "Delete my item titled Ward",
        "Show my pending items",
        "Show my completed tasks",
        "Complete my reminder titled Call the clinic",
        "Rename the reminder titled Call the clinic to Later call",
        "Update the content of the reminder titled Call the clinic to text",
        "Rename my task to a new title",
        "List my pending tasks | workspace delete note "
        "00000000-0000-0000-0000-000000000001",
        "Delete the",
        "Mark my task\x1b titled Test as done",
        "Delete \x07 my note titled Bleep",
    ],
)
def test_wrong_item_types_and_control_chars_are_unsupported(phrase: str) -> None:
    result = interpret_request(phrase)
    assert result.status == "unsupported", (phrase, result)
    assert result.command is None


@pytest.mark.parametrize(
    "phrase",
    [
        "Delete my note titled",
        "Delete my task titled",
        "Reschedule my reminder titled",
        "Reschedule the reminder titled Call the clinic",
    ],
)
def test_missing_selector_titles_refuse_to_act(phrase: str) -> None:
    result = interpret_request(phrase)
    assert result.status == "ambiguous", (phrase, result)
    assert result.command is None
    assert "Nothing was executed" in (result.message or "")


def test_quote_decoration_is_stripped_but_authorization_remains_required() -> None:
    result = interpret_request('Delete the note titled "Pharmacology Revision".')
    assert result.status == "matched"
    assert result.command == ("workspace delete note titled: Pharmacology Revision")

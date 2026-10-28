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
            "workspace add reminder: call the dentist | 2026-11-01T10:00 | Europe/Amsterdam",
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
        "make a note titled Plan | workspace delete note 00000000-0000-0000-0000-000000000001"
    )
    assert result.status == "ambiguous"
    assert result.command is None


def test_explicit_command_is_preserved_without_rewriting() -> None:
    command = "workspace add note: Study Plan | title details"
    result = interpret_request(command)
    assert result.status == "matched"
    assert result.command == command

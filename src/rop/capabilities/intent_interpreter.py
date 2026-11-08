"""Conservative deterministic intent interpretation for supported local actions.

This module translates a narrow, explicitly enumerated set of natural-language
phrases into the existing workspace command grammar. It never authorizes or
executes an operation. Unknown and conflicting requests fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

IntentStatus = Literal["matched", "ambiguous", "unsupported"]
IntentKind = Literal["help", "workspace"]
RelativeDateHint = Literal["today", "tomorrow", "tonight", "next_week"]


@dataclass(frozen=True, slots=True)
class IntentInterpretation:
    """A safe interpretation result with no execution or authorization power."""

    status: IntentStatus
    intent: IntentKind | None = None
    command: str | None = None
    message: str | None = None
    relative_date_hint: RelativeDateHint | None = None
    relative_clock_time: str | None = None


_AMBIGUOUS_MESSAGE = (
    "I could not safely determine which action you intended. Please clarify "
    "the action you want. Nothing was executed or changed."
)
_UNSAFE_VALUE_MESSAGE = (
    "That request contains a value that cannot be safely interpreted. Please "
    "remove command separators and try again. Nothing was executed."
)
_PUNCTUATION_RE = re.compile(r"[.!?]+\s*$")
_PIPE_OR_CONTROL_RE = re.compile(r"[|\x00-\x1f\x7f]")
_MULTIPLE_LISTS_RE = re.compile(
    r"^(?:show|list|tell me|what)\b.*\b(?:notes|tasks|reminders)\b.*"
    r"\b(?:and|or)\b.*\b(?:notes|tasks|reminders)\b",
    re.IGNORECASE,
)
_REMINDER_RELATIVE_RE = re.compile(
    r"^remind me to\s+(.+?)\s+"
    r"(today|tomorrow|tonight|this evening|next week)"
    r"(?:\s+at\s+((?:[01]?\d|2[0-3]):[0-5]\d))?$",
    re.IGNORECASE,
)
_CLOCK_END_RE = re.compile(r"\s+at\s+\d{1,2}:\d{2}$", re.IGNORECASE)

_HELP_PHRASES = {
    "help",
    "help me",
    "what can you do",
    "show capabilities",
    "list capabilities",
    "list available capabilities",
    "show me the commands i can use",
    "show me available commands",
    "what commands can i use",
}

_LIST_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^(?:show|list)(?: me)? (?:my )?notes$", re.IGNORECASE),
        "note",
    ),
    (
        re.compile(r"^(?:show|list)(?: me)? (?:my )?tasks$", re.IGNORECASE),
        "task",
    ),
    (
        re.compile(r"^(?:show|list)(?: me)? (?:my )?reminders$", re.IGNORECASE),
        "reminder",
    ),
    (re.compile(r"^what notes do i have$", re.IGNORECASE), "note"),
    (re.compile(r"^what tasks do i have$", re.IGNORECASE), "task"),
    (re.compile(r"^what reminders do i have$", re.IGNORECASE), "reminder"),
    (
        re.compile(r"^(?:show|list)(?: me)? (?:my )?workspace items$", re.IGNORECASE),
        "all",
    ),
)

_SEARCH_PATTERNS = (
    re.compile(r"^find files containing(?:\s+(.+))?$", re.IGNORECASE),
    re.compile(r"^search my authorized files for(?:\s+(.+))?$", re.IGNORECASE),
    re.compile(r"^search authorized files for(?:\s+(.+))?$", re.IGNORECASE),
    re.compile(r"^find (?:the )?document mentioning(?:\s+(.+))?$", re.IGNORECASE),
)

_NOTE_TITLE_PATTERNS = (
    re.compile(
        r"^(?:make|create|write) (?:me )?a note(?:\s+(?:titled|called|named)\s+(.+))?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:make|create) (?:me )?a note with title(?:\s+(.+))?$",
        re.IGNORECASE,
    ),
)
_NOTE_TITLE_SKELETON_RE = re.compile(
    r"^(?:make|create|write) (?:me )?a note (?:titled|called|named)$",
    re.IGNORECASE,
)
_TASK_TITLE_RE = re.compile(
    r"^(?:create|make|add) (?:me )?a? ?task to(?:\s+(.+))?$",
    re.IGNORECASE,
)
_TASK_REMINDER_WORKFLOW_RE = re.compile(
    r"^create (?:a )?task to (.+?) and remind me to (.+?) on "
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}) in "
    r"([A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)*|UTC)$",
    re.IGNORECASE,
)
_TASK_REMINDER_SKELETON_RE = re.compile(
    r"^create (?:a )?task to .+? and remind me to .+$",
    re.IGNORECASE,
)
_SEARCH_CREATE_TASK_PATTERNS = (
    re.compile(
        r"^(?:find files containing|search my authorized files for)\s+(.+?)"
        r"\s+and create a task to\s+(.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:find files containing|search my authorized files for)\s+(.+?)"
        r"\s+and create a task titled\s+(.+)$",
        re.IGNORECASE,
    ),
)
_SEARCH_CREATE_NOTE_PATTERNS = (
    re.compile(
        r"^(?:find files containing|search my authorized files for)\s+(.+?)"
        r"\s+and prepare a note titled\s+(.+)$",
        re.IGNORECASE,
    ),
)
_SEARCH_CREATE_SKELETON_RE = re.compile(
    r"^(?:find files containing|search my authorized files for)\s+.+?"
    r"\s+and (?:create a task(?: to| titled)?|prepare a note(?: titled)?)\s*$",
    re.IGNORECASE,
)
_REMINDER_EXPLICIT_RE = re.compile(
    r"^remind me to\s+(.+?)\s+(?:on\s+)?"
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})"
    r"(?:\s*\|\s*|\s+in\s+)"
    r"([A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)*|UTC)$",
    re.IGNORECASE,
)
_REMINDER_DATETIME_NO_ZONE_RE = re.compile(
    r"^remind me to\s+(.+?)\s+(?:on\s+)?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})$",
    re.IGNORECASE,
)
_REMINDER_RE = re.compile(r"^remind me to(?:\s+(.+))?$", re.IGNORECASE)

# Task 249: conversational management of records that already exist. Every
# phrase below only selects an existing local item by its exact normalized
# title; matching and resolution happen later at the service boundary.
_PENDING_LIST_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^(?:show|list)(?: me)? (?:my )?(?:pending|incomplete|open|unfinished)"
            r" (tasks)$",
            re.IGNORECASE,
        ),
        "task",
    ),
    (
        re.compile(
            r"^(?:show|list)(?: me)? (?:my )?(?:pending|incomplete|open|unfinished)"
            r" (notes)$",
            re.IGNORECASE,
        ),
        "note",
    ),
    (
        re.compile(
            r"^(?:show|list)(?: me)? (?:my )?(?:pending|incomplete|open|unfinished)"
            r" (reminders)$",
            re.IGNORECASE,
        ),
        "reminder",
    ),
    (
        re.compile(
            r"^what tasks do i still have to (?:do|finish|complete)$",
            re.IGNORECASE,
        ),
        "task",
    ),
)
_TASK_STATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^mark (?:my |the )?(.+?) task as (?:complete|completed|done)$",
            re.IGNORECASE,
        ),
        "complete",
    ),
    (
        re.compile(
            r"^mark (?:my |the )?task (?:titled|called|named) (.+?)"
            r" as (?:complete|completed|done)$",
            re.IGNORECASE,
        ),
        "complete",
    ),
    (
        re.compile(
            r"^(?:complete|finish) (?:my |the )?(.+?) task$",
            re.IGNORECASE,
        ),
        "complete",
    ),
    (
        re.compile(
            r"^(?:complete|finish) (?:my |the )?task (?:titled|called|named) (.+)$",
            re.IGNORECASE,
        ),
        "complete",
    ),
    (
        re.compile(r"^mark (?:my )?(.+?) task (?:as )?done$", re.IGNORECASE),
        "complete",
    ),
    (
        re.compile(
            r"^reopen (?:my |the )?(.+?) task(?: (?:again|now))?$",
            re.IGNORECASE,
        ),
        "reopen",
    ),
    (
        re.compile(
            r"^reopen (?:my |the )?task (?:titled|called|named) (.+)$",
            re.IGNORECASE,
        ),
        "reopen",
    ),
)
_DELETE_NAMED_KIND_RE = re.compile(
    r"^delete (?:my |the )?(note|task|reminder) (?:titled|called|named) (.+)$",
    re.IGNORECASE,
)
_DELETE_SUFFIX_KIND_RE = re.compile(
    r"^delete (?:my )?(.+?) (note|task|reminder)$",
    re.IGNORECASE,
)
_DELETE_SKELETON_RE = re.compile(
    r"^delete (?:my |the )?(?:note|task|reminder)(?: (?:titled|called|named))?$",
    re.IGNORECASE,
)
_UPDATE_RENAME_RE = re.compile(
    r"^(?:rename|retitle) (?:my |the |a |an )?(note|task)"
    r" (?:titled|called|named) (.+?) to (.+)$",
    re.IGNORECASE,
)
_UPDATE_RENAME_SKELETON_RE = re.compile(
    r"^(?:rename|retitle) (?:my |the |a |an )?(?:note|task)"
    r" (?:titled|called|named) .+$",
    re.IGNORECASE,
)
_UPDATE_CONTENT_RE = re.compile(
    r"^(?:update|set|change|replace) the content of (?:my |the |a |an )?(note|task)"
    r" (?:titled|called|named) (.+?) (?:to|as|with) (.+)$",
    re.IGNORECASE,
)
_UPDATE_CONTENT_SKELETON_RE = re.compile(
    r"^(?:update|set|change|replace) the content of (?:my |the |a |an )?(?:note|task)"
    r" (?:titled|called|named) .+$",
    re.IGNORECASE,
)
_UPDATE_NO_FIELD_RE = re.compile(
    r"^(?:update|edit|change) (?:my |the |a |an )?(?:note|task)"
    r" (?:titled|called|named) (.+)$",
    re.IGNORECASE,
)
_RESCHEDULE_LOCAL_TIME = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?:[+-]\d{2}:?\d{2})?"
_RESCHEDULE_ZONE = r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)*|UTC"
_RESCHEDULE_RELATIVE_DAY = r"today|tomorrow|tonight|this evening|next week"
_RESCHEDULE_SUFFIX = r"(?:(?:\s*\|\s*|\s+in\s+)({zone}))?$"
_RESCHEDULE_EXPLICIT_TITLED_RE = re.compile(
    rf"^(?:move|reschedule) (?:my |the )?reminder (?:titled|called|named) (.+?) to "
    rf"({_RESCHEDULE_LOCAL_TIME}){_RESCHEDULE_SUFFIX.format(zone=_RESCHEDULE_ZONE)}",
    re.IGNORECASE,
)
_RESCHEDULE_EXPLICIT_SUFFIX_RE = re.compile(
    rf"^(?:move|reschedule) (?:my |the )?(.+?) reminder to "
    rf"({_RESCHEDULE_LOCAL_TIME}){_RESCHEDULE_SUFFIX.format(zone=_RESCHEDULE_ZONE)}",
    re.IGNORECASE,
)
_RESCHEDULE_RELATIVE_TITLED_RE = re.compile(
    rf"^(?:move|reschedule) (?:my |the )?reminder (?:titled|called|named) (.+?) to "
    rf"({_RESCHEDULE_RELATIVE_DAY})(?: at ((?:[01]?\d|2[0-3]):[0-5]\d))?"
    rf"(?:(?:\s*\|\s*|\s+in\s+)({_RESCHEDULE_ZONE}))?$",
    re.IGNORECASE,
)
_RESCHEDULE_RELATIVE_SUFFIX_RE = re.compile(
    rf"^(?:move|reschedule) (?:my |the )?(.+?) reminder to "
    rf"({_RESCHEDULE_RELATIVE_DAY})(?: at ((?:[01]?\d|2[0-3]):[0-5]\d))?"
    rf"(?:(?:\s*\|\s*|\s+in\s+)({_RESCHEDULE_ZONE}))?$",
    re.IGNORECASE,
)
_RESCHEDULE_SKELETON_RE = re.compile(
    r"^(?:move|reschedule) (?:my |the )?(?:reminder(?: (?:titled|called|named))?)$",
    re.IGNORECASE,
)
_RESCHEDULE_NAMED_SKELETON_RE = re.compile(
    r"^(?:move|reschedule) (?:my |the )?reminder (?:titled|called|named) (.+)$",
    re.IGNORECASE,
)
_GENERIC_TITLE_WORDS = frozenset(
    {
        "my",
        "the",
        "this",
        "that",
        "it",
        "them",
        "these",
        "those",
        "all",
        "everything",
        "anything",
        "something",
    }
)


def _strip_punctuation(value: str) -> str:
    return _PUNCTUATION_RE.sub("", value.strip()).strip()


def _safe_field(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _strip_punctuation(value.strip().strip("\"'"))
    if not cleaned or _PIPE_OR_CONTROL_RE.search(cleaned):
        return None
    return cleaned


def _matched_help() -> IntentInterpretation:
    return IntentInterpretation(status="matched", intent="help", command="help")


def _matched_workspace(
    command: str,
    *,
    relative_date_hint: RelativeDateHint | None = None,
    relative_clock_time: str | None = None,
) -> IntentInterpretation:
    return IntentInterpretation(
        status="matched",
        intent="workspace",
        command=command,
        relative_date_hint=relative_date_hint,
        relative_clock_time=relative_clock_time,
    )


def _ambiguous(message: str = _AMBIGUOUS_MESSAGE) -> IntentInterpretation:
    return IntentInterpretation(status="ambiguous", message=message)


def _matched_reschedule(
    raw_title: str, raw_due_at: str, raw_timezone: str | None
) -> IntentInterpretation:
    """Map an explicit reschedule phrase to a reminder update command."""
    title = _safe_field(raw_title)
    due_at = _safe_field(raw_due_at)
    timezone = _safe_field(raw_timezone)
    if (
        not title
        or not due_at
        or len(title) > 100
        or len(due_at) > 32
        or (timezone is not None and len(timezone) > 96)
    ):
        return _ambiguous(_UNSAFE_VALUE_MESSAGE)
    if title.casefold() in _GENERIC_TITLE_WORDS:
        return _ambiguous(
            "Please provide the exact title of the reminder to reschedule. "
            "Nothing was executed or changed."
        )
    parts = [title, f"due: {due_at}"]
    if timezone:
        parts.append(f"tz: {timezone}")
    return _matched_workspace("workspace update reminder titled: " + " | ".join(parts))


def _matched_relative_reschedule(
    raw_title: str,
    raw_day_phrase: str,
    clock_time: str | None,
    raw_timezone: str | None,
) -> IntentInterpretation:
    """Map a relative reschedule phrase with its anchor and clock separately."""
    title = _safe_field(raw_title)
    timezone = _safe_field(raw_timezone)
    if not title or len(title) > 100 or (timezone is not None and len(timezone) > 96):
        return _ambiguous(_UNSAFE_VALUE_MESSAGE)
    if title.casefold() in _GENERIC_TITLE_WORDS:
        return _ambiguous(
            "Please provide the exact title of the reminder to reschedule. "
            "Nothing was executed or changed."
        )
    hint = {
        "this evening": "tonight",
        "next week": "next_week",
    }.get(raw_day_phrase, raw_day_phrase)
    command = f"workspace update reminder titled: {title}"
    if timezone:
        command += f" | tz: {timezone}"
    return _matched_workspace(
        command,
        relative_date_hint=hint,
        relative_clock_time=clock_time,
    )


def _multiple_action_conflict(message: str) -> bool:
    lowered = message.casefold()
    if _MULTIPLE_LISTS_RE.fullmatch(lowered):
        return True
    action_markers = (
        r"\bwhat can you do\b",
        r"\bhelp me\b",
        r"\b(?:show|list)\b.*\b(?:notes|tasks|reminders)\b",
        r"\b(?:find|search)\b.*\bfiles?\b",
        r"\b(?:make|create|write|save)\b.*\bnote\b",
        r"\b(?:make|create|add)\b.*\btask\b",
        r"\bremind me to\b",
        r"\b(?:delete|remove)\b.*\b(?:note|task|reminder)\b",
        r"\b(?:complete|reopen|finish|mark)\b.*\btask\b",
        r"\b(?:rename|retitle|update|edit|set|change|replace|clear)\b"
        r".*\b(?:note|task|reminder)\b",
        r"\b(?:move|reschedule|postpone)\b.*\breminder\b",
    )
    matches = sum(bool(re.search(pattern, lowered)) for pattern in action_markers)
    return matches > 1 and bool(re.search(r"\b(?:and|then|also|or)\b", lowered))


def interpret_request(message: str) -> IntentInterpretation:
    """Map one supported phrase to an existing command, without executing it.

    The grammar is deliberately exact. It does not use fuzzy or substring
    matching, and extracted values may not contain command separators/control
    characters. Explicit workspace commands remain byte-for-byte compatible.
    """
    if not isinstance(message, str):
        return IntentInterpretation(status="unsupported")

    raw = message.strip()
    if not raw:
        return IntentInterpretation(status="unsupported")

    # Explicit syntax has priority and is handed to its original parser.
    if re.match(r"^workspace\s+", raw, re.IGNORECASE):
        return _matched_workspace(raw)

    normalized = _strip_punctuation(raw)
    lowered = re.sub(r"\s+", " ", normalized).casefold()
    if lowered in _HELP_PHRASES:
        return _matched_help()

    for patterns, kind in (
        (_SEARCH_CREATE_TASK_PATTERNS, "task"),
        (_SEARCH_CREATE_NOTE_PATTERNS, "note"),
    ):
        for pattern in patterns:
            search_create = pattern.fullmatch(normalized)
            if search_create is None:
                continue
            query = _safe_field(search_create.group(1))
            title = _safe_field(search_create.group(2))
            if not query or not title or len(query) > 200 or len(title) > 100:
                return _ambiguous(_UNSAFE_VALUE_MESSAGE)
            return _matched_workspace(
                "workspace workflow search-and-create-item: "
                + " | ".join((kind, query, title))
            )

    if _SEARCH_CREATE_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "To prepare a note or task from local files, provide an exact search "
            "query and item title. Nothing was executed or changed."
        )

    workflow = _TASK_REMINDER_WORKFLOW_RE.fullmatch(normalized)
    if workflow:
        task_title = _safe_field(workflow.group(1))
        reminder_title = _safe_field(workflow.group(2))
        due_at = _safe_field(workflow.group(3))
        timezone_name = _safe_field(workflow.group(4))
        if (
            not task_title
            or not reminder_title
            or not due_at
            or not timezone_name
            or len(task_title) > 100
            or len(reminder_title) > 100
            or len(timezone_name) > 96
        ):
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        return _matched_workspace(
            "workspace workflow create task-and-reminder: "
            + " | ".join((task_title, reminder_title, due_at, timezone_name))
        )
    if _TASK_REMINDER_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "To prepare a task and reminder together, provide both titles, an "
            "exact local date/time in YYYY-MM-DDTHH:MM format, and an IANA "
            "timezone such as Europe/Amsterdam. Nothing was executed or changed."
        )

    if _multiple_action_conflict(normalized):
        if re.search(
            r"\b(?:find|search)\b.*\bfiles?\b", normalized, re.I
        ) and re.search(r"\b(?:task|note)\b", normalized, re.I):
            return _ambiguous(
                "I can search your authorized files, but need the exact task or "
                "note title before preparing a saved item. Tell me the title and "
                "the search terms. Nothing was executed or changed."
            )
        return _ambiguous()

    for pattern, kind in _LIST_PATTERNS:
        if pattern.fullmatch(normalized):
            label = {"note": "notes", "task": "tasks", "reminder": "reminders"}.get(
                kind, "all"
            )
            return _matched_workspace(
                "workspace list " + ("all" if kind == "all" else label)
            )

    for pattern, kind in _PENDING_LIST_PATTERNS:
        if pattern.fullmatch(normalized):
            label = {"note": "notes", "task": "tasks", "reminder": "reminders"}[kind]
            return _matched_workspace("workspace list pending " + label)

    for pattern in _SEARCH_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match:
            query = _safe_field(match.group(1))
            if query is None:
                return _matched_workspace("workspace search files:")
            return _matched_workspace("workspace search files: " + query)

    for pattern, action in _TASK_STATE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match:
            title = _safe_field(match.group(1))
            if title is None or len(title) > 100:
                return _ambiguous(_UNSAFE_VALUE_MESSAGE)
            if title.casefold() in _GENERIC_TITLE_WORDS:
                return _ambiguous(
                    "Please provide the exact title of the task. Nothing was "
                    "executed or changed."
                )
            verb = "complete" if action == "complete" else "reopen"
            return _matched_workspace(f"workspace {verb} task titled: {title}")

    if _DELETE_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "Tell me the exact title of the note, task, or reminder to delete. "
            "For example: delete the note titled Ward revision. Nothing was "
            "executed or changed."
        )
    match = _DELETE_NAMED_KIND_RE.fullmatch(normalized)
    if match:
        kind = match.group(1).casefold()
        title = _safe_field(match.group(2))
        if title is None or len(title) > 200:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        if title.casefold() in _GENERIC_TITLE_WORDS:
            return _ambiguous(
                f"Please provide the exact title of the {kind}. Nothing was "
                "executed or changed."
            )
        return _matched_workspace(f"workspace delete {kind} titled: {title}")
    match = _DELETE_SUFFIX_KIND_RE.fullmatch(normalized)
    if match:
        kind = match.group(2).casefold()
        title = _safe_field(match.group(1))
        if title is None or len(title) > 200:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        if title.casefold() in _GENERIC_TITLE_WORDS:
            return _ambiguous(
                f"Please provide the exact title of the {kind}. Nothing was "
                "executed or changed."
            )
        return _matched_workspace(f"workspace delete {kind} titled: {title}")

    match = _UPDATE_RENAME_RE.fullmatch(normalized)
    if match:
        kind = match.group(1).casefold()
        selector = _safe_field(match.group(2))
        new_title = _safe_field(match.group(3))
        if not selector or not new_title or len(selector) > 200 or len(new_title) > 200:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        if selector.casefold() in _GENERIC_TITLE_WORDS:
            return _ambiguous(
                "Please provide the exact current title of the item to rename. "
                "Nothing was executed or changed."
            )
        return _matched_workspace(
            f"workspace update {kind} titled: {selector} | title: {new_title}"
        )
    if _UPDATE_RENAME_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "Tell me the exact new title. For example: rename the note titled "
            "A to B. Nothing was executed or changed."
        )
    match = _UPDATE_CONTENT_RE.fullmatch(normalized)
    if match:
        kind = match.group(1).casefold()
        selector = _safe_field(match.group(2))
        content = _safe_field(match.group(3))
        if not selector or not content or len(selector) > 200 or len(content) > 512:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        if selector.casefold() in _GENERIC_TITLE_WORDS:
            return _ambiguous(
                "Please provide the exact current title of the item to update. "
                "Nothing was executed or changed."
            )
        return _matched_workspace(
            f"workspace update {kind} titled: {selector} | content: {content}"
        )
    if _UPDATE_CONTENT_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "Tell me the exact new content. For example: update the content of "
            "my note titled A to B. Nothing was invented, executed, or changed."
        )
    if _UPDATE_NO_FIELD_RE.fullmatch(normalized):
        return _ambiguous(
            "Tell me exactly what to change: the title with 'title: ...' or the "
            "content with 'content: ...'. Nothing was executed or changed."
        )

    match = _RESCHEDULE_EXPLICIT_TITLED_RE.fullmatch(normalized)
    if match:
        return _matched_reschedule(match.group(1), match.group(2), match.group(3))
    match = _RESCHEDULE_EXPLICIT_SUFFIX_RE.fullmatch(normalized)
    if match:
        return _matched_reschedule(match.group(1), match.group(2), match.group(3))
    match = _RESCHEDULE_RELATIVE_TITLED_RE.fullmatch(normalized)
    if match:
        return _matched_relative_reschedule(
            match.group(1), match.group(2), match.group(3), match.group(4)
        )
    match = _RESCHEDULE_RELATIVE_SUFFIX_RE.fullmatch(normalized)
    if match:
        return _matched_relative_reschedule(
            match.group(1), match.group(2), match.group(3), match.group(4)
        )
    if _RESCHEDULE_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "Tell me which reminder and exactly when it should be due. Nothing "
            "was executed or changed."
        )
    if _RESCHEDULE_NAMED_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "Tell me exactly when the reminder should be due: an exact local "
            "date/time such as 2026-11-12T14:00 plus an IANA timezone, or a "
            "relative date such as tomorrow. Nothing was executed or changed."
        )

    if lowered in {
        "save this as a note",
        "save as a note",
        "make a note",
        "create a note",
    }:
        return _matched_workspace("workspace add note:")

    for pattern in _NOTE_TITLE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match:
            title = _safe_field(match.group(1))
            if match.group(1) is not None and title is None:
                return _ambiguous(_UNSAFE_VALUE_MESSAGE)
            return _matched_workspace(
                "workspace add note:" + (f" {title}" if title else "")
            )

    if _NOTE_TITLE_SKELETON_RE.fullmatch(normalized):
        return _ambiguous(
            "Please provide a title for the note. Nothing was executed or changed."
        )

    match = _TASK_TITLE_RE.fullmatch(normalized)
    if match:
        title = _safe_field(match.group(1))
        if match.group(1) is not None and title is None:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        return _matched_workspace(
            "workspace add task:" + (f" {title}" if title else "")
        )

    match = _REMINDER_EXPLICIT_RE.fullmatch(normalized)
    if match:
        title = _safe_field(match.group(1))
        due_at = _safe_field(match.group(2))
        timezone = _safe_field(match.group(3))
        if not title or not due_at or not timezone:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        return _matched_workspace(
            f"workspace add reminder: {title} | {due_at} | {timezone}"
        )

    match = _REMINDER_DATETIME_NO_ZONE_RE.fullmatch(normalized)
    if match:
        title = _safe_field(match.group(1))
        due_at = _safe_field(match.group(2))
        if not title or not due_at:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        return _matched_workspace(f"workspace add reminder: {title} | {due_at}")

    relative_match = _REMINDER_RELATIVE_RE.fullmatch(normalized)
    if relative_match:
        title = _safe_field(relative_match.group(1))
        relative_phrase = relative_match.group(2).casefold()
        clock_time = relative_match.group(3)
        if not title:
            return _ambiguous("Please specify what the reminder is about.")
        relative_hint = {
            "this evening": "tonight",
            "next week": "next_week",
        }.get(relative_phrase, relative_phrase)
        return _matched_workspace(
            "workspace add reminder: " + title,
            relative_date_hint=relative_hint,
            relative_clock_time=clock_time,
        )

    match = _REMINDER_RE.fullmatch(normalized)
    if match:
        title = _safe_field(match.group(1))
        if match.group(1) is not None and title is None:
            return _ambiguous(_UNSAFE_VALUE_MESSAGE)
        if title and _CLOCK_END_RE.search(title):
            return _ambiguous(
                "I received a reminder clock time but cannot safely infer its "
                "calendar date or timezone. Provide the exact local date/time "
                "in YYYY-MM-DDTHH:MM format and an IANA timezone. Nothing was "
                "executed or changed."
            )
        return _matched_workspace(
            "workspace add reminder:" + (f" {title}" if title else "")
        )

    return IntentInterpretation(status="unsupported")


__all__ = ["IntentInterpretation", "interpret_request"]

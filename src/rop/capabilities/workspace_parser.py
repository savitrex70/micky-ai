"""Exact, deterministic command grammar for local workspace actions."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rop.capabilities.parser import CapabilityParseError
from rop.schemas.authorization import ProposedOperation

_COMMAND_PREFIX = re.compile(
    r"^\s*workspace\s+(list|search|add|delete|complete|reopen|update|workflow)\b",
    re.IGNORECASE,
)
_LIST_RE = re.compile(
    r"^\s*workspace\s+list\s+(notes|tasks|reminders|all)\s*$",
    re.IGNORECASE,
)
_SEARCH_RE = re.compile(
    r"^\s*workspace\s+search\s+files\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ADD_ITEM_RE = re.compile(
    r"^\s*workspace\s+add\s+(note|task)\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ADD_REMINDER_RE = re.compile(
    r"^\s*workspace\s+add\s+reminder\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_DELETE_RE = re.compile(
    r"^\s*workspace\s+delete\s+(note|task|reminder)\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_TASK_STATE_RE = re.compile(
    r"^\s*workspace\s+(complete|reopen)\s+task\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_UPDATE_RE = re.compile(
    r"^\s*workspace\s+update\s+(note|task|reminder)\s+([^:\s]+)\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_WORKFLOW_CREATE_RE = re.compile(
    r"^\s*workspace\s+workflow\s+create\s+task-and-reminder\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_WORKFLOW_SEARCH_CREATE_RE = re.compile(
    r"^\s*workspace\s+workflow\s+search-and-create-item\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _parts(value: str) -> list[str]:
    return [part.strip() for part in value.split("|")]


def _operation(
    operation_id: str,
    *,
    target: str | None = None,
    parameters: dict[str, str] | None = None,
) -> ProposedOperation:
    return ProposedOperation(
        operation_id=operation_id,
        target=target,
        parameters=dict(parameters or {}),
    )


def _uuid_target(value: str, missing_message: str) -> str:
    candidate = value.strip()
    try:
        return str(UUID(candidate))
    except (ValueError, TypeError, AttributeError):
        raise CapabilityParseError(
            "target",
            missing_message,
            partial_operation=None,
        ) from None


class _ReminderTimeError(ValueError):
    """Safe, field-specific reminder time validation error."""

    def __init__(self, field_name: str, question: str) -> None:
        self.field_name = field_name
        self.question = question
        super().__init__("reminder time needs clarification")


def _normalize_reminder_due(due_at: str, timezone_name: str) -> str:
    """Validate local time against its IANA zone and return canonical UTC ISO."""
    try:
        local = datetime.fromisoformat(due_at)
    except (TypeError, ValueError):
        raise _ReminderTimeError(
            "due_at",
            "Enter a valid local date and time, for example "
            "2026-10-24T09:30 | Europe/Bucharest.",
        ) from None
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise _ReminderTimeError(
            "timezone",
            "That timezone was not recognized. Enter an IANA timezone such as "
            "Europe/Bucharest.",
        ) from None

    if local.tzinfo is not None:
        zoned = local.astimezone(zone)
        if (
            zoned.replace(tzinfo=None) != local.replace(tzinfo=None)
            or zoned.utcoffset() != local.utcoffset()
        ):
            raise _ReminderTimeError(
                "due_at",
                "That UTC offset does not match the selected timezone at this "
                "local time. Enter a valid local time and matching offset.",
            )
        return local.astimezone(UTC).isoformat()

    first = local.replace(tzinfo=zone, fold=0)
    second = local.replace(tzinfo=zone, fold=1)
    first_round_trip = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    second_round_trip = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    first_valid = first_round_trip == local
    second_valid = second_round_trip == local
    if not first_valid and not second_valid:
        raise _ReminderTimeError(
            "due_at",
            "That local time does not exist because of a daylight-saving-time "
            "change. Choose a valid local time and include its UTC offset.",
        )
    if first_valid and second_valid and first.utcoffset() != second.utcoffset():
        raise _ReminderTimeError(
            "due_at",
            "That local time occurs twice because of a daylight-saving-time "
            "change. Repeat it with an explicit UTC offset, for example "
            "2026-10-25T03:30+03:00 | Europe/Bucharest.",
        )
    chosen = first if first_valid else second
    return chosen.astimezone(UTC).isoformat()


def _validate_reminder_operation(operation: ProposedOperation) -> ProposedOperation:
    """Resolve a reminder's named local timezone before confirmation."""
    if operation.operation_id not in {
        "workspace_reminder_create",
        "workspace_reminder_update",
    }:
        return operation
    parameters = dict(operation.parameters)
    due_at = parameters.get("due_at")
    timezone_name = parameters.get("timezone")
    if not due_at or not timezone_name:
        return operation
    try:
        parameters["due_at"] = _normalize_reminder_due(due_at, timezone_name)
    except _ReminderTimeError as error:
        raise CapabilityParseError(
            error.field_name,
            error.question,
            partial_operation=operation,
            missing_fields=[error.field_name],
        ) from None
    return _operation(
        operation.operation_id,
        target=operation.target,
        parameters=parameters,
    )


class WorkspaceCommandParser:
    """Recognize commands only when they follow the explicit workspace grammar.

    Supported examples:
      workspace list notes
      workspace search files: hypertension
      workspace add note: Ward revision | read chapter 3
      workspace add task: Submit the assignment
      workspace add reminder: Call the clinic | 2026-10-24T09:30 | Europe/Bucharest
      workspace delete note <uuid>
      workspace complete task <uuid>
      workspace reopen task <uuid>
      workspace update note <uuid>: New title | New details
    """

    def matches(self, message: str) -> bool:
        return bool(_COMMAND_PREFIX.match(message))

    def parse(
        self,
        message: str,
        *,
        pending_context: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ProposedOperation:
        if pending_context is not None:
            return self._continue_clarification(message, pending_context)

        search_create = _WORKFLOW_SEARCH_CREATE_RE.fullmatch(message)
        if search_create:
            parts = _parts(search_create.group(1))
            if len(parts) != 3 or any(not part for part in parts):
                raise CapabilityParseError(
                    "workflow",
                    "Provide item type, search terms, and an item title "
                    "separated by |.",
                )
            kind, query, title = parts
            if (
                kind not in {"note", "task"}
                or len(query) > 200
                or len(title) > 100
                or any(not part.isprintable() for part in parts)
            ):
                raise CapabilityParseError(
                    "workflow",
                    "The search-and-create workflow contains an unsupported value.",
                )
            payload = json.dumps(
                {"kind": kind, "query": query, "title": title},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            return _operation(
                "workspace_workflow_search_and_create_item",
                parameters={
                    "idempotency_key": idempotency_key or "",
                    "workflow_payload": payload,
                },
            )

        workflow = _WORKFLOW_CREATE_RE.fullmatch(message)
        if workflow:
            parts = _parts(workflow.group(1))
            if len(parts) != 4 or any(not part for part in parts):
                raise CapabilityParseError(
                    "workflow",
                    "Provide a task title, reminder title, exact local date/time, "
                    "and IANA timezone separated by |.",
                )
            task_title, reminder_title, due_at, timezone_name = parts
            if (
                len(task_title) > 100
                or len(reminder_title) > 100
                or len(due_at) > 32
                or len(timezone_name) > 96
                or any(not part.isprintable() for part in parts)
            ):
                raise CapabilityParseError(
                    "workflow",
                    "The workflow contains a value outside the supported limits.",
                )
            try:
                normalized_due_at = _normalize_reminder_due(due_at, timezone_name)
            except _ReminderTimeError as error:
                raise CapabilityParseError(
                    error.field_name,
                    error.question,
                ) from None
            payload = json.dumps(
                {
                    "task_title": task_title,
                    "reminder_title": reminder_title,
                    "due_at": normalized_due_at,
                    "due_at_local": due_at,
                    "timezone": timezone_name,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            return _operation(
                "workspace_workflow_create_task_and_reminder",
                parameters={
                    "idempotency_key": idempotency_key or "",
                    "workflow_payload": payload,
                },
            )

        if _LIST_RE.fullmatch(message):
            match = _LIST_RE.fullmatch(message)
            assert match is not None
            requested = match.group(1).casefold()
            kind_by_name = {
                "all": None,
                "notes": "note",
                "tasks": "task",
                "reminders": "reminder",
            }
            kind = kind_by_name[requested]
            parameters = {} if kind is None else {"kind": kind}
            return _operation("workspace_list_items", parameters=parameters)

        search = _SEARCH_RE.fullmatch(message)
        if search:
            query = search.group(1).strip()
            if not query:
                raise CapabilityParseError(
                    "query",
                    "What words should I search for in your authorized local files?",
                    partial_operation=_operation("workspace_search_files"),
                )
            return _operation(
                "workspace_search_files", parameters={"query": query[:200]}
            )

        add_item = _ADD_ITEM_RE.fullmatch(message)
        if add_item:
            kind = add_item.group(1).casefold()
            parts = _parts(add_item.group(2))
            title = parts[0] if parts else ""
            params = {"idempotency_key": idempotency_key or ""}
            if len(parts) > 1 and parts[1]:
                params["content"] = parts[1][:512]
            operation = _operation(f"workspace_{kind}_create", parameters=params)
            if not title:
                raise CapabilityParseError(
                    "title",
                    f"What title should I use for this {kind}?",
                    partial_operation=operation,
                )
            params["title"] = title[:200]
            return _operation(f"workspace_{kind}_create", parameters=params)

        add_reminder = _ADD_REMINDER_RE.fullmatch(message)
        if add_reminder:
            parts = _parts(add_reminder.group(1))
            title = parts[0] if parts else ""
            params = {"idempotency_key": idempotency_key or ""}
            if not title:
                raise CapabilityParseError(
                    "title",
                    "What should the reminder be called?",
                    partial_operation=_operation(
                        "workspace_reminder_create", parameters=params
                    ),
                )
            params["title"] = title[:200]
            if len(parts) > 1 and parts[1]:
                params["due_at"] = parts[1][:32]
            if len(parts) > 2 and parts[2]:
                params["timezone"] = parts[2][:128]
            missing = [name for name in ("due_at", "timezone") if name not in params]
            if missing:
                raise CapabilityParseError(
                    missing[0],
                    "When is this reminder due? Reply with local time and timezone as "
                    "YYYY-MM-DDTHH:MM | Europe/Bucharest.",
                    partial_operation=_operation(
                        "workspace_reminder_create", parameters=params
                    ),
                    missing_fields=missing,
                )
            return _validate_reminder_operation(
                _operation("workspace_reminder_create", parameters=params)
            )

        delete_match = _DELETE_RE.fullmatch(message)
        if delete_match:
            kind = delete_match.group(1).casefold()
            try:
                target = _uuid_target(
                    delete_match.group(2),
                    f"Which {kind} should I delete? Reply with its item ID.",
                )
            except CapabilityParseError:
                raise CapabilityParseError(
                    "target",
                    f"Which {kind} should I delete? Reply with its item ID.",
                    partial_operation=_operation(
                        f"workspace_{kind}_delete",
                        parameters={"idempotency_key": idempotency_key or ""},
                    ),
                ) from None
            return _operation(
                f"workspace_{kind}_delete",
                target=target,
                parameters={"idempotency_key": idempotency_key or ""},
            )

        state_match = _TASK_STATE_RE.fullmatch(message)
        if state_match:
            action, raw_target = state_match.groups()
            verb = action.casefold()
            try:
                target = _uuid_target(
                    raw_target,
                    "Which task should I change? Reply with its item ID.",
                )
            except CapabilityParseError:
                raise CapabilityParseError(
                    "target",
                    "Which task should I change? Reply with its item ID.",
                    partial_operation=_operation(
                        "workspace_task_complete",
                        parameters={
                            "idempotency_key": idempotency_key or "",
                            "completed": "true" if verb == "complete" else "false",
                        },
                    ),
                ) from None
            return _operation(
                "workspace_task_complete",
                target=target,
                parameters={
                    "idempotency_key": idempotency_key or "",
                    "completed": "true" if verb == "complete" else "false",
                },
            )

        update_match = _UPDATE_RE.fullmatch(message)
        if update_match:
            kind, raw_target, raw_values = update_match.groups()
            kind = kind.casefold()
            parts = _parts(raw_values)
            title = parts[0] if parts else ""
            params = {"idempotency_key": idempotency_key or ""}
            if title:
                params["title"] = title[:200]
            if len(parts) > 1 and parts[1]:
                params["content"] = parts[1][:512]
            if kind == "reminder":
                if len(parts) > 2 and parts[2]:
                    params["due_at"] = parts[2][:64]
                if len(parts) > 3 and parts[3]:
                    params["timezone"] = parts[3][:128]

            time_missing = (
                [name for name in ("due_at", "timezone") if not params.get(name)]
                if kind == "reminder"
                else []
            )
            try:
                target = _uuid_target(
                    raw_target,
                    "Which item should I update? Reply with its item ID.",
                )
            except CapabilityParseError:
                missing_fields = ["target"]
                if not title:
                    missing_fields.append("title")
                missing_fields.extend(time_missing)
                raise CapabilityParseError(
                    "target",
                    "Which item should I update? Reply with its item ID.",
                    partial_operation=_operation(
                        f"workspace_{kind}_update", parameters=params
                    ),
                    missing_fields=missing_fields,
                ) from None

            if not title:
                missing_fields = ["title", *time_missing]
                raise CapabilityParseError(
                    "title",
                    "What should the updated title be?",
                    partial_operation=_operation(
                        f"workspace_{kind}_update",
                        target=target,
                        parameters=params,
                    ),
                    missing_fields=missing_fields,
                )
            if time_missing:
                raise CapabilityParseError(
                    time_missing[0],
                    "When is the updated reminder due? Reply with local time and "
                    "timezone as YYYY-MM-DDTHH:MM | Europe/Bucharest.",
                    partial_operation=_operation(
                        "workspace_reminder_update",
                        target=target,
                        parameters=params,
                    ),
                    missing_fields=time_missing,
                )
            operation = _operation(
                f"workspace_{kind}_update", target=target, parameters=params
            )
            return _validate_reminder_operation(operation)

        raise CapabilityParseError(
            "command",
            "Use an explicit workspace command such as 'workspace list notes' "
            "or 'workspace add note: title'.",
        )

    def _continue_clarification(
        self, answer: str, context: Mapping[str, Any]
    ) -> ProposedOperation:
        raw_operation = context.get("partial_operation")
        missing = context.get("missing_fields")
        if (
            not isinstance(raw_operation, Mapping)
            or not isinstance(missing, list)
            or not missing
        ):
            raise CapabilityParseError(
                "clarification",
                "That clarification is no longer available. Start the command again.",
            )
        try:
            operation = ProposedOperation.model_validate(raw_operation)
        except Exception:
            raise CapabilityParseError(
                "clarification",
                "That clarification is no longer available. Start the command again.",
            ) from None
        fields = list(missing)
        parts = _parts(answer)
        parameters = dict(operation.parameters)
        target = operation.target
        first = fields[0]
        if first in {"title", "query"}:
            value = answer.strip()
            if not value:
                raise CapabilityParseError(
                    first,
                    "Please enter a non-empty title.",
                    operation,
                    fields,
                )
            parameters[first] = value[:200]
        elif first == "target":
            try:
                target = _uuid_target(answer, "Enter the item ID shown for the item.")
            except CapabilityParseError:
                raise CapabilityParseError(
                    "target", "Enter the item ID shown for the item.", operation, fields
                ) from None
        elif first in {"due_at", "timezone"}:
            # Ask for both values together only when both are missing. A
            # single-field correction changes only that field.
            if set(fields) == {"due_at", "timezone"}:
                due = parts[0] if parts else ""
                timezone = parts[1] if len(parts) > 1 else ""
                if due:
                    parameters["due_at"] = due[:64]
                if timezone:
                    parameters["timezone"] = timezone[:128]
            elif first == "due_at":
                if answer.strip():
                    parameters["due_at"] = answer.strip()[:64]
            elif answer.strip():
                parameters["timezone"] = answer.strip()[:128]
            still_missing = [name for name in fields if not parameters.get(name)]
            if still_missing:
                raise CapabilityParseError(
                    still_missing[0],
                    "Reply with the missing local time or IANA timezone.",
                    _operation(
                        operation.operation_id,
                        target=target,
                        parameters=parameters,
                    ),
                    still_missing,
                )
            fields = []
        else:
            raise CapabilityParseError(
                "clarification",
                "That clarification is no longer supported. Start again.",
            )
        fields = [name for name in fields if name != first]
        if fields:
            raise CapabilityParseError(
                fields[0],
                "Please provide the remaining information: " + ", ".join(fields),
                _operation(
                    operation.operation_id,
                    target=target,
                    parameters=parameters,
                ),
                fields,
            )
        completed = _operation(
            operation.operation_id, target=target, parameters=parameters
        )
        return _validate_reminder_operation(completed)


__all__ = ["WorkspaceCommandParser"]

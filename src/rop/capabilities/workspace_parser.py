"""Exact, deterministic command grammar for local workspace actions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.capabilities.parser import CapabilityParseError
from rop.schemas.authorization import ProposedOperation

_COMMAND_PREFIX = re.compile(
    r"^\s*workspace\s+(list|search|add|delete|complete|reopen|update)\b",
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
        if _LIST_RE.fullmatch(message):
            match = _LIST_RE.fullmatch(message)
            assert match is not None
            requested = match.group(1).casefold()
            kind = None if requested == "all" else requested[:-1] if requested in {"notes", "tasks", "reminders"} else requested
            parameters = {} if kind is None else {"kind": kind.rstrip("s")}
            if requested == "reminders":
                parameters = {"kind": "reminder"}
            if requested == "notes":
                parameters = {"kind": "note"}
            if requested == "tasks":
                parameters = {"kind": "task"}
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
            return _operation("workspace_search_files", parameters={"query": query[:200]})

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
                    partial_operation=_operation("workspace_reminder_create", parameters=params),
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
                    "When is this reminder due? Reply with local time and timezone as YYYY-MM-DDTHH:MM | Europe/Bucharest.",
                    partial_operation=_operation("workspace_reminder_create", parameters=params),
                    missing_fields=missing,
                )
            return _operation("workspace_reminder_create", parameters=params)

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
                target = _uuid_target(raw_target, "Which task should I change? Reply with its item ID.")
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
            try:
                target = _uuid_target(raw_target, "Which item should I update? Reply with its item ID.")
            except CapabilityParseError:
                raise CapabilityParseError(
                    "target",
                    "Which item should I update? Reply with its item ID.",
                    partial_operation=_operation(
                        f"workspace_{kind}_update",
                        parameters={"idempotency_key": idempotency_key or ""},
                    ),
                ) from None
            parts = _parts(raw_values)
            title = parts[0] if parts else ""
            if not title:
                raise CapabilityParseError(
                    "title",
                    "What should the updated title be?",
                    partial_operation=_operation(
                        f"workspace_{kind}_update",
                        target=target,
                        parameters={"idempotency_key": idempotency_key or ""},
                    ),
                )
            params = {"idempotency_key": idempotency_key or "", "title": title[:200]}
            if len(parts) > 1 and parts[1]:
                params["content"] = parts[1][:512]
            if kind == "reminder":
                if len(parts) > 2 and parts[2]:
                    params["due_at"] = parts[2][:32]
                if len(parts) > 3 and parts[3]:
                    params["timezone"] = parts[3][:128]
                missing = [n for n in ("due_at", "timezone") if n not in params]
                if missing:
                    raise CapabilityParseError(
                        missing[0],
                        "When is the updated reminder due? Reply with local time and timezone as YYYY-MM-DDTHH:MM | Europe/Bucharest.",
                        partial_operation=_operation(
                            "workspace_reminder_update", target=target, parameters=params
                        ),
                        missing_fields=missing,
                    )
            return _operation(f"workspace_{kind}_update", target=target, parameters=params)

        raise CapabilityParseError(
            "command",
            "Use an explicit workspace command such as 'workspace list notes' or 'workspace add note: title'.",
        )

    def _continue_clarification(
        self, answer: str, context: Mapping[str, Any]
    ) -> ProposedOperation:
        raw_operation = context.get("partial_operation")
        missing = context.get("missing_fields")
        if not isinstance(raw_operation, Mapping) or not isinstance(missing, list) or not missing:
            raise CapabilityParseError(
                "clarification", "That clarification is no longer available. Start the command again."
            )
        try:
            operation = ProposedOperation.model_validate(raw_operation)
        except Exception:
            raise CapabilityParseError(
                "clarification", "That clarification is no longer available. Start the command again."
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
            parameters["title"] = value[:200]
        elif first == "target":
            try:
                target = _uuid_target(answer, "Enter the item ID shown for the item.")
            except CapabilityParseError:
                raise CapabilityParseError(
                    "target", "Enter the item ID shown for the item.", operation, fields
                ) from None
        elif first in {"due_at", "timezone"}:
            # Time and timezone are collected together to avoid creating
            # a reminder with an arbitrary/implicit timezone.
            due = parts[0] if parts else ""
            timezone = parts[1] if len(parts) > 1 else ""
            if due:
                parameters["due_at"] = due[:32]
            if timezone:
                parameters["timezone"] = timezone[:128]
            still_missing = [n for n in ("due_at", "timezone") if n not in parameters]
            if still_missing:
                raise CapabilityParseError(
                    still_missing[0],
                    "Reply with local time and timezone as YYYY-MM-DDTHH:MM | Europe/Bucharest.",
                    operation,
                    still_missing,
                )
            fields = []
        else:
            raise CapabilityParseError(
                "clarification", "That clarification is no longer supported. Start again."
            )
        fields = [name for name in fields if name != first]
        if fields:
            raise CapabilityParseError(
                fields[0],
                "Please provide the remaining information: " + ", ".join(fields),
                _operation(operation.operation_id, target=target, parameters=parameters),
                fields,
            )
        return _operation(operation.operation_id, target=target, parameters=parameters)


__all__ = ["WorkspaceCommandParser"]

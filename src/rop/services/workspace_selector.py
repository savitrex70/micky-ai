"""Exact-title target resolution for conversational workspace commands.

Natural-language instructions such as "Delete my note titled Respiratory
revision" must resolve to the existing canonical UUID of one specific
local record before any authorization, confirmation, or execution
happens. This module is that resolution boundary. It is strictly
read-only: it runs queries, it never mutates records, and it never
authorizes or executes an operation.

Resolution rules:

* The intended item type (note, task, or reminder) is always required;
  every lookup is scoped to that exactly one kind.
* Matching is exact on the normalized title: whitespace runs are
  collapsed, surrounding whitespace is removed, and the result is
  compared case-insensitively. Similar or partially matching titles are
  never accepted.
* Zero matches, exactly one match, and more than one match are distinct
  outcomes. An ambiguous title is never resolved silently; the caller
  asks the user to disambiguate by item ID.
* A resolved operation is bound to the matched row's identity and to the
  row's current version, so the executor can fail safely when the item
  was deleted or changed between resolution and confirmation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models.assistant_item import AssistantItem
from rop.schemas.authorization import ProposedOperation

ItemKind = Literal["note", "task", "reminder"]

_WHITESPACE_RUN = re.compile(r"\s+")

_SELECTOR_LOOKUP_LIMIT = 500
"""Bounding cap for one kind-scoped selector lookup."""

_SELECTOR_VERSION_PARAMETER = "target_updated_at"
"""Parameter carrying the resolved row's current version at binding time."""


def normalize_selector_title(value: str) -> str:
    """Return a normalized title that is stable across case and spacing."""
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RUN.sub(" ", value).strip().casefold()


def item_version_token(item: AssistantItem) -> str:
    """Return a comparable staleness witness for one item row.

    Both the resolution boundary and the executor normalize the row's
    ``updated_at`` clock the same way, so an item changed or deleted after
    a target was resolved produces a different token at execution time and
    the operation fails instead of acting on a stale proposal.
    """
    value = item.updated_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class SelectorItem:
    """The identity values of one matching local record."""

    id: UUID
    kind: str
    title: str
    completed: bool


@dataclass(frozen=True)
class SelectorResolution:
    """The outcome of one exact-title lookup."""

    kind: ItemKind
    title: str
    normalized_title: str
    status: Literal["not_found", "unique", "ambiguous"]
    matches: tuple[SelectorItem, ...]


def select_item(item: AssistantItem) -> SelectorItem:
    """Project a record into its identity values without its content."""
    return SelectorItem(
        id=item.id,
        kind=item.kind,
        title=item.title,
        completed=bool(item.completed),
    )


def describe_item(item: SelectorItem) -> str:
    """Return the same identity line the workspace listing shows."""
    state = "completed" if item.completed else "open"
    return f"{item.title} [{item.kind}, {state}, ID: {item.id}]"


def resolve_selector_title(
    session: Session,
    *,
    kind: ItemKind,
    title: str,
) -> SelectorResolution:
    """Look up records of exactly one kind by exact normalized title.

    The lookup never mutates state. Only the newest bounded window of that
    kind is inspected: for a personal workspace this is ample, and titles
    matching a row outside the window fail closed rather than resolving to
    an unexpected record.
    """
    if kind not in {"note", "task", "reminder"}:
        raise ValueError("selector resolution requires one specific item kind")
    raw = title if isinstance(title, str) else ""
    normalized = normalize_selector_title(raw)
    if not normalized:
        raise ValueError("selector resolution requires a non-empty title")
    status_value: Literal["not_found", "unique", "ambiguous"]
    records = list(
        session.scalars(
            select(AssistantItem)
            .where(AssistantItem.kind == kind)
            .order_by(AssistantItem.updated_at.desc(), AssistantItem.id.desc())
            .limit(_SELECTOR_LOOKUP_LIMIT)
        ).all()
    )
    matches = tuple(
        select_item(record)
        for record in records
        if normalize_selector_title(record.title) == normalized
    )
    if not matches:
        status_value = "not_found"
    elif len(matches) == 1:
        status_value = "unique"
    else:
        status_value = "ambiguous"
    return SelectorResolution(
        kind=kind,
        title=raw.strip(),
        normalized_title=normalized,
        status=status_value,
        matches=matches,
    )


def bind_resolved_target(
    operation: ProposedOperation,
    item: AssistantItem,
) -> ProposedOperation:
    """Turn a selector operation into a canonical UUID-targeted operation.

    The selector is removed once identity is established, and the row's
    current version is recorded so execution can reject a deleted or
    changed target instead of acting on a stale proposal.
    """
    parameters = dict(operation.parameters)
    parameters.pop("selector_title", None)
    parameters[_SELECTOR_VERSION_PARAMETER] = item_version_token(item)
    return operation.model_copy(
        update={"target": str(item.id), "parameters": parameters}
    )


def verify_disambiguated_target(
    session: Session,
    operation: ProposedOperation,
    *,
    kind: ItemKind,
) -> SelectorItem | None:
    """Return the exact record the user disambiguated to, if it still matches.

    Used after the user answered a disambiguation question with an item
    ID. The record must exist, carry the expected kind, and still hold the
    exact selector title; any drift returns ``None`` so the caller can
    fail closed without changing anything.
    """
    selector_title = operation.parameters.get("selector_title")
    if not operation.target or not selector_title:
        return None
    try:
        item_id = UUID(operation.target)
    except (TypeError, ValueError):
        return None
    item = session.get(AssistantItem, item_id)
    if item is None or item.kind != kind:
        return None
    if normalize_selector_title(item.title) != normalize_selector_title(selector_title):
        return None
    return select_item(item)


__all__ = [
    "SelectorItem",
    "SelectorResolution",
    "ItemKind",
    "bind_resolved_target",
    "describe_item",
    "item_version_token",
    "normalize_selector_title",
    "resolve_selector_title",
    "select_item",
    "verify_disambiguated_target",
]

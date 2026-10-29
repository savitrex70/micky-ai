"""Read-only operations for the deterministic personal workspace."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from rop import database as database_module
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.authorization import ProposedOperation

if TYPE_CHECKING:
    from rop.api.retrieval import RetrievalOutcome

_REPOSITORY = AssistantWorkspaceRepository()


def search_authorized_local_files(
    query: str,
    *,
    db_session: Session | None = None,
) -> RetrievalOutcome:
    """Search identity-bound roots through the bounded secure reader."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("search query missing or outside the supported limit")

    # Lazy import avoids adding a retrieval dependency to application startup.
    from rop.api import retrieval as retrieval_api

    owns_session = db_session is None
    session = db_session or database_module.SessionLocal()
    try:
        roots = _REPOSITORY.list_roots(
            session, limit=retrieval_api._MAX_ROOTS_PER_REQUEST
        )
        authorized_total = _REPOSITORY.count_roots(session)
        root_specs = [(root.path, root.root_identity) for root in roots]
    finally:
        if owns_session:
            session.close()

    return retrieval_api.search_roots_detailed(
        root_specs, query.strip(), 10, authorized_total=authorized_total
    )


def normalize_match_preview(match: object) -> tuple[str, str]:
    """Return bounded, display-safe source details used by preview and execution."""
    source_path = str(match.path)
    snippet = " ".join(str(match.snippet).split())[:120]
    if (
        not source_path
        or len(source_path) > 280
        or any(ord(char) < 32 or ord(char) == 127 for char in source_path)
        or not snippet
    ):
        raise ValueError("matching source cannot be represented safely")
    return source_path, snippet


def prepare_search_create_operation(
    operation: ProposedOperation,
    *,
    db_session: Session,
) -> ProposedOperation:
    """Bind one exact authorized source excerpt before asking for confirmation."""
    if operation.operation_id != "workspace_workflow_search_and_create_item":
        return operation

    raw_payload = operation.parameters.get("workflow_payload")
    if not isinstance(raw_payload, str) or not raw_payload or len(raw_payload) > 512:
        raise ValueError("search-and-create request payload is invalid")
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        raise ValueError("search-and-create request payload is invalid") from None
    if not isinstance(payload, dict) or set(payload) != {"kind", "query", "title"}:
        raise ValueError("search-and-create request payload is invalid")

    kind = payload["kind"]
    query = payload["query"]
    title = payload["title"]
    if (
        kind not in {"note", "task"}
        or not isinstance(query, str)
        or not query.strip()
        or len(query) > 200
        or not query.isprintable()
        or not isinstance(title, str)
        or not title.strip()
        or len(title) > 100
        or not title.isprintable()
    ):
        raise ValueError("search-and-create request values are invalid")

    outcome = search_authorized_local_files(query, db_session=db_session)
    if not outcome.secure_backend_available:
        raise ValueError("secure authorized local search is unavailable")
    if outcome.roots_rejected or outcome.roots_skipped:
        raise ValueError("authorized local search could not inspect every root safely")
    if not outcome.matches:
        raise ValueError("no matching authorized local source was found")

    source_path, snippet = normalize_match_preview(outcome.matches[0])
    payload["source_path"] = source_path
    payload["snippet"] = snippet
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded) > 1024:
        raise ValueError("matching source preview exceeds the supported size")

    parameters = {**operation.parameters, "workflow_payload": encoded}
    return operation.model_copy(update={"parameters": parameters})


def run_workspace_read(operation: ProposedOperation) -> str:
    """Run only explicitly registered LOW-risk workspace list/search operations."""
    if operation.operation_id == "workspace_list_items":
        kind = operation.parameters.get("kind")
        if kind not in {None, "note", "task", "reminder"}:
            raise ValueError("unsupported workspace item filter")
        session = database_module.SessionLocal()
        try:
            items = _REPOSITORY.list_items(
                session, kind=kind, include_completed=True, limit=25
            )
            label = f"{kind}s" if kind in {"note", "task"} else kind
            label = label or "workspace items"
            if not items:
                return f"No {label} were found."
            lines = [f"Found {len(items)} {label} (maximum 25 shown):"]
            for item in items:
                state = "completed" if item.completed else "open"
                lines.append(f"- {item.title} [{item.kind}, {state}, ID: {item.id}]")
                if item.kind == "reminder" and item.due_at is not None:
                    lines.append(f"  Due: {item.due_at.isoformat()} ({item.timezone})")
                if item.content:
                    lines.append(f"  {item.content[:512]}")
            return "\n".join(lines)
        finally:
            session.close()

    if operation.operation_id == "workspace_search_files":
        query = operation.parameters.get("query", "").strip()
        outcome = search_authorized_local_files(query)
        matches = outcome.matches
        lines = [
            f"Local search examined {outcome.files_examined} files; "
            f"skipped {outcome.skipped_files} file(s); "
            f"skipped {outcome.skipped_entries} filesystem entr(y/ies); "
            f"found {len(matches)} matches."
        ]
        if outcome.roots_rejected:
            lines.append(
                f"{outcome.roots_rejected} authorized folder(s) were not searched "
                "because they failed a safety check (changed, unavailable, or "
                "not a permitted local folder)."
            )
        if outcome.roots_skipped:
            lines.append(
                f"{outcome.roots_skipped} authorized folder(s) were not searched "
                "in this request because a search limit was reached or secure "
                "folder search is unavailable."
            )
        for match in matches:
            lines.append(f"- {match.path}")
            lines.append(f"  {match.snippet}")
        return "\n".join(lines)

    raise ValueError("unsupported read operation")


__all__ = [
    "normalize_match_preview",
    "prepare_search_create_operation",
    "run_workspace_read",
    "search_authorized_local_files",
]

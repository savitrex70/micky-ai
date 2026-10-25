"""Read-only operations for the deterministic personal workspace."""

from rop import database as database_module
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.authorization import ProposedOperation

_REPOSITORY = AssistantWorkspaceRepository()


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
        if not query:
            raise ValueError("search query missing")
        session = database_module.SessionLocal()
        try:
            roots = _REPOSITORY.list_roots(session)
            root_specs = [(root.path, root.root_identity) for root in roots]
        finally:
            session.close()
        # The same bounded helper is used by the browser-facing retrieval API.
        from rop.api.retrieval import search_roots

        matches, examined, skipped = search_roots(root_specs, query, 10)
        lines = [
            f"Local search examined {examined} files; skipped {skipped}; "
            f"found {len(matches)} matches."
        ]
        for match in matches:
            lines.append(f"- {match.path}")
            lines.append(f"  {match.snippet}")
        return "\n".join(lines)

    raise ValueError("unsupported read operation")


__all__ = ["run_workspace_read"]

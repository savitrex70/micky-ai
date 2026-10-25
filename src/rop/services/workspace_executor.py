"""Trusted, confirmation-only executors for personal workspace mutations.

Every registered workspace mutation is protected by a separate
REQUIRE_CONFIRMATION policy rule. The executor reads the exact operation
stored in the confirmation record and writes an idempotency receipt in the
same transaction as the local mutation. This module is deliberately not
connected to the assistant request registry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from rop.authorization.executors import (
    ExecutorError,
    ExecutorInterrupted,
    ExecutorRegistry,
    ExecutorResult,
)
from rop.authorization.policy import build_default_policy
from rop.database import SessionLocal
from rop.models.assistant_item import AssistantItem
from rop.models.assistant_retrieval_root import AssistantRetrievalRoot
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.services.local_paths import (
    contains_link_or_junction,
    is_network_path,
    local_directory_identity,
    refresh_mount_table,
)
from rop.schemas.authorization import (
    AuthorizationPolicy,
    OperationRule,
    ProposedOperation,
    RiskLevel,
)

logger = logging.getLogger(__name__)
_REPOSITORY = AssistantWorkspaceRepository()
_KEY_NAME = "idempotency_key"
_MISSING = object()

_ITEM_OPERATIONS: dict[str, tuple[str, str]] = {
    "workspace_note_create": ("note", "create"),
    "workspace_note_update": ("note", "update"),
    "workspace_note_delete": ("note", "delete"),
    "workspace_task_create": ("task", "create"),
    "workspace_task_update": ("task", "update"),
    "workspace_task_delete": ("task", "delete"),
    "workspace_task_complete": ("task", "complete"),
    "workspace_reminder_create": ("reminder", "create"),
    "workspace_reminder_update": ("reminder", "update"),
    "workspace_reminder_delete": ("reminder", "delete"),
}
_ROOT_OPERATIONS = {
    "workspace_root_add": "add",
    "workspace_root_remove": "remove",
}
_ITEM_DESCRIPTIONS = {
    ("note", "create"): "Create this local note.",
    ("note", "update"): "Update this local note.",
    ("note", "delete"): "Delete this local note.",
    ("task", "create"): "Create this local task.",
    ("task", "update"): "Update this local task.",
    ("task", "delete"): "Delete this local task.",
    ("task", "complete"): "Change this task's completion state.",
    ("reminder", "create"): "Create this local reminder.",
    ("reminder", "update"): "Update this local reminder.",
    ("reminder", "delete"): "Delete this local reminder.",
}


def build_workspace_policy() -> AuthorizationPolicy:
    """Return a policy that explicitly classifies every workspace mutation.

    Read-only listing and retrieval are not executors. All writes, path
    authorization changes, and deletions require exact per-operation
    confirmation before the executor can run.
    """
    base = build_default_policy()
    rules: list[OperationRule] = list(base.rules)
    for operation_id, (kind, action) in _ITEM_OPERATIONS.items():
        requires_target = action in {"update", "delete", "complete"}
        required = [_KEY_NAME]
        if action in {"create", "update"}:
            required.append("title")
        if action == "complete":
            required.append("completed")
        if action in {"create", "update"} and kind == "reminder":
            required.extend(("due_at", "timezone"))
        rules.append(
            OperationRule(
                operation_id=operation_id,
                description=_ITEM_DESCRIPTIONS[(kind, action)],
                risk=RiskLevel.CONSEQUENTIAL,
                prohibited=False,
                requires_target=requires_target,
                required_parameters=tuple(required),
            )
        )
    rules.extend(
        (
            OperationRule(
                operation_id="workspace_root_add",
                description="Authorize this folder for local-only retrieval.",
                risk=RiskLevel.CONSEQUENTIAL,
                required_parameters=(_KEY_NAME, "path", "root_identity"),
            ),
            OperationRule(
                operation_id="workspace_root_remove",
                description="Remove this folder from local retrieval authorization.",
                risk=RiskLevel.CONSEQUENTIAL,
                requires_target=True,
                required_parameters=(_KEY_NAME,),
            ),
        )
    )
    rules.extend(
        (
            OperationRule(
                operation_id="workspace_list_items",
                description="List the user's local notes, tasks, or reminders.",
                risk=RiskLevel.LOW,
                prohibited=False,
            ),
            OperationRule(
                operation_id="workspace_search_files",
                description="Search text in explicitly authorized local folders.",
                risk=RiskLevel.LOW,
                prohibited=False,
                required_parameters=("query",),
            ),
        )
    )
    return AuthorizationPolicy(rules=tuple(rules))


def build_workspace_executor_registry() -> ExecutorRegistry:
    """Create the explicit registry for reviewed workspace-only operations."""
    registry = ExecutorRegistry()
    for operation_id in (*_ITEM_OPERATIONS, *_ROOT_OPERATIONS):
        registry.register(operation_id, execute_workspace_operation)
    return registry


def operation_fingerprint(operation: ProposedOperation) -> str:
    material = {
        "operation_id": operation.operation_id,
        "target": operation.target,
        "scope": operation.scope,
        "parameters": {
            key: value
            for key, value in operation.parameters.items()
            if key != _KEY_NAME
        },
    }
    canonical = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _operation_key(operation: ProposedOperation) -> UUID:
    raw = operation.parameters.get(_KEY_NAME)
    if not raw:
        raise ExecutorError("workspace operation key missing")
    try:
        return UUID(raw)
    except (TypeError, ValueError):
        raise ExecutorError("workspace operation key invalid") from None


def _apply_item(session, operation: ProposedOperation) -> None:
    kind, action = _ITEM_OPERATIONS[operation.operation_id]
    params = operation.parameters
    if action == "create":
        due_at = None
        timezone = None
        if kind == "reminder":
            try:
                due_at = datetime.fromisoformat(params["due_at"]).astimezone(UTC)
                timezone = params["timezone"]
            except (KeyError, TypeError, ValueError):
                raise ExecutorError("reminder fields invalid") from None
        session.add(
            AssistantItem(
                kind=kind,
                title=params["title"],
                content=params.get("content", ""),
                due_at=due_at,
                timezone=timezone,
                completed=False,
            )
        )
        return

    if operation.target is None:
        raise ExecutorError("workspace item target missing")
    try:
        item_id = UUID(operation.target)
    except (TypeError, ValueError):
        raise ExecutorError("workspace item target invalid") from None
    item = _REPOSITORY.get_item(session, item_id)
    if item is None or item.kind != kind:
        raise ExecutorError("workspace item not found")
    if action == "delete":
        session.delete(item)
    elif action == "complete":
        raw = params.get("completed")
        if raw not in {"true", "false"}:
            raise ExecutorError("task completion value invalid")
        item.completed = raw == "true"
    else:
        item.title = params["title"]
        if params.get("clear_content") == "true":
            item.content = ""
        elif "content" in params:
            item.content = params["content"]
        if kind == "reminder":
            try:
                item.due_at = datetime.fromisoformat(params["due_at"]).astimezone(UTC)
                item.timezone = params["timezone"]
            except (KeyError, TypeError, ValueError):
                raise ExecutorError("reminder fields invalid") from None


def _apply_root(session, operation: ProposedOperation) -> None:
    action = _ROOT_OPERATIONS[operation.operation_id]
    if action == "add":
        raw_path = operation.parameters.get("path")
        approved_identity = operation.parameters.get("root_identity")
        if not raw_path or not approved_identity:
            raise ExecutorError("retrieval folder approval identity missing")
        path = Path(raw_path)
        if (
            not path.is_absolute()
            or str(path) != os.path.abspath(raw_path)
            or is_network_path(path)
            or contains_link_or_junction(path)
        ):
            raise ExecutorError("retrieval folder no longer satisfies local policy")
        refresh_mount_table()
        current_identity = local_directory_identity(path)
        if current_identity is None:
            raise ExecutorError("retrieval folder cannot be verified securely")
        if current_identity != approved_identity:
            raise ExecutorError("retrieval folder identity changed after confirmation")

        existing = _REPOSITORY.get_root_by_path(session, str(path))
        if existing is not None:
            if existing.root_identity != approved_identity:
                raise ExecutorError("retrieval folder authorization identity conflicts")
            return
        session.add(
            AssistantRetrievalRoot(path=str(path), root_identity=approved_identity)
        )
        return
    if operation.target is None:
        raise ExecutorError("retrieval folder target missing")
    try:
        root_id = UUID(operation.target)
    except (TypeError, ValueError):
        raise ExecutorError("retrieval folder target invalid") from None
    root = _REPOSITORY.get_root(session, root_id)
    if root is None:
        raise ExecutorError("retrieval folder not found")
    session.delete(root)


def execute_workspace_operation(
    operation: ProposedOperation, authorized_scope
) -> ExecutorResult:
    """Execute one operation only after the trusted confirmation service calls it.

    The confirmation service has already consumed a challenge for this exact
    operation and policy identity. The database mutation and receipt commit
    together. Duplicate keys return the prior result, never reapply the write.
    """
    key = _operation_key(operation)
    fingerprint = operation_fingerprint(operation)
    session = SessionLocal()
    committing = False
    try:
        receipt = _REPOSITORY.get_receipt(session, key, for_update=True)
        if receipt is None:
            raise ExecutorError("workspace operation was not reserved")
        if receipt.operation_fingerprint != fingerprint:
            raise ExecutorError("operation key reused for different material")
        if receipt.status == "SUCCEEDED":
            return ExecutorResult.SUCCEEDED
        if receipt.status != "PENDING":
            raise ExecutorInterrupted("prior operation has no established result")

        receipt.status = "RUNNING"
        if operation.operation_id in _ITEM_OPERATIONS:
            _apply_item(session, operation)
        elif operation.operation_id in _ROOT_OPERATIONS:
            _apply_root(session, operation)
        else:
            raise ExecutorError("workspace operation unsupported")
        receipt.status = "SUCCEEDED"
        committing = True
        session.commit()
        return ExecutorResult.SUCCEEDED
    except ExecutorError:
        session.rollback()
        raise
    except ExecutorInterrupted:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        if committing:
            return _recover_receipt(key, fingerprint)
        raise ExecutorError("workspace operation conflicted") from None
    except Exception:
        session.rollback()
        if committing:
            return _recover_receipt(key, fingerprint)
        raise ExecutorError("workspace operation could not be completed") from None
    finally:
        session.close()


def _recover_receipt(key: UUID, fingerprint: str) -> ExecutorResult:
    """After an uncertain commit, recover the receipt without re-running."""
    check = SessionLocal()
    try:
        receipt = _REPOSITORY.get_receipt(check, key)
        if receipt is not None and receipt.operation_fingerprint == fingerprint:
            if receipt.status == "SUCCEEDED":
                return ExecutorResult.SUCCEEDED
        raise ExecutorInterrupted("workspace operation result is unknown")
    finally:
        check.close()


__all__ = [
    "build_workspace_executor_registry",
    "build_workspace_policy",
    "operation_fingerprint",
]

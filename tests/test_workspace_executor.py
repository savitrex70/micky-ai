"""Policy and idempotency-contract tests for workspace executors."""

from uuid import uuid4

from rop.schemas.authorization import ProposedOperation
from rop.services.workspace_executor import (
    build_workspace_executor_registry,
    build_workspace_policy,
    operation_fingerprint,
)


def test_workspace_registry_has_only_named_workspace_operations() -> None:
    registry = build_workspace_executor_registry()
    assert len(registry) == 14
    assert "workspace_workflow_create_task_and_reminder" in registry
    assert "workspace_workflow_search_and_create_item" in registry
    assert "workspace_note_create" in registry
    assert "workspace_task_complete" in registry
    assert "workspace_root_add" in registry
    assert "help" not in registry


def test_operation_fingerprint_ignores_only_the_idempotency_key() -> None:
    common = {
        "operation_id": "workspace_note_create",
        "parameters": {"title": "Ward notes", "idempotency_key": str(uuid4())},
    }
    first = ProposedOperation(**common)
    second = ProposedOperation(
        operation_id="workspace_note_create",
        parameters={
            "title": "Ward notes",
            "idempotency_key": str(uuid4()),
        },
    )
    third = ProposedOperation(
        operation_id="workspace_note_create",
        parameters={"title": "Different note", "idempotency_key": str(uuid4())},
    )
    assert operation_fingerprint(first) == operation_fingerprint(second)
    assert operation_fingerprint(first) != operation_fingerprint(third)


def test_workspace_policy_is_additive_to_help() -> None:
    policy = build_workspace_policy()
    assert policy.rule("help") is not None
    assert policy.rule("workspace_note_create") is not None
    assert policy.rule("workspace_root_remove") is not None

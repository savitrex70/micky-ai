"""Policy and idempotency-contract tests for workspace executors."""

import json
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


def test_search_create_fingerprint_binds_request_not_dynamic_preview() -> None:
    request_payload = json.dumps(
        {"kind": "note", "query": "renal physiology", "title": "Revision"},
        sort_keys=True,
        separators=(",", ":"),
    )
    bound_payload = json.dumps(
        {
            "kind": "note",
            "query": "renal physiology",
            "title": "Revision",
            "source_path": "/authorized/revision.md",
            "snippet": "autoregulation controls renal blood flow",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    original = ProposedOperation(
        operation_id="workspace_workflow_search_and_create_item",
        parameters={
            "workflow_payload": request_payload,
            "idempotency_key": str(uuid4()),
        },
    )
    bound = ProposedOperation(
        operation_id="workspace_workflow_search_and_create_item",
        parameters={
            "workflow_payload": bound_payload,
            "idempotency_key": str(uuid4()),
        },
    )
    changed_request = ProposedOperation(
        operation_id="workspace_workflow_search_and_create_item",
        parameters={
            "workflow_payload": json.dumps(
                {"kind": "note", "query": "different query", "title": "Revision"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            "idempotency_key": str(uuid4()),
        },
    )

    assert operation_fingerprint(original) == operation_fingerprint(bound)
    assert operation_fingerprint(original) != operation_fingerprint(changed_request)


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

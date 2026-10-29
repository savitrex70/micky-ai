# Task 248 — Stage 10.4 Search-and-Create Workflow

Repository: savitrex70/micky-ai
Scope: a bounded, confirmed workflow that prepares one local note or task from an authorized search result.

## Supported requests

Examples:

- “Find files containing pharmacology notes and create a task to revise chapter 3.”
- “Search my authorized files for renal physiology and prepare a note titled Revision key points.”

The deterministic interpreter requires an explicit supported search phrase, query, item type, and title. Missing titles trigger clarification. No model, fuzzy matching, shell execution, or generic planner is involved.

## Authorization and execution

The request is translated to one typed workspace operation. Before issuing a challenge, the service performs a bounded, read-only search across the user's identity-bound authorized roots and binds the selected source path and normalized excerpt into the exact operation. The confirmation preview presents the query, target item type, title, source path, and excerpt. No write occurs before confirmation.

After confirmation, execution reuses the same identity-bound authorized-root search helper as read-only workspace search. It fails without writing if the secure backend is unavailable, any authorized root is rejected or skipped, no matches are found, or the exact previewed source path/excerpt no longer matches. If the original match is still present, the executor saves one note/task with that exact source path and bounded excerpt. The source text is untrusted data and is never interpreted as instructions. The new item and durable operation receipt are committed through the existing executor transaction. Replaying the same request returns the prior result without duplicating the item.

## Regression coverage

- tests/test_intent_interpreter.py — supported search/create phrases, missing-title clarification, and separator injection.
- tests/test_workspace_api.py::test_search_and_create_note_is_confirmed_and_source_grounded
- tests/test_workspace_api.py::test_cancelled_search_and_create_task_does_not_write
- tests/test_workspace_api.py::test_search_and_create_task_fails_closed_without_matches
- tests/test_workspace_api.py::test_search_and_create_fails_if_previewed_source_changes

The source-grounding integration test uses a temporary authorized Markdown root and is skipped where the native secure traversal primitives are unavailable. Such a skip is not evidence of successful retrieval on that host.

## Limits

The workflow uses the first matching source excerpt only; it does not summarize or merge sources, infer new facts, or follow instructions found inside retrieved content. Multi-operation language outside the explicit grammars stays unsupported or asks for clarification.

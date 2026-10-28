# Task 246 — Stage 10.4 Safe Cross-Capability Workflow

Repository: savitrex70/micky-ai
Scope: one bounded, consequential multi-write workflow using the existing workspace and confirmation infrastructure.

## Implemented workflow

The deterministic grammar supports an explicitly specified request such as:

`Create a task to finish assignment and remind me to review notes on 2026-11-01T10:00 in Europe/Amsterdam`

The request must supply both item titles, an exact local date/time, and an IANA timezone. Missing or conflicting inputs do not trigger a first-match action. The parser validates the values and binds the original local timestamp, normalized timestamp, timezone, titles, and idempotency key into the stored operation.

The existing authorization and durable confirmation path creates one challenge for the complete operation. The preview names both entries and shows the user-entered local time and timezone. No task or reminder is written before confirmation. After confirmation, the existing executor validates the payload and checks that the local time, timezone, and normalized execution instant agree. It adds both records through the same database session/transaction used by the operation receipt. Cancellation produces neither record; replay of the same idempotent request reports the earlier outcome without duplicating either record.

No generic planner, unbounded chain, arbitrary shell/code execution, destructive natural-language command, or implicit authorization was added.

## Validation coverage

- `tests/test_intent_interpreter.py`: supported workflow phrase and clarification for missing exact time.
- `tests/test_workspace_api.py::test_task_reminder_workflow_is_confirmed_once_and_committed_together`: no pre-confirmation writes, exact preview values, joint execution, and idempotent replay.
- `tests/test_workspace_api.py::test_cancelled_task_reminder_workflow_creates_neither_item`: cancellation leaves both item collections unchanged.
- Existing confirmation and clarification tests continue to cover the server-owned challenge, conversation association, expiry, cancellation, retries, and recovery semantics.

## Limits

Only the task-plus-reminder workflow above is implemented as a multi-write workflow. Other multi-action language, including a file search followed by creating a note or task, does not silently execute a chain; it asks for clarification or remains unsupported. This is intentional fail-closed behavior, not a promise that all natural-language workflows are supported.

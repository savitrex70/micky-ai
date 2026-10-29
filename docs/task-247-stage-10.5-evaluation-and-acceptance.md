# Task 247 — Stage 10.5 Evaluation and Acceptance Evidence

Repository: savitrex70/micky-ai
Scope: fixed deterministic intent evaluation, regression mapping, and honest acceptance reporting.

## Evaluation corpus

`tests/fixtures/stage10_evaluation_v1.json` is a versioned synthetic corpus with 39 exact natural-language cases authored independently from the production interpreter. It covers help, item listing, local-file search, create-note/task/reminder requests, exact-time reminder handling, the bounded task-plus-reminder workflow, conflicts, malformed values, near-miss phrases, unsupported requests, and explicit-command compatibility.

The corpus includes a separate matrix linking 24 security/privacy/functional domains to existing named automated tests, including memory CRUD and clear confirmation, personal-data export, clinical/personal separation, retrieval containment and limits, offline guards, clarification recovery, and workflow confirmation/cancellation/replay. The test verifies that each matrix entry points to a real test function.

## Metrics and commands

Run the deterministic evaluation from the repository root:

```powershell
uv run python scripts/evaluate_stage10.py
uv run pytest tests/test_stage10_evaluation.py tests/test_intent_interpreter.py -q
uv run pytest tests/test_assistant_memory.py tests/test_personal_data_export.py -q
uv run pytest tests/test_workspace_api.py -k "search_and_create or task_reminder_workflow" -q
```

The report includes exact-outcome accuracy, false-match count, missed-supported-request count, micro intent precision and recall, and per-intent precision/recall. Precision is true positives divided by all predicted matches; recall is true positives divided by all expected supported matches. The script fails if exact expected outcomes are wrong, either precision or recall falls below 0.98, or false matches/missed supported requests are nonzero. The fixed-corpus tests independently enforce the expected case outcomes and metric bounds.

## Interpretation and limits

This is a small, project-owned phrase corpus. Passing it means the enumerated examples and regression cases match their defined expectations; it does not establish general language understanding, independent validation, clinical quality, or safety for arbitrary requests. Metrics must be reported from an actual run and must not be inferred from the thresholds.

Stage 10 verification must be reported separately from the Stage 8 model-acceptance gate and Stage 9 product-acceptance gate. Neither is marked accepted by these tests.

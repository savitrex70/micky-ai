# Task 231 - Stage 9 Contract Reconciliation and Scope Freeze

**Stage:** Stage 9.1
**Status:** Documentation-only. Stage 9 is not complete; this task
reconciles the contract with the actual code and freezes the roadmap.

## 1. Purpose and scope

This task establishes an accurate source of truth for Stage 9 before
any Stage 9.2 implementation begins. It:

- Reconciles `docs/stage-9-product-contract.md` with the actual `main`
  tree.
- Reconciles the Stage 9 section of `README.md` with the same source
  of truth.
- Records the agreed Stage 9.2-9.8 roadmap as the working sequence.
- Records approved defaults for reminders (Stage 9.4) and local
  retrieval (Stage 9.5) so that those design tasks start from agreed
  boundaries.
- Clarifies that implemented technical foundations are not completed
  user-facing workflows.

No application code, tests, database models, migrations, dependencies,
runtime configuration, capabilities, authorization policies, executors,
UI behaviour, or model behaviour is changed by this task.

## 2. Files inspected and status verified

Every implementation-status claim in the contract was checked against
the actual repository. The verified state at baseline `33b2616`:

- **Conversation/message persistence:** `src/rop/models/assistant_conversation.py`
  (`AssistantConversation`, table `assistant_conversations`) and
  `src/rop/models/assistant_message.py` (`AssistantMessage`, table
  `assistant_messages`). Migration `20261019_0018_create_assistant_conversations.py`
  present.
- **Conversation HTTP API:** `src/rop/api/conversations.py` exposes
  list/create/read/rename/delete and list-messages/append-message
  endpoints under `/api/assistant/conversations`, writes
  local-origin-guarded.
- **Persistent-conversation UI:** `src/rop/web/static/app.js` (~100 KB)
  with `conversations-new`, `conversation-rename`,
  `conversation-delete`, `conversation-messages` element bindings; a
  122 KB behavioural harness at `tests/conversations_ui_harness.cjs`
  and 45 KB of scenarios in
  `tests/test_conversations_ui_corrections.py`.
- **Authorization policy and dispatch:** `src/rop/authorization/policy.py`,
  `dispatch.py`, `executors.py`.
- **Durable confirmation record and lifecycle:**
  `src/rop/models/assistant_confirmation.py`
  (`assistant_confirmations`), `src/rop/services/confirmation.py`,
  `src/rop/api/confirmations.py`.
- **Production executor registry:** `build_default_executor_registry()`
  in `src/rop/authorization/executors.py` returns an empty
  `ExecutorRegistry()` by design. No production state-changing
  capability is registered.
- **Registered capabilities:** `src/rop/capabilities/registry.py` - only
  `help`.
- **Stage 8 acceptance:** not complete per
  `docs/stage-8-acceptance-readiness-checklist.md` (line 125: "remains
  NOT accepted").
- **Migrations:** 17 revisions under `alembic/versions/`, latest
  `20261019_0018_create_assistant_conversations.py`.
- **Confirmation UI and record controls:** `src/rop/api/confirmation_records.py`
  and the corresponding browser surface in `app.js`, exercised by Task
  226 and Task 227.

## 3. Approved product decisions (frozen by this task)

1. **Product identity** - Micky AI is a private, local-first,
   offline-capable personal assistant built on the existing ROP
   foundation. Not a generic ChatGPT clone, hosted assistant, or
   replacement for ROP. Useful without an approved trained model.
2. **Existing interface** - continue the existing FastAPI application
   and its locally served vanilla-JavaScript browser interface. No
   replacement UI framework or separate service without separately
   reviewed approval.
3. **Intelligence restrictions** - native model optional and advisory
   until Stage 8 acceptance gates are satisfied. No commercial-model
   APIs, hosted inference, Ollama, third-party pretrained models or
   checkpoints, automatic model downloads, or hidden provider
   fallbacks. Training never runs during normal interaction. An absent
   or unavailable model does not prevent deterministic workflows.
4. **Conversation/clinical separation** - conversation/message
   persistence remains a separate domain from clinical reasoning.
   No foreign keys, shared identifiers, joins, or hidden mappings
   between conversation IDs and clinical session IDs.
5. **Stage 9.2-9.8 roadmap** - frozen sequence in the contract §B.3:
   9.2 interaction engine; 9.3 notes and tasks; 9.4 reliable
   reminders; 9.5 private local retrieval; 9.6 ROP reasoning
   integration; 9.7 optional native intelligence (gated on Stage 8
   acceptance); 9.8 end-to-end verification. Recorded in §H.1 as the
   resolved capability-scope decision.
6. **Local UI technology** - the existing FastAPI application and its
   locally served vanilla-JavaScript browser interface remain the UI
   (H.1, resolved). No replacement UI framework or separate service is
   planned without separately reviewed approval.
7. **Conversation/clinical separation** - conversation and message
   persistence remain a separate domain from clinical reasoning
   sessions (H.1, resolved). No foreign keys, shared identifiers,
   joins, or hidden mappings between conversation IDs and clinical
   session IDs.
8. **Reminder defaults (H.3, resolved at default level; for Stage 9.4)** - reminders surface in-app
   while running; overdue reminders surface at next start; no OS
   notifications or separate background service in initial scope;
   due-time interpretation preserves intended timezone; ambiguous DST
   local times require clarification; persistence prevents silent drop
   or duplication.
9. **Retrieval defaults (H.4, resolved at default level; for Stage 9.5)** - no paths authorized
   automatically; user explicitly selects paths; no disk-wide scan; no
   network access on the ordinary retrieval path; only an explicitly
   documented tested allowlist of formats may be read, resolved in
   the Stage 9.5 design task before implementation; unsupported
   formats, inaccessible paths, invalid inputs, and unauthorized
   access handled honestly and safely.
10. **Offline boundary** - installation may require internet; normal
   startup and ordinary supported use must not require network,
   remote inference, or a model artifact. Full offline compliance is
   not claimed until tested.
11. **Authorization and safe execution** - risk-based per-operation
   confirmation (existing owner decision). A confirmation authorizes
   only its specific operation and material parameters. Production
   executor registry is empty; no production state-changing capability
   executes in this build. Notes, tasks, reminders, or any other
   operation must not be documented as executable merely because
   confirmation infrastructure exists.

## 4. Implementation facts corrected

The following statements in the contract were stale and were corrected
after verification against the current repository:

- "no conversational endpoint, no capability routing, no
  personal-assistant UI" (B.1.1) - all exist.
- "15 revisions" for the migration chain (B.1.1) - corrected to 17.
- "no conversation/message tables" (B.1.1) - both tables exist via
  migration `20261019_0018`.
- "history lives in the current browser tab only and is cleared on
  reload" (B.1.5) - history is now durably persisted via Task 228-230.
- "The browser confirmation UI is not implemented" (B.1.5) -
  contradicted by the same section and by Task 226.
- "no conversational workflow, no capability routing, no user-facing
  persistence controls, no assistant UI" (B.1.7) - all exist as
  foundations; only the end-to-end workflow spanning notes / tasks /
  reminders / retrieval is not established.
- "Status: Planned" for B.2 entries 1, 2, 3, 7 - downgraded to
  `PARTIALLY IMPLEMENTED` or `IMPLEMENTED` per actual state.
- Duplicated sentence in B.2 entry 9 ("record, and the server-side
  confirmation lifecycle are implemented. record, and the server-side
  confirmation lifecycle are implemented,") - removed.

The README's Stage 9 section contained three false claims that were
corrected:

- That there is no user-facing persistence beyond the confirmation card
  (conversation create/list/rename/delete exist).
- That there is no user-facing inspect/export/delete surface for
  confirmation records (Task 227 implements it).
- That "the conversational workflow ... do not exist" without
  qualifying which foundations do exist.

A follow-up review of the first reconciliation commit found additional
internal contradictions, which were corrected together:

- **Opening statement** no longer claims that no personal-assistant
  feature exists; it distinguishes implemented foundations from the
  unfinished Stage 9 product.
- **B.1.5 routing entry** no longer says "no conversational requests,
  no session continuity"; it now distinguishes the `help`-only
  capability registry from the implemented conversation persistence,
  HTTP API, and UI.
- **B.1.5 owner-decisions line** no longer says H.1, H.3, and H.4
  remain unresolved; it records that H.1 is resolved for scope, UI,
  and separation; H.3 and H.4 are resolved at the default level; and
  stage-specific implementation details are deferred to their
  respective stages.
- **H.1** is now a RESOLVED section recording the agreed capability
  scope (the §B.3 roadmap), UI choice (existing FastAPI + vanilla JS),
  and conversation/clinical separation (no shared identifiers, FKs,
  joins, or hidden mappings).
- **B.2.1, B.2.2, B.2.3, B.2.9 dependencies** no longer describe
  already-built infrastructure as work that must first be created;
  they describe the remaining work against the actual `main` tree.
- **B.2.4 reminder requirements** now state the approved H.3 defaults
  instead of saying owner decisions are still required; stage-specific
  parsing grammar, storage schema, recovery algorithm, UI affordance,
  and acceptance tests remain deferred to Stage 9.4.
- **G.4 reminder definition-of-done criterion** now refers to the
  H.3-approved defaults rather than to an outstanding owner decision.
- **H.2 closing sentence** no longer says H.1/H.3/H.4 are unresolved
  by that decision; it distinguishes the agreed-level resolution from
  stage-specific implementation details.

## 5. Explicitly deferred details

These remain open and are the responsibility of their respective
stages:

- **Stage 9.2:** the exact interaction-engine design (capability
  selection protocol, clarification rules, safe execution boundary,
  truthful-outcome taxonomy in code).
- **Stage 9.3:** notes/tasks data model, storage schema, UI
  affordances, and exact create/list/edit/delete semantics.
- **Stage 9.4:** reminder parsing expressions, storage schema, recovery
  algorithm, in-app surfacing UI, exact acceptance tests.
- **Stage 9.5:** the initial document-format allowlist, retrieval
  algorithm, exact acceptance tests for unauthorized-path refusal and
  offline-boundary enforcement.
- **Stage 9.6:** which ROP services are surfaced through the
  conversational interface and in what order.
- **Stage 9.7:** native-model integration is gated on Stage 8
  acceptance, which remains incomplete.
- **Stage 9.8:** the full end-to-end verification matrix.

Stage 9 owner decisions:

- **H.1 (capability scope, UI, conversation/clinical separation)** is
  **resolved** at the agreed level and recorded in the contract §H.1.
  The roadmap in §B.3 is the working scope; the existing FastAPI + JS
  interface remains; conversation/message persistence remains separate
  from clinical reasoning sessions.
- **H.3 (reminder defaults)** is **resolved at the default level** and
  recorded in §H.3. Implementation design (grammar, schema, recovery
  algorithm, UI, tests) is deferred to Stage 9.4.
- **H.4 (retrieval and offline defaults)** is **resolved at the
  default level** and recorded in §H.4. The document-format allowlist
  and retrieval algorithm are deferred to Stage 9.5 design.

No owner decision named in this document remains at the level of a
blocking open question for the Stage 9.1 scope freeze.

## 6. Acceptance criteria and evidence expectations

Each stage requires the following before it may be declared complete:

- **Implementation status must be verifiable, proportional to the
  claim.** A **foundation/component claim** (a model, a repository, an
  endpoint, a validator, a registry) requires source/code-path evidence
  plus appropriate unit or integration tests. An **end-to-end
  user-workflow claim** requires an integration or end-to-end test
  demonstrating the workflow. A **security, privacy, offline, or
  recovery claim** requires explicit tests for the relevant boundary
  or failure mode. A passing test suite does not by itself establish
  product completeness, Stage 8 acceptance, or clinical validity.
- **Foundation vs workflow distinction must be maintained.** A
  persistence layer, an API endpoint, or a routing registry is a
  foundation, not a completed user-facing workflow. This distinction
  must be reflected in the strength of the evidence cited for each
  claim, not merely in the wording.
- **Honest outcomes.** Success, failure, refusal, and
  unsupported-capability must each be demonstrable.
- **No silent execution.** Any state-changing operation classified as
  protected by the policy must require authorization before execution.
- **No overstated completeness.** A passing test suite does not
  establish clinical validity, product completeness, or Stage 8
  acceptance.
- **Reviewer evidence.** Each stage's commit must be reviewed against
  this contract, and no stage may be approved solely because its own
  tests pass.

## 7. Non-actions (unchanged by Task 231)

- No application code, tests, database models, migrations, dependencies,
  runtime configuration, capabilities, authorization policies, executors,
  UI behaviour, or model behaviour changed.
- Stage 8 acceptance remains incomplete.
- Stage 9 is not complete. Documentation reconciliation does not
  constitute implementation acceptance.

## 8. Related documents

- [`docs/stage-9-product-contract.md`](stage-9-product-contract.md) -
  the contract reconciled by this task.
- [`docs/stage-8-acceptance-readiness-checklist.md`](stage-8-acceptance-readiness-checklist.md) -
  records that Stage 8 acceptance remains not accepted.
- [`docs/task-228-conversation-persistence.md`](task-228-conversation-persistence.md),
  [`docs/task-229-conversation-http-api.md`](task-229-conversation-http-api.md),
  [`docs/task-230-persistent-conversation-ui.md`](task-230-persistent-conversation-ui.md) -
  the foundation tasks referenced in the corrected inventory.

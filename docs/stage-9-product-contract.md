# Stage 9 Product Contract - Micky AI

**Status: DRAFT - SCOPE AGREED; IMPLEMENTATION IN PROGRESS**

This document defines the product boundary for Stage 9 of Micky AI, the
personal-assistant product being built on top of the existing Reasoning
Operating Platform (ROP). It is a contract, not a finished product.

Stage 9 is **in progress and not accepted**. The current `main` tree
contains the saved-conversation foundation; deterministic help and explicit
workspace-command routing; server-owned, conversation-bound clarification;
persistent notes, tasks, and reminders; confirmation-gated workspace
mutations with idempotency receipts; bounded local retrieval from explicitly
authorized roots; and a separate clinical panel that can invoke the fully
audited ROP reasoning workflow. These components are documented in §B.1.5
and §B.2, but their presence does not by itself satisfy the full Stage 9
acceptance gate. General free-form intent inference, a model-backed chat
path, and a single conversational flow through clinical reasoning are not
implemented. Stage 8 acceptance remains incomplete, so Stage 9.7 is still
gated. The remaining work is end-to-end, privacy, security, offline,
recovery, and manual acceptance under the Stage 9.2-9.8 roadmap in §B.3.

## A. Product identity and purpose

- **Product:** Micky AI - a private, local-first personal assistant.
- **Foundation:** ROP, the existing reasoning and application stack on
  `main` (Stages 1-8).
- **Not:** a generic ChatGPT clone, a hosted assistant, or a replacement
  for the ROP backend.

Micky AI must be private, local-first, offline-capable, predictable,
transparent about uncertainty, and useful **without an approved trained
model**. The goal is to make existing ROP functionality usable through
one coherent application rather than to keep adding disconnected
technical components.

## B. Initial capability scope

### B.1 Existing capability inventory

The following inventory is derived from the actual `main` tree. Each
entry is classified with one of: `IMPLEMENTED`, `PARTIALLY IMPLEMENTED`,
`PLANNED`, `BLOCKED OR GATED`, `NOT ESTABLISHED`. A backend service or
API endpoint is not an end-user feature merely because it exists.

#### B.1.1 API and persistence foundation

- **Capability:** FastAPI application, `/health`, configuration and
  logging bootstrap.
  - Status: `IMPLEMENTED`
  - Paths: `src/rop/main.py`, `src/rop/config.py`,
    `src/rop/logging_config.py`
  - Establishes: a running HTTP application, a system health check, and
    environment-driven settings validated at startup.
  - Absent within this foundational capability: no conversation domain
    endpoint, no capability-routed request endpoint, no personal-assistant
    browser UI. These exist as separate capabilities (see B.1.5).

- **Capability:** Persistence layer (SQLAlchemy 2 + Alembic +
  PostgreSQL).
  - Status: `IMPLEMENTED`
  - Paths: `src/rop/database.py`, `alembic/env.py`, and the migration
    chain under `alembic/versions/` (17 revisions).
  - Establishes: declarative ORM base, session lifecycle, migration
    chain covering sessions, observations, entities, hypotheses,
    evidence, missing information, template matches, reasoning steps,
    candidate hypotheses, evaluated evidence, and reasoning run receipts.
  - Absent: no general user-profile table. Notes, tasks, reminders, and
    authorized retrieval roots use their separate personal-workspace tables;
    they are not stored in the clinical reasoning domain. Conversation/message
    tables exist in migration `20261019_0018` (see B.1.5).

#### B.1.2 Reasoning and evidence services

- **Capability:** Reasoning session, observation, and clinical reasoning
  API surface.
  - Status: `IMPLEMENTED` as a service and API layer; not an end-user
    feature.
  - Paths: `src/rop/api/sessions.py`, `src/rop/schemas/`,
    `src/rop/services/`, `src/rop/repositories/`
  - Establishes: session CRUD, observation CRUD and extraction,
    missing-information detection, template matching, candidate
    generation, evidence evaluation, hypothesis scoring, differential
    ranking, decision context/policy/execution, reasoning-run
    orchestration, and the Stage 6 / Stage 7 evidence, audit,
    consistency, and handoff chains.
  - Absent: no end-user UI, no conversational wrapper, no
    personal-assistant workflows. The API surface is developer-facing.

- **Capability:** Deterministic reasoning core.
  - Status: `IMPLEMENTED`
  - Paths: `src/rop/extraction/`, `src/rop/recognition/`,
    `src/rop/missing_information/`, `src/rop/candidates/`,
    `src/rop/evidence_evaluation/`, `src/rop/templates/`,
    `src/rop/rules/`, `src/rop/services/`
  - Establishes: rule-based observation extraction, medical entity
    recognition, profile-driven missing-information detection, template
    matching, candidate generation, evidence evaluation, hypothesis
    scoring, differential ranking, decision context, decision policy,
    and decision execution.
  - Absent: no LLM provider wired, no assistant-level routing, no
    user-facing surface.

#### B.1.3 Browser-accessible developer documentation

- **Capability:** Interactive OpenAPI documentation.
  - Status: `IMPLEMENTED`
  - Paths: FastAPI-generated `/docs` and `/openapi.json` via
    `src/rop/main.py`
  - Establishes: a browser-accessible OpenAPI surface that lists the
    currently implemented endpoints and schemas.
  - Absent: this is developer documentation. It exposes API endpoints
    and schemas; it is not a personal-assistant interface and does not
    provide any assistant workflow.

#### B.1.4 Stage 8 native components (synthetic scope only)

- **Capability:** Project-owned tokenizer, vocabulary, native model,
  training loop, artifact manifests and checkpoints, local CPU
  inference runtime, advisory adapter, benchmark, and acceptance gate.
  - Status: `IMPLEMENTED` on synthetic-scope only
  - Paths: `src/rop/native_model/`, `src/rop/tokenizer/`,
    `src/rop/training/`, `src/rop/artifacts/`, `src/rop/inference/`
  - Establishes: the Stage 8 native stack, demonstrated only through
    synthetic fixtures and synthetic-scope tests.
  - Absent: no authorized real dataset or authorization/provenance
    record was identified in the repository evidence reviewed; external
    existence has not been verified. Model-specific acceptance
    thresholds remain `pending`; Stage 8 acceptance is not complete;
    the native model is not wired into API request handling.

- **Capability:** LLM-side boundary services.
  - Status: `PARTIALLY IMPLEMENTED`
  - Paths: `src/rop/services/llm_*.py`, `src/rop/schemas/llm_*.py`
  - Establishes: contracts, audit records, privacy boundary checks,
    proposal inspection and normalization, and provider isolation tests.
  - Absent: no live provider is registered, no external inference path
    exists, and no production endpoint invokes any of these services.

#### B.1.5 Stage 9 assistant foundation (implemented) and planned capabilities

Implemented foundation:

- **Capability:** Local browser interface and a single capability-routed
  request endpoint, with honest success and unsupported-capability
  responses.
  - Status: `IMPLEMENTED`
  - Paths: `src/rop/web/`, `src/rop/api/assistant.py`,
    `src/rop/schemas/assistant.py`
  - Establishes: a locally served page at `GET /`, one request endpoint,
    and a truthful envelope of six request statuses:
    `success`, `unsupported-capability`, `clarification-required`,
    `confirmation-required`, `confirmation-unavailable`, and `refused`.
    Post-confirmation outcomes (`executed`, `failed`, `unknown`, `cancelled`,
    `rejected`, `refused`, `unavailable`) belong to the separate
    confirmation-decision API. Only `success` describes a successful response.
  - Absent: general free-form intent inference and a persistent user-profile
    UI. Separate workspace and clinical panels are present; they do not
    establish full Stage 9 product acceptance.

- **Capability:** Deterministic help aliases and explicit workspace-command
  routing.
  - Status: `IMPLEMENTED` for the help aliases and explicit parser-backed
    workspace commands; general free-form intent inference is not implemented.
  - Paths: `src/rop/capabilities/registry.py`,
    `src/rop/capabilities/parser.py`,
    `src/rop/capabilities/workspace_parser.py`,
    `src/rop/api/assistant.py`
  - Establishes: exact help-phrase matching after deterministic
    normalization; explicit `workspace ...` commands for list/search and
    notes/tasks/reminder mutations; server-owned clarification bound to a
    selected conversation. Unknown phrases are never guessed into a
    capability. Parsing, authorization, and execution remain separate
    boundaries.
  - Absent: open-ended natural-language intent inference, a model-backed
    chat path, and integrated clinical reasoning through the chat command
    workflow. The separate clinical reasoning panel is described below.

- **Capability:** Risk-based authorization policy, per-operation
  confirmation lifecycle, and the at-most-once executor boundary.
  - Status: `IMPLEMENTED` for the evaluator, the dispatch boundary, the
    durable confirmation record (Task 223), the server-side confirmation
    lifecycle (Task 224), the browser confirmation card (Task 226), and
    the inspect/export/delete surface for confirmation records (Task 227).
    The generic default executor factory remains empty by design.
    Workspace mutations use a dedicated fixed-operation registry and the
    existing per-operation confirmation workflow; no arbitrary command
    executor is registered.
  - Paths: `src/rop/authorization/policy.py`,
    `src/rop/schemas/authorization.py`,
    `src/rop/authorization/dispatch.py`,
    `src/rop/authorization/executors.py`,
    `src/rop/api/confirmations.py`,
    `src/rop/services/confirmation.py`,
    `src/rop/repositories/assistant_confirmation.py`
  - Establishes: a deterministic, fail-closed decision of `ALLOW`,
    `CLARIFY`, `REQUIRE_CONFIRMATION`, or `DENY` for one proposed
    operation; exact one-action authorization-scope matching; a durable
    challenge record bound to the exact stored operation and to the
    effective policy identity, with constant-time display-code
    verification and a bounded failed-attempt budget; an atomic once-only
    consumption committed before an executor may run; and a server-side
    generic default executor factory remains empty. The workspace
    workflow separately registers only reviewed note/task/reminder/root
    mutation handlers, each behind exact-operation confirmation and an
    idempotency receipt. This does not authorize arbitrary operations. See
    `docs/task-220-authorization-policy.md`,
    `docs/task-221-authorization-dispatch.md`,
    `docs/task-222-confirmation-flow-design.md`, and
    `docs/task-223-confirmation-record-storage.md`.
  - Implemented (Task 226): the browser confirmation card and its
    Confirm/Cancel controls. The card displays the stored operation
    summary, the server-issued display code, the expiry in local time,
    and clear Confirm/Cancel actions, and reports the server's honest
    decision outcome.
  - Implemented (Task 227): the user-facing inspect/export/delete
    surface for confirmation records, at
    `/api/assistant/confirmation-records` and in the browser interface.
    Workspace-specific state-changing operations are registered behind
    the exact confirmation lifecycle and receipt checks. No arbitrary
    shell/code operation is registered; Stage 9.8 acceptance of the full
    mutation and recovery path remains outstanding.

Current Stage 9.2-9.6 implementation on `main` (acceptance pending):

- **Workspace and local retrieval (Stage 9.2-9.5):** the existing browser
  page contains notes/tasks/reminders and retrieval-root/search UI.
  `workspace.js` calls the workspace API; mutations are fixed operations
  with per-operation confirmation and idempotency receipts. Chat supports
  only explicit deterministic workspace command grammar, not general
  natural-language intent guessing. Reminder parsing preserves the named
  IANA timezone and rejects nonexistent or ambiguous DST times rather than
  guessing. In-app overdue reminders are rendered when the workspace loads
  and refreshed while the page is open.
- **Private retrieval:** only explicitly authorized local roots are searched;
  the implementation allowlist is `.txt`, `.md`, `.json`, and `.csv`.
  Root selection is explicit, and traversal/symlink escape, unsupported
  file types, and network roots are excluded by the retrieval boundary.
- **ROP reasoning integration (Stage 9.6):** a separate clinical-session
  panel can run `/sessions/{session_id}/reasoning-run/execute-fully-audited`
  and displays the result as text, with a distinction for package consistency.
  It does not turn the product into a free-form clinical chatbot; package
  consistency does not establish clinical validity, and reasoning-session IDs
  remain separate from conversation IDs.
- **Acceptance status:** implementation is present but Stage 9 is not
  accepted. CI evidence must be checked on the current commit, and the
  complete end-to-end/privacy/security/offline/recovery matrix and a manual
  walkthrough remain required.

Stage 9 capability inventory and remaining acceptance work:

- **Capability:** Conversational requests and session continuity, notes,
  tasks, reminders, local retrieval from user-selected data,
  user-controlled persistence UI, uniform error/refusal/unsupported
  experience, and gating of data-modifying operations by the
  authorization policy.
  - Status: `PARTIALLY IMPLEMENTED; ACCEPTANCE PENDING`. The current tree
    contains conversation persistence/API/UI, explicit command parsing and
    clarification, workspace item workflows, bounded local retrieval, and a
    separate clinical reasoning panel. The overall Stage 9 product, the
    complete acceptance matrix, and manual walkthrough are not established.
  - Paths (persistence + API foundations):
    `src/rop/models/assistant_conversation.py`,
    `src/rop/models/assistant_message.py`,
    `src/rop/repositories/assistant_conversation.py`,
    `src/rop/schemas/assistant_conversation.py`,
    `src/rop/api/conversations.py`, migration
    `20261019_0018`.
  - Established (Task 228): two durable tables
    (`assistant_conversations`, `assistant_messages`), repository methods
    to create, retrieve, list, update-title, append-message,
    list-messages, and delete a conversation with its owned messages, and
    a migration with a working downgrade. Conversation data is stored
    separately from clinical reasoning records — no foreign keys, no
    shared rows, no coupling.
  - Established (Task 229): a FastAPI router at
    `/api/assistant/conversations` exposing list, create, read, rename,
    delete, list-messages, and append-message. Writes are
    local-origin-guarded. The public append endpoint accepts only
    `user` messages and rejects caller-supplied role fields with 422.
    Repository transaction ownership remains at the API boundary.
    Concurrent appends that race for the same sequence produce 409
    Conflict rather than silent retries.
  - Established (Task 230): a persistent-conversation interface in the
    existing browser page: list, create, select, rename, delete
    conversations; load message history; and, when a conversation is
    selected, persist each `success` exchange as an atomic
    user/assistant pair through `POST /api/assistant/requests` with a
    `conversation_id`. Non-success outcomes are shown transiently and
    not saved. Requests without a `conversation_id` retain their
    historical database-free behaviour. Deleting the selected
    conversation clears the selection without auto-selecting another,
    so future persistence never lands on a conversation the user did
    not choose. Navigating the conversation-list pagination preserves
    the selection. Post-success refresh and ambiguous-save recovery both
    use one authoritative helper that reads a fresh `X-Total-Count` and
    then loads the page containing the newest messages; the ambiguity
    marker clears only after a successful, valid message load for that
    same conversation. `503` from the persist path and `409` sequence
    conflicts are treated as ambiguous and block blind resubmission.
    Switching conversations clears the prior conversation's messages
    before the new fetch. Creating a conversation treats the POST
    response as authoritative for id and title; a subsequent list
    refresh failure is a list error, not a title corruption, and a POST
    network failure is treated as ambiguous. The Saved conversations
    toolbar has an explicit "Refresh conversations" button that is
    in-flight-guarded and preserves the selection, title, composer
    mode, and ambiguity marker. A 404 for the selected conversation's
    message fetch is treated as a confirmed deletion: it clears the
    selection, title, messages, pagination state, and ambiguity
    marker, and invalidates any in-flight load. Any other
    inconclusive outcome (network, 500, 503, unreadable) preserves
    the selection. List requests are serialized so overlapping
    pagination and refresh actions cannot start a second request while
    one is in flight. A confirmed-404 submission is sent without a
    `conversation_id`, proving no other conversation was silently
    selected. Recovery only clears the ambiguity marker when the
    fetched page validates against `AssistantMessageRead` (UUID
    identifiers, matching `conversation_id`, permitted role, integer
    `sequence`, ISO 8601 timestamp), its `X-Total-Count` is a
    non-negative integer via the shared strict parser, and the page
    ends at the reported total. Conversation-list responses are
    validated against `AssistantConversationRead` with the same strict
    count parser before any list state is committed; a malformed list
    response preserves the previous rows, offset, total, and selection.
    The API adds backward-compatible `X-Total-Count` headers on its two
    list endpoints.
  - Absent or not yet accepted: conversation import, per-message editing,
    a general-purpose profile, a free-form model-backed chat path, and the
    full Stage 9 end-to-end acceptance evidence. A versioned, paginated JSON
    export for saved conversations/messages and notes/tasks/reminders is now
    implemented; confirmation records remain on their separate export
    surface. Retrieval-root paths and clinical reasoning records are excluded
    from this export. Conversation, workspace, confirmation, and clinical
    reasoning data remain separate domains. Decisions H.1, H.3, and H.4
    remain the approved boundaries for the implementations described here.

#### B.1.6 Blocked or gated capabilities

- **Capability:** Stage 8 acceptance.
  - Status: `BLOCKED OR GATED`
  - Paths: `docs/stage-8-acceptance-readiness-checklist.md`,
    `docs/stage-8-model-thresholds-schedule.md`,
    `docs/stage-8-dataset-governance.md`
  - Establishes: the Stage 8 acceptance process is documented, but
    mandatory inputs are missing.
  - Absent: no authorized real dataset or authorization/provenance
    record was identified in the repository evidence reviewed; external
    existence has not been verified. Model-specific acceptance
    thresholds and sign-off are also outstanding. Stage 8 acceptance
    is not complete.

#### B.1.7 Not established

- **Capability:** Full end-to-end Stage 9 product acceptance across
  conversations, explicit workspace commands, notes/tasks/reminders,
  local retrieval, confirmation and recovery, and integrated ROP reasoning.
  - Status: `NOT ESTABLISHED`
  - Paths: multiple components are present, but no single passing
    acceptance record and manual walkthrough establishes the complete
    product claim.
  - Absent or not established: a unified free-form conversational flow
    across all capabilities; complete privacy/security/offline/recovery
    acceptance; Stage 9.6 manual verification of audit-package behavior
    and identity separation; and formal Stage 9.8 closeout. Existing
    components are implementation evidence, not proof of acceptance.

- **Capability:** Clinical validity of any Stage 8 artifact.
  - Status: `NOT ESTABLISHED`
  - Paths: none.
  - Absent: passing software tests do not establish clinical validity,
    fit-for-purpose clinical evaluation, or autonomous decision
    authority.

### B.2 Target Stage 9 scope

Each entry states current status, intended user outcome, dependencies,
and a measurable acceptance condition. The security invariant in
section E.1 applies to every entry below.

1. **Local browser UI**
   - Status: PARTIALLY IMPLEMENTED - the locally served interface includes
     saved conversations, workspace item forms, authorized retrieval-root
     selection/search, and a separate clinical reasoning panel. Stage 9
     acceptance is still outstanding.
   - Outcome: user interacts with the assistant through a locally
     served page on the same machine.
   - Dependencies: the existing FastAPI-served page and vanilla-JavaScript
     modules are already implemented. Remaining work is acceptance-level
     integration, recovery, privacy/offline verification, and a manual
     walkthrough. No replacement framework or external service is planned.
   - Acceptance: a documented local URL loads a working page; the page
     can submit a request and display a truthful response.

2. **Conversational requests and session continuity**
   - Status: PARTIALLY IMPLEMENTED - saved conversations and their UI
     exist, and the request endpoint supports exact explicit workspace
     commands plus server-owned clarification state. Free-form natural
     language and a single conversation workflow for clinical reasoning
     are not implemented. End-to-end acceptance remains pending.
   - Outcome: a user can hold a conversation; messages persist and can
     be revisited.
   - Dependencies: the conversation domain (`AssistantConversation`,
     `AssistantMessage`, repositories, HTTP API, and persistent UI) is
     already implemented (Tasks 228-230) and remains separate from the
     clinical `reasoning_sessions` domain. Remaining work is focused
     boundary/recovery testing and proving the implemented commands and
     state changes work end to end without cross-domain coupling.
   - Acceptance: create conversation, add messages, list, reopen,
     delete - all verifiable via tests and via the UI.

3. **Deterministic capability routing**
   - Status: IMPLEMENTED for help aliases and explicit parser-backed
     workspace commands; general free-form intent inference is not implemented.
   - Outcome: each supported request is matched to an explicitly
     registered capability; unsupported requests return an explicit
     "unsupported" response, never a fabricated success.
   - Dependencies: the registry, parser protocol, workspace command
     grammar, server-owned clarification state, policy, confirmation
     service, and outcome taxonomy exist. Commands remain exact and
     deterministic; unregistered/free-form phrases are not inferred.
     Full end-to-end and retry/recovery acceptance is still pending.
   - Acceptance: routing tests covering supported, ambiguous, and
     unsupported inputs; no hidden LLM or model selection on this path.

4. **Notes, tasks, reminders**
   - Status: IMPLEMENTATION PRESENT; ACCEPTANCE PENDING.
   - Outcome (notes and tasks): user-controlled create/list/edit/delete
     for simple everyday items, with an exact command grammar and a persistent
     workspace UI. The assistant does not guess free-form intent.
   - Outcome (reminders): a reminder created by the user is stored with
     a user-specified due time and is surfaced according to the approved
     H.3 defaults (recorded below and in §H.3). Reminder functionality
     is **not yet implemented**; Stage 9.4 owns the design and
     implementation of the exact behaviour below. The approved defaults
     define the target behaviour this stage must deliver, not a claim
     that the feature exists today.
   - Dependencies: existing workspace models/repository/API, the
     confirmation-only mutation executor, idempotency receipts, and
     `workspace.js` are present. No new external service is needed.
   - Approved reminder defaults (recorded in §H.3):
       * Reminders surface inside the Micky AI interface while the
         application is running. No OS notifications and no separate
         background notification service in the initial scope.
       * Reminders that become due while the application is closed are
         surfaced as overdue at the next start.
       * Due-time interpretation preserves the intended timezone;
         ambiguous daylight-saving-time local times require
         clarification rather than a guessed interpretation.
       * Persistence and restart recovery must prevent reminders from
         being silently dropped or duplicated.
   - Implemented in the current tree: the accepted input grammar is
     explicit and deterministic; due times are parsed against an IANA zone;
     nonexistent/ambiguous DST times are not guessed; the reminder store
     persists the normalized instant and named timezone; and the in-app
     overdue area refreshes on startup and while the page remains open.
     Stage 9.8 still needs end-to-end restart, confirmation, expiry, and
     no-drop/no-duplicate acceptance evidence.
   - Acceptance (once Stage 9.4 design is reviewed and approved):
       (a) end-to-end user workflow demonstrated for notes, tasks, and
           reminders, including create/list/edit/delete;
       (b) explicit refusal on unparsable input for every item type;
       (c) reminder due-time and timezone interpretation matches the
           approved defaults in §H.3;
       (d) in-app surfacing and overdue-on-restart behaviour match the
           approved defaults in §H.3;
       (e) persistence and restart recovery demonstrate that no
           reminder is silently dropped or duplicated.

5. **Local retrieval from explicitly selected user data**
   - Status: IMPLEMENTATION PRESENT; SECURITY/OFFLINE ACCEPTANCE PENDING.
   - Outcome: user points the assistant at specific local files or
     folders; the assistant retrieves from those only.
   - Dependencies: the retrieval service and root management UI already
     exist. The implementation reads only from explicitly authorized roots
     and uses the tested `.txt`, `.md`, `.json`, and `.csv` allowlist;
     path traversal, symlink escape, network roots, and unsupported formats
     are excluded. Full security/offline acceptance remains pending.
   - Acceptance: retrieval tests prove that unauthorized paths are not
     read and that no external fetch occurs.

6. **Integration with existing ROP functionality**
   - Status: PARTIALLY IMPLEMENTED; ACCEPTANCE PENDING.
   - Outcome: applicable ROP capabilities are exposed through explicit,
     auditable service calls in the separate clinical workspace panel.
     The current UI can run the fully audited reasoning-run endpoint and
     render the returned package as text; it is not wired into free-form chat.
   - Dependencies: the existing ROP service/API and audited reasoning-run
     endpoint are reused; the UI does not duplicate clinical business logic.
     Manual verification of package semantics and clinical/conversation
     identity separation remains required.
   - Acceptance: integration tests that invoke real ROP services;
     Stage 7 evidence, identity, fingerprint, status, and audit
     semantics preserved.

7. **User-controlled persistence**
   - Status: GENERAL EXPORT IMPLEMENTED; IMPORT NOT IMPLEMENTED;
     FINAL ACCEPTANCE PENDING. Confirmation records retain their own
     inspect/export/delete controls. Conversations and workspace items have
     CRUD controls, and a v1 bounded JSON export covers conversations,
     messages, notes, tasks, and reminders through a local API and browser
     download.
   - Outcome: the user can inspect, edit, delete, and export permitted
     personal information from the interface. Export pagination has explicit
     counts/completion metadata; the browser refuses to download when it
     detects a missing page or changing record counts.
   - Dependencies: the export uses a fixed allowlist of fields and excludes
     clinical records, confirmation/clarification state, and retrieval-root
     paths. Import remains unsupported until a separate schema validation,
     authorization, transactionality, duplicate/conflict, and recovery design
     is reviewed. The export is paginated but not a transactionally frozen
     snapshot across all browser requests.
   - Acceptance: automated API/UI coverage exists; the live browser download,
     privacy boundaries, and concurrent-change behavior still require the
     Stage 9.8 walkthrough and passing acceptance run.

8. **Uniform error, refusal, and unsupported experience**
   - Status: IMPLEMENTED at the API/UI response-contract level; full
     cross-flow acceptance pending.
   - Outcome: the assistant returns a truthful status of success,
     failure, refusal, or unsupported-capability, never a fabricated
     success.
   - Dependencies: the assistant request envelope has explicit
     unsupported-capability, clarification-required,
     confirmation-required, confirmation-unavailable, success, and refused.
     The confirmation-decision endpoint separately reports executed, failed,
     unknown, cancelled, rejected, refused, or unavailable. Browser status
     mapping distinguishes the two API contracts.
     Cross-flow/recovery acceptance remains pending.
   - Acceptance: tests covering each status.

9. **Permission boundary for data-modifying operations**
   - Status: Partially implemented. Policy evaluation, the
     authorization-enforced dispatch boundary, the durable confirmation
     record, and the server-side confirmation lifecycle are implemented,
     as are the browser confirmation card and the user-facing
     inspect/export/delete surface for confirmation records. The
     workspace product also has a dedicated fixed-operation registry whose
     mutations require exact confirmation and durable idempotency receipts;
     the generic default executor factory remains empty by design.
   - Outcome: any operation classified as protected by the agreed
     security policy requires effective authorization before it may
     execute. No protected state-changing operation may run silently.
   - Dependencies: the policy evaluator, dispatch boundary, durable
     confirmation record, server-side confirmation lifecycle, browser
     confirmation card, and confirmation-record inspect/export/delete
     surface already exist. Workspace mutations are wired through
     `build_workspace_executor_registry()` in
     `src/rop/services/workspace_executor.py`; the generic
     `build_default_executor_registry()` in
     `src/rop/authorization/executors.py` remains empty. The remaining
     gap is acceptance evidence for replay, cancelled/expired challenges,
     uncertain outcomes, and full browser-to-database recovery; arbitrary
     operations still cannot be executed.
   - Owner decision recorded (section H.2, principles in section E.2):
     risk-based per-operation confirmation. Session-scoped authorization
     was not chosen.
   - Implemented - policy evaluation (Task 220):
     `src/rop/authorization/policy.py` evaluates one proposed operation
     under a versioned rule table and returns `ALLOW`, `CLARIFY`,
     `REQUIRE_CONFIRMATION`, or `DENY` with a stable reason code.
     Operation identifiers are matched exactly and are never normalized,
     so a malformed identifier is refused as unusable input instead of
     resolving to a registered operation.
   - Implemented - dispatch enforcement (Task 221): the assistant request
     endpoint consults the policy through
     `src/rop/authorization/dispatch.py` before returning a matched
     capability's response. Only `ALLOW` dispatches; every other outcome,
     a capability with no policy rule, and any evaluation failure stop
     dispatch with an explicit non-success status. The evaluator and the
     dispatch boundary themselves execute, persist, record, and log
     nothing, call no model or network, and neither obtain, verify,
     record, nor invent a user's confirmation. The dispatch boundary
     accepts no caller-supplied `AuthorizedScope`, `confirmed` flag, or
     permission assertion.
   - Implemented - durable confirmation record (Task 223): challenges are
     persisted in the `assistant_confirmations` table with a thirty-day
     terminal retention and redaction lifecycle, and the effective policy
     identity is fingerprinted via `authorization_policy_identity`. See
     `docs/task-223-confirmation-record-storage.md`.
   - Implemented - server-side confirmation workflow (Task 224):
     `src/rop/services/confirmation.py` mints a challenge only for
     `REQUIRE_CONFIRMATION` with a registered executor, verifies the
     display code in constant time, revalidates the stored operation
     against the current effective policy identity, and consumes the
     approval at most once before invoking the executor.
     `src/rop/api/confirmations.py` exposes
     `POST /api/assistant/confirmations/{id}/decision` behind the
     loopback same-origin check; `src/rop/authorization/executors.py` is
     the server-side executor registry. Bounded startup recovery
     (`src/rop/services/confirmation_recovery.py`) marks consumed
     records without an established outcome as unknown and expires
     overdue pending challenges.
   - Remaining gaps: the generic default executor factory remains empty,
     but reviewed workspace mutations are registered separately and use
     the same confirmation lifecycle. The workspace path still requires
     complete retry/recovery acceptance and a manual walkthrough. The
     confirmation-record inspect/export/delete surface is implemented in
     Task 227 (see `docs/task-222-confirmation-flow-design.md` §6.4).
   - Acceptance (for the complete mechanism):
       (a) an unauthorized call to a protected operation is refused,
           and the refusal is recorded;
       (b) an authorized call to a protected operation completes;
       (c) no protected state-changing operation executes when
           authorization is absent, empty, or invalid.
   - Status of acceptance criteria:
       (c) is met: dispatch of a registered capability is refused unless
           the policy returns `ALLOW`, and the server-side confirmation
           workflow re-evaluates the stored operation against the
           effective policy identity before consuming a challenge or
           invoking an executor. No protected state-changing operation
           executes when authorization is absent, empty, or invalid.
       (a) is partly met: dispatch-time refusals are not persisted to a
           durable record, and the confirmation workflow returns the
           same generic refusal without writing a record for wrong-code,
           expired, locked, or unknown-challenge cases. The refusals
           that do persist are terminal challenge states (INVALIDATED,
           EXPIRED, LOCKED, CANCELLED, REJECTED); arbitrary refusals are
           not recorded.
       (b) has an implementation path for the fixed workspace operation
           set, including confirmation and idempotency receipts. The full
           product criterion is not marked accepted until the current CI
           run, operation replay/unknown-outcome checks, and manual
           end-to-end walkthrough are green on the reviewed commit.

### B.3 Agreed Stage 9 capability roadmap

Task 231 (Stage 9.1) freezes the following sequence as the working
roadmap. This is a roadmap, not a claim that the capabilities are
already implemented. Each stage requires defined acceptance criteria
and independent review before progression.

- **Stage 9.1:** Contract reconciliation and scope freeze (this task).
- **Stage 9.2:** Complete the assistant interaction engine, including
  explicit capability selection, clarification, safe execution
  boundaries, and truthful outcomes.
- **Stage 9.3:** Implement notes and tasks end to end through the
  existing interface.
- **Stage 9.4:** Implement reliable reminders.
- **Stage 9.5:** Implement private retrieval from explicitly selected
  local files or folders.
- **Stage 9.6:** Integrate suitable existing ROP reasoning services
  through explicit, auditable workflows.
- **Stage 9.7:** Evaluate optional native intelligence only after its
  authorization, data-governance, evaluation, and acceptance gates are
  satisfied.
- **Stage 9.8:** Verify the complete product through end-to-end tests,
  privacy and security checks, offline-boundary tests, recovery tests,
  resource measurements, and a manual walkthrough.

Each stage is a bounded commitment. Progressing to a stage does not
imply that later stages are approved. Stage 9.7 is explicitly gated on
Stage 8 acceptance, which remains incomplete.

The Stage 9 interface remains the existing FastAPI application and its
current locally served vanilla-JavaScript browser page. No replacement
UI framework or separate service is planned without separately reviewed
approval.

## C. Architecture and intelligence boundaries

Non-negotiable principles:

1. The existing deterministic ROP infrastructure remains authoritative
   for rules, evidence, identity, provenance, and audit decisions.
2. Intelligence can be both deterministic and native, but an unapproved
   model is not trusted and is never required for ordinary application
   startup or basic functionality.
3. Model-generated suggestions cannot invent evidence, override readable
   contradictions, falsify execution results, or bypass authorization
   and audit requirements.
4. No commercial-model APIs, hosted inference, Ollama, third-party
   pretrained models, automatic model downloads, or hidden provider
   fallbacks.
5. Keep the architecture simple. Reuse existing contracts and services.
   No duplicate business logic. New modules only for distinct
   responsibilities.
6. Preserve existing API behaviour and Stage 7 audit, certification,
   consistency, identity, and evidence contracts. Prefer additive
   integration; document any compatibility change for separate review.
7. Training must never run automatically during a normal user
   interaction.
8. This task adds no dependencies, production code, migrations, or
   configuration.

## D. Offline operation and resource target

Target deployment: a locally runnable application on a Windows 10/11
development machine with approximately 8 GB RAM and CPU-only operation.

Distinguish:

- **Installation / initial setup:** may require internet for dependency
  resolution (today, via `uv`).
- **Normal startup:** must not require network.
- **Ordinary supported use:** must not depend on internet
  connectivity, remote inference, or a model artifact.

No claim of full offline compliance until the runtime boundary is
defined and tested. No performance figures are promised here; any
figures must be measured in a later Stage 9 task.

## E. Privacy, user control, and safety

### E.1 Security invariant

- Personal information is stored locally.
- Any operation classified as protected by the agreed security policy
  requires effective authorization before it may execute. No protected
  state-changing operation may run silently.
- Logs avoid unnecessary private content and secrets.
- The user can understand, inspect, edit, export, and delete persisted
  personal information.
- The assistant never claims to have completed an action that failed.
- The existing medical / clinical reasoning functionality stays
  distinct from general personal-assistant behaviour. Nothing in
  Stage 9 implies validated autonomous diagnosis, treatment decisions,
  or clinical use of the Stage 8 model.

### E.2 Authorization interaction mechanism (owner decision recorded)

- The security invariant in section E.1 is not negotiable.
- **Owner decision (recorded here and in section H.2):** authorization
  is risk-based and **per operation**. Micky AI must ask for permission
  before executing an action that could cause harm, and must stop to
  clarify whenever it is unsure about the user's intent, the target, the
  scope, or the likely consequences. Session-scoped authorization was
  not chosen.

The following principles are the agreed policy. They are the standard the
implementation is measured against, not a description of behaviour that
already exists end to end.

**Implementation status (Tasks 223-226 and Stage 9 workspace work).**
The server-side confirmation lifecycle exists: challenge issuance, decision
handling, policy revalidation against effective policy identity, atomic
single-use consumption, and the executor boundary are implemented in
`src/rop/services/confirmation.py` and exposed at
`POST /api/assistant/confirmations/{id}/decision`. The browser card and
Confirm/Cancel controls are implemented. The generic default executor
factory remains empty, while a separate fixed-operation workspace executor
registry supports only notes/tasks/reminders and retrieval-root mutations,
with per-operation confirmation and idempotency receipts. These components
must still pass Stage 9.8 end-to-end and recovery acceptance.

- **Clear, supported, low-risk operations** may proceed without an
  additional confirmation when they are explicitly allowed by the
  applicable policy. Permission is granted by an explicit policy rule,
  never by the absence of one.
- **Potentially harmful or consequential operations** require explicit
  user confirmation before execution. This includes deleting or
  overwriting data, sensitive changes, external side effects, disclosure
  or sharing of private information, incurring cost, and actions that
  are difficult to reverse.
- **Unclear requests** require clarification before an operation is
  selected or executed. An insufficiently specified operation cannot be
  confirmed into existence, and confirmation of such an operation is not
  valid authorization.
- **Unsupported or prohibited operations** must not become executable
  merely because the user requests them or confirms them.
- **One-action scope:** a confirmation applies only to the specific
  proposed action and its material parameters - operation, target,
  scope, and parameter values. A materially changed target, scope, or
  operation requires a new authorization decision.
- **Honest outcomes:** asking for permission is not execution. A policy
  decision is not execution. The assistant must not report an operation
  as completed unless the operation was actually carried out and success
  was established.
- **Fail safely:** invalid or missing policy information, unclassified
  consequential actions, and uncertainty that cannot be resolved must
  never default to permission. A malformed machine identifier is not
  normalized into a registered operation; it is refused.

Server-side status and remaining gaps:

- **Implemented:** the durable confirmation record (Task 223), the
  server-side interaction that obtains and consumes confirmation (Task
  224), the browser confirmation card (Task 226), and confirmation-record
  inspect/export/delete controls (Task 227). The lifecycle revalidates
  effective policy identity and consumes a challenge at most once.
- **Workspace mutation path:** a separately constructed registry exposes
  only fixed note/task/reminder/root operations through the existing
  confirmation lifecycle, with idempotency receipts and recovery reads.
  The generic default executor factory remains empty by design. This is
  not an arbitrary command or generated-code execution path.
- **Acceptance gap:** Stage 9.8 must verify challenge cancellation and expiry,
  receipt recovery, uncertain outcomes, retry/replay behavior, and the
  browser-to-database flow on the current green test baseline.
- **User-controlled records:** confirmation records have inspect/export/
  delete controls. Conversations and workspace items have CRUD controls;
  a v1 bounded JSON export of conversations/messages and notes/tasks/reminders
  is implemented with API/UI regression coverage. Import remains unsupported.
  Retrieval-root authorizations and clinical reasoning records are not included
  in this general export; confirmation records remain separately exportable.
  Full Stage 9 acceptance of the real browser download and concurrent-change
  behavior is still required.

## F. Non-goals

Stage 9 does **not** promise:

- General intelligence equivalent to commercial conversational models.
- Unrestricted execution of arbitrary generated code or commands.
- Autonomous, unconfirmed consequential actions.
- Automatic access to the entire filesystem or private information.
- Clinical validity merely because software tests pass.
- Stage 8 acceptance. Stage 8 acceptance is blocked on authorization,
  evaluation thresholds, and sign-off that remain unresolved.

No additional major product commitments are introduced that the project
owner has not agreed to.

## G. Measurable Stage 9 definition of done

The following criteria are to be verifiable objectively. They are not
claimed as already achieved.

1. **Startup** - the application starts through a documented, repeatable
   local workflow without external AI credentials.
   - Verification: written run instructions plus a fresh-machine smoke
     test.
   - Evidence: startup log and a reachable local URL.

2. **Truthful interaction** - a user interacts through the intended
   local interface and receives a truthful success, failure, refusal,
   or unsupported-capability response.
   - Verification: UI and API tests, one per status.
   - Evidence: captured responses.

3. **Persistence and user control** - conversations and permitted user
   information persist and can be inspected, edited, exported, and
   deleted.
   - Verification: end-to-end tests against a fresh database covering
     inspect, edit, export, and delete for each permitted personal data
     type.
   - Evidence: tests plus a manual walkthrough.

4. **Reminder behaviour (Stage 9.4 implementation, verified against
   the §H.3 defaults)** - reminders behave according to the approved
   due-time, timezone, surfacing, and closed/restarted-application
   defaults recorded in §H.3.
   - Verification: tests covering due-time parsing, timezone edges
     (ambiguous local times and DST transitions), in-app surfacing,
     overdue-on-restart, and no-silent-drop-or-duplicate behaviour.
   - Evidence: test output plus a manual walkthrough.

5. **Verified capability workflows** - every core capability claimed in
   section B.2 has a verified end-to-end user workflow.
   - Verification: one integration test per capability.
   - Evidence: test results and manual steps.

6. **Deterministic fallback** - deterministic operation remains
   available when native intelligence is absent, disabled, invalid, or
   unavailable.
   - Verification: tests with the model artifact removed / disabled.
   - Evidence: green tests plus startup log.

7. **Offline core** - offline tests verify that the permitted core
   workflow does not invoke prohibited network or remote-inference
   paths.
   - Verification: boundary tests that fail closed on attempted
     prohibited calls.
   - Evidence: test output.

8. **Existing contracts** - existing API contracts and required
   regression gates remain satisfied.
   - Verification: the Stage 7 and Stage 8 test suites remain green.
   - Evidence: full-suite run at Stage 9 close.

9. **Permissions** - protected operations enforce their authorization
   requirements under the agreed mechanism (section E.2).
   - Verification: refusal tests without authorization; success tests
     with authorization; no silent execution tests.
   - Evidence: test output.

10. **Recovery** - the system recovers safely from missing information,
    persistence errors, invalid inputs, and unavailable capabilities.
    - Verification: fault-injection tests.
    - Evidence: test output.

11. **Honest documentation** - documentation distinguishes
    implementation, test evidence, evaluation, and approval.
    - Verification: reviewer check against this contract.
    - Evidence: docs diff.

## H. Stage 9 dependency map

Decisions in this contract guide the later Stage 9.2-9.8 roadmap.

Owner-review items required before the corresponding implementation
commitments:

### H.1 Capability scope - RESOLVED (Task 231)

The project owner approved the following decisions before Task 231
began. They are recorded here so that they are not treated as
outstanding:

- **Capability scope:** the working capability roadmap is the
  Stage 9.2-9.8 sequence recorded in §B.3. Adding or removing a stage
  requires a separately reviewed change to this contract.
- **Local UI technology:** the existing FastAPI application and its
  current locally served vanilla-JavaScript browser interface remain
  the interface. No replacement UI framework or separate service is
  planned without separately reviewed approval.
- **Conversation vs reasoning-session separation:** conversation and
  message persistence remain a separate domain from clinical
  reasoning sessions and records. No foreign keys, shared identifiers,
  joins, or hidden mappings between conversation IDs and clinical
  session IDs are permitted.

**Deferred to individual stages:** the detailed design of each stage's
own capability (for example, the notes/tasks data model, the reminder
schema, the retrieval algorithm) is not part of H.1 and remains the
responsibility of the corresponding Stage 9.x design task.

### H.2 Authorization and permissions
- RESOLVED - Authorization interaction mechanism: **risk-based
  per-operation confirmation**. A confirmation applies only to the
  specific proposed operation and its material parameters; a materially
  changed operation, target, or scope needs a new decision. Session-scoped
  authorization was not chosen. Principles are recorded in section E.2.
- IMPLEMENTED (Task 224) - the server-side interaction that obtains and
  records a confirmation. A `REQUIRE_CONFIRMATION` decision with a
  registered executor now mints a durable challenge through
  `src/rop/services/confirmation.py`; a decision request at
  `POST /api/assistant/confirmations/{id}/decision` revalidates the stored
  operation against the current effective policy identity, verifies the
  display code in constant time, and consumes the approval at most once,
  committed before the executor runs. The default production executor
  registry is empty, so a `REQUIRE_CONFIRMATION` operation still cannot
  execute in this build; and the browser confirmation card and its
  Confirm/Cancel controls are implemented (Task 226), so the user can
  decide a challenge through the UI.
- RESOLVED and IMPLEMENTED - recording and retention: **durable local
  records**, with a terminal record keeping its material values for
  **thirty days** and then retaining only decision metadata and a salted
  digest. The store itself was implemented in Task 223 (table, constraints,
  inspection, export, deletion, retention); Task 224 built the server-side
  confirmation lifecycle on top of that store
  (`src/rop/services/confirmation.py`, `src/rop/api/confirmations.py`)
  without adding a parallel record table. The user-facing HTTP and UI
  surface for inspecting, exporting, and deleting confirmation records
  was implemented in Task 227.
- The security invariant in section E.1 is not part of this decision;
  it must hold regardless of the chosen mechanism.
- This decision does not resolve stage-specific implementation details
  in H.1, H.3, or H.4. The overall roadmap, UI choice, conversation/
  clinical separation, reminder defaults, and retrieval/offline defaults
  recorded in §H and §B.3 are agreed by the project owner.

### H.3 Reminders (see section B.2 entry 4 and Stage 9.4)

**Approved defaults (Task 231):**

- Reminders surface **inside the Micky AI interface while the
  application is running**. No operating-system notifications and no
  separate background notification service are included in the initial
  scope.
- Reminders that become due while the application is closed are
  surfaced as **overdue** when the application next starts.
- Due-time interpretation must **preserve the intended timezone**.
  Ambiguous daylight-saving-time local times require **clarification**
  rather than a guessed interpretation.
- Persistence and restart behaviour must **prevent reminders from
  being silently dropped or duplicated**.

**Implementation present; Stage 9.8 verification remains required:**

- Reminders share the local workspace model, confirmation-gated mutation
  path, and durable idempotency receipts.
- The deterministic chat grammar requires an explicit local due time and
  IANA timezone. Time normalization rejects nonexistent and ambiguous
  daylight-saving-time values instead of guessing. The browser workspace
  shows overdue reminders in-app on initial load and refreshes while open;
  no OS notification or separate background service is used.
- Acceptance must still demonstrate start/restart behavior, correct timezone
  display, no silent drops, and no duplicates through a complete manual and
  automated workflow.

### H.4 Retrieval and offline boundary
**Approved defaults (Task 231):**

- **No filesystem paths are authorized automatically.** The user
  explicitly selects the paths or folders from which Micky AI may
  retrieve information.
- Retrieval must remain **inside the authorized paths** and must not
  scan the whole disk.
- Ordinary retrieval must **not access the network** or implicitly
  fetch external material.
- Only an explicitly documented, tested **allowlist of document
  formats** may be read. Stage 9.5 implementation has selected and tests
  the allowlist `.txt`, `.md`, `.json`, and `.csv`.
- Unsupported formats, inaccessible paths, invalid inputs, and
  unauthorized path access are rejected or skipped safely. The API
  resolves selected roots and the retrieval boundary rejects network roots,
  traversal outside a selected root, symlink escapes, unsupported extensions,
  and files crossing the root device boundary.
- Full offline/security acceptance remains open and must be established in
  Stage 9.8. The existence of these checks is not a claim that every runtime
  boundary has been verified.

**Offline boundary:**

- **Installation / initial setup:** may require internet for dependency
  resolution.
- **Normal startup:** must not require network.
- **Ordinary supported use:** must not depend on internet
  connectivity, remote inference, or a model artifact.

Do not claim full offline compliance without appropriate evidence and
tests. Do not implement retrieval in Task 231.

This contract does not duplicate or supersede Stage 8's acceptance
process, and it does not treat Stage 8 approval as granted.

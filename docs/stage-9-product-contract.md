# Stage 9 Product Contract - Micky AI

**Status: DRAFT - PENDING PROJECT-OWNER REVIEW**

This document defines the product boundary for Stage 9 of Micky AI, the
personal-assistant product being built on top of the existing Reasoning
Operating Platform (ROP). It is a contract, not an implementation. No
personal-assistant feature described here is claimed to exist.

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
  - Absent: no conversational endpoint, no capability routing, no
    personal-assistant UI.

- **Capability:** Persistence layer (SQLAlchemy 2 + Alembic +
  PostgreSQL).
  - Status: `IMPLEMENTED`
  - Paths: `src/rop/database.py`, `alembic/env.py`, and the migration
    chain under `alembic/versions/` (15 revisions).
  - Establishes: declarative ORM base, session lifecycle, migration
    chain covering sessions, observations, entities, hypotheses,
    evidence, missing information, template matches, reasoning steps,
    candidate hypotheses, evaluated evidence, and reasoning run receipts.
  - Absent: no conversation/message tables, no user-profile tables, no
    notes/tasks/reminders tables.

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
    and a truthful envelope of `success`, `unsupported-capability`,
    `clarification-required`, `confirmation-required`, or `refused`.
    Only `success` means a capability answered.
  - Absent: no conversation or message persistence; history lives in the
    current browser tab only and is cleared on reload.

- **Capability:** Deterministic capability routing with `help` as the
  only registered capability.
  - Status: `IMPLEMENTED` for routing and the single `help` capability.
  - Paths: `src/rop/capabilities/registry.py`
  - Establishes: exact matching after normalizing case, whitespace, and
    trailing punctuation to one registered capability; anything else is
    `unsupported-capability` and is never guessed into a capability.
  - Absent: no conversational requests, no session continuity, no notes,
    tasks, reminders, or retrieval.

- **Capability:** Risk-based authorization policy for proposed
  operations.
  - Status: `IMPLEMENTED` as an evaluator plus a dispatch boundary at the
    assistant request endpoint; the end-to-end confirmation flow is not
    implemented.
  - Paths: `src/rop/authorization/policy.py`,
    `src/rop/schemas/authorization.py`,
    `src/rop/authorization/dispatch.py`
  - Establishes: a deterministic, fail-closed decision of `ALLOW`,
    `CLARIFY`, `REQUIRE_CONFIRMATION`, or `DENY` for one proposed
    operation, exact one-action authorization-scope matching, and a
    dispatch boundary that returns a matched capability's response only
    on `ALLOW`. See `docs/task-220-authorization-policy.md` and
    `docs/task-221-authorization-dispatch.md`.
  - Absent: no confirmation interaction, no recording of a decision or a
    confirmation, and no authorization check outside that one dispatch
    path. The proposed interaction is specified, but not built, in
    `docs/task-222-confirmation-flow-design.md`.

Planned capabilities (Stage 9 target):

- **Capability:** Conversational requests and session continuity, notes,
  tasks, reminders, local retrieval from user-selected data,
  user-controlled persistence UI, uniform error/refusal/unsupported
  experience, and gating of data-modifying operations by the
  authorization policy.
  - Status: `PLANNED`
  - Paths: none - no such components exist on `main`
  - Absent: all of the above. Target scope, boundaries, and acceptance
    conditions are defined in section B.2.

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

- **Capability:** End-to-end personal-assistant capability.
  - Status: `NOT ESTABLISHED`
  - Paths: none - no code path in the repository supports this claim.
  - Absent: no conversational workflow, no capability routing, no
    user-facing persistence controls, no assistant UI.

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
   - Status: Planned
   - Outcome: user interacts with the assistant through a locally
     served page on the same machine.
   - Dependencies: a new `src/rop/web/` (or equivalent) served by the
     existing FastAPI app; no new external services.
   - Acceptance: a documented local URL loads a working page; the page
     can submit a request and display a truthful response.

2. **Conversational requests and session continuity**
   - Status: Planned
   - Outcome: a user can hold a conversation; messages persist and can
     be revisited.
   - Dependencies: new conversation domain (`conversation`, `message`)
     models and repositories, distinct from the clinical
     `reasoning_sessions` domain. Existing `reasoning_sessions` must not
     be overloaded.
   - Acceptance: create conversation, add messages, list, reopen,
     delete - all verifiable via tests and via the UI.

3. **Deterministic capability routing**
   - Status: Planned
   - Outcome: each supported request is matched to an explicitly
     registered capability; unsupported requests return an explicit
     "unsupported" response, never a fabricated success.
   - Dependencies: a capability registry and a deterministic matcher
     following the existing template-matching style.
   - Acceptance: routing tests covering supported, ambiguous, and
     unsupported inputs; no hidden LLM or model selection on this path.

4. **Notes, tasks, reminders**
   - Status: Planned.
   - Outcome (notes and tasks): user-controlled create/list/edit/delete
     for simple everyday items, with honest handling of malformed or
     partial input.
   - Outcome (reminders): a reminder created by the user is stored with
     a user-specified due time and, when it becomes due, is surfaced
     through an explicitly chosen mechanism. Actual reminder behaviour
     is a Stage 9 deliverable and is not assumed by this contract.
   - Dependencies: new persistence models and repositories; reuse the
     existing service/repository pattern.
   - Owner decisions still required before the reminder mechanism is
     implemented (see section H.3):
       * Due-time and timezone interpretation, including ambiguous
         local times and daylight-saving transitions.
       * How a due reminder is surfaced to the user.
       * Behaviour when the application is closed or restarted while a
         reminder becomes due.
   - Acceptance (after the owner decisions in section H.3 are resolved):
       (a) end-to-end user workflow demonstrated for notes, tasks, and
           reminders, including create/list/edit/delete;
       (b) explicit refusal on unparsable input for every item type;
       (c) reminder due-time and timezone interpretation matches the
           agreed rule;
       (d) surfacing behaviour matches the agreed mechanism;
       (e) closed/restarted-application behaviour matches the agreed
           rule, and no reminder is silently dropped or duplicated.
   - Until H.3 is resolved, this contract does not promise any specific
     notification mechanism or background delivery.

5. **Local retrieval from explicitly selected user data**
   - Status: Planned
   - Outcome: user points the assistant at specific local files or
     folders; the assistant retrieves from those only.
   - Dependencies: a retrieval service that reads only from the
     explicitly authorized paths; no filesystem-wide scanning; no
     network access.
   - Acceptance: retrieval tests prove that unauthorized paths are not
     read and that no external fetch occurs.

6. **Integration with existing ROP functionality**
   - Status: Planned
   - Outcome: applicable ROP capabilities (e.g., observation
     extraction, missing-information detection) are callable through
     the assistant workflow via explicit, auditable service calls.
   - Dependencies: reusing existing services; no duplicate business
     logic.
   - Acceptance: integration tests that invoke real ROP services;
     Stage 7 evidence, identity, fingerprint, status, and audit
     semantics preserved.

7. **User-controlled persistence**
   - Status: Planned
   - Outcome: the user can inspect, edit, delete, and export their
     permitted personal information from the UI.
   - Dependencies: existing repositories; an export path using a
     stable format (e.g., sorted-key JSON).
   - Acceptance: UI and API tests for inspect, edit, delete, and
     export for each permitted personal data type.

8. **Uniform error, refusal, and unsupported experience**
   - Status: Planned
   - Outcome: the assistant returns a truthful status of success,
     failure, refusal, or unsupported-capability, never a fabricated
     success.
   - Dependencies: a shared response envelope in the new conversation
     layer; existing deterministic services keep their contracts.
   - Acceptance: tests covering each status.

9. **Permission boundary for data-modifying operations**
   - Status: Partially implemented - deterministic policy evaluation only;
     no execution path is gated by it, and nothing is enforced yet.
   - Outcome: any operation classified as protected by the agreed
     security policy requires effective authorization before it may
     execute. No protected state-changing operation may run silently.
   - Dependencies: a thin permission check layer in the conversation /
     capability layer. Existing ROP services remain unchanged.
   - Owner decision recorded (section H.2, principles in section E.2):
     risk-based per-operation confirmation. Session-scoped authorization
     was not chosen.
   - Implemented: `src/rop/authorization/policy.py` evaluates one proposed
     operation under a versioned rule table and returns `ALLOW`,
     `CLARIFY`, `REQUIRE_CONFIRMATION`, or `DENY` with a stable reason
     code. Operation identifiers are matched exactly and are never
     normalized, so a malformed identifier is refused as unusable input
     instead of resolving to a registered operation. The assistant
     request endpoint consults this policy through
     `src/rop/authorization/dispatch.py` before returning a matched
     capability's response: only `ALLOW` dispatches it, and every other
     outcome, a capability with no policy rule, and any evaluation
     failure stop dispatch with an explicit non-success status. The
     evaluator and the boundary execute, persist, record, and log
     nothing, call no model or network, and neither obtain, verify,
     record, nor invent a user's confirmation.
   - Acceptance (for the complete mechanism):
       (a) an unauthorized call to a protected operation is refused,
           and the refusal is recorded;
       (b) an authorized call to a protected operation completes;
       (c) no protected state-changing operation executes when
           authorization is absent, empty, or invalid.
   - Partly met: dispatch of a registered capability is now refused unless
     the policy returns `ALLOW`, which is the dispatch half of (c). It is
     still vacuous for state-changing operations, because none is
     registered; the refusal is not recorded; and (a) and (b) need the
     confirmation interaction and its recording, neither of which exists.

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

Pending, and not resolved by this decision:

- The interaction that obtains a confirmation (prompt, scope of
  question, and how a refusal is represented).
- Whether a confirmation is recorded, and in what form, and whether it is
  bound to the policy version that produced the requirement.
- The code path that enforces a policy decision before an operation
  executes, beyond the assistant capability-dispatch boundary added by
  Task 221. No state-changing operation is reachable through that
  boundary, and no other path consults the policy, so no protected
  operation can execute on policy approval alone.

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

4. **Reminder behaviour (after section H.3 is resolved)** - reminders
   behave according to the agreed due-time, timezone, surfacing, and
   closed/restarted-application rules.
   - Verification: tests covering due-time parsing, timezone edges
     (ambiguous local times and DST transitions), surfacing through the
     agreed mechanism, and closed/restarted behaviour.
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

### H.1 Capability scope
- Scope confirmation of the capability list in section B.2
  (add / remove).
- Choice of local UI technology within existing dependencies.
- Conversation vs reasoning-session separation approach.

### H.2 Authorization and permissions
- RESOLVED - Authorization interaction mechanism: **risk-based
  per-operation confirmation**. A confirmation applies only to the
  specific proposed operation and its material parameters; a materially
  changed operation, target, or scope needs a new decision. Session-scoped
  authorization was not chosen. Principles are recorded in section E.2.
- STILL PENDING - the interaction that obtains and records a confirmation.
  Task 221 added enforcement at the assistant capability-dispatch
  boundary: a matched capability is answered only on `ALLOW`, and every
  other outcome returns an explicit non-success status. That boundary
  cannot reach a state-changing operation, because none is registered,
  and no confirmation can be obtained, recorded, or asserted through it.
  The deterministic evaluator and the dispatch boundary are independently
  tested; the end-to-end permission flow does not exist and is not
  claimed. A reviewable design for the interaction exists in
  `docs/task-222-confirmation-flow-design.md`; it is a proposal that
  decides nothing on its own, and the recording and retention choice
  remains an owner decision.
- The security invariant in section E.1 is not part of this decision;
  it must hold regardless of the chosen mechanism.
- No owner decision in sections H.1, H.3, or H.4 is resolved by this one,
  and the contract as a whole remains a draft.

### H.3 Reminders (see section B.2 entry 4)
- Due-time and timezone interpretation, including ambiguous local
  times and daylight-saving transitions.
- How a due reminder is surfaced to the user.
- Behaviour when the application is closed or restarted while a
  reminder becomes due.

### H.4 Retrieval and offline boundary
- Retrieval boundary: which paths are allowed by default (none, by
  owner confirmation).
- Offline boundary: what is permitted during install vs. run.

This contract does not duplicate or supersede Stage 8's acceptance
process, and it does not treat Stage 8 approval as granted.

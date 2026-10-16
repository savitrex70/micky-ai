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

### B.1 Existing capabilities (from audit of `main`)

Deterministic ROP infrastructure already implemented (Stage 7 through
Task 200, plus Stage 8 Tasks 201-215 on synthetic scope only):

- FastAPI application and `/health` - `src/rop/main.py`
- Reasoning session CRUD, observation CRUD/extraction, missing-information
  detection, template matching, candidate generation, evidence evaluation,
  hypothesis scoring, differential ranking, decision context/policy/
  execution, reasoning-run orchestration, Stage 6/7 evidence and audit
  chains - `src/rop/api/sessions.py`, `src/rop/services/`, `src/rop/schemas/`
- Persistence via SQLAlchemy 2 + Alembic + Postgres - `src/rop/database.py`,
  `alembic/versions/`
- Stage 8 native components on synthetic scope only -
  `src/rop/native_model/`, `src/rop/tokenizer/`, `src/rop/training/`,
  `src/rop/artifacts/`, `src/rop/inference/`

LLM-side boundary services exist as contracts and audits
(`src/rop/services/llm_*.py`) but no live provider is wired.

### B.2 Target Stage 9 scope

Each entry states current status, intended user outcome, dependencies,
and a measurable acceptance condition.

1. **Local browser UI**
   - Status: Planned
   - Outcome: user interacts with the assistant through a locally served
     page on the same machine.
   - Dependencies: a new `src/rop/web/` (or equivalent) served by the
     existing FastAPI app; no new external services.
   - Acceptance: a documented local URL loads a working page; the page
     can submit a request and display a response.

2. **Conversational requests and session continuity**
   - Status: Planned
   - Outcome: a user can hold a conversation; messages persist and can be
     revisited.
   - Dependencies: new conversation domain (`conversation`, `message`)
     models and repositories, distinct from the clinical
     `reasoning_sessions` domain. Existing `reasoning_sessions` must not
     be overloaded.
   - Acceptance: create conversation, add messages, list, reopen, delete -
     all verifiable via tests and via the UI.

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
   - Status: Planned
   - Outcome: user-controlled create/list/edit/delete for simple everyday
     items, with honest handling of malformed or partial input.
   - Dependencies: new persistence models and repositories; reuse the
     existing service/repository pattern.
   - Acceptance: end-to-end user workflow demonstrated for each item
     type; explicit refusal on unparsable input.

5. **Local retrieval from explicitly selected user data**
   - Status: Planned
   - Outcome: user points the assistant at specific local files or folders;
     the assistant retrieves from those only.
   - Dependencies: a retrieval service that reads only from the explicitly
     authorized paths; no filesystem-wide scanning; no network access.
   - Acceptance: retrieval tests prove that unauthorized paths are not
     read and that no external fetch occurs.

6. **Integration with existing ROP functionality**
   - Status: Planned
   - Outcome: applicable ROP capabilities (e.g., observation extraction,
     missing-information detection) are callable through the assistant
     workflow via explicit, auditable service calls.
   - Dependencies: reusing existing services; no duplicate business logic.
   - Acceptance: integration tests that invoke real ROP services; audit
     records preserved (Stage 7 evidence, identity, fingerprint, status).

7. **User-controlled persistence**
   - Status: Planned
   - Outcome: the user can inspect, edit, delete, and export their personal
     information from the UI.
   - Dependencies: existing repositories; an export path using a stable
     format (e.g., sorted-key JSON).
   - Acceptance: UI and API tests for inspect/edit/delete/export.

8. **Uniform error, refusal, and unsupported experience**
   - Status: Planned
   - Outcome: the assistant returns a truthful status of success, failure,
     refusal, or unsupported-capability, never a fabricated success.
   - Dependencies: a shared response envelope in the new conversation
     layer; existing deterministic services keep their contracts.
   - Acceptance: tests covering each status.

9. **Permission boundary for data-modifying operations**
   - Status: Planned
   - Outcome: operations that create, modify, or delete user data require
     an explicit user authorization step within the request; nothing is
     performed silently.
   - Dependencies: a thin permission check layer in the conversation/
     capability layer; existing ROP services remain unchanged.
   - Acceptance: attempts without permission are refused and logged.

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
- **Ordinary supported use:** must not depend on internet connectivity,
  remote inference, or a model artifact.

No claim of full offline compliance until the runtime boundary is
defined and tested. No performance figures are promised here; any
figures must be measured in a later Stage 9 task.

## E. Privacy, user control, and safety

- Personal information is stored locally.
- Sensitive operations are access-controlled and require explicit
  user authorization.
- Logs avoid unnecessary private content and secrets.
- The user can understand, inspect, edit, export, and delete persisted
  personal information.
- The assistant asks for authorization before consequential actions and
  never claims to have completed an action that failed.
- The existing medical/clinical reasoning functionality stays distinct
  from general personal-assistant behaviour. Nothing in Stage 9 implies
  validated autonomous diagnosis, treatment decisions, or clinical use
  of the Stage 8 model.

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
   - Verification: written run instructions + a fresh-machine smoke test.
   - Evidence: startup log and a reachable local URL.

2. **Truthful interaction** - a user interacts through the intended local
   interface and receives a truthful success, failure, refusal, or
   unsupported-capability response.
   - Verification: UI and API tests, one per status.
   - Evidence: captured responses.

3. **Persistence and control** - conversations and permitted user
   information persist and can be revisited, managed, and deleted.
   - Verification: end-to-end tests against a fresh database.
   - Evidence: tests plus a manual walkthrough.

4. **Verified capability workflows** - every core capability claimed in
   section B.2 has a verified end-to-end user workflow.
   - Verification: one integration test per capability.
   - Evidence: test results and manual steps.

5. **Deterministic fallback** - deterministic operation remains available
   when native intelligence is absent, disabled, invalid, or unavailable.
   - Verification: tests with the model artifact removed/disabled.
   - Evidence: green tests + startup log.

6. **Offline core** - offline tests verify that the permitted core
   workflow does not invoke prohibited network or remote-inference paths.
   - Verification: boundary tests that fail closed on attempted
     prohibited calls.
   - Evidence: test output.

7. **Existing contracts** - existing API contracts and required
   regression gates remain satisfied.
   - Verification: the Stage 7 and Stage 8 test suites remain green.
   - Evidence: full-suite run at Stage 9 close.

8. **Permissions** - sensitive operations enforce their permission
   requirements.
   - Verification: refusal tests without permission; success tests with
     permission.
   - Evidence: test output.

9. **Recovery** - the system recovers safely from missing information,
   persistence errors, invalid inputs, and unavailable capabilities.
   - Verification: fault-injection tests.
   - Evidence: test output.

10. **Honest documentation** - documentation distinguishes implementation,
    test evidence, evaluation, and approval.
    - Verification: reviewer check against this contract.
    - Evidence: docs diff.

## H. Stage 9 dependency map

Decisions in this contract guide the later Stage 9.2-9.8 roadmap.

Owner-review items required before implementation commitments:

- Scope confirmation of the capability list in section B.2 (add/remove).
- Choice of local UI technology within existing dependencies.
- Conversation vs. reasoning-session separation approach.
- Permission model shape (per-operation confirmation vs. session-scoped).
- Retrieval boundary: which paths are allowed by default (none, by
  owner confirmation).
- Offline boundary: what is permitted during install vs. run.

This contract does not duplicate or supersede Stage 8's acceptance
process, and it does not treat Stage 8 approval as granted.

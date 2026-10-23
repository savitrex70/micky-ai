# Reasoning Operating Platform

The Reasoning Operating Platform (ROP) is being built incrementally. Its deterministic reasoning infrastructure includes rule-based recognition, missing-information detection, staged reasoning runs, and deterministic release certification. Stage 7 implementation and integration coverage through Task 200 has been completed. The Task 200 checkpoint itself was not fully gate-green: its targeted run had two Task 200 integration-test failures and a Black failure. Those gate failures were corrected in the Stage 7 post-validation fixes merged through PR #15, which are now part of main; the project owner reported that the final local pytest, Ruff, and Black gates passed on that remediated Stage 7 tree. ROP has no concrete third-party model integration and performs no network inference.

## Stage 8: native intelligence

The Stage 8 architecture (Task 201) defines a project-owned deterministic reasoning engine and, only if experiments justify it, a model with randomly initialized weights trained by ROP on authorized data. Tasks 202â€“215 are implemented on main with individually reviewed commits: the deterministic reasoning contracts and composition semantics, baseline evaluation harness, synthetic-only dataset governance, tokenizer/vocabulary, native model, training loop, artifact manifests/checkpoints, local CPU inference runtime, advisory adapter, benchmark, and acceptance gate. These components are demonstrated only through synthetic fixtures and synthetic-scope evidence: no authorized real dataset exists, the model-specific acceptance thresholds remain pending, and Stage 8 acceptance is therefore not complete. The plan excludes commercial models, third-party pretrained models or checkpoints, Ollama and other external model-serving products, hosted inference APIs, and remote inference. General-purpose numerical/training libraries may be considered as engineering tools, but their pretrained models and automatic download paths are not permitted.

The deterministic system must remain useful when no trained model is available. Model suggestions must pass strict schema, identity, provenance, privacy, uncertainty, and evidence-reference checks and must not override supported evidence, readable contradictions, or Stage 7 audit contracts. Passing software tests does not validate a model for clinical use or authorize autonomous clinical decisions.

See the [Stage 8 native-intelligence architecture](docs/stage-8-native-intelligence-architecture.md) for component boundaries, data governance, offline safeguards, acceptance criteria, and the provisional Task 201â€“215 roadmap.

The deterministic baseline is evaluated by a model-free harness over a synthetic case set (contract/behavior tests only, no real-world accuracy claim). See the [baseline evaluation protocol](docs/stage-8-baseline-evaluation-protocol.md) for metrics, predeclared thresholds, and held-out policy:

```powershell
Copy-Item .env.example .env   # once; dummy settings, no database server needed
python -m rop.evaluation --cases src/rop/evaluation/synthetic_cases_v1.json --baseline-revision <git-sha>
```

Dataset preparation is synthetic-only until an authorized source exists; see the [dataset governance](docs/stage-8-dataset-governance.md) and run `pytest tests/test_dataset_preparation.py -q`.

Tokenization and vocabulary construction are project-controlled and deterministic, fitted only on the synthetic-test-only training partition; see the [tokenizer and vocabulary design](docs/stage-8-tokenizer-vocabulary.md).

The initial randomly initialized native model is a compact encoder-style Transformer for a narrow synthetic classification task; see the [native model design](docs/stage-8-native-model.md).

A bounded, deterministic training and validation loop runs only against the existing synthetic-test-only dataset scope and the Task 209 model, when explicitly invoked; see the [training loop design](docs/stage-8-training-loop.md).

Model checkpoints and artifact manifests are pickle-free, content-hashed, and lineage-bound to the synthetic-test-only workflow; see the [artifact manifests and checkpoints](docs/stage-8-artifact-manifests-checkpoints.md).

An optional, explicitly invoked CPU runtime can execute the Task 209 model from a caller-selected local checkpoint; see the [local inference runtime](docs/stage-8-local-inference-runtime.md).

## Stack

- Python 3.12
- FastAPI and Uvicorn
- PostgreSQL 16
- SQLAlchemy 2 and Alembic
- Pydantic Settings
- pytest, Ruff, and Black
- Docker Compose

## Structure

```text
.
â”œâ”€â”€ alembic/              # Migration environment and schema revisions
â”œâ”€â”€ src/rop/
â”‚   â”œâ”€â”€ config.py         # Environment-backed application settings
â”‚   â”œâ”€â”€ database.py       # SQLAlchemy engine, sessions, and ORM base
â”‚   â”œâ”€â”€ logging_config.py # Central logging setup
â”‚   â”œâ”€â”€ models/           # SQLAlchemy persistence models
â”‚   â”œâ”€â”€ repositories/     # Database access operations
â”‚   â”œâ”€â”€ recognition/      # Rule-based medical entity recognition
â”‚   â”œâ”€â”€ missing_information/ # Configurable missing-information detection
â”‚   â”œâ”€â”€ schemas/          # Pydantic input/output schemas
â”‚   â”œâ”€â”€ services/         # Thin CRUD application services
â”‚   â””â”€â”€ main.py           # FastAPI application and system endpoint
â”œâ”€â”€ tests/                # Automated tests
â”œâ”€â”€ .env.example          # Safe configuration template
â”œâ”€â”€ Dockerfile
â”œâ”€â”€ docker-compose.yml
â””â”€â”€ pyproject.toml        # Dependencies and tool configuration
```

## Development setup

Prerequisites: Python 3.12, Git, Docker Desktop, and Docker Compose.

### Local Python workflow

Runs the FastAPI app on the host and PostgreSQL in the Compose database
container. Requires Python 3.12, Git, and Docker Desktop with Docker Compose.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# Start PostgreSQL and wait until its health check reports healthy.
docker compose up -d --wait db

alembic upgrade head

uvicorn rop.main:app --host 127.0.0.1 --port 8000
```

`docker compose up -d --wait db` returns only after the `db` container
reports `healthy`; run `alembic upgrade head` after it returns. Alembic and
the application read the same `ROP_DATABASE_URL` from `.env`. The host-side
URL must use `localhost:5432`; the Compose-only hostname `db` is not
reachable from the host shell.

Verify the running service from a second terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
Start-Process  http://127.0.0.1:8000/docs
```

Stop the API with `Ctrl+C`. Stop and restart the database with
`docker compose stop db` and `docker compose up -d --wait db`. The `.env`
file and the named PostgreSQL volume preserve configuration and data
between runs.

### Local assistant web interface

Micky AI has a local browser interface served by the existing FastAPI
application at `GET /`. It is intentionally minimal: routing is
deterministic and only the `help` capability is registered, so any other
well-formed request receives an explicit `unsupported-capability`
response and no conversation or message is saved. (Confirmation
records for operations that require confirmation are a separate,
durable store; see the confirmation-records section below.) A matched capability is not answered
until the authorization policy allows it, so a request that would need
clarification or confirmation, or that is not permitted, is stopped
instead of run.

The page uses only local HTML, CSS, and vanilla JavaScript. No frontend
framework, external CDN, remote font, analytics, or telemetry is loaded.

**Host-Python workflow.** Start the API as described in the Local Python
workflow above, then open <http://127.0.0.1:8000/> in a browser.

**Docker Compose workflow.** Start the API container as described in the
Docker workflow below, then open <http://127.0.0.1:8000/> in a browser.

**Developer API documentation remains at <http://127.0.0.1:8000/docs>.**
The `/docs` page is the OpenAPI schema for developers. It is not the
assistant interface and does not represent a completed personal assistant.

**Current capabilities and limitations** (this is a working incremental
step, not a finished assistant):

- The Help capability is the first implemented user-facing capability.
  It responds to a small, explicitly registered set of phrases:
  `help`, `what can you do`, `show capabilities`, `list capabilities`,
  and `list available capabilities`. Matching is deterministic and exact
  after normalizing case, surrounding whitespace, and trailing
  punctuation. Help returns a deterministic description of what the
  assistant can and cannot do right now.
- Any other request returns `unsupported-capability`. Unregistered phrases
  are not guessed into a capability.
- A matched capability is not automatically answered. The request endpoint
  evaluates the resolved capability against the authorization policy
  before returning anything, and only `ALLOW` dispatches the capability's
  predefined response. `clarification-required`, `confirmation-required`,
  and `refused` all mean that nothing was dispatched, and the page reports
  those outcomes distinctly instead of presenting them as an unmatched
  request or a success.
- Conversation and message persistence are implemented (Tasks 228-230)
  with a durable store, an HTTP API, and a persistent UI. When a
  conversation is selected, each `success` exchange is saved as an
  atomic user/assistant pair. Non-success outcomes are not saved.
  Requests made without a `conversation_id` retain their original
  database-free behaviour. This persistence is for conversations only;
  it does not imply general-purpose user memory. Conversation data
  remains separate from clinical reasoning sessions. Notes, tasks,
  reminders, and local-file retrieval remain unimplemented in this
  version, and no general-purpose user profile is stored.
- Notes, tasks, reminders, and local-file retrieval are not implemented
  in this version.
- A deterministic, fail-closed authorization policy is implemented as an
  evaluator (`src/rop/authorization/policy.py`) that decides `ALLOW`,
  `CLARIFY`, `REQUIRE_CONFIRMATION`, or `DENY` for a proposed operation,
  whose machine identifier is matched exactly and never normalized, so a
  malformed identifier is refused rather than resolved. The assistant
  request endpoint gates capability dispatch on it
  (`src/rop/authorization/dispatch.py`), so registering a capability does
  not authorize it: a capability with no policy rule is refused.
- The server-side confirmation workflow is implemented: a
  `REQUIRE_CONFIRMATION` decision with a registered executor mints a
  durable challenge (`src/rop/services/confirmation.py`), and a decision
  request at `POST /api/assistant/confirmations/{id}/decision`
  revalidates the stored operation against the current policy, verifies
  the display code in constant time, and consumes the approval at most
  once before any executor runs. The persistence store lives in
  `assistant_confirmations` (Task 223). Bounded startup recovery marks
  consumed records whose outcome was never established as unknown and
  expires overdue pending challenges.
- The browser confirmation interface is implemented (Task 226): when
  the server returns `confirmation-required` with a valid challenge,
  the page shows a pending confirmation card with the stored operation
  summary, the server-issued display code, the expiry in local time,
  and Confirm/Cancel actions. The code-entry field starts empty; the
  user must type the code and deliberately activate Confirm. Outcomes
  are reported honestly - success only when the server also
  establishes `executed: true`. With no production executor
  registered, a consequential operation still cannot execute in this
  build.
- No production state-changing capability and no production executor are
  registered. The default executor registry
  (`src/rop/authorization/executors.py`) is empty, so a
  `REQUIRE_CONFIRMATION` operation cannot execute in this build, and the
  only capability registered is `help`. See
  [the authorization policy](docs/task-220-authorization-policy.md),
  [the dispatch boundary](docs/task-221-authorization-dispatch.md), and
  [the confirmation flow design](docs/task-222-confirmation-flow-design.md).
- The interface itself does not access model providers, remote services,
  or the network beyond the local server. The one database write the
  assistant request path performs is challenge persistence on the
  confirmation path, and only through the store above.

### Stage 7 release-readiness evidence chain

Tasks 174â€“188 form an externally composed, read-only evidence chain. Callers
invoke each service in order and pass its validated result to the next
boundary; an individual service does not orchestrate predecessor or successor
services.

| Task | Boundary | Responsibility |
| --- | --- | --- |
| 174 | `release_readiness_projection` | Projects readiness from the Task 171 attestation, Task 172 audit, and Task 173 consistency result. |
| 175 | `release_readiness_audit` | Independently derives and audits the Task 174 projection from Tasks 171â€“173. |
| 176 | `release_readiness_audit_consistency` | Checks the binding between the Task 174 projection and Task 175 audit. |
| 177 | `release_readiness_evidence_bundle` | Preserves the Task 174â€“176 records in one validated evidence bundle. |
| 178 | `release_readiness_evidence_bundle_audit` | Independently audits the Task 177 bundle against Tasks 174â€“176. |
| 179 | `release_readiness_evidence_bundle_audit_consistency` | Checks the binding between the Task 177 bundle and Task 178 audit. |
| 180 | `release_readiness_final_attestation` | Attests to the Task 177â€“179 evidence; `CERTIFIED` is distinct from a readiness projection. |
| 181 | `release_readiness_final_attestation_audit` | Independently audits the Task 180 attestation against Tasks 177â€“179. |
| 182 | `release_readiness_final_attestation_consistency` | Checks the binding between the Task 180 attestation and Task 181 audit. |
| 183 | `final_release_gate_projection` | Projects a final gate status from the Task 180â€“182 records. |
| 184 | `final_release_gate_audit` | Independently audits the Task 183 projection against Tasks 180â€“182. |
| 185 | `final_release_gate_audit_consistency` | Checks the binding between the Task 183 projection and Task 184 audit. |
| 186 | `release_handoff_evidence_package` | Packages the Task 183â€“185 gate evidence as a handoff snapshot. |
| 187 | `release_handoff_evidence_package_audit` | Independently derives the expected package state from Tasks 183â€“185 and audits Task 186. |
| 188 | `release_handoff_evidence_package_audit_consistency` | Checks the binding between the Task 186 package and Task 187 audit. |

The boundary names above are the shared filename stems under both
`src/rop/schemas/` and `src/rop/services/`; each schema module defines a strict
read model, and each service module exposes its corresponding service class.
The `REASONING_RUN_STAGE_7_*_SOURCE_TASK_<n>` constants in those schemas
identify canonical provenance for the relevant task.

Readiness projections and evidence packages use `READY`, `BLOCKED`, and
`UNAVAILABLE`. `READY` requires a complete, valid, finding-free chain with
matching canonical sources, statuses, and session bindings. `BLOCKED` means
readable evidence proves a blocking condition. `UNAVAILABLE` means the
business result cannot be established; it is not a positive or blocking
claim. Audits and consistency checks use `CONSISTENT`, `INCONSISTENT`, and
`UNAVAILABLE`: `CONSISTENT` can verify a valid business result whose status is
`UNAVAILABLE`, while an `UNAVAILABLE` audit or consistency check means that
the evidence binding could not be verified. A demonstrable contradiction
remains `INCONSISTENT` even if another record is unavailable.

Strict schemas and independent checks preserve canonical source values,
status echoes, and session identity where it is established. Finding lists
are sorted and unique, and their counts must match. Missing, malformed, or
unknown evidence is not silently promoted to `READY` or fabricated into a
contradiction.

These projections and packages are evidence-only. They do not execute or
authorize a release, invoke a provider, access a database, persist records,
or transmit a handoff.

#### Integration coverage and boundaries

Task 189's `tests/test_reasoning_run_stage_7_release_readiness_chain_integration.py`
composes the real Task 174â€“188 services. Its Task 171â€“173 attestation, audit,
and consistency inputs are constructed as validated boundary records; that
test does not invoke those three upstream services itself.

The Task 191 integration coverage in
`tests/test_reasoning_run_stage_7_release_handoff_full_chain_integration.py`
builds upstream evidence using the real Task 154â€“164 services, then invokes the
real Task 165â€“188 services in dependency order. This includes executing the
real Task 171 attestation, Task 172 audit, and Task 173 consistency services
from validated upstream results. Stage 6 certification and the provider
response are the genuine external boundaries replaced with test doubles; no
real model provider or network inference is used.

Task 200 adds a dedicated whole-path integration test that invokes the
real Task 153 entry service, then the actual Task 154â€“164 services, and
reuses the Task 191 composition helper for the real Task 165â€“188 chain. It
covers valid, blocked, unavailable, readable-contradiction, and detached-
identity paths while inspecting the resulting service records. The Stage 6
certification handoff and the explicit provider-response boundary are the
only test doubles; the tests do not call a real model provider or perform
network inference. Test fixtures use the existing in-memory SQLite setup for
session and domain-record preparation.

This gives integration coverage across the Task 153â€“188 service boundaries,
but it is not a claim that every surrounding API lifecycle or external
dependency is exercised in production conditions. The Stage 6 and provider
boundaries remain substituted. At the Task 200 checkpoint, the targeted run
had two Task 200 integration-test failures and a Black check failure; those
gate failures were corrected in the Stage 7 post-validation fixes merged
through PR #15, and the project owner reported that the final local pytest,
Ruff, and Black gates passed on that remediated Stage 7 tree. Those software
checks do not validate a future model for clinical use or substitute for any
required clinical validation and qualified oversight.

To validate the integration coverage and repository from the project root,
with the virtual environment from the local Python workflow above activated:

```powershell
pytest tests/test_reasoning_run_stage_7_release_handoff_full_chain_integration.py -q
pytest tests/test_reasoning_run_stage_7_release_readiness_chain_integration.py -q
pytest -q
ruff check .
black --check .
```

For a safe task-by-task Git review, inspect one commit at a time with
`git show --stat --oneline <commit>` and `git show --format=fuller <commit>`,
then run the focused tests for that change. Confirm the commit's files and
parent before moving to the next task; do not combine task commits or rewrite
already-pushed history.

### API endpoints

The API's persistence endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/sessions` | Create a reasoning session |
| `GET` | `/sessions` | List sessions with `offset` and `limit` pagination |
| `GET` | `/sessions/{session_id}` | Retrieve one session |
| `DELETE` | `/sessions/{session_id}` | Delete one session |
| `POST` | `/sessions/{session_id}/observations` | Create an observation for a session |
| `GET` | `/sessions/{session_id}/observations` | List observations for a session |
| `POST` | `/sessions/{session_id}/extract-observations` | Extract and store observations from free text |

Interactive OpenAPI documentation is generated at `/docs`; the raw schema is available at `/openapi.json`. The current production pipeline performs no diagnosis, model inference, or clinical interpretation; current reasoning paths are deterministic and rule-based. The Stage 8 native-model components exist only in their synthetic-only training/evaluation workflow and are not wired into API request handling; no authorized real-data capability is implemented.

### Observation extraction pipeline

`POST /sessions/{session_id}/extract-observations` accepts a JSON body containing a `text` field. The pipeline has three boundaries:

1. `ObservationExtractor` applies deterministic regular expressions and dictionaries to recognize supported facts such as age, sex, symptoms, severity, radiation, and duration.
2. `ObservationExtractionService` converts extracted values into `ObservationCreate` records and assigns the active session ID.
3. `ObservationRepository.create_many` persists the complete batch in one database transaction.

Each stored observation includes its normalized text, observation type, rule-based source, and a fixed confidence representing the extraction rule. Unsupported text produces an empty observation list. No model API, diagnosis, hypothesis generation, or clinical interpretation is involved.

### Medical entity recognition

`MedicalEntityRecognitionService.recognize` accepts a list of persisted `Observation` objects and returns `RecognizedMedicalEntity` values. The recognizer is deliberately separate from observation extraction and persistence:

1. `MedicalEntityRecognizer` maps supported observation types to `symptom`, `sign`, `anatomical_location`, `duration`, `measurement`, or `risk_factor`.
2. For label-based observations, it parses the deterministic `Label = value` format and applies the same category dictionary.
3. Each result contains the normalized category, extracted value, observation confidence, and the original `source_observation` object for traceability.

Unsupported observation types are ignored. Recognition performs no diagnosis, hypothesis generation, model inference, or database writes; a later application workflow can decide when and how recognized entities should be persisted.

### Missing-information detection

`POST /sessions/{session_id}/detect-missing-information` evaluates the session's stored observations against a configurable clinical profile. The default `chest_pain` profile reports missing age, sex, blood pressure, ECG, troponin, and past cardiac history when the session contains a chest-pain symptom. A profile is active only when its trigger rules match the observations, and it can be selected explicitly with the `profile` query parameter.

`ClinicalProfile` is the configuration boundary: each profile declares trigger conditions and ordered required-information rules. Adding a future shortness-of-breath, stroke, or abdominal-pain profile changes only this configuration; `MissingInformationDetector` and `MissingInformationService` remain unchanged. The detector owns pure rule evaluation, while the service persists resulting items in the `missing_information` table, linked to the reasoning session and profile name. Re-running a profile replaces its previous results so the session contains the current missing-information state rather than duplicates. This module reports information gaps only; it does not diagnose, rank diseases, or generate hypotheses.

### Docker workflow

Builds and runs PostgreSQL and the API as local containers.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# Build the API image from the repository Dockerfile.
docker compose build api

# Start PostgreSQL and wait until its health check reports healthy.
docker compose up -d --wait db

# Apply the schema through the API image, then start the API service.
docker compose run --rm api alembic upgrade head
docker compose up -d api
```

`docker compose up --build` does not apply database migrations
automatically. Run `alembic upgrade head` explicitly as shown above before
starting the API. Alembic is the sole owner of schema changes; the
application never calls `create_all` on startup.

Verify:

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
docker compose logs --tail=100 api
docker compose logs --tail=100 db
```

Both services bind to `127.0.0.1` only. The `postgres_data` named volume
preserves database state across container restarts. Stop and restart:

```powershell
docker compose stop
docker compose start
```
### Troubleshooting local startup

Process liveness, dependency readiness, and schema migration state are three
separate conditions. Check them in this order:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
alembic current
```

**Invalid or missing `.env` values.** Startup fails fast with an error that
names the invalid fields but never prints their values. Compare `.env`
against `.env.example` and correct the named `ROP_*` variables. Do not paste
`.env` contents into logs, issues, or chat.

**PostgreSQL not running or not ready.** `/health/ready` returns HTTP 503.
Start the database with `docker compose up -d db` and confirm with
`docker compose ps` that the `db` container reports `healthy`.

**Database connection failures.** Confirm that `ROP_DATABASE_URL` in `.env`
uses the host-accessible address (`localhost:5432`) when the API runs on the
host, and that only Compose uses the `db` service hostname. Do not print or
share the full URL or credentials.

**Missing or unapplied migrations.** `alembic current` reports the applied
revision. Apply pending revisions with `alembic upgrade head` on the host or
`docker compose run --rm api alembic upgrade head` under Compose.

**API port conflicts.** If `127.0.0.1:8000` is already in use, stop the
process bound to it or start `uvicorn` with `--port 8001`. For Compose,
change the host-side port mapping in `docker-compose.yml`.

**Container health failures.** Inspect state with
`docker inspect --format "{{.State.Health.Status}}" <container>`. The API
container reports unhealthy when its readiness check returns 503, meaning
PostgreSQL is unreachable from the API container. `docker compose logs
--tail=100 api` and `docker compose logs --tail=100 db` show the reason.

**Safe restart and recovery.** `docker compose restart api` restarts only
the API. `docker compose down` followed by `docker compose up --build`
recreates containers without deleting `postgres_data`. Do not run
`docker compose down -v` unless you intend to delete the database volume.
## Configuration

Runtime settings are defined in `src/rop/config.py` and loaded from `.env` or the process environment. Application settings use the `ROP_` prefix; Compose-specific PostgreSQL settings use the standard `POSTGRES_` variables. Compose overrides only the API container's database URL so local Python uses `localhost` while containers use the `db` service name. `.env` is ignored by Git so credentials remain local.

Create the local configuration from the template:

```powershell
Copy-Item .env.example .env
```

These application variables are required in every environment:

| Variable | Allowed values / format | Purpose |
| --- | --- | --- |
| `ROP_APP_NAME` | Non-empty text | Application display name |
| `ROP_ENVIRONMENT` | `development`, `testing`, or `production` | Runtime environment |
| `ROP_LOG_LEVEL` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, or `DEBUG` | Root logging threshold |
| `ROP_DATABASE_URL` | `postgresql+psycopg://...` | PostgreSQL connection URL |

The same schema is used for development, testing, and production. Only the values change: development uses local services, testing uses isolated test resources, and production must provide managed PostgreSQL credentials through its deployment environment. Process environment variables take precedence over `.env`. Missing or invalid required variables cause settings construction to fail immediately.

## Architectural decisions

**`src` layout:** Keeps importable application code separate from project tooling and prevents accidental imports from the repository root.

**Single settings boundary:** `pydantic-settings` provides typed, validated configuration and one cached access point. The application and Alembic do not read environment variables directly.

**Explicit environment modes:** `ROP_ENVIRONMENT` is restricted to `development`, `testing`, or `production`. This prevents silently accepting misspelled or unsupported deployment modes without introducing separate settings classes or duplicated configuration logic.

**Fail-fast required values:** Application settings have no operational defaults. `.env.example` documents the required shape, while deployment-specific values must be supplied by `.env` or the process environment.

**Application-owned logging:** Logging is configured during FastAPI startup, giving local and container execution the same stdout-oriented format while allowing the log level to be changed through configuration.

**Explicit schema migration:** Alembic uses the same configured PostgreSQL URL as the application and imports the ORM model registry. Revisions create `reasoning_sessions`, `observations`, `entities`, `hypotheses`, and then `evidence`.

**Synchronous database boundary:** SQLAlchemy's synchronous engine and `SessionLocal` match the `psycopg` driver and keep request handling straightforward. The engine is created without opening a connection; database access occurs when a session executes work.

**Request-scoped sessions:** `get_db` yields one session per dependency scope and always closes it in `finally`, preventing pooled connections from being retained by requests.

**Alembic owns schema changes:** The application never calls `create_all`. The `ReasoningSession` schema is created and changed only through explicit Alembic revisions.

**Reserved metadata mapping:** SQLAlchemy reserves the Python attribute name `metadata` on declarative bases. The ORM uses `metadata_` while mapping to the database column `metadata`; Pydantic schemas and service inputs retain the required public name `metadata`.

**Thin repository and service layers:** Repositories contain persistence operations, while the service delegates CRUD calls and not reasoning behavior. This keeps the requested model slice testable without introducing domain rules.

**Observation ownership:** Each observation has one required `session_id` foreign key. The session relationship uses delete-orphan cascade, so observations cannot outlive their owning session through the ORM.

**Rule-based extraction boundary:** Extraction logic is isolated from FastAPI and persistence. The parser returns immutable candidates, the application service assigns session ownership, and the repository performs atomic storage. This leaves the pipeline testable and makes a future extractor replaceable without changing the API contract.

**Rule-based entity recognition boundary:** Medical entity recognition accepts observations rather than free text, so it can be tested independently of extraction and retains the complete source observation on every result. Category mapping and `Label = value` parsing are deterministic dictionaries and regular expressions; the service does not call an AI model or mutate the database.

**Profile-driven missing-information boundary:** Missing-information detection consumes observations and evaluates explicit, injectable `ClinicalProfile` requirements. Persistence is session-owned and profile-scoped, allowing reruns to replace stale results while keeping the detector free of diagnosis or disease-ranking logic.

**Confidence validation:** Observation confidence is represented as a numeric value constrained to the inclusive range `0.0` to `1.0`. Observation type and source remain strings because no controlled vocabulary is defined yet.

**Entity ownership:** Each entity has one required `session_id` foreign key and is owned by exactly one reasoning session. Entity name, category, and source remain persistence fields only; no extraction, normalization, or inference is performed.

**Hypothesis ownership:** Each hypothesis has one required `session_id` foreign key and is owned by exactly one reasoning session. Likelihood and ranking are stored and validated values; the model does not calculate, compare, or transition them.

**Evidence ownership:** Each evidence record has one required `hypothesis_id` foreign key and is owned by exactly one hypothesis. `stance` is limited to `supporting` or `contradicting`; the model stores this classification without evaluating evidence or changing hypothesis state.

**Compose health dependency:** The API depends on a real PostgreSQL readiness check rather than container start order, reducing startup races in development.

**Focused test boundary:** The initial test proves the externally visible contract of the only endpoint. Future features should add tests beside their own boundary.

**Dependency source of truth:** `pyproject.toml` contains runtime and development dependencies, with major-version compatibility ranges. The development extra includes `httpx`, which FastAPI's `TestClient` requires.

**Development-only database exposure:** Compose binds both services to loopback and uses example credentials. Production deployments must supply managed credentials and an appropriately secured network configuration.

## Git workflow

```powershell
git init
git add .
git commit -m "Initialize ROP project foundation"
```

## Stage 9: Micky AI product contract

Stage 9 begins the move from ROP's technical components to a single,
local-first personal assistant product, Micky AI.

The Stage 9 product contract is a **draft with an agreed scope and
implementation in progress** and defines the intended scope, boundaries,
offline target, privacy stance, and measurable definition of done for
the stage:

- [Stage 9 product contract](docs/stage-9-product-contract.md)

The contract does **not** imply that the personal-assistant features
described within it have all been implemented. Implemented foundations
on `main` include: the locally served browser interface, the
capability-routed request endpoint with the single `help` capability,
the policy-enforced authorization check on capability dispatch, the
durable confirmation record and its server-side lifecycle, the browser
confirmation card with its Confirm/Cancel controls, the user-facing
inspect/export/delete surface for confirmation records, and durable
conversation/message persistence with an HTTP API and a working
conversation UI (create, list, select, rename, delete, load history,
save exchanges as atomic user/assistant pairs).

The current `main` tree also contains the Stage 9.2-9.5 workspace
implementation: deterministic workspace command parsing and
conversation-scoped clarification state; notes, tasks, and reminders
with confirmation-gated mutations and idempotency receipts; and local
retrieval from explicitly selected roots using a bounded format
allowlist. Relevant code includes `src/rop/capabilities/workspace_parser.py`,
`src/rop/api/workspace.py`, `src/rop/services/workspace_executor.py`,
`src/rop/api/retrieval.py`, and `src/rop/web/static/workspace.js`.
These implementations are not a claim that full product acceptance has
passed.

Still outstanding before Stage 9 can close: Stage 9.6 is only partially
integrated. The workspace UI can list/create clinical sessions, add
observations, and invoke observation extraction, but a complete auditable
reasoning workflow with run orchestration, result/status display, and
safe conversation handoff is not established. Stage 9.8 end-to-end/privacy/
security/offline acceptance also remains outstanding. Stage 9.7 optional native intelligence remains gated because
Stage 8 acceptance is incomplete; no model/provider fallback is allowed.
The original generic assistant executor registry remains intentionally
empty. Workspace writes use their separate confirmation-gated flow; no
arbitrary shell/code execution is introduced.

See [`docs/stage-9-product-contract.md`](docs/stage-9-product-contract.md)
for the agreed roadmap and
[`docs/task-233-stage-9-implementation-consolidation.md`](docs/task-233-stage-9-implementation-consolidation.md)
for the current implementation inventory, CI evidence, and remaining
acceptance blockers. Stage 10 must not begin until those blockers are
closed.

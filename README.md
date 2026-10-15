# Reasoning Operating Platform

The Reasoning Operating Platform (ROP) is being built incrementally. Its deterministic reasoning infrastructure includes rule-based recognition, missing-information detection, staged reasoning runs, and deterministic release certification. Stage 7 implementation and integration coverage through Task 200 has been completed. The Task 200 checkpoint itself was not fully gate-green: its targeted run had two Task 200 integration-test failures and a Black failure. Those gate failures were corrected in the Stage 7 post-validation fixes merged through PR #15, which are now part of main; the project owner reported that the final local pytest, Ruff, and Black gates passed on that remediated Stage 7 tree. ROP has no concrete third-party model integration and performs no network inference.

## Stage 8: native intelligence

The Stage 8 architecture (Task 201) defines a project-owned deterministic reasoning engine and, only if experiments justify it, a model with randomly initialized weights trained by ROP on authorized data. Tasks 202–215 are implemented on main with individually reviewed commits: the deterministic reasoning contracts and composition semantics, baseline evaluation harness, synthetic-only dataset governance, tokenizer/vocabulary, native model, training loop, artifact manifests/checkpoints, local CPU inference runtime, advisory adapter, benchmark, and acceptance gate. These components are demonstrated only through synthetic fixtures and synthetic-scope evidence: no authorized real dataset exists, the model-specific acceptance thresholds remain pending, and Stage 8 acceptance is therefore not complete. The plan excludes commercial models, third-party pretrained models or checkpoints, Ollama and other external model-serving products, hosted inference APIs, and remote inference. General-purpose numerical/training libraries may be considered as engineering tools, but their pretrained models and automatic download paths are not permitted.

The deterministic system must remain useful when no trained model is available. Model suggestions must pass strict schema, identity, provenance, privacy, uncertainty, and evidence-reference checks and must not override supported evidence, readable contradictions, or Stage 7 audit contracts. Passing software tests does not validate a model for clinical use or authorize autonomous clinical decisions.

See the [Stage 8 native-intelligence architecture](docs/stage-8-native-intelligence-architecture.md) for component boundaries, data governance, offline safeguards, acceptance criteria, and the provisional Task 201–215 roadmap.

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
├── alembic/              # Migration environment and schema revisions
├── src/rop/
│   ├── config.py         # Environment-backed application settings
│   ├── database.py       # SQLAlchemy engine, sessions, and ORM base
│   ├── logging_config.py # Central logging setup
│   ├── models/           # SQLAlchemy persistence models
│   ├── repositories/     # Database access operations
│   ├── recognition/      # Rule-based medical entity recognition
│   ├── missing_information/ # Configurable missing-information detection
│   ├── schemas/          # Pydantic input/output schemas
│   ├── services/         # Thin CRUD application services
│   └── main.py           # FastAPI application and system endpoint
├── tests/                # Automated tests
├── .env.example          # Safe configuration template
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml        # Dependencies and tool configuration
```

## Development setup

Prerequisites: Python 3.12, Git, Docker Desktop, and Docker Compose.

### Local Python workflow

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
ruff check .
black --check .
uvicorn rop.main:app --reload
```

The API is available at `http://localhost:8000`. The health check is `GET /health`, and the OpenAPI UI is at `/docs`.

### Stage 7 release-readiness evidence chain

Tasks 174–188 form an externally composed, read-only evidence chain. Callers
invoke each service in order and pass its validated result to the next
boundary; an individual service does not orchestrate predecessor or successor
services.

| Task | Boundary | Responsibility |
| --- | --- | --- |
| 174 | `release_readiness_projection` | Projects readiness from the Task 171 attestation, Task 172 audit, and Task 173 consistency result. |
| 175 | `release_readiness_audit` | Independently derives and audits the Task 174 projection from Tasks 171–173. |
| 176 | `release_readiness_audit_consistency` | Checks the binding between the Task 174 projection and Task 175 audit. |
| 177 | `release_readiness_evidence_bundle` | Preserves the Task 174–176 records in one validated evidence bundle. |
| 178 | `release_readiness_evidence_bundle_audit` | Independently audits the Task 177 bundle against Tasks 174–176. |
| 179 | `release_readiness_evidence_bundle_audit_consistency` | Checks the binding between the Task 177 bundle and Task 178 audit. |
| 180 | `release_readiness_final_attestation` | Attests to the Task 177–179 evidence; `CERTIFIED` is distinct from a readiness projection. |
| 181 | `release_readiness_final_attestation_audit` | Independently audits the Task 180 attestation against Tasks 177–179. |
| 182 | `release_readiness_final_attestation_consistency` | Checks the binding between the Task 180 attestation and Task 181 audit. |
| 183 | `final_release_gate_projection` | Projects a final gate status from the Task 180–182 records. |
| 184 | `final_release_gate_audit` | Independently audits the Task 183 projection against Tasks 180–182. |
| 185 | `final_release_gate_audit_consistency` | Checks the binding between the Task 183 projection and Task 184 audit. |
| 186 | `release_handoff_evidence_package` | Packages the Task 183–185 gate evidence as a handoff snapshot. |
| 187 | `release_handoff_evidence_package_audit` | Independently derives the expected package state from Tasks 183–185 and audits Task 186. |
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
composes the real Task 174–188 services. Its Task 171–173 attestation, audit,
and consistency inputs are constructed as validated boundary records; that
test does not invoke those three upstream services itself.

The Task 191 integration coverage in
`tests/test_reasoning_run_stage_7_release_handoff_full_chain_integration.py`
builds upstream evidence using the real Task 154–164 services, then invokes the
real Task 165–188 services in dependency order. This includes executing the
real Task 171 attestation, Task 172 audit, and Task 173 consistency services
from validated upstream results. Stage 6 certification and the provider
response are the genuine external boundaries replaced with test doubles; no
real model provider or network inference is used.

Task 200 adds a dedicated whole-path integration test that invokes the
real Task 153 entry service, then the actual Task 154–164 services, and
reuses the Task 191 composition helper for the real Task 165–188 chain. It
covers valid, blocked, unavailable, readable-contradiction, and detached-
identity paths while inspecting the resulting service records. The Stage 6
certification handoff and the explicit provider-response boundary are the
only test doubles; the tests do not call a real model provider or perform
network inference. Test fixtures use the existing in-memory SQLite setup for
session and domain-record preparation.

This gives integration coverage across the Task 153–188 service boundaries,
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

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The API runs on `127.0.0.1:8000` and PostgreSQL runs on `127.0.0.1:5432`; both ports are intentionally limited to the local machine for development. The API waits for PostgreSQL's health check before starting. The named volume preserves PostgreSQL data between container restarts.

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

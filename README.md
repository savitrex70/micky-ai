# Reasoning Operating Platform

The Reasoning Operating Platform (ROP) is being built incrementally. The current foundation includes one persistence model, `ReasoningSession`, but no reasoning engine, business logic, authentication, or AI integrations.

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

### API endpoints

The first API exposes persistence operations only:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/sessions` | Create a reasoning session |
| `GET` | `/sessions` | List sessions with `offset` and `limit` pagination |
| `GET` | `/sessions/{session_id}` | Retrieve one session |
| `DELETE` | `/sessions/{session_id}` | Delete one session |
| `POST` | `/sessions/{session_id}/observations` | Create an observation for a session |
| `GET` | `/sessions/{session_id}/observations` | List observations for a session |
| `POST` | `/sessions/{session_id}/extract-observations` | Extract and store observations from free text |

Interactive OpenAPI documentation is generated at `/docs`; the raw schema is available at `/openapi.json`. The API performs no reasoning, diagnosis, hypothesis generation, or state transitions.

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

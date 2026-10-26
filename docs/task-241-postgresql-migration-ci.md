# Task 241 — PostgreSQL and Migration Acceptance in CI

**Repository:** savitrex70/micky-ai  
**Branch policy:** main only  
**Status:** CI change committed; acceptance depends on the resulting GitHub Actions run.

## Changes

- The full test job now provisions a disposable PostgreSQL 16 service database named micky_ai_test and sets both ROP_DATABASE_URL and ROP_TEST_DATABASE_URL to that isolated database.
- CI explicitly runs uv run alembic upgrade head on the fresh database before pytest.
- The full suite uses pytest -q -ra so pytest's short summary includes skip reasons in the job log.
- Database-backed suites that are skipped when no test URL is supplied now fail if a URL is supplied but the database is unreachable. The missing-URL case remains an intentional local skip; invalid configuration is not treated as a green database validation.
- Corrected the conversation migration test cleanup: it said it left the database at head but actually upgraded only to 20261019_0018. It now restores head so later tests can rely on current schema columns and tables.

## Safety

The service database is created fresh for the Actions job. The destructive database tests enforce the _test suffix. The workflow uses a separate disposable CI database and does not point these tests at a user's local application database.

## Verification

The source changes themselves do not constitute a CI pass. The CI run for the commit must demonstrate Ruff, Black, a fresh migration upgrade, the complete pytest suite, and an explicit skip summary. Any PostgreSQL or migration skip/error is a blocker, not evidence of a successful database test.

# Task 241 — PostgreSQL and Migration Acceptance in CI

**Repository:** savitrex70/micky-ai  
**Branch policy:** main only  
**Latest verified code candidate:** 789d771fa4609b5c05091d6773f26fe040c9246d  
**Status:** Implemented and verified by [GitHub Actions run 40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463).

## Changes

- The test job provisions a disposable PostgreSQL 16 database named `micky_ai_test` and sets both `ROP_DATABASE_URL` and `ROP_TEST_DATABASE_URL` to the isolated database.
- CI explicitly runs `uv run alembic upgrade head` on the fresh database before pytest.
- The full suite uses `pytest -q -ra` so pytest reports skip reasons.
- Database-backed suites fail if an explicitly configured database is unreachable. An absent local test URL remains an intentional skip; invalid configured infrastructure is not treated as a passing database validation.
- Corrected the conversation migration test cleanup: it previously claimed to restore head but stopped at `20261019_0018`. It now restores head so subsequent tests use the current schema.

## Safety

The service database is freshly created for the Actions job. Destructive database tests enforce the `_test` suffix. The workflow does not point destructive tests at a user's application database.

## Verified result

Run 40360442463 completed successfully:
- Fresh PostgreSQL 16 Alembic upgrade to head: PASS
- Full pytest: **8,222 passed, 3 skipped, 36 warnings**
- Ruff: PASS
- Black 24.10.0: PASS

The three skips were reported explicitly: real-junction integration on a Linux host, a Windows-only retrieval-policy test on Linux, and an intentional Task 166 snapshot-value case. A documentation-only update triggers its own run, but the tested functional-code candidate above has green CI.

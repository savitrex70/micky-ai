# Task 239 — General Personal-Data Export

**Repository:** savitrex70/micky-ai  
**Branch policy:** main only  
**Initial implementation commit:** 258800e6e9909f148d5540c0ae43fa0f041cfb7a  
**Latest verified code candidate:** 789d771fa4609b5c05091d6773f26fe040c9246d  
**Verification:** PASS in [GitHub Actions run 40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463): 8,222 passed, 3 skipped, 36 warnings; Ruff and Black passed.

## Scope

Implemented `GET /api/assistant/personal-data/export`, a read-only paginated JSON export with format identifier `micky-ai-personal-data` and schema version 1. The response reports generated time, offset, limit, per-domain counts, total records, next offset and a completion flag. The maximum page size is 500 records. Ordering is deterministic within each section: conversations, messages, then workspace items.

The export includes only explicitly mapped, user-visible fields for saved conversation metadata, user/assistant messages, and notes/tasks/reminders including due time, timezone and completion state.

The browser fetches every bounded page, validates format/version and pagination progression, compares total counts across pages and refuses to download a partial result. A Node-based UI harness verifies successful multi-page downloads and refusal to download an incomplete response. Export responses include no-store/no-cache, Pragma no-cache and nosniff headers; offsets beyond total records are rejected.

## Explicit exclusions and limits

- Clinical reasoning sessions, observations, hypotheses, evidence, audit packages and Stage 8 artifacts are not exported.
- Pending confirmations/clarifications, authorization/policy material, operation receipts and internal challenge data are not exported.
- Retrieval-root paths and identities are excluded; confirmation records use their separate established export surface.
- Import is not implemented; the downloaded JSON does not imply import support.
- Pagination is bounded and deterministic, but is not an immutable database-wide snapshot. If record contents change without changing counts while an export is running, count comparison cannot detect it. For the cleanest result, avoid editing/deleting records during the download.

## Tests and acceptance

`tests/test_personal_data_export.py` validates the schema envelope, cross-section pagination, record totals, completion metadata, all three workspace item types, allowed record types/fields, privacy headers and invalid query bounds. Its Node harness checks browser download success and incomplete-page behavior. These automated tests passed in the cited CI run.

A real browser download on the target Windows machine has not been manually verified. Import remains a separate design task requiring schema/size policies, duplicate/conflict rules, explicit confirmation, transactionality, rollback and recovery rules. No import endpoint or import button was added.

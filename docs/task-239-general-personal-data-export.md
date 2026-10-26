# Task 239 — General Personal-Data Export

**Repository:** savitrex70/micky-ai  
**Branch policy:** main only  
**Implementation commit:** 258800e6e9909f148d5540c0ae43fa0f041cfb7a  
**Status:** Implementation added; automated checks are pending for this revision.

## Scope

Added GET /api/assistant/personal-data/export, a read-only, paginated JSON export with format identifier micky-ai-personal-data and schema version 1. The response reports generated_at, offset, limit, per-domain counts, total_records, next_offset, and a truthful complete flag. The maximum page size is 500 records. Ordering is deterministic within each section: conversations, messages, then workspace items.

The export includes only explicitly mapped, user-visible fields for:
- saved conversation metadata;
- saved user/assistant message content and sequence;
- notes, tasks, and reminders, including due time, timezone, and completion state.

The browser control fetches every bounded page, validates the format/version and pagination progression, checks total counts do not change during the export, and refuses to download a partial result. It produces a JSON file locally in the browser.

## Explicit exclusions and limits

- Clinical reasoning sessions, observations, hypotheses, evidence, audit packages, and Stage 8 artifacts are not exported.
- Pending confirmations/clarifications, authorization/policy material, operation receipts, and internal challenge data are not exported.
- Retrieval-root paths and identities are excluded; confirmation records continue to use their separate established export surface.
- Import is not implemented and the downloaded JSON must not imply that it can be imported.
- Pagination is bounded and deterministic, but it is not a database-wide immutable snapshot. The UI checks record totals/counts across pages and fails closed if these change; a change to content that leaves counts unchanged can still occur during a long export. For the cleanest export, avoid editing or deleting records while the download is running.

## Tests added

tests/test_personal_data_export.py checks the v1 envelope, cross-section pagination, record totals and completion flags, required reminder fields, allowed record types/fields, and invalid query bounds. It also checks that the page exposes the export control and that the UI calls the local export endpoint and has explicit incomplete-export handling.

These tests have been committed but have not been independently run in a local checkout here. The GitHub Actions result for the commit is the live validation source; do not mark the task accepted until that run is green and the browser download is checked on the user's local app.

## Import boundary

Import remains a separate design task. It would require a schema/size policy, duplicate and conflict rules, explicit confirmation/authorization, transactionality, rollback, and recovery rules. No import endpoint or import button was added.

# Task 244 — Private User-Controlled Memory and Preferences

Repository: savitrex70/micky-ai
Scope: Stage 10.2 structured, explicit, local memory persistence.

## Data and API

The assistant_memory_entries table stores a typed memory or preference, title, content, and timestamps. A forward-only migration creates the table and index. Entries are global to the local application, not tied to one conversation, so an explicitly saved preference can remain available across conversations.

The /api/assistant/memories API supports bounded listing/search, create, partial update, single-entry deletion, and clear-all. Mutating operations require the configured local origin and strict request schemas. Responses use no-store/no-cache headers. Clear-all requires the exact phrase CLEAR ALL SAVED MEMORY. Obvious credential assignments and explicit patient identifiers are rejected server-side.

There is no automatic message ingestion. Clinical session content is never queried or imported by this facility. The current application has a single local-user security model and does not claim account-level multi-user isolation.

The API persistence layer is implemented; the user-facing memory interface and personal-data export integration are being completed in Stage 10.2 follow-up work.

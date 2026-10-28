# Task 245 — Stage 10.3 Local Information Retrieval

Repository: savitrex70/micky-ai
Scope: expose the existing safe local retrieval path through deterministic natural-language requests.

## Implementation

The intent interpreter maps explicit phrases such as “Search my authorized files for pharmacology” and “Find files containing my revision notes” to the existing workspace search grammar. The request then follows the existing saved-conversation requirement, server-side parser, authorization policy, and read-only workspace service. The interpreter does not read files or authorize a root.

The existing read service enumerates only explicitly authorized retrieval roots and calls the bounded retrieval implementation with the persisted root identity. The search uses the current allowlist (.txt, .md, .json, and .csv), existing byte/file/entry/root ceilings, secure platform traversal, and fail-closed policy. Search results include the local source path and a bounded snippet. Files are treated as untrusted data, never as policy or execution instructions.

No remote search, hosted inference, external indexing, telemetry, or hidden network fallback was introduced. Unsupported formats are not described as having been searched.

## Validation coverage

- `tests/test_intent_interpreter.py`: natural-language search matching, unsupported near-matches, conflicting requests, and command-separator rejection.
- `tests/test_workspace_api.py::test_confirmed_root_identity_is_persisted_and_used_by_retrieval`: authorizes a real temporary root, verifies direct retrieval, then verifies natural-language search against that same authorized root.
- `tests/test_assistant_retrieval.py`: allowlist, path containment, symlink/reparse behavior, unsupported formats, remote mounts, and resource ceilings.
- `tests/test_windows_retrieval.py` and `tests/test_native_offline_boundary.py`: native Windows retrieval and Python-level offline-boundary regressions.

The real-root integration test skips on systems where the required secure traversal backend is unavailable; that skip is not a claim that the backend worked on that host. Automated test evidence remains separate from real target-machine and OS-level offline acceptance.

## Limits

Natural-language matching is deterministic and narrow. A phrase outside the explicit grammar remains unsupported or requires clarification. PDF and other non-allowlisted formats are not searched. Search reads only the fixed number of authorized roots and matches allowed by the existing resource ceilings.

# Task 238 — Retrieval Adversarial and Runtime Offline Verification

**Starting revision:** cfa5ad97c52a8cdc7ee7ee6b9af7a9497a946ab3  
**Scope:** Explicitly authorized local retrieval, path containment, bounded traversal and reads, and Python-level runtime network-denial tests.  
**Status:** Implementation and tests are available for independent review; this document does not confer Stage 9 acceptance.

## Confirmed defects addressed

- **Authorized-root substitution:** retrieval previously resolved a stored root at search time and treated the new resolved target as authorized. A replaced root or ancestor symlink could redirect a previously approved path. Search now rejects symlink/junction roots and any root spelling whose current canonical path differs from the stored canonical spelling.
- **Path containment:** directories and files are re-resolved and checked against the approved root, the root device, and local-path policy immediately before processing. Symlinks and junctions are excluded. On platforms exposing O_NOFOLLOW, the final file component is opened without following a symlink.
- **Network paths and mounts:** shared path policy rejects UNC/device-style paths, mapped Windows network drives, and known remote filesystem types reported by Linux mountinfo. If Linux mount metadata cannot be read, retrieval fails closed. Root addition and retrieval use the same network-path decision.
- **Hard read bounds:** each file is capped at 1,000,000 bytes; the opened file descriptor is checked and only the remaining request byte budget is read before post-read size validation.
- **Total-work bounds:** a search is limited to 20,000,000 bytes read, 1,000 allowlisted files, and 10,000 directory entries; each root is limited to 250 visited directories. Traversal consumes bounded scandir batches rather than sorting an unbounded os.walk listing.
- **Special files:** retrieval skips non-regular files, including FIFOs, instead of opening a named pipe that could block indefinitely.

The supported format allowlist remains .txt, .md, .json, and .csv. No new provider, model, download, or network retrieval path was introduced.

## Test coverage

tests/test_assistant_retrieval.py covers root and ancestor symlink substitution, file/directory symlink containment, junction classification and fail-closed junction inspection, mocked Windows mapped-drive detection, UNC/device-path rejection, mocked Linux network-mount metadata, unavailable mount metadata, file/aggregate-byte ceilings, file/entry/directory ceilings, and POSIX FIFO avoidance. A real junction integration test is Windows-only and is skipped on non-Windows hosts.

tests/test_native_offline_boundary.py also runs local retrieval under the suite's existing Python network guards. The guards fail if the tested path attempts socket construction, socket-pair creation, connection creation, DNS resolution, urllib access, or HTTPConnection/HTTPSConnection calls.

## Verification limits

- The local execution container had no repository checkout or Git metadata, and outbound DNS/network access was unavailable. The source was reviewed against the verified remote main revision and the changes are committed directly to main through the repository API.
- The runtime offline test is a mocked Python-level boundary test, not proof of OS-wide network isolation. It does not verify network access attempted inside compiled dependency internals that bypass the guarded Python callables.
- The Windows junction integration test, mapped-drive OS behavior, and network-mount classification have not been validated on a real Windows host or a real network-mounted filesystem. Mocked tests validate policy logic only.
- No firewall-denied environment run, real browser walkthrough, PostgreSQL test, or Stage 9 acceptance is claimed by this task.

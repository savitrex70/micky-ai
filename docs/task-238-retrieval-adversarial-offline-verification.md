# Task 238 — Retrieval Adversarial and Runtime Offline Verification

**Original Task 238 starting revision:** cfa5ad97c52a8cdc7ee7ee6b9af7a9497a946ab3  
**Correction review base:** 440b2beef86bdfa63317c27d529bb51de0d3a8c5  
**Scope:** Explicitly authorized local retrieval, path containment, bounded traversal and reads, and Python-level runtime network-denial tests.  
**Status:** Implementation and tests are available for independent review; this document does not confer Stage 9 acceptance.

## Confirmed defects addressed

- **Authorized-root substitution:** the approval operation stores a stable identity from the opened directory (device, inode, and Linux mount ID). The executor rechecks the local-path policy and opens the stored absolute path component-by-component without following links; it registers the root only if the identity still matches the identity bound into the confirmation and operation receipt. Legacy roots without an identity fail closed and require removal and explicit reauthorization.
- **Filesystem TOCTOU:** retrieval requires Linux descriptor-relative directory traversal and no-follow flags. It scans pinned directory descriptors, uses descriptor-relative no-follow metadata/open calls, compares the entry's device/inode with the object actually opened, and requires every opened file/directory to remain on the approved root mount ID as well as its device. This rejects replacement by another object even on the same filesystem and rejects mount boundaries by descriptor identity, not only pathname classification.
- **Platform fail-closed behavior:** when the required Linux `openat2`, `O_NOFOLLOW`, directory-descriptor, `/proc/self/fdinfo` mount-identity, or mount-table primitives are unavailable, retrieval and new root authorizations fail closed rather than falling back to path-based opens. Windows junction and mapped-drive cases remain covered by policy tests but are not an active retrieval backend under this strict mode.
- **Network paths and mounts:** shared path policy rejects UNC/device-style paths, mapped Windows network drives, and known remote filesystem types reported by Linux mountinfo. If Linux mount metadata cannot be read, retrieval fails closed. Root addition and retrieval use the same network-path decision.
- **Hard read bounds:** each file is capped at 1,000,000 bytes; the opened file descriptor is checked and only the remaining request byte budget is read before post-read size validation.
- **Total-work bounds:** a search is limited to 20,000,000 bytes read, 1,000 allowlisted files, and 10,000 directory entries; each root is limited to 250 visited directories. Traversal consumes bounded scandir batches rather than sorting an unbounded os.walk listing.
- **Special files:** retrieval skips non-regular files, including FIFOs, instead of opening a named pipe that could block indefinitely.

The supported format allowlist remains .txt, .md, .json, and .csv. No new provider, model, download, or network retrieval path was introduced.

## Test coverage

tests/test_assistant_retrieval.py covers root and ancestor symlink substitution, root/ancestor replacement after validation, replacement of a directory between entry scan and descriptor-relative open, replacement of the root pathname between scan and file open while retaining pinned-directory authority, a same-filesystem symlink substitution before file open, network-policy change at the open seam, legacy roots with no identity, fail-closed behavior when secure openat2 is unavailable, file/directory symlink containment, junction classification and fail-closed junction inspection, mocked Windows mapped-drive detection, UNC/device-path rejection, mocked Linux network-mount metadata, unavailable mount metadata, file/aggregate-byte ceilings, file/entry/directory ceilings, and POSIX FIFO avoidance. The added race tests assert that no distinctive substituted content is returned. tests/test_workspace_api.py adds the real confirmation/API/executor flow for root substitution and a simulated network-policy change after preparation. A real junction integration test is Windows-only and is skipped on non-Windows hosts.

tests/test_native_offline_boundary.py also runs local retrieval under the suite's existing Python network guards. The guards fail if the tested path attempts socket construction, socket-pair creation, connection creation, DNS resolution, urllib access, or HTTPConnection/HTTPSConnection calls.

## Verification limits

- The local execution container had no repository checkout or Git metadata, and outbound DNS/network access was unavailable. Source files were read and updated directly through the repository API against the verified remote `main` history. Therefore no local working-tree status or local targeted pytest/Ruff/Black command could be run in this environment; only checks actually reported for the resulting SHA may be treated as executed.
- The runtime offline test is a mocked Python-level boundary test, not proof of OS-wide network isolation. It does not verify network access attempted inside compiled dependency internals that bypass the guarded Python callables.
- The Windows junction integration test, mapped-drive OS behavior, and network-mount classification have not been validated on a real Windows host or a real network-mounted filesystem. The network-policy race is deterministically simulated; it is not a live network-mount experiment. Mocked tests validate policy logic only. Linux mount containment is enforced using the opened object's mount ID, but no stress test with a concurrently mutated real mount namespace was performed.
- No firewall-denied environment run, real browser walkthrough, PostgreSQL test, or Stage 9 acceptance is claimed by this task.

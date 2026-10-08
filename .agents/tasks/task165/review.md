# Task 165: Canonical Stage 7 Vertical-Slice Evidence Bundle

Task 165 adds a pure aggregation boundary over the already-published Task 162 audit package, Task 163 vertical-slice verdict, and Task 164 consistency audit. The assembler receives three already-validated Pydantic objects, runs structural checks, and produces a single deterministic `bundle_status` (`READY` / `BLOCKED` / `UNAVAILABLE`). No child service is called, no fingerprint is recomputed, no database is written, and no provider is imported. All 41 tests pass.

**Watch for:** (1) confirmed — two plan-specified BLOCKED test cases are absent (`test_inconsistent_proposal_audit_produces_blocked_bundle` and `test_unavailable_slice163_prevents_ready`), though the underlying logic is present and covered obliquely; (2) confirmed — `__init__.py` adds Task 162/163/164 schema exports that did not exist before, making this commit the first time those are public; (3) possible — `DEGRADED` diagnostics from pkg162 falls into `UNAVAILABLE` not `BLOCKED`, which is the correct intent per the task spec but could surprise callers who conflate it with `UNHEALTHY`.

**Verdict**: APPROVED

---

## High-level view

The assembler is a static-method class with a single `assemble()` entry point that takes three typed Pydantic objects. Session binding (Step A) runs first and produces `STAGE_7_SESSION_MISMATCH` if any of the three IDs diverge or if one is an empty string; the resolved `session_id` is then `""` in all mismatch cases, preventing any foreign session leaking into the canonical identity. Source constants, fingerprint shape, and attribution follow in steps B–D, each capable of adding a structural finding code to `bundle_findings`. Status determination (Step E) evaluates BLOCKED conditions first, then the full READY conjunction, then falls back to UNAVAILABLE — in that strict priority order. Task 164 `INCONSISTENT` and `UNAVAILABLE` both fall to UNAVAILABLE, not BLOCKED, exactly as the task specifies.

The schema enforces structural coherence that the assembler alone cannot guarantee: `audit_available` must equal `(slice_audit_status != "UNAVAILABLE")`, `audit_consistent` must equal `(slice_audit_status == "CONSISTENT")`, all three finding lists must be sorted and deduplicated with matching counts, and a `READY` bundle must carry an empty `bundle_findings` and a non-empty `session_id`. Because the `_project` step validates the assembled dict through the schema before returning, any assembler bug that violates these invariants raises `ReasoningRunStage7EvidenceBundleContractError` rather than silently returning a malformed dict.

The `__init__.py` change exports `ReasoningRunStage7AuditPackageRead`, `ReasoningRunStage7VerticalSliceRead`, and `ReasoningRunStage7VerticalSliceAuditRead` for the first time alongside `ReasoningRunStage7EvidenceBundleRead`. These were previously internal to their respective modules; the public surface now includes them.

---

<details>
<summary>Issues (3)</summary>

1. **Missing BLOCKED test for inconsistent proposal audit** — The plan specifies `test_inconsistent_proposal_audit_produces_blocked_bundle` (Category 2, item 7 from the full plan listing). The logic in `assemble()` correctly gates on `pkg162.proposal_audit_status == "INCONSISTENT"` for BLOCKED, but no test exercises this specific path. Add a test that tampers `proposal_audit_status` to `"INCONSISTENT"` and asserts `bundle_status == "BLOCKED"`, analogous to `test_inconsistent_request_audit_produces_blocked_bundle`.

2. **Missing `test_unavailable_slice163_prevents_ready`** — The plan specifies a test for a genuinely UNAVAILABLE slice163. The current suite has `test_unavailable_audit164_prevents_ready` but no equivalent for an UNAVAILABLE Task 163 verdict. The logic prevents READY when `slice163.slice_status != "READY"`, but BLOCKED conditions in slice163 are covered by a different test; a case where slice163 is `UNAVAILABLE` (not `BLOCKED`) is not explicitly tested. The gap is narrow given the existing coverage but was explicitly called out in the plan.

3. **First-time public export of Task 162/163/164 schemas** — `__init__.py` now exports `ReasoningRunStage7AuditPackageRead`, `ReasoningRunStage7VerticalSliceRead`, and `ReasoningRunStage7VerticalSliceAuditRead` alongside the new `ReasoningRunStage7EvidenceBundleRead`. This is the first commit that makes those three schemas part of the module's public surface. Verify that this expansion of `__all__` is intentional for Task 165 and that any downstream code that imports from `rop.schemas` is not broken by the addition. No blocking concern — the exports are additive — but worth a deliberate sign-off.

</details>

---

<details>
<summary>Details</summary>

### BLOCKED/READY/UNAVAILABLE boundary correctness

The five BLOCKED conditions (`slice163.slice_status == "BLOCKED"`, `pkg162.admission_status == "BLOCKED"`, `pkg162.diagnostics_status == "UNHEALTHY"`, `pkg162.request_audit_status == "INCONSISTENT"`, `pkg162.proposal_audit_status == "INCONSISTENT"`) all appear verbatim in the `blocked` expression. BLOCKED is evaluated before READY, so a BLOCKED-flagged bundle can still carry structural `bundle_findings` without incorrectly falling to UNAVAILABLE.

`DEGRADED` diagnostics does not trigger BLOCKED — only `UNHEALTHY` does. A `DEGRADED` package produces UNAVAILABLE, not BLOCKED. Callers who conflate `DEGRADED` with `UNHEALTHY` will see unexpected UNAVAILABLE.

### Missing test coverage

The plan calls for `test_inconsistent_proposal_audit_produces_blocked_bundle` (tamper `pkg162` with `proposal_audit_status = "INCONSISTENT"`, assert BLOCKED). This test is absent. The condition is in the `blocked` expression but has no dedicated test exercising it, unlike the parallel `test_inconsistent_request_audit_produces_blocked_bundle`.

The plan also calls for `test_unavailable_slice163_prevents_ready`. UNAVAILABLE slice163 falls to UNAVAILABLE (not BLOCKED) — correct — but untested directly. The current suite reaches only the BLOCKED slice163 path and various indirect UNAVAILABLE paths.

### Session binding: all-empty-string edge case

The set-size check `len(ids) == 1` produces `len == 1` for three identical empty strings. The additional `pkg162.session_id != ""` guard closes this: three empty strings correctly produce `STAGE_7_SESSION_MISMATCH` and `session_id = ""`. Confirmed by `test_session_id_empty_string_prevents_ready`.

### Schema coherence rules

The `model_validator` enforces that `audit_available == (slice_audit_status != "UNAVAILABLE")` and `audit_consistent == (slice_audit_status == "CONSISTENT")`. These constraints mean a BLOCKED bundle whose Task 164 input happens to carry `slice_audit_status = "UNAVAILABLE"` must have `audit_available = False` in the bundle — the assembler propagates `audit164.available` verbatim from the already-validated `ReasoningRunStage7VerticalSliceAuditRead`, which already enforces this derivation in its own contract, so no new gap is introduced.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|---|---|
| `src/rop/schemas/reasoning_run_stage_7_evidence_bundle.py` | New: `ReasoningRunStage7EvidenceBundleRead` schema with coherence validator |
| `src/rop/services/reasoning_run_stage_7_evidence_bundle.py` | New: `ReasoningRunStage7EvidenceBundleService.assemble()` aggregation assembler and `ReasoningRunStage7EvidenceBundleContractError` |
| `tests/test_reasoning_run_stage_7_evidence_bundle.py` | New: 41 tests across 9 categories covering READY/BLOCKED/UNAVAILABLE paths, session binding, finding preservation, determinism, schema strictness, and source hygiene |
| `src/rop/schemas/__init__.py` | Added exports for `ReasoningRunStage7EvidenceBundleRead` plus first-time exports for Task 162/163/164 schemas |

Full diff: `git show f630412c23766d49fd1656855bb0b891dc415242`

</details>

# Implementation Plan: Task 165 Schema Hardening

## Overview

This plan hardens `ReasoningRunStage7EvidenceBundleRead` to independently enforce all essential bundle invariants, making it impossible to bypass service-level checks by calling `model_validate()` directly. The schema will mirror every structural check performed by `ReasoningRunStage7EvidenceBundleService.assemble()` using Pydantic `model_validator(mode='after')`.

## Implementation Strategy

The existing `_coherent_bundle` validator currently checks:
- Finding count/sorted/dedup for all three finding lists
- Provider/model parity
- Derived field coherence (audit_available, audit_consistent)
- Basic READY session/findings check

We will **extend** (not replace) this validator with all missing invariants documented below. To avoid circular imports, canonical source constants will be defined as string literals directly in the schema file rather than importing from service modules.

---

# Implementation Plan

- [ ] 1. **Extend the schema validator with canonical source enforcement**

      Modify `c:\Users\micha\Desktop\rop\micky-ai\src\rop\schemas\reasoning_run_stage_7_evidence_bundle.py` to define the four canonical source constants as module-level string literals at the top of the file (after imports, before the class definition). Then add checks in `_coherent_bundle` to validate that `t162_audit_source`, `certification_source`, `audit_source`, and `bundle_source` exactly match their canonical values.
      
      The constants to define:
      ```python
      # Canonical source identifiers (defined here to avoid circular imports)
      _REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162 = "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_TASK_162"
      _REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163 = "REASONING_RUN_STAGE_7_VERTICAL_SLICE_TASK_163"
      _REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164 = "REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_TASK_164"
      _REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165 = "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_TASK_165"
      ```
      
      Add validation checks in `_coherent_bundle`:
      - `t162_audit_source` must equal `_REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162`
      - `certification_source` must equal `_REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163`
      - `audit_source` must equal `_REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164`
      - `bundle_source` must equal `_REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165`
      
      Files: `c:\Users\micha\Desktop\rop\micky-ai\src\rop\schemas\reasoning_run_stage_7_evidence_bundle.py`
      
      Verify: Run `pytest tests/test_reasoning_run_stage_7_evidence_bundle.py -v` and confirm all existing tests still pass.

- [ ] 2. **Add request fingerprint shape validation**

      Add a regex pattern and validation logic to `_coherent_bundle` that enforces:
      - When `request_fingerprint` is not None, it must be exactly 64 lowercase hexadecimal characters (fullmatch `[0-9a-f]{64}`)
      - When `bundle_status == "READY"`, `request_fingerprint` must be present (not None) and pass the shape check
      
      Add the regex pattern as a module-level constant:
      ```python
      import re
      _REQUEST_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
      ```
      
      Files: `c:\Users\micha\Desktop\rop\micky-ai\src\rop\schemas\reasoning_run_stage_7_evidence_bundle.py`
      
      Verify: Run `pytest tests/test_reasoning_run_stage_7_evidence_bundle.py::test_malformed_request_fingerprint_prevents_ready -v` after implementing the test in step 5, and confirm ValidationError is raised for malformed fingerprints.

- [ ] 3. **Add comprehensive READY coherence validation**

      Extend `_coherent_bundle` to enforce that when `bundle_status == "READY"`, ALL of the following conditions hold:
      - `session_id` is non-empty string (already exists)
      - `slice_status == "READY"`
      - `admission_status == "ADMITTED"`
      - `diagnostics_status == "HEALTHY"`
      - `request_audit_status == "CONSISTENT"`
      - `proposal_audit_status == "CONSISTENT"`
      - `request_fingerprint` is present and canonical (added in step 2)
      - `provider_name` is present and not whitespace-only
      - `model_name` is present and not whitespace-only
      - `finding_count == 0`
      - `findings == []`
      - `slice_audit_status == "CONSISTENT"`
      - `audit_available is True`
      - `audit_consistent is True`
      - `published_slice_status == "READY"`
      - `expected_slice_status == "READY"`
      - `audit_finding_count == 0`
      - `audit_findings == []`
      - All four source fields are canonical (added in step 1)
      - `bundle_finding_count == 0`
      - `bundle_findings == []` (already exists)
      
      Files: `c:\Users\micha\Desktop\rop\micky-ai\src\rop\schemas\reasoning_run_stage_7_evidence_bundle.py`
      
      Verify: Run `pytest tests/test_reasoning_run_stage_7_evidence_bundle.py::test_genuine_ready_bundle_is_ready -v` and confirm it passes with the hardened validator.

- [ ] 4. **Add BLOCKED and UNAVAILABLE coherence validation**

      Extend `_coherent_bundle` with two additional checks:
      
      **BLOCKED coherence:** When `bundle_status == "BLOCKED"`, at least ONE of the following must hold:
      - `slice_status == "BLOCKED"`
      - `admission_status == "BLOCKED"`
      - `diagnostics_status == "UNHEALTHY"`
      - `request_audit_status == "INCONSISTENT"`
      - `proposal_audit_status == "INCONSISTENT"`
      
      **UNAVAILABLE contradiction:** When `bundle_status == "UNAVAILABLE"`, the bundle must NOT simultaneously satisfy all READY conditions. This prevents a structurally-perfect bundle from declaring itself UNAVAILABLE. Check: if bundle_status is UNAVAILABLE but all READY conditions would be satisfied, raise ValueError.
      
      Files: `c:\Users\micha\Desktop\rop\micky-ai\src\rop\schemas\reasoning_run_stage_7_evidence_bundle.py`
      
      Verify: Run `pytest tests/test_reasoning_run_stage_7_evidence_bundle.py -v -k "blocked or unavailable"` and confirm both genuine BLOCKED and genuine UNAVAILABLE bundles pass validation, while contradictory states raise ValidationError.

- [ ] 5. **Add Category 10 direct schema validation tests**

      Create a new test category at the end of `c:\Users\micha\Desktop\rop\micky-ai\tests\test_reasoning_run_stage_7_evidence_bundle.py` with comprehensive direct schema validation tests. These tests bypass `assemble()` and call `ReasoningRunStage7EvidenceBundleRead.model_validate()` directly on tampered dict payloads.
      
      Add the following test groups under a "Category 10 — Direct schema validation (bypass protection)" comment:
      
      **Source forgery tests (4 tests):**
      - `test_schema_rejects_forged_t162_audit_source()` - tamper `t162_audit_source` to "FORGED" → ValidationError
      - `test_schema_rejects_forged_certification_source()` - tamper `certification_source` to "FORGED" → ValidationError
      - `test_schema_rejects_forged_audit_source()` - tamper `audit_source` to "FORGED" → ValidationError
      - `test_schema_rejects_forged_bundle_source()` - tamper `bundle_source` to "FORGED" → ValidationError
      
      **Fingerprint forgery tests (9 tests):**
      - `test_schema_rejects_ready_with_none_fingerprint()` - `request_fingerprint=None` → ValidationError
      - `test_schema_rejects_ready_with_empty_fingerprint()` - `request_fingerprint=""` → ValidationError
      - `test_schema_rejects_ready_with_short_fingerprint()` - `request_fingerprint="a"*63` → ValidationError
      - `test_schema_rejects_ready_with_long_fingerprint()` - `request_fingerprint="a"*65` → ValidationError
      - `test_schema_rejects_ready_with_nonhex_fingerprint()` - `request_fingerprint="g"*64` → ValidationError
      - `test_schema_rejects_ready_with_uppercase_fingerprint()` - `request_fingerprint="A"*64` → ValidationError
      - `test_schema_rejects_ready_with_mixed_case_fingerprint()` - `request_fingerprint=("a"*32 + "A"*32)` → ValidationError
      - `test_schema_rejects_ready_with_fingerprint_trailing_newline()` - `request_fingerprint=("a"*63 + "\n")` → ValidationError
      - `test_schema_rejects_ready_with_fingerprint_whitespace()` - `request_fingerprint=(" " + "a"*64)` → ValidationError
      
      **READY structural forgery tests (18 tests):**
      - `test_schema_rejects_ready_with_blocked_slice_status()` - tamper `slice_status="BLOCKED"` → ValidationError
      - `test_schema_rejects_ready_with_blocked_admission()` - tamper `admission_status="BLOCKED"` → ValidationError
      - `test_schema_rejects_ready_with_unhealthy_diagnostics()` - tamper `diagnostics_status="UNHEALTHY"` → ValidationError
      - `test_schema_rejects_ready_with_inconsistent_request_audit()` - tamper `request_audit_status="INCONSISTENT"` → ValidationError
      - `test_schema_rejects_ready_with_inconsistent_proposal_audit()` - tamper `proposal_audit_status="INCONSISTENT"` → ValidationError
      - `test_schema_rejects_ready_with_none_provider_name()` - tamper `provider_name=None, model_name=None` → ValidationError
      - `test_schema_rejects_ready_with_whitespace_provider_name()` - tamper `provider_name="  ", model_name="  "` → ValidationError
      - `test_schema_rejects_ready_with_none_model_name()` - tamper `model_name=None, provider_name=None` → ValidationError
      - `test_schema_rejects_ready_with_nonzero_finding_count()` - tamper `finding_count=1, findings=["X"]` → ValidationError
      - `test_schema_rejects_ready_with_nonempty_findings()` - tamper `findings=["X"], finding_count=1` → ValidationError
      - `test_schema_rejects_ready_with_inconsistent_slice_audit()` - tamper `slice_audit_status="INCONSISTENT", audit_available=True, audit_consistent=False` → ValidationError
      - `test_schema_rejects_ready_with_audit_unavailable()` - tamper `slice_audit_status="UNAVAILABLE", audit_available=False, audit_consistent=False` → ValidationError
      - `test_schema_rejects_ready_with_blocked_published_slice()` - tamper `published_slice_status="BLOCKED"` → ValidationError
      - `test_schema_rejects_ready_with_blocked_expected_slice()` - tamper `expected_slice_status="BLOCKED"` → ValidationError
      - `test_schema_rejects_ready_with_nonzero_audit_finding_count()` - tamper `audit_finding_count=1, audit_findings=["X"]` → ValidationError
      - `test_schema_rejects_ready_with_nonempty_audit_findings()` - tamper `audit_findings=["X"], audit_finding_count=1` → ValidationError
      - `test_schema_rejects_ready_with_none_request_fingerprint()` - tamper `request_fingerprint=None` → ValidationError (duplicate of fingerprint test, can merge)
      - `test_schema_rejects_ready_with_empty_session_id()` - tamper `session_id=""` → ValidationError
      
      **BLOCKED forgery tests (2 tests):**
      - `test_schema_rejects_blocked_without_blocking_conditions()` - create bundle with `bundle_status="BLOCKED"` but all status fields are non-blocking (slice_status="READY", admission_status="ADMITTED", diagnostics_status="HEALTHY", request_audit_status="CONSISTENT", proposal_audit_status="CONSISTENT") → ValidationError
      - `test_schema_accepts_genuine_blocked_bundle()` - create genuine BLOCKED bundle with `slice_status="BLOCKED"` → must NOT raise ValidationError
      
      **UNAVAILABLE contradiction tests (1 test):**
      - `test_schema_rejects_unavailable_with_all_ready_conditions()` - create bundle with `bundle_status="UNAVAILABLE"` but all READY conditions satisfied (canonical sources, valid fingerprint, no findings, etc.) → ValidationError
      
      **Genuine states acceptance tests (3 tests):**
      - `test_schema_accepts_genuine_ready_bundle_direct()` - produce a READY bundle via `_assemble()`, then validate the dict directly with `ReasoningRunStage7EvidenceBundleRead.model_validate()` → must pass
      - `test_schema_accepts_genuine_blocked_bundle_direct()` - produce a BLOCKED bundle via `_assemble()`, validate directly → must pass
      - `test_schema_accepts_genuine_unavailable_bundle_direct()` - produce an UNAVAILABLE bundle (e.g., with a bundle finding like session mismatch), validate directly → must pass
      
      Each test follows this pattern:
      ```python
      def test_schema_rejects_X():
          _, pkg, verdict, audit = _produce_ready_inputs("test label")
          valid_bundle = _assemble(pkg, verdict, audit)
          assert valid_bundle["bundle_status"] == "READY"
          
          tampered = _with(valid_bundle, field_name=bad_value, ...)
          
          with pytest.raises(ValidationError):
              ReasoningRunStage7EvidenceBundleRead.model_validate(tampered)
      ```
      
      Files: `c:\Users\micha\Desktop\rop\micky-ai\tests\test_reasoning_run_stage_7_evidence_bundle.py`
      
      Verify: Run `pytest tests/test_reasoning_run_stage_7_evidence_bundle.py -v -k "Category_10 or schema_rejects or schema_accepts"` and confirm all new tests pass.

- [ ] 6. **Run full test suite and verify no regressions**

      Run the complete test suite for the evidence bundle module to ensure all existing tests still pass and the new schema validation is working correctly across all scenarios.
      
      Files: None (verification only)
      
      Verify: Run `pytest tests/test_reasoning_run_stage_7_evidence_bundle.py -v` and confirm all tests pass (existing + new Category 10 tests). The output should show approximately 50+ tests passing with no failures.

---

## Design Decisions

### 1. Canonical source constants in the schema

**Decision:** Define canonical source string literals directly in the schema file rather than importing from service modules.

**Rationale:** The service already imports the schema (`ReasoningRunStage7EvidenceBundleRead`). If the schema imports back from the service, Python will raise a circular import error. String literals avoid this entirely while maintaining type safety and validation strength. The constants are simple string values that never change, so duplication is safe.

### 2. Extending vs replacing the validator

**Decision:** Extend the existing `_coherent_bundle` validator rather than creating multiple validators.

**Rationale:** Pydantic executes validators in definition order. A single comprehensive validator keeps all invariant checks in one place, makes the validation logic easier to read, and avoids potential ordering dependencies between multiple validators.

### 3. BLOCKED validation strategy

**Decision:** Check that at least ONE blocking condition holds, rather than checking all possible BLOCKED scenarios.

**Rationale:** The service uses an explicit OR condition for BLOCKED status. The schema mirrors this logic: a BLOCKED bundle must have evidence of at least one blocking condition. This prevents forging a BLOCKED status on a bundle that has no actual blocking evidence.

### 4. UNAVAILABLE validation strategy

**Decision:** When bundle_status is UNAVAILABLE, verify that NOT ALL READY conditions hold simultaneously.

**Rationale:** UNAVAILABLE is the fallback state for "everything else" in the service logic. A bundle that satisfies every READY condition but declares UNAVAILABLE is contradictory and likely forged. The validator prevents this specific contradiction while allowing legitimate UNAVAILABLE bundles (those with findings, missing data, session mismatches, etc.).

### 5. Test organization

**Decision:** Add Category 10 tests that call `model_validate()` directly, separate from the existing service-based tests.

**Rationale:** Existing tests verify the service's `assemble()` behavior. The new tests verify that schema-level validation catches bypass attempts. Separating them makes the purpose of each test category clear and preserves the existing test structure.

### 6. Fingerprint validation pattern

**Decision:** Use fullmatch regex `[0-9a-f]{64}` identical to the service's `_canonical_fingerprint()` check.

**Rationale:** The schema must enforce exactly the same fingerprint shape as the service. Using the same regex pattern (with fullmatch semantics) ensures consistency and prevents any discrepancy between service-level and schema-level validation.

---

## Verification Strategy

After each step:
1. Run the specific test category to verify the change works
2. Run the full test suite to verify no regressions
3. Confirm ValidationError messages are clear and actionable

Final verification:
- All existing tests pass (Categories 1-9)
- All new Category 10 tests pass
- A genuine READY bundle passes direct schema validation
- A tampered READY bundle with any single forged field fails validation
- BLOCKED and UNAVAILABLE bundles with valid structures pass validation
- Contradictory bundles (BLOCKED with no blocking evidence, UNAVAILABLE with all READY evidence) fail validation

---

## Risk Mitigation

**Circular import risk:** Avoided by defining canonical constants as string literals in the schema file.

**Performance impact:** The extended validator runs only during `model_validate()`, not on every field access. The checks are simple comparisons and have negligible performance cost.

**Test maintenance:** Category 10 tests are isolated and follow a consistent pattern. Adding new invariants in the future requires adding corresponding tests in the same section.

**Backward compatibility:** The schema changes are purely additive (stricter validation). Bundles produced by the service will continue to pass validation. Invalid bundles that previously passed schema validation (but failed at the service level) will now correctly fail at the schema level.

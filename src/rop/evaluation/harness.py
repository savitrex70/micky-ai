"""Task 206: deterministic baseline evaluation harness.

Loads a versioned case set, executes the actual deterministic
composition service through its public contract, scores
predeclared metrics, and emits a deterministic machine-readable
report. Every valid and invalid-input case is evaluated twice per
run on fresh service instances; any divergence fails determinism.
Cross-invocation report-byte equality is verified separately by
rerunning the command. Unexpected errors mark the run invalid,
never silently dropped. No model, provider, network, training,
GPU, database session, or hosted service is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from rop.evaluation.cases import (
    CASE_SET_VERSION,
    EvaluationCase,
    EvaluationCaseSet,
)
from rop.services.native_composition import (
    NativeCompositionCondition,
    NativeCompositionContractError,
    NativeCompositionRule,
    NativeCompositionService,
    NativeContradictionRule,
    NativeEvidenceRequirement,
)

EVALUATION_PROTOCOL_VERSION = "1.1"
REPORT_SCHEMA_VERSION = "1.1"

BASELINE_REVISION_UNRESOLVED = "unresolved-baseline"

_SYNTHETIC_DISCLAIMER = (
    "Synthetic-only contract and behavior testing. These results "
    "establish no real-world accuracy and no clinical validity. "
    "Real-data evaluation remains blocked pending authorized data."
)

_PENDING_REASON = "pending task/data approval; blocks final model acceptance"


class EvaluationHarnessError(Exception):
    """A case-file or harness-usage failure with a non-sensitive message."""


class NonDeterministicEvaluation(EvaluationHarnessError):
    """A repeated execution diverged; the run cannot be trusted."""


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical bytes for hashing: sorted keys, compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def case_set_sha256(case_set: EvaluationCaseSet) -> str:
    """Hash the canonical case-set bytes (sorted case-ID evaluation order)."""
    ordered = case_set.model_dump(mode="json")
    ordered["cases"] = sorted(ordered["cases"], key=lambda case: case["case_id"])
    return hashlib.sha256(canonical_json_bytes(ordered)).hexdigest()


def _build_service(case: EvaluationCase) -> NativeCompositionService:
    """Build the case's composition service, failing closed on bad config."""
    try:
        rules = tuple(
            NativeCompositionRule(
                rule_id=decl.rule_id,
                task_id=decl.task_id,
                condition=NativeCompositionCondition(
                    required_evidence_type=decl.condition.required_evidence_type,
                    min_evidence_count=decl.condition.min_evidence_count,
                    expected_content=decl.condition.expected_content,
                ),
                uncertainty=decl.uncertainty,
            )
            for decl in case.support_rules
        )
        contradictions = tuple(
            NativeContradictionRule(
                rule_id=decl.rule_id,
                task_id=decl.task_id,
                affirming_content=decl.affirming_content,
                denying_content=decl.denying_content,
                required_evidence_type=decl.required_evidence_type,
                min_evidence_count=decl.min_evidence_count,
                uncertainty=decl.uncertainty,
            )
            for decl in case.contradiction_rules
        )
        requirements = tuple(
            NativeEvidenceRequirement(
                requirement_id=decl.requirement_id,
                task_id=decl.task_id,
                required_evidence_type=decl.required_evidence_type,
                expected_content=decl.expected_content,
            )
            for decl in case.requirements
        )
        return NativeCompositionService(
            rules=rules, contradiction_rules=contradictions, requirements=requirements
        )
    except (ValueError, TypeError, NativeCompositionContractError) as exc:
        raise EvaluationHarnessError(
            f"case '{case.case_id}': composition configuration is invalid"
        ) from exc


def load_case_set(data: Mapping[str, Any]) -> EvaluationCaseSet:
    """Validate a raw case-set mapping, whole or not at all.

    Raises ``EvaluationHarnessError`` with a non-sensitive message
    for any structural problem, duplicate identifiers, or
    composition configuration the service contracts reject.
    """
    if not isinstance(data, Mapping):
        raise EvaluationHarnessError("case file must contain a JSON object")
    try:
        case_set = EvaluationCaseSet.model_validate(dict(data))
    except ValidationError as exc:
        raise EvaluationHarnessError(
            f"case file failed validation ({len(exc.errors())} problem(s) rejected)"
        ) from exc
    for case in case_set.cases:
        if case.category != "invalid-input":
            _build_service(case)
    return case_set


class MetricValue(BaseModel):
    """One ratio metric with an explicit denominator and null rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    numerator: int
    denominator: int
    value: float | None


def _ratio(numerator: int, denominator: int) -> MetricValue:
    if denominator == 0:
        return MetricValue(numerator=numerator, denominator=denominator, value=None)
    return MetricValue(
        numerator=numerator, denominator=denominator, value=numerator / denominator
    )


class UnsupportedReferences(BaseModel):
    """Emitted evidence references absent from the validated input set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    emitted: int
    unsupported: int
    rate: float
    denominator_zero: bool
    target_met: bool


class CategoryOutcome(BaseModel):
    """Counts for one result category (contradiction/abstention/insufficiency)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected: int
    correct: int
    incorrect: int


class DeterminismOutcome(BaseModel):
    """Repeat-execution evidence for the run.

    Every case requires one repeat check: both executions must
    finish on separately constructed service instances with
    identical normalized outcomes. The gate passes only when every
    required check completed with no divergence and no
    repeat-execution error; a missing or failed check fails the
    gate instead of counting as deterministic.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repeat_passed: bool
    checks_attempted: int
    checks_completed: int
    diverged: int


class ThresholdStatus(BaseModel):
    """One predeclared gate and its disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold_id: str
    status: Literal["passed", "failed", "pending"]
    detail: str


class ModelAcceptance(BaseModel):
    """Learned-component acceptance state (never accepted by this harness)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluated: Literal[False]
    accepted: Literal[False]
    reason: str


class EvaluationReport(BaseModel):
    """Deterministic machine-readable baseline evaluation report (v1.0)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_schema_version: Literal["1.1"]
    protocol_version: Literal["1.1"]
    baseline_revision: str
    case_set_id: str
    case_set_version: Literal["1.0"]
    case_set_sha256: str
    case_count: int
    total_cases: int
    valid_cases: int
    invalid_input_cases: int
    valid_passed: int
    valid_failed: int
    invalid_passed: int
    invalid_failed: int
    errored: int
    run_valid: bool
    run_errors: tuple[str, ...]
    status_agreement: MetricValue
    reason_agreement: MetricValue
    evidence_exactness: MetricValue
    unsupported_references: UnsupportedReferences
    contradiction: CategoryOutcome
    abstention: CategoryOutcome
    insufficiency: CategoryOutcome
    status_distribution: dict[str, int]
    abstention_rate: MetricValue
    determinism: DeterminismOutcome
    thresholds: tuple[ThresholdStatus, ...]
    model_acceptance: ModelAcceptance
    synthetic_only: Literal[True]
    synthetic_disclaimer: str


def report_sha256(report: EvaluationReport) -> str:
    """Hash the canonical report bytes (no timestamps exist to exclude)."""
    return hashlib.sha256(
        canonical_json_bytes(report.model_dump(mode="json"))
    ).hexdigest()


def _input_evidence_ids(case: EvaluationCase) -> set[str]:
    assert case.binding is not None
    return {str(record.evidence_id) for record in case.binding.evidence}


def _evaluate_valid_case(case: EvaluationCase) -> dict[str, Any]:
    """Evaluate one valid case twice on separately built services.

    Each execution constructs its own identically configured
    service instance, so no mutable service state is shared between
    repeats. Service construction failures are evaluation failures.
    Unexpected errors fail closed; divergence fails determinism.
    """
    assert case.binding is not None
    try:
        first = _build_service(case).compose(case.binding)
        second = _build_service(case).compose(case.binding)
    except Exception as exc:
        raise EvaluationHarnessError(
            f"case '{case.case_id}': unexpected evaluation error "
            f"({type(exc).__name__})"
        ) from exc
    if first != second:
        raise NonDeterministicEvaluation(
            f"case '{case.case_id}': non-deterministic evaluation"
        )
    actual_supporting = {str(value) for value in first["supporting_evidence_ids"]}
    actual_contradicting = {str(value) for value in first["contradicting_evidence_ids"]}
    actual_missing = {str(value) for value in first["missing_information_ids"]}
    expected_supporting = {str(value) for value in case.expected_supporting}
    expected_contradicting = {str(value) for value in case.expected_contradicting}
    expected_missing = set(case.expected_missing)
    refs_exact = (
        actual_supporting == expected_supporting
        and actual_contradicting == expected_contradicting
        and actual_missing == expected_missing
    )
    emitted = actual_supporting | actual_contradicting
    allowed = _input_evidence_ids(case)
    return {
        "status_match": first["status"] == case.expected_status,
        "reason_match": first["reason_code"] == case.expected_reason,
        "refs_exact": refs_exact,
        "actual_status": first["status"],
        "unsupported": len(emitted - allowed),
        "emitted": len(emitted),
    }


def _evaluate_invalid_case(case: EvaluationCase) -> dict[str, Any]:
    """An invalid-input case passes only when the typed error is raised.

    Executed twice on fresh service instances like valid cases; any
    divergence fails determinism instead of being trusted.
    """
    assert case.raw_binding is not None and case.expect_error is not None
    first = _run_invalid_once(case)
    second = _run_invalid_once(case)
    if first != second:
        raise NonDeterministicEvaluation(
            f"case '{case.case_id}': non-deterministic evaluation"
        )
    if first["error"] is not None:
        raise EvaluationHarnessError(
            f"case '{case.case_id}': unexpected evaluation error ({first['error']})"
        )
    return {"passed": first["passed"]}


def _run_invalid_once(case: EvaluationCase) -> dict[str, Any]:
    """One normalized invalid-input execution; never raises for outcomes."""
    assert case.raw_binding is not None and case.expect_error is not None
    service = NativeCompositionService()
    try:
        service.compose(case.raw_binding)
    except NativeCompositionContractError as exc:
        return {
            "passed": exc.invariant == case.expect_error,
            "invariant": exc.invariant,
            "error": None,
        }
    except Exception as exc:
        return {"passed": False, "invariant": None, "error": type(exc).__name__}
    return {"passed": False, "invariant": None, "error": None}


def evaluate_case_set(
    case_set: EvaluationCaseSet, *, baseline_revision: str
) -> EvaluationReport:
    """Evaluate every case and score the predeclared metrics."""
    if not baseline_revision or len(baseline_revision) > 120:
        raise EvaluationHarnessError("baseline revision is invalid")
    ordered = sorted(case_set.cases, key=lambda case: case.case_id)
    valid = [case for case in ordered if case.category != "invalid-input"]
    invalid = [case for case in ordered if case.category == "invalid-input"]

    run_errors: list[str] = []
    diverged = 0
    repeat_completed = 0
    status_hits = 0
    reason_hits = 0
    exact_hits = 0
    failed = 0
    emitted_total = 0
    unsupported_total = 0
    abstained = 0
    distribution = {
        "SUPPORTED": 0,
        "CONTRADICTED": 0,
        "INSUFFICIENT": 0,
        "ABSTAINED": 0,
    }
    contradiction = {"expected": 0, "correct": 0, "incorrect": 0}
    abstention = {"expected": 0, "correct": 0, "incorrect": 0}
    insufficiency = {"expected": 0, "correct": 0, "incorrect": 0}

    for case in valid:
        assert case.expected_status is not None
        try:
            outcome = _evaluate_valid_case(case)
        except NonDeterministicEvaluation as exc:
            run_errors.append(str(exc))
            diverged += 1
            failed += 1
            continue
        except EvaluationHarnessError as exc:
            run_errors.append(str(exc))
            failed += 1
            continue
        repeat_completed += 1
        if outcome["status_match"]:
            status_hits += 1
        else:
            failed += 1
        if outcome["reason_match"]:
            reason_hits += 1
        if outcome["refs_exact"]:
            exact_hits += 1
        emitted_total += outcome["emitted"]
        unsupported_total += outcome["unsupported"]
        distribution[outcome["actual_status"]] += 1
        if outcome["actual_status"] == "ABSTAINED":
            abstained += 1
        if case.expected_status == "CONTRADICTED":
            contradiction["expected"] += 1
            if outcome["actual_status"] == "CONTRADICTED" and outcome["refs_exact"]:
                contradiction["correct"] += 1
            else:
                contradiction["incorrect"] += 1
        elif case.expected_status == "ABSTAINED":
            abstention["expected"] += 1
            if (
                outcome["actual_status"] == "ABSTAINED"
                and outcome["reason_match"]
                and outcome["refs_exact"]
            ):
                abstention["correct"] += 1
            else:
                abstention["incorrect"] += 1
        elif case.expected_status == "INSUFFICIENT":
            insufficiency["expected"] += 1
            if outcome["actual_status"] == "INSUFFICIENT" and outcome["refs_exact"]:
                insufficiency["correct"] += 1
            else:
                insufficiency["incorrect"] += 1
        if (
            outcome["actual_status"] == "CONTRADICTED"
            and case.expected_status != "CONTRADICTED"
        ):
            contradiction["incorrect"] += 1

    invalid_passed = 0
    invalid_failed = 0
    for case in invalid:
        try:
            if _evaluate_invalid_case(case)["passed"]:
                invalid_passed += 1
            else:
                invalid_failed += 1
        except NonDeterministicEvaluation as exc:
            run_errors.append(str(exc))
            diverged += 1
            invalid_failed += 1
            continue
        except EvaluationHarnessError as exc:
            run_errors.append(str(exc))
            invalid_failed += 1
            continue
        repeat_completed += 1

    run_valid = not run_errors
    # The determinism gate passes only when every required case
    # completed its repeat check with no divergence and no
    # repeat-execution error. Missing or failed checks fail the
    # gate; they never count as deterministic. Cross-invocation
    # report-byte equality is verified separately by rerunning the
    # command.
    total_cases = len(ordered)
    determinism_passed = diverged == 0 and repeat_completed == total_cases
    n_valid = len(valid)
    status_metric = _ratio(status_hits, n_valid)
    unsupported_rate = (unsupported_total / emitted_total) if emitted_total else 0.0
    unsupported = UnsupportedReferences(
        emitted=emitted_total,
        unsupported=unsupported_total,
        rate=unsupported_rate,
        denominator_zero=emitted_total == 0,
        target_met=unsupported_total == 0,
    )

    def _threshold(
        threshold_id: str, status: Literal["passed", "failed", "pending"], detail: str
    ) -> ThresholdStatus:
        return ThresholdStatus(threshold_id=threshold_id, status=status, detail=detail)

    thresholds = (
        _threshold(
            "unsupported-references-zero",
            "passed" if unsupported_total == 0 else "failed",
            "approved integrity gate: emitted references absent from "
            "validated inputs must be zero",
        ),
        _threshold(
            "invalid-input-all-pass",
            "passed" if (len(invalid) > 0 and invalid_failed == 0) else "failed",
            "approved integrity gate: every invalid-input case raises "
            "its expected typed error",
        ),
        _threshold(
            "run-valid",
            "passed" if run_valid else "failed",
            "approved integrity gate: no unexpected evaluation errors",
        ),
        _threshold(
            "baseline-self-consistency",
            "passed" if (status_metric.value == 1.0) else "failed",
            "provisional operational target: synthetic status agreement "
            "is 1.0 (guards fixture and implementation drift)",
        ),
        _threshold(
            "determinism",
            "passed" if determinism_passed else "failed",
            "provisional operational target: every required repeat "
            "check completed with identical outcomes",
        ),
        _threshold("model-valid-contract-rate", "pending", _PENDING_REASON),
        _threshold("model-fabricated-refs-zero", "pending", _PENDING_REASON),
        _threshold("model-false-contradiction-rate", "pending", _PENDING_REASON),
        _threshold("model-abstention-respect", "pending", _PENDING_REASON),
        _threshold("model-accuracy-vs-baseline", "pending", _PENDING_REASON),
        _threshold("model-repeatability-offline", "pending", _PENDING_REASON),
        _threshold("model-resource-limits", "pending", _PENDING_REASON),
    )

    return EvaluationReport(
        report_schema_version=REPORT_SCHEMA_VERSION,
        protocol_version=EVALUATION_PROTOCOL_VERSION,
        baseline_revision=baseline_revision,
        case_set_id=case_set.case_set_id,
        case_set_version=CASE_SET_VERSION,
        case_set_sha256=case_set_sha256(case_set),
        case_count=len(ordered),
        total_cases=len(ordered),
        valid_cases=n_valid,
        invalid_input_cases=len(invalid),
        valid_passed=status_hits,
        valid_failed=failed,
        invalid_passed=invalid_passed,
        invalid_failed=invalid_failed,
        errored=len(run_errors),
        run_valid=run_valid,
        run_errors=tuple(sorted(run_errors)),
        status_agreement=status_metric,
        reason_agreement=_ratio(reason_hits, n_valid),
        evidence_exactness=_ratio(exact_hits, n_valid),
        unsupported_references=unsupported,
        contradiction=CategoryOutcome(**contradiction),
        abstention=CategoryOutcome(**abstention),
        insufficiency=CategoryOutcome(**insufficiency),
        status_distribution=distribution,
        abstention_rate=_ratio(abstained, n_valid),
        determinism=DeterminismOutcome(
            repeat_passed=determinism_passed,
            checks_attempted=total_cases,
            checks_completed=repeat_completed,
            diverged=diverged,
        ),
        thresholds=thresholds,
        model_acceptance=ModelAcceptance(
            evaluated=False,
            accepted=False,
            reason=(
                "baseline-only harness; no learned component evaluated "
                "and model thresholds remain pending"
            ),
        ),
        synthetic_only=True,
        synthetic_disclaimer=_SYNTHETIC_DISCLAIMER,
    )


def _failure_locs(exc: ValidationError) -> str:
    locs = []
    for error in exc.errors():
        locs.append(".".join(str(part) for part in error["loc"]))
    return "[" + ", ".join(sorted(set(locs))) + "]"


def main(argv: list[str] | None = None) -> int:
    """Run the baseline evaluation from explicit file inputs."""
    parser = argparse.ArgumentParser(
        prog="rop.evaluation",
        description=(
            "Deterministic Stage 8 baseline evaluation harness. Loads one "
            "versioned case set, executes the deterministic composition "
            "service, and prints the machine-readable report. No model, "
            "network, GPU, database session, or hosted service is used. "
            "Exit 0 only when the run is valid and every decided "
            "threshold passes; the report is still printed when the "
            "evaluation completed with failures."
        ),
    )
    parser.add_argument("--cases", required=True, help="path to a case-set JSON file")
    parser.add_argument("--report", default=None, help="optional report output path")
    parser.add_argument(
        "--baseline-revision",
        default=BASELINE_REVISION_UNRESOLVED,
        help="baseline source revision recorded in the report",
    )
    args = parser.parse_args(argv)
    try:
        with open(args.cases, encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        print(f"error: case file not found: {args.cases}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"error: case file is not valid JSON: {args.cases}", file=sys.stderr)
        return 1
    except OSError:
        print(f"error: case file is unreadable: {args.cases}", file=sys.stderr)
        return 1
    try:
        case_set = load_case_set(raw)
    except EvaluationHarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(
            f"error: case file failed validation " f"({_failure_locs(exc)} rejected)",
            file=sys.stderr,
        )
        return 1
    try:
        report = evaluate_case_set(case_set, baseline_revision=args.baseline_revision)
    except EvaluationHarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)
    if args.report is not None:
        try:
            with open(args.report, "w", encoding="utf-8") as handle:
                handle.write(rendered + "\n")
        except OSError:
            print(f"error: report path is not writable: {args.report}", file=sys.stderr)
            return 1
    print(rendered)
    decided_failed = any(
        threshold.status == "failed" for threshold in report.thresholds
    )
    if not report.run_valid or decided_failed:
        print("error: evaluation failed; see report", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "BASELINE_REVISION_UNRESOLVED",
    "EVALUATION_PROTOCOL_VERSION",
    "REPORT_SCHEMA_VERSION",
    "CategoryOutcome",
    "DeterminismOutcome",
    "EvaluationHarnessError",
    "EvaluationReport",
    "MetricValue",
    "ModelAcceptance",
    "NonDeterministicEvaluation",
    "ThresholdStatus",
    "UnsupportedReferences",
    "canonical_json_bytes",
    "case_set_sha256",
    "evaluate_case_set",
    "load_case_set",
    "main",
    "report_sha256",
]

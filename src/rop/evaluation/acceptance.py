"""Task 215: deterministic end-to-end evaluation acceptance gate.

The gate evaluates explicit mandatory criteria over two existing
validated evidence reports — a Task 214 benchmark report and a Task 206
baseline evaluation report — under a versioned acceptance policy, and
returns an auditable PASS/FAIL decision. Every mandatory criterion
must pass; anything missing, invalid, mismatched, or contradictory is
a FAIL, never a warning that still permits acceptance.

What the gate deliberately does not establish: model accuracy,
safety, clinical utility, or readiness. The benchmark's traced memory
is not process RSS, ``LOCAL_CPU_OFFLINE`` describes the exercised
code path rather than proving process-wide isolation, and the
benchmark's deterministic contexts are measurement scaffolding, not
reasoning evidence. Advisory suggestions are never treated as
decisions, and Task 213 strict validation is never bypassed: this
module performs no inference and no validation of its own.

Local-only by construction: no network, provider, download, serving,
or persistence facilities are imported or used.
"""

from __future__ import annotations

import hashlib

from pydantic import ValidationError

from rop.evaluation.harness import (
    EvaluationReport,
    canonical_json_bytes,
    report_sha256,
)
from rop.schemas.acceptance import (
    MANDATORY_CRITERIA,
    AcceptanceCriterionId,
    AcceptanceDecision,
    AcceptanceErrorCode,
    AcceptancePolicy,
    AcceptanceReport,
    CriterionOutcome,
)
from rop.schemas.benchmark import BENCHMARK_CONTRACT_VERSION, BenchmarkReport

__all__ = [
    "AcceptanceError",
    "acceptance_policy_hash",
    "benchmark_report_hash",
    "evaluate_acceptance",
]

_POLICY_HASH_DOMAIN = "rop.acceptance.policy.v1"
_GATE_DIGEST_DOMAIN = "rop.acceptance.gate.v1"

LIMITATIONS: tuple[str, ...] = (
    "acceptance describes the supplied evidence only; it establishes "
    "no model accuracy, safety, clinical utility, or readiness",
    "benchmark traced memory is Python tracemalloc memory, not process "
    "RSS or total system memory",
    "benchmark offline mode describes the exercised code path; it does "
    "not prove the surrounding process had no network access",
    "benchmark deterministic contexts are measurement scaffolding, "
    "not reasoning evidence",
    "underlying evaluation evidence is synthetic-scope only",
)


class AcceptanceError(Exception):
    """A typed acceptance failure with a static, sanitized message."""

    def __init__(self, code: AcceptanceErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def acceptance_policy_hash(policy: AcceptancePolicy) -> str:
    """Canonical identity hash of the acceptance policy itself."""
    body = canonical_json_bytes(policy.model_dump(mode="json")).decode("utf-8")
    return hashlib.sha256(f"{_POLICY_HASH_DOMAIN}\n{body}".encode()).hexdigest()


def benchmark_report_hash(report: BenchmarkReport) -> str:
    """Canonical hash binding the exact benchmark evidence content."""
    body = canonical_json_bytes(report.model_dump(mode="json")).decode("utf-8")
    return hashlib.sha256(
        f"{_GATE_DIGEST_DOMAIN}:benchmark\n{body}".encode()
    ).hexdigest()


def _checked_policy(value: object) -> AcceptancePolicy:
    if not isinstance(value, AcceptancePolicy):
        raise AcceptanceError(
            AcceptanceErrorCode.INVALID_POLICY, "acceptance policy is invalid"
        )
    try:
        return AcceptancePolicy.model_validate(value.model_dump())
    except ValidationError:
        raise AcceptanceError(
            AcceptanceErrorCode.INVALID_POLICY, "acceptance policy is invalid"
        ) from None


def _checked_benchmark(value: object) -> BenchmarkReport:
    if not isinstance(value, BenchmarkReport):
        raise AcceptanceError(
            AcceptanceErrorCode.INVALID_INPUT, "benchmark evidence is invalid"
        )
    try:
        return BenchmarkReport.model_validate(value.model_dump())
    except ValidationError:
        raise AcceptanceError(
            AcceptanceErrorCode.EVIDENCE_INVALID, "benchmark evidence is invalid"
        ) from None


def _checked_evaluation(value: object) -> EvaluationReport:
    if not isinstance(value, EvaluationReport):
        raise AcceptanceError(
            AcceptanceErrorCode.INVALID_INPUT, "evaluation evidence is invalid"
        )
    try:
        return EvaluationReport.model_validate(value.model_dump())
    except ValidationError:
        raise AcceptanceError(
            AcceptanceErrorCode.EVIDENCE_INVALID, "evaluation evidence is invalid"
        ) from None


def _outcome(
    criterion_id: AcceptanceCriterionId, passed: bool, detail: str
) -> CriterionOutcome:
    return CriterionOutcome(criterion_id=criterion_id, passed=passed, reason=detail)


def _evaluate(
    benchmark: BenchmarkReport,
    evaluation: EvaluationReport,
    policy: AcceptancePolicy,
) -> list[CriterionOutcome]:
    outcomes: list[CriterionOutcome] = []
    outcomes.append(
        _outcome(
            "benchmark-contract-version",
            benchmark.contract_version == BENCHMARK_CONTRACT_VERSION,
            (
                "benchmark report contract is supported"
                if benchmark.contract_version == BENCHMARK_CONTRACT_VERSION
                else "benchmark report contract is not supported"
            ),
        )
    )
    outcomes.append(
        _outcome(
            "benchmark-report-integrity",
            True,
            "benchmark report revalidated against its strict schema",
        )
    )
    outcomes.append(
        _outcome(
            "benchmark-report-pinned",
            benchmark_report_hash(benchmark) == policy.expected_benchmark_report_hash,
            (
                "benchmark report matches the pinned evidence hash"
                if benchmark_report_hash(benchmark)
                == policy.expected_benchmark_report_hash
                else "benchmark report does not match the pinned evidence hash"
            ),
        )
    )
    identity_matches = (
        benchmark.artifact_id == policy.expected_artifact_id
        and benchmark.vocabulary_hash == policy.expected_vocabulary_hash
        and benchmark.policy_hash == policy.expected_policy_hash
        and benchmark.benchmark_config_hash == policy.expected_benchmark_config_hash
        and benchmark.case_set_digest == policy.expected_case_set_digest
    )
    outcomes.append(
        _outcome(
            "benchmark-identity",
            identity_matches,
            (
                "benchmark artifact, vocabulary, policy, configuration, and "
                "case-set identities match the acceptance policy"
                if identity_matches
                else "benchmark identity does not match the acceptance policy"
            ),
        )
    )
    outcomes.append(
        _outcome(
            "benchmark-budget-within",
            benchmark.within_declared_budgets,
            (
                "benchmark measurements are within declared resource budgets"
                if benchmark.within_declared_budgets
                else "benchmark measurements exceed declared resource budgets"
            ),
        )
    )
    outcomes.append(
        _outcome(
            "benchmark-offline-mode",
            benchmark.execution_mode == "LOCAL_CPU_OFFLINE",
            "benchmark declares local offline execution",
        )
    )
    outcomes.append(
        _outcome(
            "evaluation-contract-version",
            evaluation.report_schema_version == "1.1"
            and evaluation.protocol_version == "1.1",
            (
                "evaluation report contract is supported"
                if evaluation.report_schema_version == "1.1"
                and evaluation.protocol_version == "1.1"
                else "evaluation report contract is not supported"
            ),
        )
    )
    outcomes.append(
        _outcome(
            "evaluation-report-integrity",
            True,
            "evaluation report revalidated against its strict schema",
        )
    )
    outcomes.append(
        _outcome(
            "evaluation-report-pinned",
            report_sha256(evaluation) == policy.expected_evaluation_report_sha256,
            (
                "evaluation report matches the pinned evidence hash"
                if report_sha256(evaluation) == policy.expected_evaluation_report_sha256
                else "evaluation report does not match the pinned evidence hash"
            ),
        )
    )
    evaluation_identity_matches = (
        evaluation.case_set_id == policy.expected_evaluation_case_set_id
        and evaluation.case_set_sha256 == policy.expected_evaluation_case_set_sha256
    )
    outcomes.append(
        _outcome(
            "evaluation-identity",
            evaluation_identity_matches,
            (
                "evaluation case set matches the acceptance policy"
                if evaluation_identity_matches
                else "evaluation case set does not match the acceptance policy"
            ),
        )
    )
    run_valid = (
        evaluation.run_valid
        and evaluation.errored == 0
        and len(evaluation.run_errors) == 0
    )
    outcomes.append(
        _outcome(
            "evaluation-run-valid",
            run_valid,
            (
                "evaluation run completed without errors"
                if run_valid
                else "evaluation run did not complete cleanly"
            ),
        )
    )
    by_id = {item.threshold_id: item.status for item in evaluation.thresholds}
    thresholds_pass = all(
        by_id.get(threshold_id) == "passed"
        for threshold_id in policy.required_threshold_ids
    )
    outcomes.append(
        _outcome(
            "evaluation-thresholds",
            thresholds_pass,
            (
                "every required evaluation threshold passed"
                if thresholds_pass
                else "a required evaluation threshold is missing or not passed"
            ),
        )
    )
    determinism = evaluation.determinism
    determinism_ok = (
        determinism.repeat_passed
        and determinism.checks_attempted > 0
        and determinism.checks_completed == determinism.checks_attempted
        and determinism.diverged == 0
    )
    outcomes.append(
        _outcome(
            "evaluation-determinism",
            determinism_ok,
            (
                "evaluation repeat-execution evidence is complete"
                if determinism_ok
                else "evaluation determinism evidence is missing or diverged"
            ),
        )
    )
    no_claim = (
        not benchmark.clinical_utility_established
        and not evaluation.model_acceptance.accepted
    )
    outcomes.append(
        _outcome(
            "no-clinical-or-acceptance-claim",
            no_claim,
            "no input claims clinical utility or prior acceptance",
        )
    )
    synthetic_scope = evaluation.synthetic_only and bool(
        evaluation.synthetic_disclaimer
    )
    outcomes.append(
        _outcome(
            "evidence-scope-synthetic",
            synthetic_scope,
            "evidence is synthetic-scope with a stated disclaimer",
        )
    )
    assert [outcome.criterion_id for outcome in outcomes] == list(MANDATORY_CRITERIA)
    return outcomes


def evaluate_acceptance(
    *,
    benchmark: BenchmarkReport,
    evaluation: EvaluationReport,
    policy: AcceptancePolicy,
) -> AcceptanceReport:
    """Evaluate the acceptance policy over validated evidence reports.

    Evidence is revalidated on entry; anything structurally invalid
    raises instead of producing a decision. Identity expectations come
    from the policy while bound values come from the reports. A FAIL
    decision is returned — never an exception — for evidence that is
    well-formed but does not satisfy every mandatory criterion.
    """
    checked_policy = _checked_policy(policy)
    checked_benchmark = _checked_benchmark(benchmark)
    checked_evaluation = _checked_evaluation(evaluation)
    outcomes = _evaluate(checked_benchmark, checked_evaluation, checked_policy)
    decision: AcceptanceDecision = (
        "PASS" if all(outcome.passed for outcome in outcomes) else "FAIL"
    )
    gate_body = canonical_json_bytes(
        {
            "policy": acceptance_policy_hash(checked_policy),
            "benchmark": benchmark_report_hash(checked_benchmark),
            "evaluation": report_sha256(checked_evaluation),
            "criteria": [
                {"id": outcome.criterion_id, "passed": outcome.passed}
                for outcome in outcomes
            ],
            "decision": decision,
        }
    ).decode("utf-8")
    try:
        return AcceptanceReport(
            decision=decision,
            artifact_id=checked_benchmark.artifact_id,
            vocabulary_hash=checked_benchmark.vocabulary_hash,
            policy_hash=checked_benchmark.policy_hash,
            benchmark_config_hash=checked_benchmark.benchmark_config_hash,
            case_set_digest=checked_benchmark.case_set_digest,
            benchmark_report_hash=benchmark_report_hash(checked_benchmark),
            evaluation_case_set_id=checked_evaluation.case_set_id,
            evaluation_case_set_sha256=checked_evaluation.case_set_sha256,
            evaluation_report_sha256=report_sha256(checked_evaluation),
            acceptance_policy_hash=acceptance_policy_hash(checked_policy),
            criteria=tuple(outcomes),
            limitations=LIMITATIONS,
            gate_digest=hashlib.sha256(
                f"{_GATE_DIGEST_DOMAIN}\n{gate_body}".encode()
            ).hexdigest(),
        )
    except ValidationError:
        raise AcceptanceError(
            AcceptanceErrorCode.REPORT_INCONSISTENT,
            "acceptance report is internally inconsistent",
        ) from None

"""Task 215: end-to-end evaluation acceptance gate tests.

Synthetic fixtures only: benchmark evidence comes from the real Task 214
runner over a stub model, and evaluation evidence is a hand-built Task 206
report. Synthetic evidence demonstrates gate mechanics; it proves no
real-world model quality or clinical usefulness.
"""

from __future__ import annotations

import pytest
import torch
from pydantic import ValidationError

from rop.evaluation.acceptance import (
    AcceptanceError,
    acceptance_policy_hash,
    benchmark_report_hash,
    evaluate_acceptance,
)
from rop.evaluation.harness import EvaluationReport, report_sha256
from rop.inference.advisory import AdvisoryAdapter
from rop.inference.benchmark import run_inference_benchmark
from rop.inference.runtime import InferenceSession
from rop.schemas.acceptance import (
    MANDATORY_CRITERIA,
    AcceptanceErrorCode,
    AcceptancePolicy,
    AcceptanceReport,
)
from rop.schemas.advisory import AdvisoryClassLabelMapping
from rop.schemas.benchmark import BenchmarkConfig, BenchmarkReport
from rop.schemas.tokenizer import Vocabulary

ARTIFACT_ID = "artifact-synthetic"
VOCAB_HASH = "c" * 64
VOCAB_SIZE = 8
CASE_SET_KEY = b"0123456789abcdef"


class _StubModel:
    def __init__(self) -> None:
        self.training = False

    def eval(self) -> _StubModel:
        self.training = False
        return self

    def train(self, mode: bool = True) -> _StubModel:
        self.training = mode
        return self

    def __call__(self, token_ids: torch.Tensor) -> torch.Tensor:
        batch = token_ids.shape[0]
        return torch.tensor([[2.0, 0.5, 1.0]] * batch, dtype=torch.float32)


def _vocabulary() -> Vocabulary:
    return Vocabulary.model_validate(
        {
            "metadata": {
                "vocabulary_version": "1.0",
                "tokenizer_version": "1.0",
                "policy_version": "1.0",
                "tokenizer_config_hash": "d" * 64,
                "reserved_tokens": ["<pad>", "<unk>"],
                "vocabulary_size": VOCAB_SIZE,
                "max_vocab_size": 16,
                "min_frequency": 1,
                "vocabulary_hash": VOCAB_HASH,
                "dataset_id": "synthetic-bench",
                "dataset_integrity_hash": "e" * 64,
                "split_assignment_hash": "f" * 64,
                "data_scope": "synthetic-test-only",
                "metadata_integrity_hash": "a" * 64,
            },
            "tokens": ["<pad>", "<unk>"]
            + [f"tok-{index}" for index in range(2, VOCAB_SIZE)],
        }
    )


def _adapter() -> AdvisoryAdapter:
    return AdvisoryAdapter(
        class_label_mapping=AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-215-synthetic-mapping",
                "num_classes": 3,
                "entries": [
                    {"class_index": 0, "label": "alpha"},
                    {"class_index": 2, "label": "beta"},
                ],
            }
        ),
        approved_labels=("alpha", "beta", "gamma"),
    )


def _benchmark() -> BenchmarkReport:
    session = InferenceSession(
        model=_StubModel(),
        artifact_id=ARTIFACT_ID,
        vocab_size=VOCAB_SIZE,
        max_seq_len=16,
        num_classes=3,
    )
    return run_inference_benchmark(
        session=session,
        vocabulary=_vocabulary(),
        adapter=_adapter(),
        cases=[(2, 3), (4, 5)],
        config=BenchmarkConfig.model_validate(
            {
                "warmup_iterations": 0,
                "measured_iterations": 2,
                "latency_budget_ms": 60000.0,
                "peak_memory_budget_bytes": 2**31,
            }
        ),
        expected_artifact_id=ARTIFACT_ID,
        expected_vocabulary_hash=VOCAB_HASH,
        case_set_key=CASE_SET_KEY,
    )


def _metric(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (numerator / denominator) if denominator else None,
    }


def _evaluation(**overrides: object) -> EvaluationReport:
    payload: dict[str, object] = {
        "report_schema_version": "1.1",
        "protocol_version": "1.1",
        "baseline_revision": "synthetic-baseline-1",
        "case_set_id": "synthetic-case-set-1",
        "case_set_version": "1.0",
        "case_set_sha256": "b" * 64,
        "case_count": 4,
        "total_cases": 4,
        "valid_cases": 2,
        "invalid_input_cases": 2,
        "valid_passed": 2,
        "valid_failed": 0,
        "invalid_passed": 2,
        "invalid_failed": 0,
        "errored": 0,
        "run_valid": True,
        "run_errors": [],
        "status_agreement": _metric(2, 2),
        "reason_agreement": _metric(2, 2),
        "evidence_exactness": _metric(2, 2),
        "unsupported_references": {
            "emitted": 2,
            "unsupported": 0,
            "rate": 0.0,
            "denominator_zero": False,
            "target_met": True,
        },
        "contradiction": {"expected": 1, "correct": 1, "incorrect": 0},
        "abstention": {"expected": 1, "correct": 1, "incorrect": 0},
        "insufficiency": {"expected": 0, "correct": 0, "incorrect": 0},
        "status_distribution": {"SUPPORTED": 2},
        "abstention_rate": _metric(0, 2),
        "determinism": {
            "repeat_passed": True,
            "checks_attempted": 4,
            "checks_completed": 4,
            "diverged": 0,
        },
        "thresholds": [
            {"threshold_id": "t-agreement", "status": "passed", "detail": "met"}
        ],
        "model_acceptance": {
            "evaluated": False,
            "accepted": False,
            "reason": "synthetic harness never accepts",
        },
        "synthetic_only": True,
        "synthetic_disclaimer": "synthetic-only evidence",
    }
    payload.update(overrides)
    return EvaluationReport.model_validate(payload)


def _policy(
    benchmark: BenchmarkReport, evaluation: EvaluationReport, **overrides: object
) -> AcceptancePolicy:
    payload: dict[str, object] = {
        "expected_artifact_id": benchmark.artifact_id,
        "expected_vocabulary_hash": benchmark.vocabulary_hash,
        "expected_policy_hash": benchmark.policy_hash,
        "expected_benchmark_config_hash": benchmark.benchmark_config_hash,
        "expected_case_set_digest": benchmark.case_set_digest,
        "expected_benchmark_report_hash": benchmark_report_hash(benchmark),
        "expected_evaluation_case_set_id": evaluation.case_set_id,
        "expected_evaluation_case_set_sha256": evaluation.case_set_sha256,
        "expected_evaluation_report_sha256": report_sha256(evaluation),
        "required_threshold_ids": ["t-agreement"],
    }
    payload.update(overrides)
    return AcceptancePolicy.model_validate(payload)


def _evaluate(**overrides: object) -> AcceptanceReport:
    benchmark = _benchmark()
    evaluation = _evaluation()
    payload: dict[str, object] = {
        "benchmark": benchmark,
        "evaluation": evaluation,
        "policy": _policy(benchmark, evaluation),
    }
    payload.update(overrides)
    return evaluate_acceptance(**payload)  # type: ignore[arg-type]


def test_matching_validated_evidence_passes() -> None:
    report = _evaluate()
    assert report.decision == "PASS"
    assert all(outcome.passed for outcome in report.criteria)
    assert [outcome.criterion_id for outcome in report.criteria] == list(
        MANDATORY_CRITERIA
    )
    assert report.artifact_id == ARTIFACT_ID
    assert report.evaluation_case_set_id == "synthetic-case-set-1"
    assert len(report.limitations) >= 1
    assert AcceptanceReport.model_validate(report.model_dump()) == report


def test_missing_evidence_is_rejected() -> None:
    with pytest.raises(AcceptanceError) as raised:
        evaluate_acceptance(
            benchmark=None,  # type: ignore[arg-type]
            evaluation=_evaluation(),
            policy=_policy(_benchmark(), _evaluation()),
        )
    assert raised.value.code == AcceptanceErrorCode.INVALID_INPUT
    with pytest.raises(AcceptanceError) as raised:
        evaluate_acceptance(
            benchmark=_benchmark(),
            evaluation="not-a-report",  # type: ignore[arg-type]
            policy=_policy(_benchmark(), _evaluation()),
        )
    assert raised.value.code == AcceptanceErrorCode.INVALID_INPUT


def test_unsupported_report_versions_fail() -> None:
    benchmark = _benchmark()
    forged = BenchmarkReport.model_construct(
        **{**benchmark.model_dump(), "contract_version": "2"}
    )
    with pytest.raises(AcceptanceError) as raised:
        _evaluate(benchmark=forged)
    assert raised.value.code == AcceptanceErrorCode.EVIDENCE_INVALID


def test_identity_mismatches_fail() -> None:
    benchmark = _benchmark()
    evaluation = _evaluation()
    for field in (
        "expected_artifact_id",
        "expected_vocabulary_hash",
        "expected_policy_hash",
        "expected_benchmark_config_hash",
        "expected_case_set_digest",
        "expected_benchmark_report_hash",
    ):
        policy = _policy(benchmark, evaluation, **{field: "0" * 64})
        if field == "expected_artifact_id":
            policy = _policy(benchmark, evaluation, expected_artifact_id="other")
        report = evaluate_acceptance(
            benchmark=benchmark, evaluation=evaluation, policy=policy
        )
        assert report.decision == "FAIL"
    policy = _policy(benchmark, evaluation, expected_evaluation_case_set_id="other-set")
    report = evaluate_acceptance(
        benchmark=benchmark, evaluation=evaluation, policy=policy
    )
    assert report.decision == "FAIL"


def test_caller_supplied_identity_substitution_fails() -> None:
    benchmark = _benchmark()
    evaluation = _evaluation()
    tampered = BenchmarkReport.model_validate(
        {**benchmark.model_dump(mode="json"), "artifact_id": "artifact-evil"}
    )
    report = evaluate_acceptance(
        benchmark=tampered,
        evaluation=evaluation,
        policy=_policy(benchmark, evaluation),
    )
    assert report.decision == "FAIL"
    assert report.artifact_id == "artifact-evil"


def test_unknown_fields_are_rejected() -> None:
    benchmark = _benchmark()
    evaluation = _evaluation()
    with pytest.raises(ValidationError):
        BenchmarkReport.model_validate(
            {**benchmark.model_dump(mode="json"), "extra": True}
        )
    with pytest.raises(ValidationError):
        AcceptancePolicy.model_validate(
            {
                **_policy(benchmark, evaluation).model_dump(mode="json"),
                "unknown": True,
            }
        )


def test_contradictory_and_inconsistent_reports_fail_validation() -> None:
    report = _evaluate()
    tampered = report.model_dump()
    tampered["decision"] = "FAIL"
    with pytest.raises(ValidationError):
        AcceptanceReport.model_validate(tampered)
    tampered = report.model_dump()
    tampered["criteria"] = tuple(
        {**outcome, "passed": False} for outcome in tampered["criteria"][:1]
    ) + tuple(tampered["criteria"][1:])
    with pytest.raises(ValidationError):
        AcceptanceReport.model_validate(tampered)


def test_failed_mandatory_criterion_prevents_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Deterministic 1ms samples against a 0.5ms budget: genuinely over
    # budget with a self-consistent report, so only the budget criterion
    # (plus nothing else) fails.
    import time

    steps = [1_000_000.0]
    state = {"time": 0.0, "calls": 0}

    def fake_ns() -> float:
        if state["calls"] % 2 == 1:
            state["time"] += steps[(state["calls"] // 2) % len(steps)]
        state["calls"] += 1
        return state["time"]

    monkeypatch.setattr(time, "perf_counter_ns", fake_ns)
    session = InferenceSession(
        model=_StubModel(),
        artifact_id=ARTIFACT_ID,
        vocab_size=VOCAB_SIZE,
        max_seq_len=16,
        num_classes=3,
    )
    over_budget = run_inference_benchmark(
        session=session,
        vocabulary=_vocabulary(),
        adapter=_adapter(),
        cases=[(2, 3), (4, 5)],
        config=BenchmarkConfig.model_validate(
            {
                "warmup_iterations": 0,
                "measured_iterations": 2,
                "latency_budget_ms": 0.5,
                "peak_memory_budget_bytes": 2**31,
            }
        ),
        expected_artifact_id=ARTIFACT_ID,
        expected_vocabulary_hash=VOCAB_HASH,
        case_set_key=CASE_SET_KEY,
    )
    assert over_budget.within_declared_budgets is False
    report = _evaluate(
        benchmark=over_budget,
        policy=_policy(over_budget, _evaluation()),
    )
    assert report.decision == "FAIL"
    failed = [o for o in report.criteria if not o.passed]
    assert [o.criterion_id for o in failed] == ["benchmark-budget-within"]


def test_missing_threshold_evidence_prevents_acceptance() -> None:
    evaluation = _evaluation(
        thresholds=[{"threshold_id": "t-other", "status": "passed", "detail": "met"}]
    )
    report = _evaluate(evaluation=evaluation, policy=_policy(_benchmark(), evaluation))
    assert report.decision == "FAIL"


def test_unverifiable_determinism_prevents_acceptance() -> None:
    evaluation = _evaluation(
        determinism={
            "repeat_passed": True,
            "checks_attempted": 0,
            "checks_completed": 0,
            "diverged": 0,
        }
    )
    report = _evaluate(evaluation=evaluation, policy=_policy(_benchmark(), evaluation))
    assert report.decision == "FAIL"


def test_decisions_and_digests_are_deterministic() -> None:
    benchmark = _benchmark()
    evaluation = _evaluation()
    policy = _policy(benchmark, evaluation)
    first = evaluate_acceptance(
        benchmark=benchmark, evaluation=evaluation, policy=policy
    )
    second = evaluate_acceptance(
        benchmark=benchmark, evaluation=evaluation, policy=policy
    )
    assert first.decision == second.decision == "PASS"
    assert first.gate_digest == second.gate_digest
    assert first == second
    assert first.acceptance_policy_hash == acceptance_policy_hash(policy)


def test_failures_are_sanitized() -> None:
    with pytest.raises(AcceptanceError) as raised:
        _evaluate(benchmark=object())  # type: ignore[arg-type]
    assert "object" not in str(raised.value)
    benchmark = _benchmark()
    forged = BenchmarkReport.model_construct(
        **{**benchmark.model_dump(), "within_declared_budgets": "yes"}
    )
    with pytest.raises(AcceptanceError) as raised:
        _evaluate(benchmark=forged)
    assert raised.value.code == AcceptanceErrorCode.EVIDENCE_INVALID


def test_task214_limitations_are_recorded_not_overstated() -> None:
    report = _evaluate()
    text = " ".join(report.limitations)
    assert "traced" in text or "tracemalloc" in text
    assert "LOCAL_CPU_OFFLINE" not in text or "code path" in text
    assert "synthetic" in text
    assert "accuracy" in text or "clinical" in text


def test_task212_213_boundaries_remain_in_force() -> None:
    from rop.schemas.inference import InferenceResult

    with pytest.raises(ValidationError):
        InferenceResult.model_validate(
            {
                "artifact_id": ARTIFACT_ID,
                "batch_size": 1,
                "sequence_length": 4,
                "num_classes": 3,
                "logits": ((float("inf"), 0.0, 0.0),),
            }
        )
    benchmark = _benchmark()
    forged = BenchmarkReport.model_construct(
        **{**benchmark.model_dump(), "policy_hash": "f" * 64}
    )
    # Schema-valid but mismatched evidence is a FAIL rejection, not an
    # exception: the strict boundary still holds, nothing is accepted.
    report = _evaluate(benchmark=forged)
    assert report.decision == "FAIL"
    assert any(
        outcome.criterion_id in ("benchmark-identity", "benchmark-report-pinned")
        and not outcome.passed
        for outcome in report.criteria
    )

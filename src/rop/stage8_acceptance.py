"""Task 215: end-to-end Stage 8 evaluation and acceptance gate.

The gate composes the held-out TEST split, authorized dataset manifest,
verified model artifact, local inference, strict suggestion validation,
baseline comparison and resource benchmark. Synthetic data can demonstrate
the mechanics but can never satisfy the acceptance gate.

Identity completeness: the final report is bound to the exact checkpoint
(``artifact_hash``), the exact strict suggestion policy (``policy_hash``), a
predeclared benchmark configuration, and the exact held-out TEST workload.
Model version and vocabulary hash alone do not identify a checkpoint, so a
benchmark taken on any other artifact, policy, configuration, budgets or
workload is rejected rather than accepted as evidence.

Contract version 2 adds ``artifact_hash`` and ``policy_hash`` to the report and
makes its validator cross-check every child report against the report identity.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from rop.evaluation import compare_systems
from rop.native_artifacts import NativeModelArtifact
from rop.native_benchmark import (
    NativeBenchmarkConfig,
    NativeBenchmarkReport,
    case_set_digest,
)
from rop.native_inference import NativeLocalInference
from rop.native_suggestion_validation import (
    SuggestionValidationPolicy,
    validate_suggestion_response,
)
from rop.native_training import label_space_hash
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetManifest,
    PermittedPurpose,
)
from rop.schemas.evaluation_harness import (
    CandidatePrediction,
    EvaluationComparisonReport,
    EvaluationRunConfiguration,
    EvaluationSplit,
)

MAX_BLOCKERS = 16
STAGE8_ACCEPTANCE_CONTRACT_VERSION = "2"
BASELINE_SYSTEM_ID = "deterministic-baseline"

BLOCKER_REAL_DATA = "REAL_AUTHORIZED_DATA_REQUIRED"
BLOCKER_RESOURCE_BUDGET = "RESOURCE_BUDGET_FAILED"
BLOCKER_EVALUATION = "EVALUATION_GATE_FAILED"


class Stage8AcceptanceError(Exception):
    """Stable, privacy-safe failure of an acceptance input contract."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


class Stage8AcceptanceReport(BaseModel):
    """Final evidence package; acceptance is distinct from evaluation scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["2"] = STAGE8_ACCEPTANCE_CONTRACT_VERSION
    run_id: StrictStr = Field(min_length=1, max_length=100)
    dataset_id: StrictStr = Field(min_length=1, max_length=200)
    dataset_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    training_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    model_version: StrictStr = Field(min_length=1, max_length=32)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation: EvaluationComparisonReport
    benchmark: NativeBenchmarkReport
    authorized_real_data: StrictBool
    blockers: tuple[StrictStr, ...] = Field(max_length=MAX_BLOCKERS)
    limitations: tuple[StrictStr, ...] = Field(max_length=32)
    accepted: StrictBool

    @field_validator("blockers", "limitations")
    @classmethod
    def _canonical_strings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("values must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("values must be canonically sorted")
        return value

    @model_validator(mode="after")
    def _child_reports_share_one_identity(self) -> Stage8AcceptanceReport:
        evaluation = self.evaluation
        benchmark = self.benchmark
        if evaluation.run_id != self.run_id:
            raise ValueError("evaluation run identity does not match the report")
        if (
            evaluation.dataset_id != self.dataset_id
            or evaluation.dataset_snapshot_hash != self.dataset_fingerprint
        ):
            raise ValueError("evaluation dataset identity does not match the report")
        if evaluation.candidate.system_id != self.model_version:
            raise ValueError("evaluated candidate is not the reported model version")
        if (
            benchmark.model_version != self.model_version
            or benchmark.vocabulary_hash != self.vocabulary_hash
            or benchmark.artifact_hash != self.artifact_hash
            or benchmark.policy_hash != self.policy_hash
        ):
            raise ValueError(
                "benchmark model, vocabulary, artifact or policy identity "
                "does not match the report"
            )
        if benchmark.case_count != evaluation.candidate.example_count:
            raise ValueError("benchmark workload does not cover the evaluated examples")
        return self

    @model_validator(mode="after")
    def _acceptance_and_blockers_follow_the_recorded_gates(
        self,
    ) -> Stage8AcceptanceReport:
        expected_blockers: set[str] = set()
        if not self.authorized_real_data:
            expected_blockers.add(BLOCKER_REAL_DATA)
        if not self.benchmark.within_declared_budgets:
            expected_blockers.add(BLOCKER_RESOURCE_BUDGET)
        if not self.evaluation.accepted:
            expected_blockers.add(BLOCKER_EVALUATION)
        if set(self.blockers) != expected_blockers:
            raise ValueError("blockers contradict the recorded gate outcomes")
        if self.accepted is not (not expected_blockers):
            raise ValueError("Stage 8 acceptance requires every gate to pass")
        return self


def run_stage8_acceptance_gate(
    *,
    run_configuration: EvaluationRunConfiguration,
    dataset_manifest: DatasetManifest,
    artifact: NativeModelArtifact,
    inference: NativeLocalInference,
    policy: SuggestionValidationPolicy,
    texts_by_example_id: dict[str, str],
    baseline_predictions: tuple[CandidatePrediction, ...],
    benchmark: NativeBenchmarkReport,
    expected_benchmark_config: NativeBenchmarkConfig,
) -> Stage8AcceptanceReport:
    """Evaluate the held-out TEST set and produce the final acceptance record.

    ``expected_benchmark_config`` is the predeclared benchmark configuration
    (repetitions and latency/memory budgets). The supplied benchmark report must
    have been produced under exactly that configuration.
    """
    if run_configuration.evaluated_splits != (EvaluationSplit.TEST,):
        raise Stage8AcceptanceError(
            "TEST_SPLIT_REQUIRED",
            "final acceptance must evaluate only the held-out TEST split",
        )
    split_manifest = run_configuration.split_manifest
    if (
        split_manifest.dataset_id != dataset_manifest.dataset_id
        or split_manifest.dataset_snapshot_hash != dataset_manifest.dataset_fingerprint
    ):
        raise Stage8AcceptanceError(
            "DATASET_BINDING_MISMATCH",
            "evaluation manifest does not match the prepared dataset",
        )
    if (
        run_configuration.task.task_id != policy.task_id
        or run_configuration.task.labels != policy.allowed_labels
    ):
        raise Stage8AcceptanceError(
            "TASK_POLICY_MISMATCH",
            "evaluation task and suggestion policy do not match",
        )
    if (
        artifact.model_config_payload.model_version != policy.expected_model_version
        or artifact.vocabulary_hash != policy.expected_vocabulary_hash
    ):
        raise Stage8AcceptanceError(
            "MODEL_POLICY_MISMATCH",
            "artifact identity does not match the suggestion policy",
        )
    if (
        inference.artifact_hash != artifact.artifact_hash
        or inference.artifact.artifact_hash != artifact.artifact_hash
    ):
        raise Stage8AcceptanceError(
            "INFERENCE_ARTIFACT_MISMATCH",
            "inference adapter is not using the supplied artifact",
        )
    if (
        label_space_hash(tuple(inference.labels))
        != artifact.training_report.label_space_hash
    ):
        raise Stage8AcceptanceError(
            "LABEL_SPACE_BINDING_MISMATCH",
            "inference labels are not the label space the artifact was trained on",
        )
    train_fingerprint = dict(dataset_manifest.split_fingerprints).get("train")
    if (
        train_fingerprint is None
        or artifact.dataset_fingerprint != train_fingerprint
        or artifact.training_report.dataset_fingerprint != train_fingerprint
    ):
        raise Stage8AcceptanceError(
            "TRAINING_DATASET_MISMATCH",
            "artifact training lineage does not match the dataset manifest",
        )
    if (
        benchmark.model_version != artifact.model_config_payload.model_version
        or benchmark.vocabulary_hash != artifact.vocabulary_hash
    ):
        raise Stage8AcceptanceError(
            "BENCHMARK_BINDING_MISMATCH",
            "benchmark belongs to a different model or vocabulary",
        )
    if benchmark.artifact_hash != artifact.artifact_hash:
        raise Stage8AcceptanceError(
            "BENCHMARK_ARTIFACT_MISMATCH",
            "benchmark was not measured on the supplied artifact",
        )
    if benchmark.policy_hash != policy.policy_hash():
        raise Stage8AcceptanceError(
            "BENCHMARK_POLICY_MISMATCH",
            "benchmark did not use the suggestion policy of this gate",
        )
    if (
        benchmark.benchmark_config_hash != expected_benchmark_config.config_hash()
        or benchmark.declared_latency_budget_ms
        != expected_benchmark_config.latency_budget_ms
        or benchmark.declared_peak_memory_budget_bytes
        != expected_benchmark_config.peak_memory_budget_bytes
        or benchmark.warmup_iterations != expected_benchmark_config.warmup_iterations
        or benchmark.measured_iterations
        != expected_benchmark_config.measured_iterations
    ):
        raise Stage8AcceptanceError(
            "BENCHMARK_CONFIG_MISMATCH",
            "benchmark configuration or budgets differ from the predeclared ones",
        )

    test_entries = split_manifest.examples_for(EvaluationSplit.TEST)
    if not test_entries:
        raise Stage8AcceptanceError(
            "EMPTY_TEST_SPLIT",
            "final acceptance requires a nonempty held-out TEST split",
        )
    test_ids = {entry.example_id for entry in test_entries}
    if set(texts_by_example_id) != test_ids:
        raise Stage8AcceptanceError(
            "TEST_TEXT_SET_MISMATCH",
            "text inputs must cover exactly the held-out TEST examples",
        )
    if any(not isinstance(value, str) for value in texts_by_example_id.values()):
        raise Stage8AcceptanceError(
            "TEST_TEXT_INVALID", "all held-out TEST inputs must be text strings"
        )
    baseline_ids = [item.example_id for item in baseline_predictions]
    if len(set(baseline_ids)) != len(baseline_ids) or set(baseline_ids) != test_ids:
        raise Stage8AcceptanceError(
            "BASELINE_SET_MISMATCH",
            "baseline predictions must cover exactly the held-out TEST examples",
        )
    # The benchmark workload must be the held-out TEST inputs, in canonical
    # TEST-entry order, and every one of them must have been measured.
    ordered_texts = tuple(
        texts_by_example_id[entry.example_id] for entry in test_entries
    )
    if (
        benchmark.case_count != len(ordered_texts)
        or benchmark.cases_measured != len(ordered_texts)
        or benchmark.case_set_digest != case_set_digest(ordered_texts)
    ):
        raise Stage8AcceptanceError(
            "BENCHMARK_WORKLOAD_MISMATCH",
            "benchmark workload is not the held-out TEST input set",
        )

    candidate_predictions: list[CandidatePrediction] = []
    for entry in test_entries:
        start = time.perf_counter_ns()
        response = inference.predict_text(texts_by_example_id[entry.example_id])
        latency_ms = (time.perf_counter_ns() - start) / 1_000_000.0
        validated = validate_suggestion_response(response, policy)
        labels = tuple(sorted(item.label for item in validated.suggestions))
        candidate_predictions.append(
            CandidatePrediction(
                example_id=entry.example_id,
                predicted_labels=labels,
                abstained=not labels,
                latency_ms=latency_ms,
                invalid=False,
            )
        )

    real_authorized_data = (
        dataset_manifest.source.authorization is AuthorizationStatus.AUTHORIZED
        and not dataset_manifest.source.is_synthetic
        and PermittedPurpose.TRAINING in dataset_manifest.source.permitted_purposes
        and PermittedPurpose.EVALUATION in dataset_manifest.source.permitted_purposes
        and dataset_manifest.training_blocked_reason is None
    )
    limitations = [
        "Model suggestions are advisory and are not clinical decisions.",
        "Acceptance is not evidence of clinical safety or clinical utility.",
    ]
    blockers: list[str] = []
    if not real_authorized_data:
        blockers.append(BLOCKER_REAL_DATA)
        limitations.append(
            "Synthetic, unauthorized, or purpose-limited data cannot satisfy "
            "Stage 8 acceptance."
        )
    if not benchmark.within_declared_budgets:
        blockers.append(BLOCKER_RESOURCE_BUDGET)

    evaluation = compare_systems(
        run_configuration=run_configuration,
        baseline_predictions=baseline_predictions,
        candidate_predictions=tuple(candidate_predictions),
        baseline_system_id=BASELINE_SYSTEM_ID,
        candidate_system_id=artifact.model_config_payload.model_version,
        limitations=tuple(sorted(set(limitations))),
    )
    if not evaluation.accepted:
        blockers.append(BLOCKER_EVALUATION)
    blockers = sorted(set(blockers))
    accepted = (
        not blockers
        and evaluation.accepted
        and benchmark.within_declared_budgets
        and real_authorized_data
    )
    return Stage8AcceptanceReport(
        run_id=run_configuration.run_id,
        dataset_id=dataset_manifest.dataset_id,
        dataset_fingerprint=dataset_manifest.dataset_fingerprint,
        training_fingerprint=train_fingerprint,
        model_version=artifact.model_config_payload.model_version,
        vocabulary_hash=artifact.vocabulary_hash,
        artifact_hash=artifact.artifact_hash,
        policy_hash=policy.policy_hash(),
        evaluation=evaluation,
        benchmark=benchmark,
        authorized_real_data=real_authorized_data,
        blockers=tuple(blockers),
        limitations=tuple(sorted(set(limitations))),
        accepted=accepted,
    )


__all__ = [
    "BASELINE_SYSTEM_ID",
    "STAGE8_ACCEPTANCE_CONTRACT_VERSION",
    "Stage8AcceptanceError",
    "Stage8AcceptanceReport",
    "run_stage8_acceptance_gate",
]

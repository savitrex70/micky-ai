"""Task 215 end-to-end acceptance tests; synthetic fixtures must stay blocked."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError

from rop.native_artifacts import NativeModelArtifact, create_native_artifact
from rop.native_benchmark import (
    NativeBenchmarkConfig,
    NativeBenchmarkReport,
    case_set_digest,
    run_native_benchmark,
)
from rop.native_inference import NativeInferenceConfig, NativeLocalInference
from rop.native_suggestion_validation import SuggestionValidationPolicy
from rop.schemas.dataset_manifest import DatasetManifest
from rop.schemas.evaluation_harness import (
    CandidatePrediction,
    EvaluationRunConfiguration,
    EvaluationSplitManifest,
)
from rop.stage8_acceptance import (
    BASELINE_SYSTEM_ID,
    STAGE8_ACCEPTANCE_CONTRACT_VERSION,
    Stage8AcceptanceError,
    Stage8AcceptanceReport,
    run_stage8_acceptance_gate,
)
from tests.test_evaluation_harness import _metric_configuration, _task
from tests.test_native_training import LABEL_SPACE, _fixture, _train

TASK_ID = "task-labtag-1"
EXAMPLE_IDS = ("example-1", "example-2", "example-3", "example-4")
TEXTS = {
    "example-1": "synthetic anion gap",
    "example-2": "synthetic potassium",
    "example-3": "synthetic anion gap again",
    "example-4": "synthetic potassium again",
}
EXPECTED_LABELS = {
    "example-1": ("ANION_GAP_HIGH",),
    "example-2": ("POTASSIUM_HIGH",),
    "example-3": ("ANION_GAP_HIGH",),
    "example-4": ("POTASSIUM_HIGH",),
}
EXPECTED_CONFIG = NativeBenchmarkConfig(
    warmup_iterations=0,
    measured_iterations=4,
    latency_budget_ms=60000.0,
    peak_memory_budget_bytes=10000000,
)


def _trained(fixture=None, **train_overrides):
    fixture = fixture or _fixture()
    vocabulary, model_config = fixture[2], fixture[3]
    result = _train(fixture, **train_overrides)
    artifact = create_native_artifact(
        model_config=model_config,
        parameters=result.parameters,
        training_report=result.report,
        vocabulary=vocabulary,
    )
    return artifact, vocabulary, fixture[1]


def _inference(artifact: NativeModelArtifact, vocabulary) -> NativeLocalInference:
    return NativeLocalInference(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=LABEL_SPACE,
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )


def _policy(artifact, vocabulary, task_id: str = TASK_ID):
    return SuggestionValidationPolicy(
        task_id=task_id,
        expected_model_version=artifact.model_config_payload.model_version,
        expected_vocabulary_hash=vocabulary.vocabulary_hash,
        allowed_labels=LABEL_SPACE,
        minimum_probability=0.0,
        maximum_suggestions=2,
    )


def _benchmark(inference, policy, texts, config=EXPECTED_CONFIG):
    return run_native_benchmark(
        inference=inference, policy=policy, texts=tuple(texts), config=config
    )


def _run_configuration(dataset_manifest: DatasetManifest, snapshot_hash=None):
    split_manifest = EvaluationSplitManifest(
        contract_version="1",
        dataset_id=dataset_manifest.dataset_id,
        dataset_snapshot_hash=snapshot_hash or dataset_manifest.dataset_fingerprint,
        task_id=TASK_ID,
        entries=tuple(
            {
                "example_id": example_id,
                "split": "TEST",
                "expected_labels": EXPECTED_LABELS[example_id],
            }
            for example_id in EXAMPLE_IDS
        ),
    )
    return EvaluationRunConfiguration(
        contract_version="1",
        run_id="stage8-synthetic-run",
        task=_task(),
        metric_configuration=_metric_configuration(),
        split_manifest=split_manifest,
        evaluated_splits=("TEST",),
    )


def _baseline():
    return tuple(
        CandidatePrediction(
            example_id=example_id,
            predicted_labels=EXPECTED_LABELS[example_id],
            abstained=False,
            latency_ms=1.0,
        )
        for example_id in EXAMPLE_IDS
    )


@dataclass
class Setup:
    run_configuration: EvaluationRunConfiguration
    dataset_manifest: DatasetManifest
    artifact: NativeModelArtifact
    inference: NativeLocalInference
    policy: SuggestionValidationPolicy
    texts: dict[str, str]
    baseline: tuple[CandidatePrediction, ...]
    benchmark: NativeBenchmarkReport

    def kwargs(self, **patch: Any) -> dict[str, Any]:
        value: dict[str, Any] = {
            "run_configuration": self.run_configuration,
            "dataset_manifest": self.dataset_manifest,
            "artifact": self.artifact,
            "inference": self.inference,
            "policy": self.policy,
            "texts_by_example_id": self.texts,
            "baseline_predictions": self.baseline,
            "benchmark": self.benchmark,
            "expected_benchmark_config": EXPECTED_CONFIG,
        }
        value.update(patch)
        return value

    def run(self, **patch: Any) -> Stage8AcceptanceReport:
        return run_stage8_acceptance_gate(**self.kwargs(**patch))

    def code(self, **patch: Any) -> str:
        with pytest.raises(Stage8AcceptanceError) as caught:
            self.run(**patch)
        return caught.value.code


def _setup(snapshot_hash: str | None = None) -> Setup:
    artifact, vocabulary, dataset_manifest = _trained()
    inference = _inference(artifact, vocabulary)
    policy = _policy(artifact, vocabulary)
    texts = dict(TEXTS)
    return Setup(
        run_configuration=_run_configuration(dataset_manifest, snapshot_hash),
        dataset_manifest=dataset_manifest,
        artifact=artifact,
        inference=inference,
        policy=policy,
        texts=texts,
        baseline=_baseline(),
        benchmark=_benchmark(
            inference, policy, [texts[example_id] for example_id in EXAMPLE_IDS]
        ),
    )


def _other_checkpoint(setup: Setup):
    """A different checkpoint with the same model version and vocabulary."""
    fixture = _fixture()
    other_config = fixture[5].model_copy(update={"epochs": 4})
    artifact, vocabulary, _ = _trained(fixture, training_config=other_config)
    assert artifact.artifact_hash != setup.artifact.artifact_hash
    assert (
        artifact.model_config_payload.model_version
        == setup.artifact.model_config_payload.model_version
    )
    assert artifact.vocabulary_hash == setup.artifact.vocabulary_hash
    return artifact, vocabulary


# --- preserved behaviour --------------------------------------------------------------


def test_stage8_gate_never_accepts_synthetic_dataset():
    setup = _setup()
    report = setup.run()
    assert report.accepted is False
    assert report.authorized_real_data is False
    assert "REAL_AUTHORIZED_DATA_REQUIRED" in report.blockers
    assert report.evaluation.run_configuration_hash


def test_stage8_gate_rejects_detached_dataset_snapshot():
    assert _setup("f" * 64).code() == "DATASET_BINDING_MISMATCH"


def test_stage8_gate_rejects_missing_test_text():
    setup = _setup()
    setup.texts.pop("example-1")
    assert setup.code() == "TEST_TEXT_SET_MISMATCH"


def test_stage8_gate_rejects_non_text_test_inputs():
    setup = _setup()
    setup.texts["example-1"] = 7  # type: ignore[assignment]
    assert setup.code() == "TEST_TEXT_INVALID"


def test_stage8_gate_rejects_baseline_that_misses_a_test_example():
    setup = _setup()
    assert setup.code(baseline_predictions=setup.baseline[:-1]) == (
        "BASELINE_SET_MISMATCH"
    )


# --- the report carries the exact identities -----------------------------------------


def test_report_binds_artifact_policy_and_benchmark_identity():
    setup = _setup()
    report = setup.run()
    assert report.contract_version == STAGE8_ACCEPTANCE_CONTRACT_VERSION == "2"
    assert report.artifact_hash == setup.artifact.artifact_hash
    assert report.artifact_hash == setup.inference.artifact_hash
    assert report.artifact_hash == report.benchmark.artifact_hash
    assert report.policy_hash == setup.policy.policy_hash()
    assert report.policy_hash == report.benchmark.policy_hash
    assert report.benchmark.benchmark_config_hash == EXPECTED_CONFIG.config_hash()
    assert report.evaluation.candidate.system_id == report.model_version
    assert report.evaluation.baseline.system_id == BASELINE_SYSTEM_ID
    assert report.evaluation.run_id == report.run_id


# --- negative end-to-end: artifact, policy, configuration, workload -----------------


def test_benchmark_on_another_checkpoint_with_same_version_is_rejected():
    setup = _setup()
    other_artifact, other_vocabulary = _other_checkpoint(setup)
    other_inference = _inference(other_artifact, other_vocabulary)
    other_policy = _policy(other_artifact, other_vocabulary)
    assert other_policy.policy_hash() == setup.policy.policy_hash()
    other_benchmark = _benchmark(
        other_inference, other_policy, [TEXTS[item] for item in EXAMPLE_IDS]
    )
    assert other_benchmark.model_version == setup.benchmark.model_version
    assert other_benchmark.vocabulary_hash == setup.benchmark.vocabulary_hash
    assert setup.code(benchmark=other_benchmark) == "BENCHMARK_ARTIFACT_MISMATCH"


def test_inference_adapter_built_from_another_checkpoint_is_rejected():
    setup = _setup()
    other_artifact, other_vocabulary = _other_checkpoint(setup)
    assert (
        setup.code(inference=_inference(other_artifact, other_vocabulary))
        == "INFERENCE_ARTIFACT_MISMATCH"
    )


def test_benchmark_under_a_different_policy_is_rejected():
    setup = _setup()
    other_policy = _policy(setup.artifact, setup.inference.vocabulary, "other-task")
    assert other_policy.policy_hash() != setup.policy.policy_hash()
    benchmark = _benchmark(
        setup.inference, other_policy, [TEXTS[item] for item in EXAMPLE_IDS]
    )
    assert setup.code(benchmark=benchmark) == "BENCHMARK_POLICY_MISMATCH"


@pytest.mark.parametrize(
    "patch",
    [
        {"latency_budget_ms": 50000.0},
        {"peak_memory_budget_bytes": 2**31},
        {"measured_iterations": 8},
        {"warmup_iterations": 1},
    ],
)
def test_benchmark_with_other_budgets_or_configuration_is_rejected(patch):
    setup = _setup()
    other = EXPECTED_CONFIG.model_copy(update=patch)
    benchmark = _benchmark(
        setup.inference, setup.policy, [TEXTS[item] for item in EXAMPLE_IDS], other
    )
    assert benchmark.benchmark_config_hash != EXPECTED_CONFIG.config_hash()
    assert setup.code(benchmark=benchmark) == "BENCHMARK_CONFIG_MISMATCH"


def test_gate_requires_the_predeclared_configuration_to_match_the_benchmark():
    setup = _setup()
    changed = EXPECTED_CONFIG.model_copy(update={"latency_budget_ms": 59999.0})
    assert setup.code(expected_benchmark_config=changed) == "BENCHMARK_CONFIG_MISMATCH"


def test_gate_requires_an_expected_benchmark_configuration():
    setup = _setup()
    arguments = setup.kwargs()
    del arguments["expected_benchmark_config"]
    with pytest.raises(TypeError):
        run_stage8_acceptance_gate(**arguments)


def test_benchmark_on_a_different_workload_is_rejected():
    setup = _setup()
    ordered = [TEXTS[item] for item in EXAMPLE_IDS]
    different_content = [*ordered[:-1], "synthetic something else"]
    swapped = [ordered[1], ordered[0], *ordered[2:]]
    for workload in (different_content, swapped, ordered[:2]):
        benchmark = _benchmark(setup.inference, setup.policy, workload)
        assert setup.code(benchmark=benchmark) == "BENCHMARK_WORKLOAD_MISMATCH"


def test_workload_digest_uses_canonical_test_entry_order_not_dict_order():
    setup = _setup()
    reordered_texts = {item: TEXTS[item] for item in reversed(EXAMPLE_IDS)}
    report = setup.run(texts_by_example_id=reordered_texts)
    assert report.benchmark.case_set_digest == case_set_digest(
        tuple(TEXTS[item] for item in EXAMPLE_IDS)
    )


# --- negative end-to-end: detached training and dataset identities -------------------


def test_dataset_manifest_with_a_detached_train_fingerprint_is_rejected():
    setup = _setup()
    manifest = setup.dataset_manifest
    detached = manifest.model_copy(
        update={
            "split_fingerprints": tuple(
                (name, "f" * 64 if name == "train" else value)
                for name, value in manifest.split_fingerprints
            )
        }
    )
    assert setup.code(dataset_manifest=detached) == "TRAINING_DATASET_MISMATCH"


def test_artifact_trained_on_a_different_train_split_is_rejected():
    setup = _setup()
    other_artifact, other_vocabulary, _ = _trained(_fixture(train_count=5))
    assert other_artifact.dataset_fingerprint != setup.artifact.dataset_fingerprint
    inference = _inference(other_artifact, other_vocabulary)
    policy = _policy(other_artifact, other_vocabulary)
    benchmark = _benchmark(inference, policy, [TEXTS[item] for item in EXAMPLE_IDS])
    assert (
        setup.code(
            artifact=other_artifact,
            inference=inference,
            policy=policy,
            benchmark=benchmark,
        )
        == "TRAINING_DATASET_MISMATCH"
    )


def test_inference_label_space_must_be_the_trained_label_space():
    setup = _setup()

    class _Relabelled(NativeLocalInference):
        @property
        def labels(self) -> tuple[str, ...]:
            return ("OTHER_A", "OTHER_B")

    relabelled = _Relabelled(
        artifact=setup.artifact,
        vocabulary=setup.inference.vocabulary,
        labels=LABEL_SPACE,
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )
    assert setup.code(inference=relabelled) == "LABEL_SPACE_BINDING_MISMATCH"


def test_synthetic_fixtures_cannot_satisfy_real_data_acceptance():
    setup = _setup()
    assert setup.dataset_manifest.source.is_synthetic is True
    report = setup.run()
    assert report.accepted is False
    assert report.authorized_real_data is False
    assert "REAL_AUTHORIZED_DATA_REQUIRED" in report.blockers


# --- report-level consistency (public contract) --------------------------------------


def _payload(report: Stage8AcceptanceReport) -> dict[str, Any]:
    return copy.deepcopy(report.model_dump())


def _rejected(payload: dict[str, Any], reason: str | None = None) -> None:
    """The payload must fail; ``reason`` pins which validator rejected it."""
    with pytest.raises(ValidationError, match=reason):
        Stage8AcceptanceReport.model_validate(payload)


def _expected_blockers(payload: dict[str, Any]) -> list[str]:
    blockers = []
    if not payload["authorized_real_data"]:
        blockers.append("REAL_AUTHORIZED_DATA_REQUIRED")
    if not payload["benchmark"]["within_declared_budgets"]:
        blockers.append("RESOURCE_BUDGET_FAILED")
    if not payload["evaluation"]["accepted"]:
        blockers.append("EVALUATION_GATE_FAILED")
    return sorted(blockers)


def test_valid_report_round_trips_through_the_public_schema():
    report = _setup().run()
    assert Stage8AcceptanceReport.model_validate(_payload(report)) == report


def test_consistent_report_with_real_data_authorization_validates():
    payload = _payload(_setup().run())
    payload["authorized_real_data"] = True
    payload["blockers"] = tuple(_expected_blockers(payload))
    payload["accepted"] = not payload["blockers"]
    report = Stage8AcceptanceReport.model_validate(payload)
    assert report.accepted is (not report.blockers)
    # The acceptance flag cannot be flipped independently of the gates.
    flipped = _payload(report)
    flipped["accepted"] = not flipped["accepted"]
    _rejected(flipped, "requires every gate to pass")


@pytest.mark.parametrize(
    "path",
    [
        ("run_id",),
        ("dataset_id",),
        ("dataset_fingerprint",),
        ("model_version",),
        ("vocabulary_hash",),
        ("artifact_hash",),
        ("policy_hash",),
        ("benchmark", "artifact_hash"),
        ("benchmark", "policy_hash"),
        ("benchmark", "vocabulary_hash"),
        ("benchmark", "model_version"),
        ("evaluation", "run_id"),
        ("evaluation", "dataset_id"),
        ("evaluation", "dataset_snapshot_hash"),
        ("evaluation", "candidate", "system_id"),
    ],
)
def test_report_rejects_a_child_that_identifies_a_different_run_or_artifact(path):
    payload = _payload(_setup().run())
    target = payload
    for key in path[:-1]:
        target = target[key]
    original = target[path[-1]]
    is_hash = len(original) == 64 and not original.strip("0123456789abcdef")
    # A well-formed but different value, so only the cross-report identity
    # check (not a pattern or length check) can reject it.
    replacement = (
        ("e" * 64 if original != "e" * 64 else "d" * 64) if is_hash else ("other-value")
    )
    target[path[-1]] = replacement
    _rejected(payload, "match the report|not the reported")


def test_report_rejects_a_benchmark_that_did_not_cover_the_evaluated_examples():
    payload = _payload(_setup().run())
    payload["benchmark"]["case_count"] = 3
    payload["benchmark"]["cases_measured"] = 3
    _rejected(payload, "does not cover the evaluated examples")


def test_report_rejects_forged_acceptance_and_blockers():
    base = _payload(_setup().run())
    assert base["accepted"] is False

    forged = copy.deepcopy(base)
    forged["accepted"] = True
    _rejected(forged, "requires every gate to pass")

    forged = copy.deepcopy(base)
    forged["blockers"] = ()
    _rejected(forged, "blockers contradict")

    forged = copy.deepcopy(base)
    forged["blockers"] = tuple(
        item for item in base["blockers"] if item != "REAL_AUTHORIZED_DATA_REQUIRED"
    )
    _rejected(forged, "blockers contradict")

    forged = copy.deepcopy(base)
    forged["authorized_real_data"] = True  # blocker for it must now disappear
    forged["blockers"] = base["blockers"]
    _rejected(forged, "blockers contradict")

    forged = copy.deepcopy(base)
    forged["blockers"] = tuple(sorted({*base["blockers"], "RESOURCE_BUDGET_FAILED"}))
    _rejected(forged, "blockers contradict")


def test_report_rejects_old_contract_version_and_missing_identities():
    base = _payload(_setup().run())
    old = copy.deepcopy(base)
    old["contract_version"] = "1"
    _rejected(old)
    for field in ("artifact_hash", "policy_hash"):
        missing = copy.deepcopy(base)
        del missing[field]
        _rejected(missing)

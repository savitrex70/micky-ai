"""Task 210: bounded, deterministic native training loop tests.

Synthetic fixtures only. No network access, pretrained artifacts,
external datasets, or GPU hardware is required. Convergence is never
asserted: a completed run proves loop plumbing only.
"""

from __future__ import annotations

import pytest
import torch
from pydantic import ValidationError

from rop.dataset_preparation import compose_test_registry, prepare_dataset
from rop.dataset_preparation.pipeline import partition_records
from rop.native_model import initialize_model
from rop.schemas.dataset_manifest import GroupAssignment, PreparationResult
from rop.schemas.native_model import NativeModelConfig
from rop.schemas.tokenizer import TokenizerConfig, Vocabulary
from rop.schemas.training import (
    MAX_BATCH_SIZE,
    MAX_EPOCHS,
    MAX_LEARNING_RATE,
    EpochMetrics,
    TrainingConfig,
    TrainingReport,
)
from rop.tokenizer import build_vocabulary
from rop.training import NativeTrainingError, run_training
from rop.training import loop as training_loop_module

REGISTRY = compose_test_registry(
    [
        {
            "source_id": "synthetic-test-loop-1",
            "authorization_version": "1.0",
            "origin_description": "In-repo synthetic fixture source",
            "license_basis": "repo-internal-synthetic",
            "intended_purpose": "native-training",
            "permitted_operations": ("training",),
            "status": "APPROVED",
            "approval_reference": "approval-loop-1",
            "valid_until": "2999-12-31",
        }
    ]
)

_WORDS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
)

_TOKENIZER_CONFIG = TokenizerConfig(
    tokenizer_version="1.0",
    normalization="NFC",
    preserve_case=True,
    max_sequence_length=8,
)

_TRAINING_CONFIG = {
    "contract_version": "1",
    "epochs": 2,
    "batch_size": 4,
    "learning_rate": 0.1,
    "seed": 99,
}


def _build_result() -> PreparationResult:
    """Build a governed synthetic dataset with all partitions populated."""
    records = []
    for index, word in enumerate(_WORDS, start=1):
        records.append(
            {
                "record_id": f"r-{index:02d}",
                "source_id": "synthetic-test-loop-1",
                "group_id": f"g-{index:02d}",
                "label": "alpha" if index % 2 == 1 else "beta",
                "content_text": f"synthetic {word} text sample {index}",
                "provenance_ref": "synthetic-in-repo-fixture-1",
            }
        )
    return prepare_dataset(
        records=records,
        authorizations=REGISTRY,
        dataset_id="synthetic-native-loop",
        purpose="native-training",
        operation="training",
        as_of="2026-01-01",
        allowed_labels=("alpha", "beta"),
        grouping_unit="single record",
        split_config={
            "seed": 7,
            "train_ratio": 0.5,
            "validation_ratio": 0.25,
            "test_ratio": 0.25,
        },
    )


_RESULT = _build_result()
"""Shared, immutable PreparationResult (pydantic frozen)."""

_VOCABULARY = build_vocabulary(_RESULT, tokenizer_config=_TOKENIZER_CONFIG)

_MODEL_CONFIG = NativeModelConfig(
    model_version="1.0",
    architecture="tiny-encoder-v1",
    vocab_size=_VOCABULARY.metadata.vocabulary_size,
    hidden_dim=16,
    num_layers=1,
    num_heads=4,
    max_seq_len=16,
    num_classes=2,
    dropout=0.1,
    init_seed=42,
    init_std=0.05,
)

assert len(partition_records(_RESULT, "train")) > 0
assert len(partition_records(_RESULT, "validation")) > 0
assert len(partition_records(_RESULT, "test")) > 0
assert len(_VOCABULARY.tokens) >= 3


def _fresh_model() -> torch.nn.Module:
    return initialize_model(_MODEL_CONFIG)


def _run(
    model: torch.nn.Module | None = None,
    result: PreparationResult = _RESULT,
    vocabulary: Vocabulary = _VOCABULARY,
):
    return run_training(
        result,
        model=model if model is not None else _fresh_model(),
        vocabulary=vocabulary,
        tokenizer_config=_TOKENIZER_CONFIG,
        config=TrainingConfig(**_TRAINING_CONFIG),
    )


def _snapshot(model: torch.nn.Module) -> dict[str, torch.Tensor]:
    return {
        name: parameter.detach().clone() for name, parameter in model.named_parameters()
    }


def _assert_equal_snapshots(
    first: dict[str, torch.Tensor], second: dict[str, torch.Tensor]
) -> None:
    assert set(first) == set(second)
    for name, value in first.items():
        assert torch.equal(value, second[name]), f"parameter {name} differs"


# --- Successful training --------------------------------------------------------


class TestSuccessfulTraining:
    def test_small_dataset_completes_bounded_run(self) -> None:
        report = _run()
        assert report.run_completed is True
        assert report.synthetic_only is True
        assert report.authorization_kind == "synthetic-test-only"
        assert report.dataset_id == "synthetic-native-loop"
        assert report.model_version == "1.0"
        assert report.architecture == "tiny-encoder-v1"
        assert len(report.model_config_hash) == 64
        assert len(report.training_config_hash) == 64

    def test_parameters_change_after_valid_optimizer_update(self) -> None:
        model = _fresh_model()
        before = _snapshot(model)
        _run(model)
        after = _snapshot(model)
        changed = any(not torch.equal(before[name], after[name]) for name in before)
        assert changed, "no parameter changed after a valid training run"

    def test_report_metrics_structure_and_finiteness(self) -> None:
        report = _run()
        assert isinstance(report, TrainingReport)
        for entry in report.epoch_metrics:
            assert isinstance(entry, EpochMetrics)
            assert entry.epoch >= 1
            assert entry.train_examples >= 1
            assert entry.train_batches >= 1
            assert entry.validation_examples >= 1
            assert entry.validation_batches >= 1
            for value in (
                entry.train_loss,
                entry.validation_loss,
                entry.validation_accuracy,
            ):
                assert isinstance(value, float)
                assert value == value and abs(value) != float("inf")

    def test_epoch_and_batch_counts_reflect_completed_work(self) -> None:
        config = TrainingConfig(**_TRAINING_CONFIG)
        report = _run()
        train_count = len(partition_records(_RESULT, "train"))
        expected_batches = -(-train_count // config.batch_size)
        assert report.epochs_completed == config.epochs == len(report.epoch_metrics)
        assert report.batches_completed == config.epochs * expected_batches
        assert report.train_example_count == train_count
        for entry in report.epoch_metrics:
            assert entry.train_batches == expected_batches
            assert entry.train_examples == train_count

    def test_model_mode_restored_after_run(self) -> None:
        model = _fresh_model()
        assert model.training is False  # initialize_model returns eval mode
        _run(model)
        assert model.training is False


# --- Determinism and isolation --------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_repeatable(self) -> None:
        first = _run()
        second = _run()
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_run_preserves_global_rng_state(self) -> None:
        torch.manual_seed(12345)
        reference = torch.rand(3)
        torch.manual_seed(12345)
        state_before = torch.get_rng_state()
        _run()
        assert torch.equal(state_before, torch.get_rng_state())
        following = torch.rand(3)
        assert torch.equal(reference, following)

    def test_rng_preserved_even_when_run_fails(self) -> None:
        torch.manual_seed(12345)
        reference = torch.rand(3)
        torch.manual_seed(12345)
        state_before = torch.get_rng_state()
        tampered = _tamper_field(_RESULT, "train", "label", "zeta-unknown")
        with pytest.raises(NativeTrainingError):
            _run(_fresh_model(), tampered)
        assert torch.equal(state_before, torch.get_rng_state())
        assert torch.equal(reference, torch.rand(3))


class TestPartitionIsolation:
    def test_loop_never_requests_test_partition(self, monkeypatch) -> None:
        requested: list[str] = []
        real = training_loop_module.partition_records

        def spy(result, partition):
            requested.append(partition)
            return real(result, partition)

        monkeypatch.setattr(training_loop_module, "partition_records", spy)
        _run()
        assert "test" not in requested
        assert set(requested) == {"train", "validation"}
        real_partition_names = [entry.partition for entry in _RESULT.partitions]
        assert real_partition_names == ["train", "validation", "test"]

    def test_tampered_test_partition_fails_integrity_preflight(self) -> None:
        """The pre-fit integrity preflight covers the complete record set.

        A corrupted test partition fails dataset integrity verification
        before any fitting; this is the one narrow, structural reason
        the loop reads test records (never encoding, fitting, evaluate,
        selecting, logging, or reporting them).
        """
        tampered = _tamper_field(_RESULT, "test", "label", "zeta-poison")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=tampered)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_dataset_view_excludes_test_examples(self) -> None:
        dataset = training_loop_module.build_training_dataset(
            _RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
        used_ids = {
            example.record_id
            for example in (*dataset.train_examples, *dataset.validation_examples)
        }
        test_ids = {record.record_id for record in partition_records(_RESULT, "test")}
        train_ids = {record.record_id for record in partition_records(_RESULT, "train")}
        validation_ids = {
            record.record_id for record in partition_records(_RESULT, "validation")
        }
        assert used_ids == train_ids | validation_ids
        assert used_ids.isdisjoint(test_ids)
        assert dataset.train_examples and dataset.validation_examples

    def test_validation_evaluation_never_updates_parameters(self) -> None:
        model = _fresh_model()
        real_evaluate = training_loop_module._evaluate_validation
        windows: list[tuple[dict[str, torch.Tensor], dict[str, torch.Tensor]]] = []

        def spy(*args, **kwargs):
            before = _snapshot(model)
            outcome = real_evaluate(*args, **kwargs)
            after = _snapshot(model)
            windows.append((before, after))
            return outcome

        training_loop_module._evaluate_validation = spy
        try:
            _run(model)
        finally:
            training_loop_module._evaluate_validation = real_evaluate
        epochs = TrainingConfig(**_TRAINING_CONFIG).epochs
        assert len(windows) == epochs
        for before, after in windows:
            _assert_equal_snapshots(before, after)

    def test_optimizer_steps_only_on_training_batches(self) -> None:
        model = _fresh_model()
        real_cls = training_loop_module._OPTIMIZER_CLS
        steps: list[int] = []

        class SpyOptimizer(real_cls):  # type: ignore[valid-type,misc]
            def step(self, *args, **kwargs):
                steps.append(1)
                return super().step(*args, **kwargs)

        monkey_train = training_loop_module._train_one_epoch
        training_loop_module._OPTIMIZER_CLS = SpyOptimizer
        train_batches: list[int] = []
        real_train_epoch = training_loop_module._train_one_epoch

        def epoch_spy(*args, **kwargs):
            outcome = real_train_epoch(*args, **kwargs)
            train_batches.append(len(outcome))
            return outcome

        training_loop_module._train_one_epoch = epoch_spy
        try:
            report = _run(model)
        finally:
            training_loop_module._OPTIMIZER_CLS = real_cls
            training_loop_module._train_one_epoch = monkey_train
        assert len(steps) == sum(train_batches)
        assert report.batches_completed == sum(train_batches)

    def test_fitting_consumes_only_training_examples(self) -> None:
        """Every fitted example comes from the train partition only."""
        dataset = training_loop_module.build_training_dataset(
            _RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
        validation_ids = {example.record_id for example in dataset.validation_examples}
        model = _fresh_model()
        real_train_epoch = training_loop_module._train_one_epoch
        fitted: list[list[str]] = []

        def spy(examples, **kwargs):
            fitted.append([example.record_id for example in examples])
            return real_train_epoch(examples, **kwargs)

        training_loop_module._train_one_epoch = spy
        try:
            _run(model)
        finally:
            training_loop_module._train_one_epoch = real_train_epoch
        for examples in fitted:
            assert not (set(examples) & validation_ids)


# --- Input and integrity validation ---------------------------------------------


def _tamper_field(
    result: PreparationResult, partition: str, field: str, value: object
) -> PreparationResult:
    """Tamper one record field inside one partition (schema-construction bypass)."""
    target = next(entry for entry in result.partitions if entry.partition == partition)
    first = target.records[0]
    tampered = first.model_copy(update={field: value})
    new_partition = target.model_copy(
        update={
            "records": tuple(
                tampered if record.record_id == first.record_id else record
                for record in target.records
            )
        }
    )
    return result.model_copy(
        update={
            "partitions": tuple(
                new_partition if entry.partition == partition else entry
                for entry in result.partitions
            )
        }
    )


def _swap_assignments(result: PreparationResult) -> PreparationResult:
    """Swap the first two split assignments, leaving the recorded hash alone."""
    assignments = list(result.split_manifest.assignments)
    assert len(assignments) >= 2
    first, second = assignments[0], assignments[1]
    swapped = [
        GroupAssignment(group_id=first.group_id, partition=second.partition),
        GroupAssignment(group_id=second.group_id, partition=first.partition),
        *assignments[2:],
    ]
    split = result.split_manifest.model_copy(update={"assignments": tuple(swapped)})
    return result.model_copy(update={"split_manifest": split})


def _current_record_label(result: PreparationResult, partition: str) -> str:
    target = next(entry for entry in result.partitions if entry.partition == partition)
    return target.records[0].label


class TestInputAndIntegrityValidation:
    def test_non_preparation_result_rejected(self) -> None:
        with pytest.raises(NativeTrainingError) as exc:
            run_training(
                "not a result",
                model=_fresh_model(),
                vocabulary=_VOCABULARY,
                tokenizer_config=_TOKENIZER_CONFIG,
                config=TrainingConfig(**_TRAINING_CONFIG),
            )  # type: ignore[arg-type]
        assert exc.value.code == "INVALID_INPUT"

    def test_tampered_vocabulary_identity_rejected(self) -> None:
        tampered_metadata = _VOCABULARY.metadata.model_copy(
            update={"dataset_id": "synthetic-other-dataset"}
        )
        tampered_vocab = Vocabulary(
            metadata=tampered_metadata, tokens=_VOCABULARY.tokens
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), _RESULT, tampered_vocab)
        assert exc.value.code == "INCOMPATIBLE_DATASET"

    def test_unauthorized_scope_unexpressible_and_rejected(self) -> None:
        """Only synthetic-test-only scope can be constructed as data input.

        The scope fields are Literal types, so no real, clinical, or
        production trust scope can be manufactured through the Task
        207/208/210 data contracts; the integrity hashes still catch
        any in-memory tampering (see the vocab identity test).
        """
        from rop.schemas.dataset_manifest import DatasetManifest

        manifest_fields = _RESULT.dataset_manifest.model_dump()
        manifest_fields["authorization_kind"] = "real-clinical-data"
        with pytest.raises(ValidationError):
            DatasetManifest.model_validate(manifest_fields)
        tokenizer_fields = _TOKENIZER_CONFIG.model_dump()
        tokenizer_fields["normalization"] = "NFKC-FORGED"
        with pytest.raises(ValidationError):
            TokenizerConfig.model_validate(tokenizer_fields)

    def test_split_assignment_hash_tamper_rejected(self) -> None:
        """A forged assignment hash fails the Task 207 replay check first."""
        changed_split = _RESULT.split_manifest.model_copy(
            update={"assignment_hash": "0" * 64}
        )
        broken = _RESULT.model_copy(update={"split_manifest": changed_split})
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_tampered_train_record_label_rejected(self) -> None:
        """A permitted-label change with unchanged content closes the gap.

        Flipping a train record from alpha to beta (both labels are
        permitted) leaves the content digest untouched, so only the
        independent Task 207 record-integrity verification catches it:
        the canonical integrity representation binds the label.
        """
        old_label = _current_record_label(_RESULT, "train")
        other = "beta" if old_label == "alpha" else "alpha"
        broken = _tamper_field(_RESULT, "train", "label", other)
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_tampered_group_id_rejected(self) -> None:
        broken = _tamper_field(_RESULT, "train", "group_id", "g-tampered")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_tampered_source_id_rejected(self) -> None:
        broken = _tamper_field(_RESULT, "train", "source_id", "synthetic-other")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_tampered_record_id_rejected(self) -> None:
        broken = _tamper_field(_RESULT, "train", "record_id", "r-tampered")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_tampered_provenance_rejected(self) -> None:
        broken = _tamper_field(
            _RESULT, "train", "provenance_ref", "synthetic-forged-ref"
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_split_assignment_tamper_with_stale_hash_rejected(self) -> None:
        """Swapped assignments with an unchanged recorded hash fail."""
        broken = _swap_assignments(_RESULT)
        assert (
            broken.split_manifest.assignment_hash
            == _RESULT.split_manifest.assignment_hash
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_split_seed_violating_split_contract_rejected(self) -> None:
        """Split metadata that no longer matches the deterministic
        assignment policy fails replay verification.
        """
        changed_split = _RESULT.split_manifest.model_copy(
            update={"seed": _RESULT.split_manifest.seed + 1}
        )
        broken = _RESULT.model_copy(update={"split_manifest": changed_split})
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_manifest_hash_diverges_from_recomputed_integrity_rejected(
        self,
    ) -> None:
        """Cross-artifact agreement is checked against the recomputed
        integrity hash, not only among recorded values.
        """
        changed_manifest = _RESULT.dataset_manifest.model_copy(
            update={"record_integrity_hash": "0" * 64}
        )
        broken = _RESULT.model_copy(update={"dataset_manifest": changed_manifest})
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "HASH_MISMATCH"

    def test_preflight_failure_never_creates_optimizer_or_updates_params(
        self, monkeypatch
    ) -> None:
        """A pre-training integrity failure precedes optimizer creation."""
        real_cls = training_loop_module._OPTIMIZER_CLS
        built: list[int] = []

        class SpyOptimizer(real_cls):  # type: ignore[valid-type,misc]
            def __init__(self, *args, **kwargs):
                built.append(1)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(training_loop_module, "_OPTIMIZER_CLS", SpyOptimizer)
        model = _fresh_model()
        before = _snapshot(model)
        old_label = _current_record_label(_RESULT, "train")
        other = "beta" if old_label == "alpha" else "alpha"
        broken = _tamper_field(_RESULT, "train", "label", other)
        with pytest.raises(NativeTrainingError) as exc:
            _run(model, broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
        assert built == []
        _assert_equal_snapshots(before, _snapshot(model))

    def test_model_class_mismatch_rejected(self) -> None:
        mismatched = NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=_MODEL_CONFIG.vocab_size,
            hidden_dim=16,
            num_layers=1,
            num_heads=4,
            max_seq_len=16,
            num_classes=3,
            dropout=0.1,
            init_seed=42,
            init_std=0.05,
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(initialize_model(mismatched))
        assert exc.value.code == "INCOMPATIBLE_MODEL"

    def test_vocabulary_size_mismatch_rejected(self) -> None:
        mismatched = NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=_MODEL_CONFIG.vocab_size + 1,
            hidden_dim=16,
            num_layers=1,
            num_heads=4,
            max_seq_len=16,
            num_classes=2,
            dropout=0.1,
            init_seed=42,
            init_std=0.05,
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(initialize_model(mismatched))
        assert exc.value.code == "INCOMPATIBLE_VOCABULARY"

    def test_tokenizer_sequence_length_over_model_limit_rejected(self) -> None:
        longer = TokenizerConfig(
            tokenizer_version="1.0",
            normalization="NFC",
            preserve_case=True,
            max_sequence_length=_MODEL_CONFIG.max_seq_len + 1,
        )
        with pytest.raises(NativeTrainingError) as exc:
            run_training(
                _RESULT,
                model=_fresh_model(),
                vocabulary=_VOCABULARY,
                tokenizer_config=longer,
                config=TrainingConfig(**_TRAINING_CONFIG),
            )
        assert exc.value.code == "INCOMPATIBLE_TOKENIZER"

    def test_invalid_tokenizer_config_rejected(self) -> None:
        with pytest.raises(NativeTrainingError) as exc:
            run_training(
                _RESULT,
                model=_fresh_model(),
                vocabulary=_VOCABULARY,
                tokenizer_config={"tokenizer_version": "1.0"},
                config=TrainingConfig(**_TRAINING_CONFIG),
            )
        assert exc.value.code == "INVALID_CONFIG"

    def test_empty_training_partition_rejected(self) -> None:
        result = prepare_dataset(
            records=[
                {
                    "record_id": "r-01",
                    "source_id": "synthetic-test-loop-1",
                    "group_id": "g-01",
                    "label": "alpha",
                    "content_text": "synthetic one record here",
                    "provenance_ref": "synthetic-in-repo-fixture-1",
                },
                {
                    "record_id": "r-02",
                    "source_id": "synthetic-test-loop-1",
                    "group_id": "g-02",
                    "label": "beta",
                    "content_text": "synthetic two records here",
                    "provenance_ref": "synthetic-in-repo-fixture-1",
                },
            ],
            authorizations=REGISTRY,
            dataset_id="synthetic-native-loop",
            purpose="native-training",
            operation="training",
            as_of="2026-01-01",
            allowed_labels=("alpha", "beta"),
            grouping_unit="single record",
            split_config={
                "seed": 7,
                "train_ratio": 0.0,
                "validation_ratio": 1.0,
                "test_ratio": 0.0,
            },
        )
        assert len(partition_records(result, "train")) == 0
        assert len(partition_records(result, "validation")) == 2
        vocabulary = build_vocabulary(result, tokenizer_config=_TOKENIZER_CONFIG)
        assert vocabulary.metadata.vocabulary_size == 2
        model = initialize_model(
            NativeModelConfig(
                model_version="1.0",
                architecture="tiny-encoder-v1",
                vocab_size=2,
                hidden_dim=16,
                num_layers=1,
                num_heads=4,
                max_seq_len=16,
                num_classes=2,
                dropout=0.1,
                init_seed=42,
                init_std=0.05,
            )
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(model, result=result, vocabulary=vocabulary)
        assert exc.value.code == "EMPTY_PARTITION"

    def test_empty_validation_partition_rejected(self) -> None:
        result = prepare_dataset(
            records=[
                {
                    "record_id": "r-01",
                    "source_id": "synthetic-test-loop-1",
                    "group_id": "g-01",
                    "label": "alpha",
                    "content_text": "synthetic one record here",
                    "provenance_ref": "synthetic-in-repo-fixture-1",
                },
                {
                    "record_id": "r-02",
                    "source_id": "synthetic-test-loop-1",
                    "group_id": "g-02",
                    "label": "beta",
                    "content_text": "synthetic two records here",
                    "provenance_ref": "synthetic-in-repo-fixture-1",
                },
            ],
            authorizations=REGISTRY,
            dataset_id="synthetic-native-loop",
            purpose="native-training",
            operation="training",
            as_of="2026-01-01",
            allowed_labels=("alpha", "beta"),
            grouping_unit="single record",
            split_config={
                "seed": 7,
                "train_ratio": 1.0,
                "validation_ratio": 0.0,
                "test_ratio": 0.0,
            },
        )
        assert len(partition_records(result, "validation")) == 0
        vocabulary = build_vocabulary(result, tokenizer_config=_TOKENIZER_CONFIG)
        model = initialize_model(
            NativeModelConfig(
                model_version="1.0",
                architecture="tiny-encoder-v1",
                vocab_size=vocabulary.metadata.vocabulary_size,
                hidden_dim=16,
                num_layers=1,
                num_heads=4,
                max_seq_len=16,
                num_classes=2,
                dropout=0.1,
                init_seed=42,
                init_std=0.05,
            )
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(model, result=result, vocabulary=vocabulary)
        assert exc.value.code == "EMPTY_PARTITION"

    def test_tampered_record_digest_rejected(self) -> None:
        target = next(
            entry for entry in _RESULT.partitions if entry.partition == "train"
        )
        first = target.records[0]
        tampered = first.model_copy(update={"content_text": "tampered content"})
        new_partition = target.model_copy(
            update={
                "records": tuple(
                    tampered if record.record_id == first.record_id else record
                    for record in target.records
                )
            }
        )
        broken = _RESULT.model_copy(
            update={
                "partitions": tuple(
                    new_partition if entry.partition == "train" else entry
                    for entry in _RESULT.partitions
                )
            }
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "MALFORMED_EXAMPLE"

    def test_oversized_partition_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr(training_loop_module, "MAX_EXAMPLES_PER_PARTITION", 2)
        with pytest.raises(NativeTrainingError) as exc:
            _run()
        assert exc.value.code == "RESOURCE_LIMIT"

    def test_verify_model_hash_failure_rejected(self) -> None:
        model = _fresh_model()
        with torch.no_grad():
            next(model.parameters()).add_(0.5)
        with pytest.raises(NativeTrainingError) as exc:
            _run(model)
        assert exc.value.code == "INVALID_INPUT"


class TestConfigValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("epochs", 0),
            ("epochs", MAX_EPOCHS + 1),
            ("epochs", -1),
            ("epochs", "2"),
            ("epochs", True),
            ("batch_size", 0),
            ("batch_size", MAX_BATCH_SIZE + 1),
            ("batch_size", "4"),
            ("batch_size", False),
            ("learning_rate", 0.0),
            ("learning_rate", -0.1),
            ("learning_rate", MAX_LEARNING_RATE + 0.1),
            ("learning_rate", "0.1"),
            ("learning_rate", True),
            ("seed", -1),
            ("seed", 2**32),
            ("seed", "99"),
            ("seed", True),
        ],
    )
    def test_invalid_training_config_values_rejected(
        self, field: str, value: object
    ) -> None:
        data = dict(_TRAINING_CONFIG)
        data[field] = value  # type: ignore[literal-arg]
        with pytest.raises(ValidationError):
            TrainingConfig.model_validate(data)

    def test_extra_fields_rejected(self) -> None:
        data = dict(_TRAINING_CONFIG)
        data["momentum"] = 0.9
        with pytest.raises(ValidationError):
            TrainingConfig(**data)

    def test_configuration_hash_tracks_changes(self) -> None:
        first = TrainingConfig(**_TRAINING_CONFIG)
        second = TrainingConfig(epochs=2, batch_size=4, learning_rate=0.1, seed=100)
        assert first.configuration_hash() != second.configuration_hash()
        assert first.configuration_hash() == (
            TrainingConfig(**_TRAINING_CONFIG).configuration_hash()
        )


# --- Failure behavior -----------------------------------------------------------


class TestFailureBehavior:
    def test_non_finite_parameter_fails_clearly(self, monkeypatch) -> None:
        real_cls = training_loop_module._OPTIMIZER_CLS

        class CorruptingOptimizer(real_cls):  # type: ignore[valid-type,misc]
            def step(self, *args, **kwargs):
                result = super().step(*args, **kwargs)
                with torch.no_grad():
                    next(iter(self.param_groups[0]["params"])).fill_(float("nan"))
                return result

        monkeypatch.setattr(training_loop_module, "_OPTIMIZER_CLS", CorruptingOptimizer)
        model = _fresh_model()
        with pytest.raises(NativeTrainingError) as exc:
            _run(model)
        assert exc.value.code == "NON_FINITE_PARAMETER"

    def test_non_finite_loss_fails_clearly(self, monkeypatch) -> None:
        real_cross_entropy = training_loop_module.F.cross_entropy

        def infinite_loss(*args, **kwargs):
            return real_cross_entropy(*args, **kwargs) * float("inf")

        monkeypatch.setattr(
            training_loop_module.F,
            "cross_entropy",
            infinite_loss,
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run()
        assert exc.value.code == "NON_FINITE_LOSS"

    def test_failure_does_not_return_report_or_leave_rng_changed(self) -> None:
        torch.manual_seed(12345)
        state_before = torch.get_rng_state()
        broken = _tamper_field(_RESULT, "train", "label", "zeta-unknown")
        with pytest.raises(NativeTrainingError):
            _run(_fresh_model(), broken)
        assert torch.equal(state_before, torch.get_rng_state())

    def test_error_codes_are_stable(self) -> None:
        model = initialize_model(
            NativeModelConfig(
                model_version="1.0",
                architecture="tiny-encoder-v1",
                vocab_size=_MODEL_CONFIG.vocab_size,
                hidden_dim=16,
                num_layers=1,
                num_heads=4,
                max_seq_len=16,
                num_classes=5,
                dropout=0.1,
                init_seed=42,
                init_std=0.05,
            )
        )
        with pytest.raises(NativeTrainingError) as exc:
            _run(model)
        error = exc.value
        assert error.code == "INCOMPATIBLE_MODEL"
        assert isinstance(str(error), str) and error.code in str(error)


# --- Finding 1: Partition container membership verification ---


def _move_record_between_partitions(
    result: PreparationResult, from_partition: str, to_partition: str
) -> PreparationResult:
    """Move the first record from one partition to another
    (schema-construction bypass).
    """
    from_entry = next(
        entry for entry in result.partitions if entry.partition == from_partition
    )
    to_entry = next(
        entry for entry in result.partitions if entry.partition == to_partition
    )
    record_to_move = from_entry.records[0]
    new_from_records = from_entry.records[1:]
    new_to_records = to_entry.records + (record_to_move,)
    new_from = from_entry.model_copy(update={"records": new_from_records})
    new_to = to_entry.model_copy(update={"records": new_to_records})
    return result.model_copy(
        update={
            "partitions": tuple(
                (
                    new_from
                    if entry.partition == from_partition
                    else (new_to if entry.partition == to_partition else entry)
                )
                for entry in result.partitions
            )
        }
    )


class TestPartitionMembershipVerification:
    def test_validation_record_moved_to_train_rejected(self) -> None:
        """A record assigned to validation by the manifest cannot be moved to train."""
        # Find a validation record
        val_entry = next(e for e in _RESULT.partitions if e.partition == "validation")
        val_record = val_entry.records[0]
        val_group = val_record.group_id
        # Verify manifest assigns it to validation
        manifest_assign = next(
            a for a in _RESULT.split_manifest.assignments if a.group_id == val_group
        )
        assert manifest_assign.partition == "validation"

        # Move it to train
        broken = _move_record_between_partitions(_RESULT, "validation", "train")
        # The total retained record count stays the same, but partition counts change
        # The key is that the manifest assignment is violated
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_train_record_moved_to_validation_rejected(self) -> None:
        """A record assigned to training by the manifest cannot
        be moved to validation.
        """
        train_entry = next(e for e in _RESULT.partitions if e.partition == "train")
        train_record = train_entry.records[0]
        train_group = train_record.group_id
        manifest_assign = next(
            a for a in _RESULT.split_manifest.assignments if a.group_id == train_group
        )
        assert manifest_assign.partition == "train"

        broken = _move_record_between_partitions(_RESULT, "train", "validation")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_tampering_rejected_even_when_total_retained_unchanged(self) -> None:
        """Partition membership tampering rejected even when total
        retained records unchanged.
        """
        # The total retained record count stays the same, but partition
        # assignment is violated
        broken = _move_record_between_partitions(_RESULT, "validation", "train")
        # Verify total retained records unchanged
        all_records = sum(
            len(partition_records(broken, p)) for p in ("train", "validation", "test")
        )
        orig_all = sum(
            len(partition_records(_RESULT, p)) for p in ("train", "validation", "test")
        )
        assert all_records == orig_all

        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_test_partition_membership_also_checked(self) -> None:
        """The test partition is checked against manifest
        assignment during preflight.
        """
        test_entry = next(e for e in _RESULT.partitions if e.partition == "test")
        test_record = test_entry.records[0]
        test_group = test_record.group_id
        manifest_assign = next(
            a for a in _RESULT.split_manifest.assignments if a.group_id == test_group
        )
        assert manifest_assign.partition == "test"

        # Move test record to train
        broken = _move_record_between_partitions(_RESULT, "test", "train")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

        # Move test record to validation
        broken2 = _move_record_between_partitions(_RESULT, "test", "validation")
        with pytest.raises(NativeTrainingError) as exc:
            _run(_fresh_model(), result=broken2)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"

    def test_legitimate_data_still_trains(self) -> None:
        """Untampered synthetic data still trains successfully."""
        report = _run(_fresh_model())
        assert report.run_completed is True
        assert report.epochs_completed > 0

    def test_membership_violation_fails_before_optimizer(self, monkeypatch) -> None:
        """Membership violation fails before optimizer creation
        and leaves params unchanged.
        """
        real_cls = training_loop_module._OPTIMIZER_CLS
        built: list[int] = []

        class SpyOptimizer(real_cls):  # type: ignore[valid-type,misc]
            def __init__(self, *args, **kwargs):
                built.append(1)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(training_loop_module, "_OPTIMIZER_CLS", SpyOptimizer)
        model = _fresh_model()
        before = _snapshot(model)
        broken = _move_record_between_partitions(_RESULT, "validation", "train")
        with pytest.raises(NativeTrainingError) as exc:
            _run(model, result=broken)
        assert exc.value.code == "SPLIT_INTEGRITY_FAILURE"
        assert built == [], "optimizer was constructed before membership check"
        _assert_equal_snapshots(before, _snapshot(model))

"""Task 210 deterministic training tests; all fixtures are synthetic."""

from __future__ import annotations

import pytest

from rop.dataset_preparation import (
    PreparedSplits,
    build_manifest,
    content_fingerprint,
)
from rop.native_model import NativeModel
from rop.native_training import NativeTrainingConfig, NativeTrainingError, NativeTrainingExample, train_native_model
from rop.schemas.dataset_manifest import AuthorizationStatus, DatasetSourceDescriptor, PermittedPurpose, RawDatasetRecord
from rop.schemas.native_model import NativeModelConfig
from rop.tokenization import TokenizerConfig, build_vocabulary

LABEL_SPACE = ("ANION_GAP_HIGH", "POTASSIUM_HIGH")


def _splits_and_manifest():
    records = tuple(
        RawDatasetRecord(
            record_id=f"r{index}",
            group_key=f"g{index}",
            content_fingerprint=content_fingerprint(f"synthetic record {index}"),
            labels=("ANION_GAP_HIGH",),
            privacy_safe=True,
        )
        for index in range(12)
    )
    splits = PreparedSplits(train=records[:6], validation=records[6:9], test=records[9:])
    source = DatasetSourceDescriptor(
        source_id="synthetic-source",
        authorization=AuthorizationStatus.AUTHORIZED,
        permitted_purposes=tuple(sorted((PermittedPurpose.TRAINING, PermittedPurpose.EVALUATION), key=lambda item: item.value)),
        provenance_reference="synthetic-fixture",
        is_synthetic=True,
    )
    manifest = build_manifest(
        dataset_id="synthetic-dataset",
        schema_version="1",
        label_space_version="1",
        source=source,
        splits=splits,
        label_space=LABEL_SPACE,
        authorization_evidence_reference="synthetic-approval",
    )
    texts = {record.record_id: f"synthetic token {index}" for index, record in enumerate(splits.train)}
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=TokenizerConfig(max_token_length=32, max_sequence_length=16, max_vocab_size=64, min_frequency=1),
        training_texts=texts,
    )
    model_config = NativeModelConfig(
        vocab_size=len(vocabulary.tokens),
        embedding_dim=4,
        num_labels=2,
        max_sequence_length=16,
        initialization_seed=42,
        model_version="training-test-1",
    )
    examples = tuple(
        NativeTrainingExample(record_id=record.record_id, token_ids=(2, 3), label_ids=(0,))
        for record in splits.train
    )
    training_config = NativeTrainingConfig(epochs=3, learning_rate=0.05, max_examples=100, gradient_clip=1.0)
    return splits, manifest, vocabulary, model_config, examples, training_config


def test_training_is_reproducible_for_identical_inputs():
    splits, manifest, vocabulary, model_config, examples, training_config = _splits_and_manifest()
    initial = NativeModel.reproducible(model_config)
    first = train_native_model(
        model_config=model_config,
        training_config=training_config,
        initial_parameters=initial,
        examples=examples,
        splits=splits,
        manifest=manifest,
        vocabulary=vocabulary,
    )
    second = train_native_model(
        model_config=model_config,
        training_config=training_config,
        initial_parameters=initial,
        examples=examples,
        splits=splits,
        manifest=manifest,
        vocabulary=vocabulary,
    )
    assert first.parameters == second.parameters
    assert first.report == second.report


def test_training_records_only_safe_reproducibility_metadata():
    splits, manifest, vocabulary, model_config, examples, training_config = _splits_and_manifest()
    result = train_native_model(
        model_config=model_config,
        training_config=training_config,
        initial_parameters=NativeModel.reproducible(model_config),
        examples=examples,
        splits=splits,
        manifest=manifest,
        vocabulary=vocabulary,
    )
    assert result.report.example_count == len(splits.train)
    assert result.report.dataset_fingerprint == vocabulary.training_fingerprint
    assert result.report.parameters_hash
    assert "synthetic token" not in result.report.model_dump_json()


def test_training_rejects_unauthorized_dataset():
    splits, manifest, vocabulary, model_config, examples, training_config = _splits_and_manifest()
    blocked = manifest.model_copy(update={"training_blocked_reason": "approval missing"})
    with pytest.raises(NativeTrainingError) as caught:
        train_native_model(
            model_config=model_config,
            training_config=training_config,
            initial_parameters=NativeModel.reproducible(model_config),
            examples=examples,
            splits=splits,
            manifest=blocked,
            vocabulary=vocabulary,
        )
    assert caught.value.code == "TRAINING_NOT_AUTHORIZED"


def test_training_rejects_examples_outside_train_split():
    splits, manifest, vocabulary, model_config, examples, training_config = _splits_and_manifest()
    altered = examples[:-1] + (examples[0],)
    with pytest.raises(NativeTrainingError) as caught:
        train_native_model(
            model_config=model_config,
            training_config=training_config,
            initial_parameters=NativeModel.reproducible(model_config),
            examples=altered,
            splits=splits,
            manifest=manifest,
            vocabulary=vocabulary,
        )
    assert caught.value.code == "TRAINING_SPLIT_MISMATCH"


def test_training_rejects_out_of_range_label_ids():
    splits, manifest, vocabulary, model_config, examples, training_config = _splits_and_manifest()
    invalid = examples[:-1] + (
        NativeTrainingExample(record_id=examples[-1].record_id, token_ids=(2,), label_ids=(9,)),
    )
    with pytest.raises(NativeTrainingError) as caught:
        train_native_model(
            model_config=model_config,
            training_config=training_config,
            initial_parameters=NativeModel.reproducible(model_config),
            examples=invalid,
            splits=splits,
            manifest=manifest,
            vocabulary=vocabulary,
        )
    assert caught.value.code == "LABEL_ID_OUT_OF_RANGE"

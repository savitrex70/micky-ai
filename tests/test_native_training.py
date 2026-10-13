"""Task 210 deterministic training tests; all fixtures are synthetic."""

from __future__ import annotations

import dataclasses
import math

import pytest
from pydantic import ValidationError

from rop.dataset_preparation import (
    PreparedSplits,
    build_manifest,
    content_fingerprint,
)
from rop.native_model import NativeModel, NativeModelParameters
from rop.native_training import (
    LABEL_SPACE_HASH_DOMAIN,
    NATIVE_TRAINING_REPORT_CONTRACT_VERSION,
    NativeTrainingConfig,
    NativeTrainingError,
    NativeTrainingExample,
    NativeTrainingReport,
    canonical_label_mapping,
    label_space_hash,
    train_native_model,
)
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetSourceDescriptor,
    PermittedPurpose,
    RawDatasetRecord,
)
from rop.schemas.native_model import NativeModelConfig
from rop.tokenization import TokenizerConfig, build_vocabulary, encode_text

LABEL_SPACE = ("ANION_GAP_HIGH", "POTASSIUM_HIGH")
MAPPING = canonical_label_mapping(LABEL_SPACE)


def _labels(index: int) -> tuple[str, ...]:
    return ("ANION_GAP_HIGH",) if index % 2 == 0 else LABEL_SPACE


def _fixture(train_count: int = 6):
    texts_all = {f"r{i}": f"synthetic token {i}" for i in range(12)}
    records = tuple(
        RawDatasetRecord(
            record_id=f"r{index}",
            group_key=f"g{index}",
            content_fingerprint=content_fingerprint(texts_all[f"r{index}"]),
            labels=_labels(index),
            privacy_safe=True,
        )
        for index in range(12)
    )
    splits = PreparedSplits(
        train=records[:train_count],
        validation=records[6:9],
        test=records[9:],
    )
    source = DatasetSourceDescriptor(
        source_id="synthetic-source",
        authorization=AuthorizationStatus.AUTHORIZED,
        permitted_purposes=tuple(
            sorted(
                (PermittedPurpose.TRAINING, PermittedPurpose.EVALUATION),
                key=lambda item: item.value,
            )
        ),
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
    texts = {record.record_id: texts_all[record.record_id] for record in splits.train}
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=TokenizerConfig(
            max_token_length=32,
            max_sequence_length=16,
            max_vocab_size=64,
            min_frequency=1,
        ),
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
        NativeTrainingExample(
            record_id=record.record_id,
            token_ids=encode_text(texts[record.record_id], vocabulary),
            label_ids=tuple(sorted(MAPPING[label] for label in record.labels)),
        )
        for record in splits.train
    )
    training_config = NativeTrainingConfig(
        epochs=3, learning_rate=0.05, max_examples=100, gradient_clip=1.0
    )
    return splits, manifest, vocabulary, model_config, examples, training_config, texts


def _train(fixture=None, **overrides):
    splits, manifest, vocabulary, model_config, examples, training_config, texts = (
        fixture or _fixture()
    )
    arguments = {
        "model_config": model_config,
        "training_config": training_config,
        "initial_parameters": NativeModel.reproducible(model_config),
        "examples": examples,
        "splits": splits,
        "manifest": manifest,
        "vocabulary": vocabulary,
        "label_space": LABEL_SPACE,
        "training_texts": texts,
    }
    arguments.update(overrides)
    return train_native_model(**arguments)


def _code(**overrides) -> str:
    with pytest.raises(NativeTrainingError) as caught:
        _train(**overrides)
    return caught.value.code


# --- existing behavior (adapted to the strict boundary) ------------------------


def test_training_is_reproducible_for_identical_inputs():
    first = _train()
    second = _train()
    assert first.parameters == second.parameters
    assert first.report == second.report


def test_training_records_only_safe_reproducibility_metadata():
    fixture = _fixture()
    result = _train(fixture)
    assert result.report.example_count == len(fixture[0].train)
    assert result.report.dataset_fingerprint == fixture[2].training_fingerprint
    assert result.report.parameters_hash
    assert "synthetic token" not in result.report.model_dump_json()


def test_training_rejects_unauthorized_dataset():
    fixture = _fixture()
    blocked = fixture[1].model_copy(
        update={"training_blocked_reason": "approval missing"}
    )
    assert _code(fixture=fixture, manifest=blocked) == "TRAINING_NOT_AUTHORIZED"


def test_training_rejects_examples_outside_train_split():
    fixture = _fixture()
    examples = fixture[4]
    altered = examples[:-1] + (examples[0],)
    assert _code(fixture=fixture, examples=altered) == "TRAINING_SPLIT_MISMATCH"


def test_training_rejects_out_of_range_label_ids():
    fixture = _fixture()
    examples = fixture[4]
    invalid = examples[:-1] + (
        NativeTrainingExample(
            record_id=examples[-1].record_id,
            token_ids=examples[-1].token_ids,
            label_ids=(9,),
        ),
    )
    assert _code(fixture=fixture, examples=invalid) == "LABEL_ID_OUT_OF_RANGE"


# --- initialization binding ----------------------------------------------------


def test_initialization_from_a_different_seed_is_rejected():
    fixture = _fixture()
    other = fixture[3].model_copy(update={"initialization_seed": 43})
    assert (
        _code(fixture=fixture, initial_parameters=NativeModel.reproducible(other))
        == "INITIALIZATION_MISMATCH"
    )


def test_externally_substituted_parameters_are_rejected():
    fixture = _fixture()
    initial = NativeModel.reproducible(fixture[3])
    tweaked = dataclasses.replace(
        initial, head_bias=tuple(value + 1e-9 for value in initial.head_bias)
    )
    assert (
        _code(fixture=fixture, initial_parameters=tweaked) == "INITIALIZATION_MISMATCH"
    )


def test_already_trained_parameters_are_not_a_fresh_initialization():
    fixture = _fixture()
    trained = _train(fixture).parameters
    assert (
        _code(fixture=fixture, initial_parameters=trained) == "INITIALIZATION_MISMATCH"
    )


@pytest.mark.parametrize("field", ["embedding", "head_weight"])
def test_malformed_parameter_row_widths_are_rejected(field: str) -> None:
    fixture = _fixture()
    initial = NativeModel.reproducible(fixture[3])
    rows = list(getattr(initial, field))
    rows[-1] = rows[-1][:-1]  # one dimension short in the last row only
    broken = dataclasses.replace(initial, **{field: tuple(rows)})
    assert (
        _code(fixture=fixture, initial_parameters=broken) == "PARAMETER_SHAPE_MISMATCH"
    )


def test_wrong_parameter_counts_are_rejected():
    fixture = _fixture()
    initial = NativeModel.reproducible(fixture[3])
    short_embedding = dataclasses.replace(initial, embedding=initial.embedding[:-1])
    short_bias = dataclasses.replace(initial, head_bias=initial.head_bias[:-1])
    short_head = dataclasses.replace(initial, head_weight=initial.head_weight[:-1])
    for broken in (short_embedding, short_bias, short_head):
        assert (
            _code(fixture=fixture, initial_parameters=broken)
            == "PARAMETER_SHAPE_MISMATCH"
        )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_initial_parameters_are_rejected(bad: float) -> None:
    fixture = _fixture()
    initial = NativeModel.reproducible(fixture[3])
    row = (bad,) + initial.embedding[0][1:]
    broken = dataclasses.replace(initial, embedding=(row,) + initial.embedding[1:])
    assert (
        _code(fixture=fixture, initial_parameters=broken)
        == "NON_FINITE_INITIAL_PARAMETER"
    )
    bias = dataclasses.replace(initial, head_bias=(bad,) + initial.head_bias[1:])
    assert (
        _code(fixture=fixture, initial_parameters=bias)
        == "NON_FINITE_INITIAL_PARAMETER"
    )


# --- label binding -------------------------------------------------------------


def test_canonical_label_mapping_is_stable_and_sorted():
    assert canonical_label_mapping(LABEL_SPACE) == {
        "ANION_GAP_HIGH": 0,
        "POTASSIUM_HIGH": 1,
    }
    assert canonical_label_mapping(LABEL_SPACE) == canonical_label_mapping(LABEL_SPACE)


@pytest.mark.parametrize(
    "bad",
    [
        ("POTASSIUM_HIGH", "ANION_GAP_HIGH"),  # not canonical order
        ("ANION_GAP_HIGH", "ANION_GAP_HIGH"),  # duplicate
        ("ANION_GAP_HIGH",),  # too small
        ("ANION_GAP_HIGH", " "),  # blank
        ["ANION_GAP_HIGH", "POTASSIUM_HIGH"],  # not a tuple
    ],
)
def test_invalid_label_spaces_are_rejected(bad) -> None:
    with pytest.raises(NativeTrainingError) as caught:
        canonical_label_mapping(bad)
    assert caught.value.code == "LABEL_SPACE_INVALID"
    assert _code(label_space=bad) == "LABEL_SPACE_INVALID"


def test_label_space_size_must_match_the_model_head():
    assert (
        _code(label_space=("A_LABEL", "B_LABEL", "C_LABEL")) == "LABEL_SPACE_MISMATCH"
    )


def test_record_labels_outside_the_label_space_are_rejected():
    assert (
        _code(label_space=("ANION_GAP_HIGH", "ZZZ_OTHER")) == "LABEL_NOT_IN_LABEL_SPACE"
    )


def _replace_example(examples, index: int, **patch):
    changed = examples[index].model_copy(update=patch)
    return examples[:index] + (changed,) + examples[index + 1 :]


def test_label_ids_that_do_not_match_the_record_are_rejected():
    fixture = _fixture()
    examples = fixture[4]
    # r0 is declared ANION_GAP_HIGH only; claim POTASSIUM_HIGH instead.
    assert (
        _code(fixture=fixture, examples=_replace_example(examples, 0, label_ids=(1,)))
        == "LABEL_MAPPING_MISMATCH"
    )


def test_missing_and_extra_label_ids_are_rejected():
    fixture = _fixture()
    examples = fixture[4]
    # r1 is declared with both labels: dropping one is a missing label,
    # adding one to r0 is an extra label.
    assert (
        _code(fixture=fixture, examples=_replace_example(examples, 1, label_ids=(0,)))
        == "LABEL_MAPPING_MISMATCH"
    )
    assert (
        _code(fixture=fixture, examples=_replace_example(examples, 0, label_ids=(0, 1)))
        == "LABEL_MAPPING_MISMATCH"
    )


def test_duplicate_label_ids_are_rejected():
    fixture = _fixture()
    examples = fixture[4]
    assert (
        _code(
            fixture=fixture, examples=_replace_example(examples, 1, label_ids=(0, 1, 1))
        )
        == "LABEL_MAPPING_MISMATCH"
    )


# --- text and token binding ----------------------------------------------------


def test_altered_token_ids_are_rejected():
    fixture = _fixture()
    examples = fixture[4]
    other = examples[0].token_ids[:-1] + ((examples[0].token_ids[-1] % 5) + 2,)
    if other == examples[0].token_ids:
        other = other[:-1] + (other[-1] + 1,)
    altered = _replace_example(examples, 0, token_ids=other)
    assert _code(fixture=fixture, examples=altered) == "TOKEN_BINDING_MISMATCH"


def test_truncated_or_extended_token_ids_are_rejected():
    fixture = _fixture()
    examples = fixture[4]
    for token_ids in (examples[0].token_ids[:-1], examples[0].token_ids + (1,)):
        altered = _replace_example(examples, 0, token_ids=token_ids)
        assert _code(fixture=fixture, examples=altered) == "TOKEN_BINDING_MISMATCH"


def test_out_of_vocabulary_token_ids_are_rejected():
    fixture = _fixture()
    examples = fixture[4]
    altered = _replace_example(examples, 0, token_ids=(10_000,))
    assert _code(fixture=fixture, examples=altered) == "TOKEN_ID_OUT_OF_RANGE"


def test_modified_training_text_is_rejected_without_leaking_it():
    fixture = _fixture()
    texts = dict(fixture[6])
    texts["r0"] = "completely different confidential text"
    with pytest.raises(NativeTrainingError) as caught:
        _train(fixture, training_texts=texts)
    assert caught.value.code == "TEXT_FINGERPRINT_MISMATCH"
    assert "confidential" not in str(caught.value)


def test_canonically_equivalent_text_with_matching_fingerprint_is_accepted():
    fixture = _fixture()
    texts = dict(fixture[6])
    texts["r0"] = "  SYNTHETIC   Token 0 "
    assert _train(fixture, training_texts=texts).report.example_count == 6


def test_training_texts_must_cover_exactly_the_train_split():
    fixture = _fixture()
    missing = {key: value for key, value in fixture[6].items() if key != "r0"}
    assert _code(fixture=fixture, training_texts=missing) == "TRAINING_TEXT_MISMATCH"
    extra = {**fixture[6], "r9": "validation text"}
    assert _code(fixture=fixture, training_texts=extra) == "TRAINING_TEXT_MISMATCH"


def test_detached_vocabulary_or_manifest_is_rejected():
    fixture = _fixture()
    other_vocabulary = _fixture(train_count=5)[2]
    assert (
        _code(fixture=fixture, vocabulary=other_vocabulary)
        == "TRAINING_FINGERPRINT_MISMATCH"
    )


# --- gradient and loss behavior ------------------------------------------------


def _summed_bce(
    parameters: NativeModelParameters, token_ids, label_ids, labels
) -> float:
    model = NativeModel(NativeModelConfig(**_dump(labels)))
    model.parameters = parameters
    probabilities = model.predict(tuple(token_ids))
    total = 0.0
    for label, probability in enumerate(probabilities):
        target = 1.0 if label in label_ids else 0.0
        total -= target * math.log(probability) + (1 - target) * math.log(
            1 - probability
        )
    return total


def _dump(model_config: NativeModelConfig) -> dict:
    return model_config.model_dump()


def test_single_step_update_matches_the_numerical_gradient_with_repeated_tokens():
    # One train record whose tokens repeat: "synthetic synthetic token".
    fixture = _fixture(train_count=1)
    splits, manifest, vocabulary, model_config, _examples, _config, _texts = fixture
    text = "synthetic synthetic token"
    # Rebind the single record to repeated-token text through a fresh fixture.
    record = splits.train[0]
    record = record.model_copy(
        update={"content_fingerprint": content_fingerprint(text)}
    )
    splits = PreparedSplits(
        train=(record,), validation=splits.validation, test=splits.test
    )
    source = manifest.source
    manifest = build_manifest(
        dataset_id="synthetic-dataset",
        schema_version="1",
        label_space_version="1",
        source=source,
        splits=splits,
        label_space=LABEL_SPACE,
        authorization_evidence_reference="synthetic-approval",
    )
    texts = {record.record_id: text}
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=TokenizerConfig(
            max_token_length=32,
            max_sequence_length=16,
            max_vocab_size=64,
            min_frequency=1,
        ),
        training_texts=texts,
    )
    model_config = model_config.model_copy(
        update={"vocab_size": len(vocabulary.tokens)}
    )
    token_ids = encode_text(text, vocabulary)
    assert len(token_ids) == 3 and len(set(token_ids)) == 2
    label_ids = tuple(sorted(MAPPING[label] for label in record.labels))
    example = NativeTrainingExample(
        record_id=record.record_id, token_ids=token_ids, label_ids=label_ids
    )
    rate = 1e-3
    config = NativeTrainingConfig(
        epochs=1, learning_rate=rate, max_examples=10, gradient_clip=100.0
    )
    initial = NativeModel.reproducible(model_config)
    result = train_native_model(
        model_config=model_config,
        training_config=config,
        initial_parameters=initial,
        examples=(example,),
        splits=splits,
        manifest=manifest,
        vocabulary=vocabulary,
        label_space=LABEL_SPACE,
        training_texts=texts,
    )

    def loss_at(parameters: NativeModelParameters) -> float:
        return _summed_bce(parameters, token_ids, set(label_ids), model_config)

    eps = 1e-6

    def numeric(field: str, row: int, column: int | None) -> float:
        def bumped(delta: float) -> NativeModelParameters:
            value = [
                list(item) if isinstance(item, tuple) else item
                for item in getattr(initial, field)
            ]
            if column is None:
                value[row] += delta
            else:
                value[row][column] += delta
            frozen = tuple(tuple(i) if isinstance(i, list) else i for i in value)
            return dataclasses.replace(initial, **{field: frozen})

        return (loss_at(bumped(eps)) - loss_at(bumped(-eps))) / (2 * eps)

    for field, row, column in (
        ("embedding", token_ids[0], 0),  # repeated token (twice in the sequence)
        ("embedding", token_ids[2], 1),  # single-occurrence token
        ("head_weight", 0, 2),
        ("head_bias", 1, None),
    ):
        before = getattr(initial, field)
        after = getattr(result.parameters, field)
        if column is None:
            actual = (before[row] - after[row]) / rate
        else:
            actual = (before[row][column] - after[row][column]) / rate
        assert actual == pytest.approx(numeric(field, row, column), rel=1e-4, abs=1e-7)


def test_training_reduces_loss_and_is_not_justified_by_determinism_alone():
    fixture = _fixture()
    config = fixture[5].model_copy(update={"epochs": 40, "learning_rate": 0.5})
    result = _train(fixture, training_config=config)
    assert (
        result.report.final_binary_cross_entropy
        < result.report.initial_binary_cross_entropy
    )
    assert result.parameters != NativeModel.reproducible(fixture[3])


def test_gradient_clipping_bounds_each_parameter_step():
    fixture = _fixture()
    clip = 1e-4
    rate = 0.5
    config = fixture[5].model_copy(
        update={"epochs": 1, "learning_rate": rate, "gradient_clip": clip}
    )
    initial = NativeModel.reproducible(fixture[3])
    result = _train(fixture, training_config=config)
    # Per example each parameter moves at most rate*clip; 6 examples, 1 epoch.
    bound = rate * clip * len(fixture[4]) + 1e-12
    for before_row, after_row in zip(
        initial.head_weight, result.parameters.head_weight, strict=True
    ):
        assert all(
            abs(a - b) <= bound for a, b in zip(before_row, after_row, strict=True)
        )
    assert all(
        abs(a - b) <= bound
        for a, b in zip(initial.head_bias, result.parameters.head_bias, strict=True)
    )


# --- Task 210 correction: label-space identity ----------------------------------


def test_label_space_hash_is_deterministic_and_domain_separated() -> None:
    import hashlib

    first = label_space_hash(LABEL_SPACE)
    assert first == label_space_hash(tuple(LABEL_SPACE))
    assert len(first) == 64 and first == first.lower()
    # Domain separation: not the bare SHA-256 of the joined labels.
    assert first != hashlib.sha256("|".join(LABEL_SPACE).encode()).hexdigest()
    assert LABEL_SPACE_HASH_DOMAIN == "rop.native.label-space.v1"


def test_same_size_label_sets_have_different_label_space_hashes() -> None:
    reference = label_space_hash(("ANION_GAP_HIGH", "POTASSIUM_HIGH"))
    assert label_space_hash(("ANION_GAP_HIGH", "SODIUM_LOW")) != reference
    assert label_space_hash(("A_LABEL", "B_LABEL")) != reference
    assert label_space_hash(("ANION_GAP_HIGH", "POTASSIUM_LOW")) != reference


def test_label_space_hash_encoding_is_unambiguous() -> None:
    # Length prefixes keep ("AB", "C") distinct from ("A", "BC").
    assert label_space_hash(("AB", "C")) != label_space_hash(("A", "BC"))
    assert label_space_hash(("A", "B")) != label_space_hash(("A", "B", "C"))


@pytest.mark.parametrize(
    "bad",
    [
        ("POTASSIUM_HIGH", "ANION_GAP_HIGH"),
        ("ANION_GAP_HIGH", "ANION_GAP_HIGH"),
        ("ANION_GAP_HIGH",),
        ("ANION_GAP_HIGH", " "),
    ],
)
def test_label_space_hash_refuses_a_non_canonical_space(bad) -> None:
    with pytest.raises(NativeTrainingError) as caught:
        label_space_hash(bad)
    assert caught.value.code == "LABEL_SPACE_INVALID"


def test_training_report_records_the_exact_label_mapping_identity() -> None:
    report = _train().report
    assert report.contract_version == NATIVE_TRAINING_REPORT_CONTRACT_VERSION == "2"
    assert report.label_space_scheme_version == "native-label-space-v1"
    # label_map[i] is the label of head index i: it is the exact mapping used.
    assert report.label_map == tuple(MAPPING)
    assert all(MAPPING[label] == index for index, label in enumerate(report.label_map))
    assert report.label_space_hash == label_space_hash(LABEL_SPACE)
    assert report.label_space_hash == label_space_hash(report.label_map)


def test_report_hash_is_computed_by_training_not_supplied() -> None:
    # Training has no parameter through which a hash could be supplied.
    import inspect

    assert "label_space_hash" not in inspect.signature(train_native_model).parameters


def test_report_rejects_a_forged_or_mismatched_label_space_hash() -> None:
    report = _train().report
    payload = report.model_dump(mode="json")
    other = label_space_hash(("ANION_GAP_HIGH", "SODIUM_LOW"))
    with pytest.raises(ValidationError, match="label_space_hash"):
        NativeTrainingReport.model_validate({**payload, "label_space_hash": other})
    # A relabelled map with the original hash is rejected as well.
    with pytest.raises(ValidationError, match="label_space_hash"):
        NativeTrainingReport.model_validate(
            {**payload, "label_map": ["ANION_GAP_HIGH", "SODIUM_LOW"]}
        )
    assert NativeTrainingReport.model_validate(payload) == report


@pytest.mark.parametrize(
    "bad_map",
    [
        ["POTASSIUM_HIGH", "ANION_GAP_HIGH"],
        ["ANION_GAP_HIGH", "ANION_GAP_HIGH"],
        ["ANION_GAP_HIGH", " "],
    ],
)
def test_report_rejects_a_non_canonical_label_map(bad_map) -> None:
    payload = _train().report.model_dump(mode="json")
    with pytest.raises(ValidationError, match="label_map"):
        NativeTrainingReport.model_validate({**payload, "label_map": bad_map})


def test_report_requires_the_label_space_fields_and_new_contract_version() -> None:
    payload = _train().report.model_dump(mode="json")
    for key in ("label_space_hash", "label_map"):
        without = {k: v for k, v in payload.items() if k != key}
        with pytest.raises(ValidationError):
            NativeTrainingReport.model_validate(without)
    with pytest.raises(ValidationError):
        NativeTrainingReport.model_validate({**payload, "contract_version": "1"})


def test_report_contains_no_raw_training_text() -> None:
    dumped = str(_train().report.model_dump(mode="json"))
    assert "synthetic token" not in dumped


def test_training_refuses_a_manifest_declaring_another_fingerprint_scheme() -> None:
    splits, manifest, *_ = _fixture()
    stale = manifest.model_copy(
        update={"fingerprint_scheme_version": "records-fingerprint-v1"}
    )
    assert _code(manifest=stale) == "TRAINING_FINGERPRINT_MISMATCH"

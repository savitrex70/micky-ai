"""Task 208 project-controlled tokenizer tests; no pretrained assets or network."""

from __future__ import annotations

from pathlib import Path

import pytest

from rop.dataset_preparation import (
    PreparedSplits,
    assign_group_safe_splits,
    build_manifest,
    content_fingerprint,
)
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetSourceDescriptor,
    PermittedPurpose,
    RawDatasetRecord,
)
from rop.tokenization import (
    RESERVED_PAD,
    RESERVED_TOKENS,
    RESERVED_UNK,
    RESERVED_UNK_ID,
    TokenizerConfig,
    TokenizerError,
    TokenizerErrorCode,
    Vocabulary,
    build_vocabulary,
    encode_text,
    load_vocabulary,
    parse_vocabulary,
    save_vocabulary,
    serialize_vocabulary,
    tokenize_text,
)

LABEL_SPACE = ("ANION_GAP_HIGH", "POTASSIUM_HIGH")
AUTH_REF = "auth:approval-2026-0001"


def _config(**patch: object) -> TokenizerConfig:
    value = {
        "max_token_length": 32,
        "max_sequence_length": 64,
        "max_vocab_size": 128,
        "min_frequency": 1,
    }
    value.update(patch)
    return TokenizerConfig.model_validate(value)


def _source(**patch: object) -> DatasetSourceDescriptor:
    value = {
        "source_id": "source-lab-1",
        "authorization": AuthorizationStatus.AUTHORIZED,
        "permitted_purposes": [
            PermittedPurpose.EVALUATION,
            PermittedPurpose.TRAINING,
            PermittedPurpose.VALIDATION,
        ],
        "provenance_reference": "doc:dataset-provenance-1",
        "is_synthetic": False,
    }
    value.update(patch)
    return DatasetSourceDescriptor.model_validate(value)


def _record(record_id: str, group_key: str, content: str) -> RawDatasetRecord:
    return RawDatasetRecord.model_validate(
        {
            "record_id": record_id,
            "group_key": group_key,
            "content_fingerprint": content_fingerprint(content),
            "labels": ["ANION_GAP_HIGH"],
            "privacy_safe": True,
        }
    )


def _default_content(record_id: str) -> str:
    return f"anion gap high potassium {record_id} case"


def _splits(overrides: dict[str, str] | None = None) -> PreparedSplits:
    """Splits whose record fingerprints match the text later supplied.

    Group assignment depends only on the group key, so the train ids are
    identical with or without content overrides.
    """
    overrides = overrides or {}
    records = []
    for group in range(4):
        for index in range(3):
            record_id = f"r-{group}-{index}"
            records.append(
                _record(
                    record_id,
                    f"group-{group}",
                    overrides.get(record_id, _default_content(record_id)),
                )
            )
    return assign_group_safe_splits(
        tuple(records), train_ratio=0.5, validation_ratio=0.25
    )


def _manifest(splits: PreparedSplits, **source_patch: object):
    return build_manifest(
        dataset_id="dataset-1",
        schema_version="schema-1",
        label_space_version="labels-1",
        source=_source(**source_patch),
        splits=splits,
        label_space=LABEL_SPACE,
        authorization_evidence_reference=AUTH_REF,
    )


def _training_texts(
    splits: PreparedSplits, overrides: dict[str, str] | None = None
) -> dict[str, str]:
    # Synthetic demonstration text keyed by training record identifiers; it is
    # exactly the content each record's fingerprint was computed from.
    overrides = overrides or {}
    return {
        record.record_id: overrides.get(
            record.record_id, _default_content(record.record_id)
        )
        for record in sorted(splits.train, key=lambda r: r.record_id)
    }


# --- tokenizer basics --------------------------------------------------------


def test_tokenize_text_is_deterministic_and_casefolded() -> None:
    config = _config()
    assert tokenize_text("Anion  Gap--HIGH", config) == (
        "anion",
        "gap",
        "high",
    )
    assert tokenize_text("ANION GAP", config) == tokenize_text("anion gap", config)


def test_tokenize_text_handles_unicode_and_malformed_input() -> None:
    config = _config()
    assert tokenize_text("café  NaCl", config) == ("café", "nacl")
    assert tokenize_text("", config) == ()
    assert tokenize_text("   \n\t ", config) == ()
    assert tokenize_text("!!! ??? ...", config) == ()
    with pytest.raises(TokenizerError):
        tokenize_text(b"bytes", config)  # type: ignore[arg-type]


def test_tokens_are_truncated_to_the_configured_length() -> None:
    config = _config(max_token_length=4)
    assert tokenize_text("abcdefghij", config) == ("abcd",)


# --- vocabulary fitting ------------------------------------------------------


def test_vocabulary_fit_is_deterministic_and_reserved_tokens_lead() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    first = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=_training_texts(splits),
    )
    second = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=dict(reversed(list(_training_texts(splits).items()))),
    )
    assert first == second
    assert first.tokens[:2] == RESERVED_TOKENS
    assert first.tokens[0] == RESERVED_PAD
    assert first.tokens[1] == RESERVED_UNK


def test_vocabulary_frequency_ordering_breaks_ties_lexicographically() -> None:
    train_ids = sorted(record.record_id for record in _splits().train)
    # Every token appears exactly twice except 'zeta' which appears once.
    texts = {
        train_ids[0]: "alpha beta zeta",
        train_ids[1]: "alpha beta",
    }
    for record_id in train_ids[2:]:
        texts[record_id] = ""
    splits = _splits(texts)
    manifest = _manifest(splits)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=texts,
    )
    assert vocabulary.tokens[2:] == ("alpha", "beta", "zeta")


def test_vocabulary_refuses_validation_or_test_records() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    leaked_id = next(record.record_id for record in splits.test)
    texts[leaked_id] = "leaked record text"
    with pytest.raises(TokenizerError) as caught:
        build_vocabulary(
            splits=splits,
            manifest=manifest,
            config=_config(),
            training_texts=texts,
        )
    assert caught.value.code is (
        TokenizerErrorCode.VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT
    )


def test_vocabulary_refuses_incomplete_training_coverage() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    texts.pop(next(iter(texts)))
    with pytest.raises(TokenizerError) as caught:
        build_vocabulary(
            splits=splits, manifest=manifest, config=_config(), training_texts=texts
        )
    assert caught.value.code is (
        TokenizerErrorCode.VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT
    )


def test_vocabulary_refuses_a_manifest_that_disagrees_with_the_split() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    other_splits = assign_group_safe_splits(
        tuple(_record(f"x-{i}", f"other-{i}", f"other content {i}") for i in range(6)),
        train_ratio=0.5,
        validation_ratio=0.25,
    )
    with pytest.raises(TokenizerError) as caught:
        build_vocabulary(
            splits=other_splits,
            manifest=manifest,
            config=_config(),
            training_texts={
                record.record_id: "other content" for record in other_splits.train
            },
        )
    assert caught.value.code is TokenizerErrorCode.MANIFEST_MISMATCH


def test_vocabulary_refuses_an_unauthorized_source() -> None:
    splits = _splits()
    # The manifest contract forces an unknown source to declare that
    # training is blocked; the tokenizer must still refuse to fit.
    manifest = build_manifest(
        dataset_id="dataset-1",
        schema_version="schema-1",
        label_space_version="labels-1",
        source=_source(authorization=AuthorizationStatus.UNKNOWN),
        splits=splits,
        label_space=LABEL_SPACE,
        authorization_evidence_reference=AUTH_REF,
        training_blocked_reason="Source authorization not yet approved.",
    )
    with pytest.raises(TokenizerError) as caught:
        build_vocabulary(
            splits=splits,
            manifest=manifest,
            config=_config(),
            training_texts=_training_texts(splits),
        )
    assert caught.value.code is TokenizerErrorCode.UNAUTHORIZED_SOURCE


def test_min_frequency_filters_rare_tokens() -> None:
    train_ids = sorted(record.record_id for record in _splits().train)
    texts = {
        train_ids[0]: "common common rare",
        train_ids[1]: "common",
    }
    for record_id in train_ids[2:]:
        texts[record_id] = ""
    splits = _splits(texts)
    manifest = _manifest(splits)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(min_frequency=2),
        training_texts=texts,
    )
    assert "common" in vocabulary.tokens
    assert "rare" not in vocabulary.tokens


# --- encoding -----------------------------------------------------------------


def test_encoding_maps_unknown_tokens_to_the_reserved_identifier() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=_training_texts(splits),
    )
    identifiers = encode_text("anion unseenword potassium", vocabulary)
    assert RESERVED_UNK_ID in identifiers
    assert identifiers[0] != RESERVED_UNK_ID
    assert encode_text("", vocabulary) == ()


def test_encoding_truncates_to_the_configured_sequence_length() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    config = _config(max_sequence_length=2)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=config,
        training_texts=_training_texts(splits),
    )
    identifiers = encode_text("one two three four", vocabulary)
    assert len(identifiers) == 2


# --- artifact round-trip and corruption ----------------------------------------


def test_vocabulary_round_trips_through_local_artifact_storage(tmp_path: Path) -> None:
    splits = _splits()
    manifest = _manifest(splits)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=_training_texts(splits),
    )
    path = save_vocabulary(vocabulary, tmp_path)
    assert path.parent == tmp_path
    loaded = load_vocabulary(path)
    assert loaded == vocabulary
    assert path.name == f"vocabulary-{vocabulary.vocabulary_hash[:16]}.json"


def test_corrupt_and_malformed_artifacts_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(TokenizerError) as caught:
        parse_vocabulary("{SENSITIVE_ARTIFACT_PAYLOAD not json")
    assert caught.value.code is TokenizerErrorCode.CORRUPT_VOCABULARY
    # `from None` suppresses the original exception at the rendering
    # boundary, so raw artifact text stays out of formatted tracebacks.
    import traceback

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    # The final rendered exception line never carries the payload text.
    final_line = rendered.strip().splitlines()[-1]
    assert "SENSITIVE_ARTIFACT_PAYLOAD" not in final_line

    with pytest.raises(TokenizerError) as caught:
        parse_vocabulary('{"contract_version": "1"}')
    assert caught.value.code is TokenizerErrorCode.CORRUPT_VOCABULARY
    assert caught.value.__suppress_context__ is True

    missing = tmp_path / "missing.json"
    with pytest.raises(TokenizerError) as caught:
        load_vocabulary(missing)
    assert caught.value.code is TokenizerErrorCode.CORRUPT_VOCABULARY


def test_tampered_vocabulary_hash_is_rejected() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=_training_texts(splits),
    )
    payload = vocabulary.model_dump(mode="json")
    # A token injected after the fact leaves the stored hash stale.
    payload["tokens"] = list(payload["tokens"]) + ["injected"]
    import json

    with pytest.raises(TokenizerError) as caught:
        parse_vocabulary(json.dumps(payload))
    assert caught.value.code is TokenizerErrorCode.CORRUPT_VOCABULARY


def test_reserved_tokens_never_appear_from_raw_text() -> None:
    # Token boundaries strip punctuation, so raw "<PAD>" text cannot
    # produce the reserved token itself.
    config = _config()
    assert "<pad>" not in tokenize_text("<PAD> literal", config)
    assert tokenize_text("<PAD> literal", config) == ("pad", "literal")


def test_serialization_is_stable_across_repeated_calls() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    vocabulary = build_vocabulary(
        splits=splits,
        manifest=manifest,
        config=_config(),
        training_texts=_training_texts(splits),
    )
    assert serialize_vocabulary(vocabulary) == serialize_vocabulary(vocabulary)
    assert Vocabulary.model_validate(vocabulary.model_dump(mode="json")) == vocabulary


# --- Task 208 correction: training text bound to the authorized record -------


def _fit(splits: PreparedSplits, manifest, texts: dict[str, str]) -> Vocabulary:
    return build_vocabulary(
        splits=splits, manifest=manifest, config=_config(), training_texts=texts
    )


def test_changed_text_with_the_correct_id_set_is_rejected_before_a_vocabulary() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    victim = sorted(texts)[0]
    texts[victim] = texts[victim] + " injected extra content"
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, manifest, texts)
    assert caught.value.code is TokenizerErrorCode.TEXT_FINGERPRINT_MISMATCH


def test_swapped_texts_between_training_records_are_rejected() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    first, second = sorted(texts)[:2]
    texts[first], texts[second] = texts[second], texts[first]
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, manifest, texts)
    assert caught.value.code is TokenizerErrorCode.TEXT_FINGERPRINT_MISMATCH


def test_mismatch_error_never_contains_raw_text_or_identifiers() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    victim = sorted(texts)[0]
    texts[victim] = "SECRET-RAW-PAYLOAD"
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, manifest, texts)
    message = str(caught.value)
    assert "SECRET-RAW-PAYLOAD" not in message
    assert victim not in message
    assert caught.value.__cause__ is None


def test_text_with_the_same_canonical_content_is_accepted_and_equivalent() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    baseline = _fit(splits, manifest, texts)
    variant = {
        record_id: "  " + text.upper().replace(" ", "   ") + "\n"
        for record_id, text in texts.items()
    }
    # Same Task 207 canonical normalization, hence the same fingerprint.
    assert content_fingerprint(variant[sorted(variant)[0]]) == content_fingerprint(
        texts[sorted(texts)[0]]
    )
    assert _fit(splits, manifest, variant) == baseline


def test_non_string_training_text_is_rejected_with_a_safe_error() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts: dict = _training_texts(splits)
    texts[sorted(texts)[0]] = b"bytes"
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, manifest, texts)
    assert caught.value.code is TokenizerErrorCode.INVALID_TEXT


def test_validation_or_test_ids_with_matching_text_are_still_rejected() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    for leaked in (splits.validation[0], splits.test[0]):
        with_leak = {**texts, leaked.record_id: _default_content(leaked.record_id)}
        with pytest.raises(TokenizerError) as caught:
            _fit(splits, manifest, with_leak)
        assert caught.value.code is (
            TokenizerErrorCode.VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT
        )


def test_omitting_a_training_record_is_rejected() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    del texts[sorted(texts)[0]]
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, manifest, texts)
    assert caught.value.code is (
        TokenizerErrorCode.VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT
    )


def test_detached_manifest_is_rejected_before_text_binding() -> None:
    splits = _splits()
    first_train_id = sorted(record.record_id for record in splits.train)[0]
    other = _splits({first_train_id: "entirely different content"})
    detached = _manifest(other)
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, detached, _training_texts(splits))
    assert caught.value.code is TokenizerErrorCode.MANIFEST_MISMATCH


def test_detached_split_with_consistent_texts_is_rejected() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    # Train records altered after the manifest was built (same IDs, new
    # content fingerprints), with texts matching the altered records.
    train_ids = sorted(record.record_id for record in splits.train)
    altered = _splits({train_ids[0]: "tampered training content"})
    with pytest.raises(TokenizerError) as caught:
        _fit(
            altered,
            manifest,
            _training_texts(altered, {train_ids[0]: "tampered training content"}),
        )
    assert caught.value.code is TokenizerErrorCode.MANIFEST_MISMATCH


def test_vocabulary_hash_binds_the_authorized_content_only() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    texts = _training_texts(splits)
    first = _fit(splits, manifest, texts)
    second = _fit(splits, manifest, dict(reversed(list(texts.items()))))
    assert first.vocabulary_hash == second.vocabulary_hash


def test_vocabulary_requires_the_declared_fingerprint_scheme() -> None:
    splits = _splits()
    manifest = _manifest(splits)
    assert manifest.fingerprint_scheme_version == "records-fingerprint-v2"
    # A manifest whose declared scheme differs (bypassing validation) is
    # refused before any fingerprint comparison.
    stale = manifest.model_copy(
        update={"fingerprint_scheme_version": "records-fingerprint-v1"}
    )
    with pytest.raises(TokenizerError) as caught:
        _fit(splits, stale, _training_texts(splits))
    assert caught.value.code is TokenizerErrorCode.MANIFEST_MISMATCH

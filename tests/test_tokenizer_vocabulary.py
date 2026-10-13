"""Task 208: tokenizer and vocabulary tests.

Synthetic fixtures only, via the Task 207 test-only preparation
path. No pretrained artifacts, model, training, network, or GPU.
"""

from __future__ import annotations

import pathlib

import pytest
from pydantic import ValidationError

from rop.dataset_preparation.pipeline import (
    compose_test_registry,
    partition_records,
    prepare_dataset,
)
from rop.schemas.dataset_manifest import SplitConfig
from rop.schemas.tokenizer import (
    PAD_ID,
    RESERVED_TOKENS,
    TOKENIZER_VERSION,
    UNK_ID,
    VOCABULARY_VERSION,
    TokenizerConfig,
    Vocabulary,
)
from rop.tokenizer.tokenizer import TokenizerError, tokenize_text
from rop.tokenizer.vocabulary import (
    VocabularyPolicy,
    build_vocabulary,
    encode_text,
    verify_vocabulary,
)

LABELS = ["refutes", "supports"]
CONFIG = TokenizerConfig(
    tokenizer_version="1.0",
    normalization="NFC",
    preserve_case=True,
    max_sequence_length=64,
)
GROUPS = [f"synthetic-group-00{i}" for i in range(1, 7)]
SPLIT = SplitConfig(seed=7, train_ratio=0.6, validation_ratio=0.2, test_ratio=0.2)
SPLIT_TRAIN_ONLY = SplitConfig(
    seed=7, train_ratio=1.0, validation_ratio=0.0, test_ratio=0.0
)

_AUTH = {
    "source_id": "synthetic-test-source-001",
    "authorization_version": "1.0",
    "origin_description": "synthetic test origin",
    "license_basis": "synthetic-test-only",
    "intended_purpose": "synthetic-pilot",
    "permitted_operations": ["training"],
    "status": "APPROVED",
    "approval_reference": "synthetic-test-approval-001",
}


def _registry():
    return compose_test_registry([dict(_AUTH)])


def _record(record_id, content, group):
    return {
        "record_id": record_id,
        "source_id": "synthetic-test-source-001",
        "group_id": group,
        "label": "supports",
        "content_text": content,
        "provenance_ref": "synthetic:doc-1",
    }


def _prepare(contents_by_group, split_config=None):
    records = [
        _record(f"synthetic-rec-{group[-3:]}", content, group)
        for group, content in contents_by_group.items()
    ]
    return prepare_dataset(
        records=records,
        authorizations=_registry(),
        dataset_id="synthetic-tokenizer-001",
        purpose="synthetic-pilot",
        operation="training",
        as_of="2026-06-01",
        allowed_labels=LABELS,
        grouping_unit="synthetic-source-document",
        split_config=split_config if split_config is not None else SPLIT_TRAIN_ONLY,
    )


def _standard_contents():
    return {
        group: f"synthetic tokenizer fixture {word}"
        for group, word in zip(
            GROUPS,
            ["one", "two", "three", "four", "five", "six"],
            strict=True,
        )
    }


def _partition_token_sets(result):
    from rop.tokenizer.tokenizer import tokenize_text as tokenize

    sets = {}
    for name in ("train", "validation", "test"):
        tokens: set[str] = set()
        for record in partition_records(result, name):
            tokens |= set(tokenize(record.content_text))
        sets[name] = tokens
    return sets


# --- token splitter ---


def test_exact_ascii_outputs() -> None:
    assert tokenize_text("Hello, world!") == ("Hello", ",", "world", "!")
    assert tokenize_text("don't") == ("don't",)
    assert tokenize_text("abc123") == ("abc123",)
    assert tokenize_text("123") == ("123",)
    assert tokenize_text("a-b") == ("a", "-", "b")
    assert tokenize_text("'hello'") == ("'", "hello", "'")
    assert tokenize_text("rock 'n' roll") == ("rock", "'", "n", "'", "roll")
    assert tokenize_text("a_b") == ("a", "_", "b")


def test_whitespace_unicode_and_case() -> None:
    assert tokenize_text("  a   b\tc\nd ") == ("a", "b", "c", "d")
    assert tokenize_text("café") == ("café",)
    assert tokenize_text("é") == ("é",)
    assert tokenize_text("ABC") == ("ABC",)
    assert tokenize_text("Hello") != tokenize_text("hello")
    assert tokenize_text("日本語") == ("日", "本", "語")


def test_empty_and_whitespace_input() -> None:
    assert tokenize_text("") == ()
    assert tokenize_text("   \t\n ") == ()


def test_malformed_unicode_rejected() -> None:
    with pytest.raises(TokenizerError) as exc:
        tokenize_text("a\ud800b")
    assert exc.value.code == "INVALID_INPUT"
    assert "ud800" not in str(exc.value).lower()


def test_non_string_inputs_rejected_without_coercion() -> None:
    for bad in (123, True, False, None, b"bytes", ["a"], {"a": 1}):
        with pytest.raises(TokenizerError) as exc:
            tokenize_text(bad)  # type: ignore[arg-type]
        assert exc.value.code == "INVALID_INPUT"


# --- reserved tokens and unknown handling ---


def test_reserved_ids_and_spelling_collisions() -> None:
    assert RESERVED_TOKENS == ("<pad>", "<unk>")
    assert PAD_ID == 0
    assert UNK_ID == 1
    assert tokenize_text("<pad>") == ("<", "pad", ">")
    result = _prepare({"synthetic-group-001": "hello world"})
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    ids = encode_text("<pad>", vocabulary=vocab, tokenizer_config=CONFIG)
    assert PAD_ID not in ids
    assert ids == (UNK_ID, UNK_ID, UNK_ID)


def test_unknown_tokens_map_to_unk() -> None:
    result = _prepare({"synthetic-group-001": "hello world"})
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    assert encode_text("hello", vocabulary=vocab, tokenizer_config=CONFIG) == (2,)
    assert encode_text("missing", vocabulary=vocab, tokenizer_config=CONFIG) == (
        UNK_ID,
    )


# --- sequence limits ---


def test_sequence_length_boundaries() -> None:
    config = TokenizerConfig(
        tokenizer_version="1.0",
        normalization="NFC",
        preserve_case=True,
        max_sequence_length=8,
    )
    result = _prepare({"synthetic-group-001": "a b c d e f g h i j k l"})
    vocab = build_vocabulary(result, tokenizer_config=config)
    assert (
        len(encode_text("a b c d e f g", vocabulary=vocab, tokenizer_config=config))
        == 7
    )
    assert (
        len(encode_text("a b c d e f g h", vocabulary=vocab, tokenizer_config=config))
        == 8
    )
    long_ids = encode_text(
        "a b c d e f g h i", vocabulary=vocab, tokenizer_config=config
    )
    assert len(long_ids) == 8
    assert long_ids == encode_text(
        "a b c d e f g h", vocabulary=vocab, tokenizer_config=config
    )


def test_invalid_length_settings_rejected() -> None:
    for bad in (0, 513, "8", True, -1, None):
        with pytest.raises((TokenizerError, ValidationError)):
            TokenizerConfig(
                tokenizer_version="1.0",
                normalization="NFC",
                preserve_case=True,
                max_sequence_length=bad,  # type: ignore[arg-type]
            )


# --- vocabulary ordering and limits ---


def test_frequency_ordering_and_tie_break() -> None:
    result = _prepare({"synthetic-group-001": "b b a a c"})
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    assert vocab.tokens == ("<pad>", "<unk>", "a", "b", "c")


def test_min_frequency_boundary() -> None:
    result = _prepare({"synthetic-group-001": "b b a a c"})
    vocab = build_vocabulary(
        result,
        tokenizer_config=CONFIG,
        policy=VocabularyPolicy(min_frequency=2),
    )
    assert vocab.tokens == ("<pad>", "<unk>", "a", "b")
    with pytest.raises(ValueError):
        VocabularyPolicy(min_frequency=0)
    with pytest.raises(ValueError):
        VocabularyPolicy(min_frequency=True)  # type: ignore[arg-type]


def test_max_vocab_size_boundary() -> None:
    result = _prepare({"synthetic-group-001": "b b a a c"})
    vocab = build_vocabulary(
        result, tokenizer_config=CONFIG, policy=VocabularyPolicy(max_vocab_size=4)
    )
    assert vocab.tokens == ("<pad>", "<unk>", "a", "b")
    with pytest.raises(ValueError):
        VocabularyPolicy(max_vocab_size=1)
    assert build_vocabulary(
        result, tokenizer_config=CONFIG, policy={"max_vocab_size": 3}
    ).tokens == ("<pad>", "<unk>", "a")


def test_empty_training_partition_yields_reserved_only() -> None:
    empty_split = SplitConfig(
        seed=7, train_ratio=0.0, validation_ratio=0.5, test_ratio=0.5
    )
    records = [
        _record("synthetic-rec-001", "hello world", "synthetic-group-001"),
        _record("synthetic-rec-002", "other words here", "synthetic-group-002"),
        _record("synthetic-rec-003", "more distinct text", "synthetic-group-003"),
    ]
    result = prepare_dataset(
        records=records,
        authorizations=_registry(),
        dataset_id="synthetic-tokenizer-001",
        purpose="synthetic-pilot",
        operation="training",
        as_of="2026-06-01",
        allowed_labels=LABELS,
        grouping_unit="synthetic-source-document",
        split_config=empty_split,
    )
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    assert vocab.tokens == ("<pad>", "<unk>")
    assert vocab.metadata.vocabulary_size == 2
    verify_vocabulary(vocab, tokenizer_config=CONFIG)


def test_duplicate_and_malformed_vocabulary_rejected() -> None:
    result = _prepare({"synthetic-group-001": "hello world"})
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    dumped = vocab.model_dump(mode="json")
    dumped["tokens"] = ["<pad>", "<unk>", "hello", "hello"]
    with pytest.raises(ValidationError):
        Vocabulary.model_validate(dumped)
    dumped = vocab.model_dump(mode="json")
    dumped["tokens"] = ["<unk>", "<pad>", "hello", "world"]
    with pytest.raises(ValidationError):
        Vocabulary.model_validate(dumped)
    dumped = vocab.model_dump(mode="json")
    dumped["metadata"]["vocabulary_version"] = "9.9"
    with pytest.raises(ValidationError):
        Vocabulary.model_validate(dumped)


def test_hash_verification_and_tampering() -> None:
    result = _prepare({"synthetic-group-001": "hello world"})
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    verify_vocabulary(vocab, tokenizer_config=CONFIG)
    dumped = vocab.model_dump(mode="json")
    dumped["metadata"]["vocabulary_hash"] = "0" * 64
    with pytest.raises(TokenizerError) as exc:
        verify_vocabulary(Vocabulary.model_validate(dumped))
    assert exc.value.code == "HASH_MISMATCH"
    other_config = TokenizerConfig(
        tokenizer_version="1.0",
        normalization="NFC",
        preserve_case=True,
        max_sequence_length=8,
    )
    with pytest.raises(TokenizerError) as exc:
        verify_vocabulary(vocab, tokenizer_config=other_config)
    assert exc.value.code == "HASH_MISMATCH"
    with pytest.raises(TokenizerError) as exc:
        verify_vocabulary("not-a-vocabulary")  # type: ignore[arg-type]
    assert exc.value.code == "INCOMPATIBLE_VOCABULARY"


def test_repeated_construction_equivalent_and_immutable() -> None:
    first = build_vocabulary(_prepare(_standard_contents()), tokenizer_config=CONFIG)
    second = build_vocabulary(_prepare(_standard_contents()), tokenizer_config=CONFIG)
    assert first == second
    assert first.metadata.vocabulary_hash == second.metadata.vocabulary_hash
    with pytest.raises(ValidationError):
        first.tokens = ("<pad>",)  # type: ignore[misc]
    shuffled = dict(reversed(list(_standard_contents().items())))
    assert build_vocabulary(_prepare(shuffled), tokenizer_config=CONFIG) == first


def test_config_change_alters_config_hash_only() -> None:
    result = _prepare({"synthetic-group-001": "hello world"})
    first = build_vocabulary(result, tokenizer_config=CONFIG)
    other = TokenizerConfig(
        tokenizer_version="1.0",
        normalization="NFC",
        preserve_case=True,
        max_sequence_length=8,
    )
    second = build_vocabulary(result, tokenizer_config=other)
    assert first.tokens == second.tokens
    assert first.metadata.vocabulary_hash == second.metadata.vocabulary_hash
    assert first.metadata.tokenizer_config_hash != second.metadata.tokenizer_config_hash


def test_training_data_change_alters_vocabulary_hash() -> None:
    first = build_vocabulary(
        _prepare({"synthetic-group-001": "hello world"}), tokenizer_config=CONFIG
    )
    second = build_vocabulary(
        _prepare({"synthetic-group-001": "hello there"}),
        tokenizer_config=CONFIG,
    )
    assert first.tokens != second.tokens
    assert first.metadata.vocabulary_hash != second.metadata.vocabulary_hash
    assert first.metadata.tokenizer_config_hash == (
        second.metadata.tokenizer_config_hash
    )


# --- held-out leakage ---


def test_training_only_tokens_eligible() -> None:
    result = _prepare(_standard_contents(), split_config=SPLIT)
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    sets = _partition_token_sets(result)
    assert sets["validation"] and sets["test"]
    for partition, other in (
        ("validation", "test"),
        ("test", "validation"),
    ):
        exclusive = sets[partition] - sets["train"] - sets[other]
        assert exclusive
        for token in exclusive:
            assert token not in vocab.tokens
    train_only = sets["train"] - sets["validation"] - sets["test"]
    assert train_only
    for token in train_only:
        assert token in vocab.tokens
    shared = sets["train"] & sets["validation"] & sets["test"]
    assert shared
    for token in shared:
        assert token in vocab.tokens


def test_changing_held_out_text_changes_nothing() -> None:
    first_result = _prepare(_standard_contents(), split_config=SPLIT)
    first = build_vocabulary(first_result, tokenizer_config=CONFIG)
    held_out = {
        group
        for group, partition in (
            (entry.group_id, entry.partition)
            for entry in first_result.split_manifest.assignments
        )
        if partition in ("validation", "test")
    }
    assert held_out
    changed = {
        group: (
            f"changed held out text for {group[-3:]}" if group in held_out else content
        )
        for group, content in _standard_contents().items()
    }
    second = build_vocabulary(
        _prepare(changed, split_config=SPLIT), tokenizer_config=CONFIG
    )
    assert second.tokens == first.tokens
    assert second.metadata.vocabulary_size == first.metadata.vocabulary_size
    assert second.metadata.vocabulary_hash == first.metadata.vocabulary_hash


def test_builder_rejects_non_train_entry_points() -> None:
    result = _prepare(_standard_contents())

    with pytest.raises(TokenizerError) as exc:
        build_vocabulary(
            partition_records(result, "validation"),  # type: ignore[arg-type]
            tokenizer_config=CONFIG,
        )
    assert exc.value.code == "INVALID_INPUT"
    with pytest.raises(TokenizerError) as exc:
        build_vocabulary("not-a-result", tokenizer_config=CONFIG)  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_INPUT"
    with pytest.raises(TokenizerError) as exc:
        build_vocabulary(result, tokenizer_config="bad")  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_CONFIG"


def test_synthetic_scope_preserved() -> None:
    result = _prepare(_standard_contents())
    vocab = build_vocabulary(result, tokenizer_config=CONFIG)
    assert vocab.metadata.data_scope == "synthetic-test-only"
    tampered = result.model_copy(
        update={
            "dataset_manifest": result.dataset_manifest.model_copy(
                update={"authorization_kind": "production"}
            )
        }
    )
    with pytest.raises(TokenizerError) as exc:
        build_vocabulary(tampered, tokenizer_config=CONFIG)
    assert exc.value.code == "UNSUPPORTED_SCOPE"


# --- misc ---


def test_policy_versions_and_no_network_dependency() -> None:
    from rop.tokenizer.vocabulary import VOCABULARY_POLICY_VERSION

    assert TOKENIZER_VERSION == "1.0"
    assert VOCABULARY_VERSION == "1.0"
    assert VOCABULARY_POLICY_VERSION == "1.0"
    package = pathlib.Path(__file__).parent.parent / "src" / "rop" / "tokenizer"
    imported: set[str] = set()
    for name in ("__init__.py", "tokenizer.py", "vocabulary.py"):
        for line in (package / name).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                imported.add(stripped.split()[1].split(".")[0])
            elif stripped.startswith("from "):
                imported.add(stripped.split()[1].split(".")[0])
    forbidden = {
        "anthropic",
        "gemini",
        "httpx",
        "ollama",
        "openai",
        "os",
        "requests",
        "sklearn",
        "socket",
        "subprocess",
        "torch",
        "transformers",
        "urllib",
    }
    assert not (imported & forbidden)

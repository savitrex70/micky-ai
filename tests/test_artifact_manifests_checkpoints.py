"""Task 211: artifact manifest and checkpoint integrity tests.

Synthetic fixtures only, temporary files only. No network access,
pretrained artifacts, external datasets, clinical data, or GPU.
"""

from __future__ import annotations

import io
import json
import struct

import pytest
import torch
from pydantic import ValidationError

from rop.artifacts import (
    ArtifactError,
    apply_checkpoint_to_model,
    build_artifact_manifest,
    build_checkpoint_bytes,
    content_digest,
    load_artifact_files,
    parse_checkpoint_header,
    verify_artifact,
    verify_manifest_integrity,
    write_artifact_files,
)
from rop.dataset_preparation import compose_test_registry, prepare_dataset
from rop.dataset_preparation.pipeline import partition_records
from rop.native_model import initialize_model
from rop.schemas.artifact import (
    ARTIFACT_MANIFEST_VERSION,
    CHECKPOINT_FORMAT,
    CHECKPOINT_FORMAT_VERSION,
    ArtifactManifest,
)
from rop.schemas.native_model import NativeModelConfig
from rop.schemas.tokenizer import TokenizerConfig
from rop.schemas.training import TrainingConfig
from rop.tokenizer import build_vocabulary

REGISTRY = compose_test_registry(
    [
        {
            "source_id": "synthetic-test-artifact-1",
            "authorization_version": "1.0",
            "origin_description": "In-repo synthetic fixture source",
            "license_basis": "repo-internal-synthetic",
            "intended_purpose": "native-training",
            "permitted_operations": ("training",),
            "status": "APPROVED",
            "approval_reference": "approval-artifact-1",
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

_TRAINING_CONFIG = TrainingConfig(
    contract_version="1",
    epochs=1,
    batch_size=4,
    learning_rate=0.1,
    seed=99,
)


def _build_result():
    records = []
    for index, word in enumerate(_WORDS, start=1):
        records.append(
            {
                "record_id": f"r-{index:02d}",
                "source_id": "synthetic-test-artifact-1",
                "group_id": f"g-{index:02d}",
                "label": "alpha" if index % 2 == 1 else "beta",
                "content_text": f"synthetic {word} text sample {index}",
                "provenance_ref": "synthetic-in-repo-fixture-1",
            }
        )
    return prepare_dataset(
        records=records,
        authorizations=REGISTRY,
        dataset_id="synthetic-native-artifact",
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


def _fresh_model():
    return initialize_model(_MODEL_CONFIG)


def _build_fixture(artifact_id: str = "synthetic-ckpt-001"):
    model = _fresh_model()
    content = build_checkpoint_bytes(model)
    manifest = build_artifact_manifest(
        artifact_id=artifact_id,
        content=content,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    return model, content, manifest


def _snapshot(model) -> dict[str, torch.Tensor]:
    return {name: p.detach().clone() for name, p in model.named_parameters()}


def test_valid_manifest_and_artifact_verification() -> None:
    model, content, manifest = _build_fixture()
    assert manifest.manifest_version == ARTIFACT_MANIFEST_VERSION
    assert manifest.artifact_type == "model-checkpoint"
    assert manifest.checkpoint_format == CHECKPOINT_FORMAT
    assert manifest.checkpoint_format_version == CHECKPOINT_FORMAT_VERSION
    assert manifest.data_scope == "synthetic-test-only"
    verify_manifest_integrity(manifest)
    header = verify_artifact(
        content=content,
        manifest=manifest,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    assert header["parameter_count"] == manifest.parameter_count
    assert content_digest(content) == manifest.content_digest


def test_artifact_byte_tampering_detected() -> None:
    _, content, manifest = _build_fixture()
    tampered = bytearray(content)
    tampered[-1] ^= 0x01
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=bytes(tampered),
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "HASH_MISMATCH"


def test_manifest_metadata_tampering_detected() -> None:
    _, content, manifest = _build_fixture()
    tampered = manifest.model_copy(update={"artifact_id": "synthetic-ckpt-002"})
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=tampered,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "MANIFEST_DIGEST_MISMATCH"


def test_invalid_digest_format_rejected() -> None:
    _, content, manifest = _build_fixture()
    bad = manifest.model_dump(mode="json")
    bad["content_digest"] = "not-a-digest"
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(bad)
    # Content digest of wrong length is also rejected at schema level.
    bad["content_digest"] = "0" * 63
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(bad)


def test_unsupported_manifest_version_rejected() -> None:
    _, _, manifest = _build_fixture()
    bad = manifest.model_dump(mode="json")
    bad["manifest_version"] = "9.9"
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(bad)


def test_unsupported_checkpoint_version_rejected() -> None:
    model = _fresh_model()
    content = build_checkpoint_bytes(model)
    header_len = struct.unpack(">I", content[8:12])[0]
    header = json.loads(content[12 : 12 + header_len].decode("utf-8"))
    header["checkpoint_format_version"] = "9.9"
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    forged = b"ROPCHK01" + struct.pack(">I", len(header_bytes)) + header_bytes
    forged += content[12 + header_len :]
    with pytest.raises(ArtifactError) as exc:
        parse_checkpoint_header(forged)
    assert exc.value.code == "UNSUPPORTED_VERSION"


def test_wrong_artifact_type_rejected() -> None:
    _, content, manifest = _build_fixture()
    tampered = ArtifactManifest.model_construct(
        **{**manifest.model_dump(mode="python"), "artifact_type": "model-weights"}
    )
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=tampered,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "WRONG_ARTIFACT_TYPE"


def test_missing_required_metadata_rejected() -> None:
    _, content, manifest = _build_fixture()
    dropped = manifest.model_dump(mode="json")
    del dropped["dataset_id"]
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(dropped)
    with pytest.raises(ArtifactError) as exc:
        build_artifact_manifest(
            artifact_id="synthetic-ckpt-001",
            content=content,
            model_config=_MODEL_CONFIG,
            training_config=None,  # type: ignore[arg-type]
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INVALID_INPUT"


def test_inconsistent_model_reference_rejected() -> None:
    _, content, manifest = _build_fixture()
    other = _MODEL_CONFIG.model_copy(update={"hidden_dim": 32})
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=manifest,
            model_config=other,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_MODEL"


def test_inconsistent_training_reference_rejected() -> None:
    _, content, manifest = _build_fixture()
    other = TrainingConfig(
        contract_version="1", epochs=1, batch_size=4, learning_rate=0.1, seed=100
    )
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=other,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_TRAINING"


def test_inconsistent_dataset_reference_rejected() -> None:
    _, content, manifest = _build_fixture()
    other_records = []
    for index, word in enumerate(_WORDS, start=1):
        other_records.append(
            {
                "record_id": f"q-{index:02d}",
                "source_id": "synthetic-test-artifact-1",
                "group_id": f"h-{index:02d}",
                "label": "alpha" if index % 2 == 1 else "beta",
                "content_text": f"synthetic {word} text sample {index}",
                "provenance_ref": "synthetic-in-repo-fixture-1",
            }
        )
    other_result = prepare_dataset(
        records=other_records,
        authorizations=REGISTRY,
        dataset_id="synthetic-other-dataset",
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
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=other_result,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_DATASET"


def test_inconsistent_vocabulary_reference_rejected() -> None:
    _, content, manifest = _build_fixture()
    second_words = tuple(f"otherword{i}" for i in range(12))
    second_records = []
    for index, word in enumerate(second_words, start=1):
        second_records.append(
            {
                "record_id": f"s-{index:02d}",
                "source_id": "synthetic-test-artifact-1",
                "group_id": f"j-{index:02d}",
                "label": "alpha" if index % 2 == 1 else "beta",
                "content_text": f"synthetic {word} text sample {index}",
                "provenance_ref": "synthetic-in-repo-fixture-1",
            }
        )
    second_result = prepare_dataset(
        records=second_records,
        authorizations=REGISTRY,
        dataset_id="synthetic-native-artifact",
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
    other_vocab = build_vocabulary(second_result, tokenizer_config=_TOKENIZER_CONFIG)
    assert other_vocab.metadata.vocabulary_hash != manifest.vocabulary_hash
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=other_vocab,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_VOCABULARY"


def test_inconsistent_tokenizer_reference_rejected() -> None:
    _, content, manifest = _build_fixture()
    other_tokenizer = TokenizerConfig(
        tokenizer_version="1.0",
        normalization="NFC",
        preserve_case=True,
        max_sequence_length=16,
    )
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=other_tokenizer,
        )
    assert exc.value.code in ("INCOMPATIBLE_TOKENIZER", "HASH_MISMATCH")


def test_manifest_and_content_digests_are_separate() -> None:
    _, content, manifest = _build_fixture()
    assert manifest.content_digest != manifest.manifest_digest
    # Tampering only the manifest digest leaves the content digest valid.
    forged = manifest.model_copy(update={"manifest_digest": "0" * 64})
    with pytest.raises(ArtifactError) as exc:
        verify_manifest_integrity(forged)
    assert exc.value.code == "MANIFEST_DIGEST_MISMATCH"
    # Tampering only the bytes leaves the manifest digest valid.
    tampered = bytearray(content)
    tampered[20] ^= 0xFF
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=bytes(tampered),
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "HASH_MISMATCH"


def test_checkpoint_structure_rejection() -> None:
    # Truncated content.
    _, content, _ = _build_fixture()
    with pytest.raises(ArtifactError) as exc:
        parse_checkpoint_header(content[:10])
    assert exc.value.code == "CORRUPT_CHECKPOINT"
    # Foreign pickle bytes (torch.save format) are rejected as unsupported.
    buf = io.BytesIO()
    torch.save({"weights": torch.zeros(4)}, buf)
    with pytest.raises(ArtifactError) as exc:
        parse_checkpoint_header(buf.getvalue())
    assert exc.value.code == "UNSUPPORTED_FORMAT"
    # Random bytes are rejected without deserialization.
    with pytest.raises(ArtifactError) as exc:
        parse_checkpoint_header(b"\x00" * 64)
    assert exc.value.code in ("UNSUPPORTED_FORMAT", "CORRUPT_CHECKPOINT")


def test_mismatched_content_and_manifest_rejected() -> None:
    model_a, content_a, _ = _build_fixture("synthetic-ckpt-001")
    model_b = initialize_model(_MODEL_CONFIG.model_copy(update={"init_seed": 43}))
    content_b = build_checkpoint_bytes(model_b)
    assert content_a != content_b
    manifest_a = build_artifact_manifest(
        artifact_id="synthetic-ckpt-001",
        content=content_a,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content_b,
            manifest=manifest_a,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "HASH_MISMATCH"


def test_deterministic_canonicalization() -> None:
    model, content_a, manifest_a = _build_fixture()
    content_b = build_checkpoint_bytes(model)
    manifest_b = build_artifact_manifest(
        artifact_id="synthetic-ckpt-001",
        content=content_b,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    assert content_a == content_b
    assert content_digest(content_a) == content_digest(content_b)
    assert manifest_a == manifest_b
    assert manifest_a.manifest_digest == manifest_b.manifest_digest


def test_malformed_inputs_and_extra_fields_rejected() -> None:
    _, content, manifest = _build_fixture()
    with pytest.raises(ArtifactError):
        verify_artifact(
            content="not-bytes",  # type: ignore[arg-type]
            manifest=manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    with pytest.raises(ArtifactError):
        verify_artifact(
            content=content,
            manifest={"artifact_id": "x"},  # type: ignore[arg-type]
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    extra = manifest.model_dump(mode="json")
    extra["unknown_field"] = "x"
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(extra)


def test_unsupported_scope_and_operation_rejected() -> None:
    model, content, _ = _build_fixture()
    bad_manifest = ArtifactManifest.model_construct(
        **{**_build_fixture()[2].model_dump(mode="python"), "data_scope": "prod"}
    )
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=bad_manifest,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "UNSUPPORTED_SCOPE"
    bad_operation = _RESULT.dataset_manifest.model_copy(
        update={"operation": "evaluation"}
    )
    broken_result = _RESULT.model_copy(update={"dataset_manifest": bad_operation})
    with pytest.raises(ArtifactError) as exc:
        build_artifact_manifest(
            artifact_id="synthetic-ckpt-001",
            content=content,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=broken_result,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "OPERATION_NOT_PERMITTED"


def test_jointly_forged_lineage_rejected_by_authoritative_source() -> None:
    """Mutually matching forged metadata must fail against the real lineage."""
    from rop.artifacts.checkpoints import _manifest_digest_for

    _, content, _ = _build_fixture()
    forged_manifest = build_artifact_manifest(
        artifact_id="synthetic-ckpt-001",
        content=content,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    # Forge dataset identity consistently inside the manifest only.
    forged = forged_manifest.model_copy(update={"dataset_id": "synthetic-forged"})
    object.__setattr__(forged, "manifest_digest", _manifest_digest_for(forged))
    # The forged manifest is internally consistent, but the real result disagrees.
    with pytest.raises(ArtifactError) as exc:
        verify_artifact(
            content=content,
            manifest=forged,
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_DATASET"


def test_apply_checkpoint_roundtrip_and_failure_atomicity() -> None:
    source = _fresh_model()
    content = build_checkpoint_bytes(source)
    # Same authoritative configuration in a fresh instance: perturb it so
    # the copy is observable, then restore via the checkpoint.
    target = _fresh_model()
    with torch.no_grad():
        next(target.parameters()).add_(1.0)
    before_target = _snapshot(target)
    assert any(
        not torch.equal(before_target[n], p.detach())
        for n, p in source.named_parameters()
    )
    apply_checkpoint_to_model(target, content)
    live = dict(target.named_parameters())
    for name, param in source.named_parameters():
        assert torch.equal(param.detach(), live[name].detach())
    # A foreign configuration is rejected even though the layout matches.
    foreign = initialize_model(_MODEL_CONFIG.model_copy(update={"init_seed": 7}))
    foreign_before = _snapshot(foreign)
    with pytest.raises(ArtifactError) as exc:
        apply_checkpoint_to_model(foreign, content)
    assert exc.value.code == "INCOMPATIBLE_MODEL"
    for name, value in foreign_before.items():
        assert torch.equal(value, dict(foreign.named_parameters())[name].detach())
    # Corrupt bytes must leave the model untouched.
    bad = bytearray(content)
    bad[12] ^= 0xFF
    before = _snapshot(target)
    with pytest.raises(ArtifactError):
        apply_checkpoint_to_model(target, bytes(bad))
    for name, value in before.items():
        assert torch.equal(value, dict(target.named_parameters())[name].detach())


def test_file_roundtrip_in_tmp_path(tmp_path) -> None:
    _, content, manifest = _build_fixture("synthetic-ckpt-tmp")
    ckpt_path, manifest_path = write_artifact_files(
        tmp_path, content=content, manifest=manifest
    )
    assert ckpt_path.is_file() and manifest_path.is_file()
    raw, loaded = load_artifact_files(ckpt_path, manifest_path)
    assert raw == content
    assert loaded == manifest
    header = verify_artifact(
        content=raw,
        manifest=loaded,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    assert header["parameter_count"] == manifest.parameter_count
    with pytest.raises(ArtifactError):
        load_artifact_files(tmp_path / "missing.ckpt", manifest_path)


# --- Correction: checkpoint identity bound to model configuration ---


def _reheader(content: bytes, mutate) -> bytes:
    """Re-serialize checkpoint bytes with a mutated header (test helper)."""
    header_len = struct.unpack(">I", content[8:12])[0]
    header = json.loads(content[12 : 12 + header_len].decode("utf-8"))
    mutate(header)
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    return (
        b"ROPCHK01"
        + struct.pack(">I", len(header_bytes))
        + header_bytes
        + content[12 + header_len :]
    )


def _manifest_for(content: bytes, artifact_id: str = "synthetic-ckpt-001"):
    return build_artifact_manifest(
        artifact_id=artifact_id,
        content=content,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )


def _verify_base(content: bytes, manifest) -> None:
    verify_artifact(
        content=content,
        manifest=manifest,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )


def test_same_param_count_incompatible_config_rejected() -> None:
    """Equal parameter counts do not imply configuration compatibility."""
    from rop.native_model.native_model import count_parameters

    alt_config = _MODEL_CONFIG.model_copy(update={"num_heads": 8})
    alt_model = initialize_model(alt_config)
    alt_content = build_checkpoint_bytes(alt_model)
    base_model = _fresh_model()
    assert count_parameters(alt_model) == count_parameters(base_model)
    manifest = _manifest_for(alt_content)
    with pytest.raises(ArtifactError) as exc:
        _verify_base(alt_content, manifest)
    assert exc.value.code == "INCOMPATIBLE_MODEL"


def test_architecture_and_version_mismatch_rejected() -> None:
    """Checkpoints with forged architecture/version are rejected with valid digests."""
    _, content, _ = _build_fixture()
    tampered_arch = _reheader(content, lambda h: h.update({"architecture": "other"}))
    with pytest.raises(ArtifactError) as exc:
        _verify_base(tampered_arch, _manifest_for(tampered_arch))
    assert exc.value.code == "INCOMPATIBLE_MODEL"
    tampered_ver = _reheader(content, lambda h: h.update({"model_version": "9.9"}))
    with pytest.raises(ArtifactError) as exc:
        _verify_base(tampered_ver, _manifest_for(tampered_ver))
    assert exc.value.code == "INCOMPATIBLE_MODEL"


def test_correct_hashes_incompatible_layout_rejected() -> None:
    """A valid fingerprint with a forged tensor layout is still rejected."""

    def _reshape_bias(header: dict) -> None:
        params = header["parameters"]
        name = next(
            n for n, e in params.items() if e["shape"] == [2] and e["nbytes"] == 8
        )
        params[name]["shape"] = [2, 1]

    _, content, _ = _build_fixture()
    tampered = _reheader(content, _reshape_bias)
    with pytest.raises(ArtifactError) as exc:
        _verify_base(tampered, _manifest_for(tampered))
    assert exc.value.code == "INCOMPATIBLE_MODEL"


def test_apply_rejects_incompatible_before_mutation() -> None:
    """apply_checkpoint_to_model rejects foreign configs atomically."""
    alt_config = _MODEL_CONFIG.model_copy(update={"num_heads": 8})
    alt_content = build_checkpoint_bytes(initialize_model(alt_config))
    target = _fresh_model()
    before = _snapshot(target)
    with pytest.raises(ArtifactError) as exc:
        apply_checkpoint_to_model(target, alt_content)
    assert exc.value.code == "INCOMPATIBLE_MODEL"
    for name, value in before.items():
        assert torch.equal(value, dict(target.named_parameters())[name].detach())

    _, content, _ = _build_fixture()
    tampered = _reheader(content, lambda h: h.update({"architecture": "other"}))
    before = _snapshot(target)
    with pytest.raises(ArtifactError) as exc:
        apply_checkpoint_to_model(target, tampered)
    assert exc.value.code == "INCOMPATIBLE_MODEL"
    for name, value in before.items():
        assert torch.equal(value, dict(target.named_parameters())[name].detach())


def test_malformed_header_types_rejected() -> None:
    """Boolean/novel/missing header fields fail structural parsing."""
    _, content, _ = _build_fixture()

    def _first_param(header: dict) -> dict:
        name = sorted(header["parameters"])[0]
        return header["parameters"][name]

    cases = [
        lambda h: h.update({"unexpected": 1}),
        lambda h: h.update({"parameter_count": True}),
        lambda h: _first_param(h).update({"offset": "0"}),
        lambda h: _first_param(h).update({"nbytes": True}),
        lambda h: _first_param(h).update({"shape": [True]}),
        lambda h: _first_param(h).update({"extra": 0}),
        lambda h: h.pop("model_config_hash"),
        lambda h: h.update({"model_config_hash": "zz"}),
        lambda h: h.update({"architecture": ""}),
    ]
    for mutate in cases:
        with pytest.raises(ArtifactError) as exc:
            parse_checkpoint_header(_reheader(content, mutate))
        assert exc.value.code in ("CORRUPT_CHECKPOINT", "UNSUPPORTED_VERSION")


def test_legacy_v1_header_rejected() -> None:
    """Format 1.0 bytes without a fingerprint are rejected, not reinterpreted."""
    _, content, _ = _build_fixture()
    header_len = struct.unpack(">I", content[8:12])[0]
    header = json.loads(content[12 : 12 + header_len].decode("utf-8"))
    del header["model_config_hash"]
    header["checkpoint_format_version"] = "1.0"
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    legacy = (
        b"ROPCHK01"
        + struct.pack(">I", len(header_bytes))
        + header_bytes
        + content[12 + header_len :]
    )
    with pytest.raises(ArtifactError) as exc:
        parse_checkpoint_header(legacy)
    assert exc.value.code == "UNSUPPORTED_VERSION"

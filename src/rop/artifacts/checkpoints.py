"""Task 211: artifact manifest and checkpoint integrity implementation.

Minimal, pickle-free checkpoint handling for the Task 209
``tiny-encoder-v1`` model with Task 210 training lineage. Checkpoint
bytes use a small raw-tensor layout (magic + JSON header + float32
payload) so untrusted files are validated structurally before any
tensor is applied to a model. No pretrained weights, external files,
downloads, network, inference, or clinical logic live here.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any

import torch

from rop.dataset_preparation.pipeline import (
    DatasetPreparationError,
    dataset_integrity_hash,
    verify_split,
)
from rop.native_model.native_model import (
    NativeModel,
)
from rop.native_model.native_model import (
    _canonical_config_dict as _model_canonical_dict,
)
from rop.native_model.native_model import (
    _canonical_hash as _canonical_hash_fn,
)
from rop.native_model.native_model import (
    _estimate_parameter_count as _estimate_model_params,
)
from rop.schemas.artifact import (
    ARTIFACT_MANIFEST_VERSION,
    ARTIFACT_TYPE_MODEL_CHECKPOINT,
    CHECKPOINT_FORMAT,
    CHECKPOINT_FORMAT_VERSION,
    MAX_CHECKPOINT_BYTES,
    MAX_HEADER_BYTES,
    ArtifactErrorCode,
    ArtifactManifest,
)
from rop.schemas.dataset_manifest import PreparationResult
from rop.schemas.native_model import NativeModelConfig
from rop.schemas.tokenizer import TokenizerConfig, Vocabulary
from rop.schemas.training import TrainingConfig
from rop.tokenizer.vocabulary import (
    _canonical_config_dict as _tokenizer_canonical_dict,
)
from rop.tokenizer.vocabulary import (
    verify_vocabulary,
)

__all__ = [
    "ArtifactError",
    "apply_checkpoint_to_model",
    "build_artifact_manifest",
    "build_checkpoint_bytes",
    "content_digest",
    "load_artifact_files",
    "parse_checkpoint_header",
    "verify_artifact",
    "verify_manifest_integrity",
    "write_artifact_files",
]

_MAGIC = b"ROPCHK01"
_MAGIC_LEN = 8
_HEADER_LEN_SIZE = 4
_SUPPORTED_DTYPE = "float32"
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

_HEADER_ALLOWED_FIELDS = frozenset(
    {
        "checkpoint_format",
        "checkpoint_format_version",
        "architecture",
        "model_version",
        "model_config_hash",
        "parameter_count",
        "parameters",
    }
)
_ENTRY_ALLOWED_FIELDS = frozenset({"dtype", "shape", "offset", "nbytes"})


def _strict_int(value: object) -> bool:
    """True only for genuine ints; booleans are rejected."""
    return isinstance(value, int) and not isinstance(value, bool)


class ArtifactError(Exception):
    """A typed artifact failure with a safe, generic message."""

    def __init__(self, code: ArtifactErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def content_digest(data: bytes) -> str:
    """SHA-256 hex digest of the exact checkpoint bytes."""
    if not isinstance(data, (bytes, bytearray)):
        raise ArtifactError("INVALID_INPUT", "checkpoint content is invalid")
    return hashlib.sha256(bytes(data)).hexdigest()


def _canonical_manifest_dict(manifest: ArtifactManifest) -> dict[str, Any]:
    """Canonical manifest representation (v1.0), excluding the digest itself."""
    return {
        "manifest_version": manifest.manifest_version,
        "artifact_type": manifest.artifact_type,
        "artifact_id": manifest.artifact_id,
        "content_digest": manifest.content_digest,
        "checkpoint_format": manifest.checkpoint_format,
        "checkpoint_format_version": manifest.checkpoint_format_version,
        "model_version": manifest.model_version,
        "architecture": manifest.architecture,
        "model_config_hash": manifest.model_config_hash,
        "parameter_count": manifest.parameter_count,
        "training_config_hash": manifest.training_config_hash,
        "training_seed": manifest.training_seed,
        "model_init_seed": manifest.model_init_seed,
        "dataset_id": manifest.dataset_id,
        "dataset_integrity_hash": manifest.dataset_integrity_hash,
        "split_assignment_hash": manifest.split_assignment_hash,
        "vocabulary_hash": manifest.vocabulary_hash,
        "tokenizer_config_hash": manifest.tokenizer_config_hash,
        "data_scope": manifest.data_scope,
    }


def _manifest_digest_for(manifest: ArtifactManifest) -> str:
    canonical = json.dumps(
        _canonical_manifest_dict(manifest), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _checked_manifest(manifest: ArtifactManifest) -> ArtifactManifest:
    """Revalidate a manifest instance to defeat model_copy bypass."""
    if not isinstance(manifest, ArtifactManifest):
        raise ArtifactError("INVALID_INPUT", "artifact manifest is invalid")
    try:
        return ArtifactManifest.model_validate(manifest.model_dump())
    except Exception as exc:
        raise ArtifactError("INVALID_MANIFEST", "artifact manifest is invalid") from exc


def _checked_model_config(config: NativeModelConfig) -> NativeModelConfig:
    if not isinstance(config, NativeModelConfig):
        raise ArtifactError("INVALID_INPUT", "model configuration is invalid")
    try:
        return NativeModelConfig.model_validate(config.model_dump())
    except Exception as exc:
        raise ArtifactError(
            "INVALID_MANIFEST", "model configuration is invalid"
        ) from exc


def _checked_training_config(config: TrainingConfig) -> TrainingConfig:
    if not isinstance(config, TrainingConfig):
        raise ArtifactError("INVALID_INPUT", "training configuration is invalid")
    try:
        return TrainingConfig.model_validate(config.model_dump(mode="json"))
    except Exception as exc:
        raise ArtifactError(
            "INVALID_MANIFEST", "training configuration is invalid"
        ) from exc


def _checked_tokenizer_config(
    config: TokenizerConfig,
) -> TokenizerConfig:
    if not isinstance(config, TokenizerConfig):
        raise ArtifactError("INVALID_INPUT", "tokenizer configuration is invalid")
    try:
        return TokenizerConfig.model_validate(config.model_dump())
    except Exception as exc:
        raise ArtifactError(
            "INVALID_MANIFEST", "tokenizer configuration is invalid"
        ) from exc


def verify_manifest_integrity(manifest: ArtifactManifest) -> None:
    """Recompute and check the manifest digest; never trust the recorded value."""
    checked = _checked_manifest(manifest)
    if _manifest_digest_for(checked) != checked.manifest_digest:
        raise ArtifactError(
            "MANIFEST_DIGEST_MISMATCH", "manifest digest does not match"
        )


def _model_shapes(model: NativeModel) -> dict[str, list[int]]:
    return {name: list(p.shape) for name, p in model.named_parameters()}


def _expected_layout(model_cfg: NativeModelConfig) -> dict[str, list[int]]:
    """Derive the expected parameter layout from the authoritative config.

    Constructs a reference model via the existing Task 209 construction
    contract (with global RNG state preserved) so the layout never
    drifts from the real architecture. Used to bind checkpoint headers
    to the full configuration, not merely the parameter count.
    """
    rng_state = torch.get_rng_state()
    try:
        reference = NativeModel(model_cfg)
    finally:
        torch.set_rng_state(rng_state)
    return _model_shapes(reference)


def _model_fingerprint(model_cfg: NativeModelConfig) -> str:
    """Canonical model-configuration fingerprint (Task 209 scheme)."""
    return _canonical_hash_fn(_model_canonical_dict(model_cfg))


def build_checkpoint_bytes(model: NativeModel) -> bytes:
    """Serialize an initialized model to pickle-free checkpoint bytes.

    Layout (v2.0): 8-byte magic ``ROPCHK01`` + 4-byte big-endian header
    length + sorted-key compact JSON header + concatenated little-endian
    float32 payload in sorted parameter-name order. The header embeds
    the canonical model-configuration fingerprint so the bytes are
    bound to the complete authoritative configuration.
    """
    if not isinstance(model, NativeModel) or not model._initialized:
        raise ArtifactError("INVALID_INPUT", "model is invalid")
    shapes = _model_shapes(model)
    for _name, shape in shapes.items():
        if not shape or any(not isinstance(d, int) or d <= 0 for d in shape):
            raise ArtifactError("INVALID_INPUT", "model parameter shape is invalid")
    for param in model.parameters():
        if param.dtype != torch.float32:
            raise ArtifactError("INVALID_INPUT", "model parameters must be float32")
        if not torch.all(torch.isfinite(param)).item():
            raise ArtifactError("INVALID_INPUT", "model parameters must be finite")
    names = sorted(shapes)
    entries: dict[str, dict[str, Any]] = {}
    offset = 0
    for name in names:
        shape = shapes[name]
        count = 1
        for dim in shape:
            count *= dim
        nbytes = count * 4
        entries[name] = {
            "dtype": _SUPPORTED_DTYPE,
            "shape": list(shape),
            "offset": offset,
            "nbytes": nbytes,
        }
        offset += nbytes
    header = {
        "checkpoint_format": CHECKPOINT_FORMAT,
        "checkpoint_format_version": CHECKPOINT_FORMAT_VERSION,
        "architecture": model.config.architecture,
        "model_version": model.config.model_version,
        "model_config_hash": _model_fingerprint(model.config),
        "parameter_count": sum(v["nbytes"] // 4 for v in entries.values()),
        "parameters": entries,
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(header_bytes) > MAX_HEADER_BYTES:
        raise ArtifactError("INVALID_INPUT", "checkpoint header is too large")
    payload = bytearray()
    with torch.no_grad():
        for name in names:
            param = dict(model.named_parameters())[name]
            payload.extend(bytes(param.detach().cpu().contiguous().untyped_storage()))
    if len(payload) + _MAGIC_LEN + _HEADER_LEN_SIZE + len(header_bytes) > (
        MAX_CHECKPOINT_BYTES
    ):
        raise ArtifactError("INVALID_INPUT", "checkpoint content is too large")
    return _MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes + bytes(payload)


def parse_checkpoint_header(data: bytes | bytearray) -> dict[str, Any]:
    """Parse and fully validate a checkpoint header without applying state.

    Returns the decoded header dict. Raises before any tensor is
    constructed from the payload.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ArtifactError("INVALID_INPUT", "checkpoint content is invalid")
    raw = bytes(data)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint content is too large")
    if len(raw) < _MAGIC_LEN + _HEADER_LEN_SIZE:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint content is truncated")
    if raw[:_MAGIC_LEN] != _MAGIC:
        raise ArtifactError("UNSUPPORTED_FORMAT", "checkpoint format is not supported")
    (header_len,) = struct.unpack(">I", raw[_MAGIC_LEN : _MAGIC_LEN + 4])
    if header_len < 1 or header_len > MAX_HEADER_BYTES:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    header_start = _MAGIC_LEN + _HEADER_LEN_SIZE
    header_end = header_start + header_len
    if len(raw) < header_end:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint content is truncated")
    try:
        header = json.loads(raw[header_start:header_end].decode("utf-8"))
    except Exception as exc:
        raise ArtifactError(
            "CORRUPT_CHECKPOINT", "checkpoint header is invalid"
        ) from exc
    if not isinstance(header, dict):
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    if header.get("checkpoint_format") != CHECKPOINT_FORMAT:
        raise ArtifactError("UNSUPPORTED_FORMAT", "checkpoint format is not supported")
    if header.get("checkpoint_format_version") != CHECKPOINT_FORMAT_VERSION:
        raise ArtifactError(
            "UNSUPPORTED_VERSION", "checkpoint format version is not supported"
        )
    if set(header) != set(_HEADER_ALLOWED_FIELDS):
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    if not isinstance(header.get("architecture"), str) or not header["architecture"]:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    if not isinstance(header.get("model_version"), str) or not header["model_version"]:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    fingerprint = header.get("model_config_hash")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    if not _strict_int(header.get("parameter_count")):
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    parameters = header.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    total = 0
    for name in sorted(parameters):
        if not isinstance(name, str) or not name:
            raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
        entry = parameters[name]
        if not isinstance(entry, dict) or set(entry) != set(_ENTRY_ALLOWED_FIELDS):
            raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
        if entry.get("dtype") != _SUPPORTED_DTYPE:
            raise ArtifactError(
                "UNSUPPORTED_FORMAT", "checkpoint parameter dtype is not supported"
            )
        shape = entry.get("shape")
        if (
            not isinstance(shape, list)
            or not shape
            or any(not _strict_int(d) or d <= 0 for d in shape)
        ):
            raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
        count = 1
        for dim in shape:
            count *= dim
        if not _strict_int(entry.get("nbytes")) or entry["nbytes"] != count * 4:
            raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
        if not _strict_int(entry.get("offset")) or entry["offset"] != total:
            raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
        total += count * 4
    if header.get("parameter_count") != total // 4:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    if total // 4 < 1:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint header is invalid")
    payload = raw[header_end:]
    if len(payload) != total:
        raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint payload is invalid")
    return header


def apply_checkpoint_to_model(model: NativeModel, data: bytes | bytearray) -> None:
    """Validate checkpoint bytes fully, then apply state to the model.

    Supported target policy: every target parameter must be float32 on
    CPU (the Task 209 contract). Any other dtype or device is rejected
    before mutation. All structural validation (magic, version, header,
    shapes, payload size), identity checks, target policy checks, and
    decoded-tensor finiteness checks happen before any model parameter
    is modified; a failure leaves model parameters unchanged. Because
    the copy is an exact same-dtype, same-device transfer of already
    validated finite tensors, no conversion failure is possible after
    mutation begins. The checkpoint architecture, model version, and
    embedded configuration fingerprint are checked against the target
    model before any state is decoded.
    """
    if not isinstance(model, NativeModel) or not model._initialized:
        raise ArtifactError("INVALID_INPUT", "model is invalid")
    header = parse_checkpoint_header(data)
    if header["architecture"] != model.config.architecture:
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint architecture does not match the model"
        )
    if header["model_version"] != model.config.model_version:
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint model version does not match the model"
        )
    if header["model_config_hash"] != _model_fingerprint(model.config):
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint configuration does not match the model"
        )
    raw = bytes(data)
    header_len = struct.unpack(">I", raw[_MAGIC_LEN : _MAGIC_LEN + 4])[0]
    payload = raw[_MAGIC_LEN + _HEADER_LEN_SIZE + header_len :]
    expected = _model_shapes(model)
    header_params = header["parameters"]
    if set(header_params) != set(expected):
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint parameters do not match the model"
        )
    for name, shape in expected.items():
        if list(header_params[name]["shape"]) != list(shape):
            raise ArtifactError(
                "INCOMPATIBLE_MODEL", "checkpoint parameters do not match the model"
            )
    # Target policy gate: only float32 CPU parameters are supported, so
    # the subsequent copy is an exact transfer with no dtype conversion
    # and no overflow risk. Anything else is rejected before mutation.
    for _name, param in model.named_parameters():
        if param.dtype != torch.float32:
            raise ArtifactError(
                "INVALID_INPUT", "target model parameters must be float32"
            )
        if param.device.type != "cpu":
            raise ArtifactError("INVALID_INPUT", "target model must be on CPU")
    decoded: dict[str, torch.Tensor] = {}
    for name in sorted(header_params):
        entry = header_params[name]
        chunk = payload[entry["offset"] : entry["offset"] + entry["nbytes"]]
        tensor = torch.frombuffer(bytearray(chunk), dtype=torch.float32).clone()
        tensor = tensor.reshape(entry["shape"])
        if not torch.all(torch.isfinite(tensor)).item():
            raise ArtifactError("CORRUPT_CHECKPOINT", "checkpoint values are invalid")
        decoded[name] = tensor
    with torch.no_grad():
        live = dict(model.named_parameters())
        for name, tensor in decoded.items():
            live[name].copy_(tensor)


def _retained_records(result: PreparationResult) -> tuple[Any, ...]:
    return tuple(
        record for partition in result.partitions for record in partition.records
    )


def build_artifact_manifest(
    *,
    artifact_id: str,
    content: bytes | bytearray,
    model_config: NativeModelConfig,
    training_config: TrainingConfig,
    result: PreparationResult,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig,
) -> ArtifactManifest:
    """Build a manifest for checkpoint bytes from authoritative lineage objects."""
    if not isinstance(artifact_id, str):
        raise ArtifactError("INVALID_INPUT", "artifact identifier is invalid")
    if not isinstance(content, (bytes, bytearray)):
        raise ArtifactError("INVALID_INPUT", "checkpoint content is invalid")
    if not isinstance(result, PreparationResult):
        raise ArtifactError("INVALID_INPUT", "preparation result is invalid")
    model_cfg = _checked_model_config(model_config)
    train_cfg = _checked_training_config(training_config)
    tokenizer_cfg = _checked_tokenizer_config(tokenizer_config)
    if not isinstance(vocabulary, Vocabulary):
        raise ArtifactError("INVALID_INPUT", "vocabulary is invalid")
    manifest = result.dataset_manifest
    if manifest.authorization_kind != "synthetic-test-only":
        raise ArtifactError("UNSUPPORTED_SCOPE", "dataset scope is not supported")
    if manifest.operation != "training":
        raise ArtifactError(
            "OPERATION_NOT_PERMITTED", "dataset operation is not training"
        )
    try:
        verify_vocabulary(vocabulary, tokenizer_config=tokenizer_cfg)
    except Exception as exc:
        raise ArtifactError(
            "HASH_MISMATCH", "vocabulary integrity check failed"
        ) from exc
    digest = content_digest(bytes(content))
    model_hash = _canonical_hash_fn(_model_canonical_dict(model_cfg))
    tokenizer_hash = _canonical_hash_fn(_tokenizer_canonical_dict(tokenizer_cfg))
    if tokenizer_hash != vocabulary.metadata.tokenizer_config_hash:
        raise ArtifactError(
            "INCOMPATIBLE_TOKENIZER", "tokenizer configuration does not match"
        )
    if model_cfg.vocab_size != vocabulary.metadata.vocabulary_size:
        raise ArtifactError(
            "INCOMPATIBLE_VOCABULARY", "model vocabulary size does not match"
        )
    parameter_count = _estimate_model_params(model_cfg)
    candidate = ArtifactManifest(
        manifest_version=ARTIFACT_MANIFEST_VERSION,
        artifact_type=ARTIFACT_TYPE_MODEL_CHECKPOINT,
        artifact_id=artifact_id,
        content_digest=digest,
        checkpoint_format=CHECKPOINT_FORMAT,
        checkpoint_format_version=CHECKPOINT_FORMAT_VERSION,
        model_version=model_cfg.model_version,
        architecture=model_cfg.architecture,
        model_config_hash=model_hash,
        parameter_count=parameter_count,
        training_config_hash=train_cfg.configuration_hash(),
        training_seed=train_cfg.seed,
        model_init_seed=model_cfg.init_seed,
        dataset_id=manifest.dataset_id,
        dataset_integrity_hash=manifest.record_integrity_hash,
        split_assignment_hash=result.split_manifest.assignment_hash,
        vocabulary_hash=vocabulary.metadata.vocabulary_hash,
        tokenizer_config_hash=tokenizer_hash,
        data_scope="synthetic-test-only",
        manifest_digest="0" * 64,
    )
    return candidate.model_copy(
        update={"manifest_digest": _manifest_digest_for(candidate)}
    )


def verify_artifact(
    *,
    content: bytes | bytearray,
    manifest: ArtifactManifest,
    model_config: NativeModelConfig,
    training_config: TrainingConfig,
    result: PreparationResult,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig,
) -> dict[str, Any]:
    """Independently verify checkpoint bytes against a manifest and lineage.

    Returns the parsed checkpoint header on success. Never trusts a
    copied digest: both digests are recomputed.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise ArtifactError("INVALID_INPUT", "checkpoint content is invalid")
    if not isinstance(manifest, ArtifactManifest):
        raise ArtifactError("INVALID_INPUT", "artifact manifest is invalid")
    # Precise codes for bypass-constructed manifests: inspect raw
    # field values before schema revalidation (which would report a
    # generic INVALID_MANIFEST).
    raw_fields = manifest.__dict__
    if raw_fields.get("artifact_type", ARTIFACT_TYPE_MODEL_CHECKPOINT) != (
        ARTIFACT_TYPE_MODEL_CHECKPOINT
    ):
        raise ArtifactError("WRONG_ARTIFACT_TYPE", "artifact type is not supported")
    if raw_fields.get("manifest_version", ARTIFACT_MANIFEST_VERSION) != (
        ARTIFACT_MANIFEST_VERSION
    ):
        raise ArtifactError(
            "UNSUPPORTED_VERSION", "artifact manifest version is not supported"
        )
    if raw_fields.get("data_scope", "synthetic-test-only") != "synthetic-test-only":
        raise ArtifactError("UNSUPPORTED_SCOPE", "artifact scope is not supported")
    checked_manifest = _checked_manifest(manifest)
    if checked_manifest.checkpoint_format != CHECKPOINT_FORMAT:
        raise ArtifactError("UNSUPPORTED_FORMAT", "checkpoint format is not supported")
    if checked_manifest.checkpoint_format_version != CHECKPOINT_FORMAT_VERSION:
        raise ArtifactError(
            "UNSUPPORTED_VERSION", "checkpoint format version is not supported"
        )
    if not isinstance(result, PreparationResult):
        raise ArtifactError("INVALID_INPUT", "preparation result is invalid")
    if not isinstance(vocabulary, Vocabulary):
        raise ArtifactError("INVALID_INPUT", "vocabulary is invalid")
    model_cfg = _checked_model_config(model_config)
    train_cfg = _checked_training_config(training_config)
    tokenizer_cfg = _checked_tokenizer_config(tokenizer_config)

    # 1. Manifest integrity first: recompute, never trust.
    if _manifest_digest_for(checked_manifest) != checked_manifest.manifest_digest:
        raise ArtifactError(
            "MANIFEST_DIGEST_MISMATCH", "manifest digest does not match"
        )

    # 2. Content digest from actual bytes.
    raw = bytes(content)
    if hashlib.sha256(raw).hexdigest() != checked_manifest.content_digest:
        raise ArtifactError("HASH_MISMATCH", "artifact content digest does not match")

    # 3. Checkpoint structure before lineage: rejects pickle/foreign bytes.
    header = parse_checkpoint_header(raw)

    # 3b. Bind the checkpoint to the authoritative model configuration:
    # architecture, version, embedded fingerprint, and complete
    # parameter layout derived from the config — not merely the count.
    if header["architecture"] != model_cfg.architecture:
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint architecture does not match"
        )
    if header["model_version"] != model_cfg.model_version:
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint model version does not match"
        )
    if header["model_config_hash"] != _model_fingerprint(model_cfg):
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint configuration does not match"
        )
    expected_layout = _expected_layout(model_cfg)
    header_layout = {
        name: list(entry["shape"]) for name, entry in header["parameters"].items()
    }
    if header_layout != expected_layout:
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "checkpoint layout does not match the configuration"
        )

    # 4. Lineage cross-checks against authoritative objects.
    if _canonical_hash_fn(_model_canonical_dict(model_cfg)) != (
        checked_manifest.model_config_hash
    ):
        raise ArtifactError("INCOMPATIBLE_MODEL", "model configuration does not match")
    if model_cfg.init_seed != checked_manifest.model_init_seed:
        raise ArtifactError("INCOMPATIBLE_MODEL", "model seed does not match")
    if _estimate_model_params(model_cfg) != checked_manifest.parameter_count:
        raise ArtifactError(
            "INCOMPATIBLE_MODEL", "model parameter count does not match"
        )
    if header["parameter_count"] != checked_manifest.parameter_count:
        raise ArtifactError("INCOMPATIBLE_MODEL", "checkpoint parameters do not match")
    if train_cfg.configuration_hash() != checked_manifest.training_config_hash:
        raise ArtifactError(
            "INCOMPATIBLE_TRAINING", "training configuration does not match"
        )
    if train_cfg.seed != checked_manifest.training_seed:
        raise ArtifactError("INCOMPATIBLE_TRAINING", "training seed does not match")
    dataset_manifest = result.dataset_manifest
    if dataset_manifest.authorization_kind != "synthetic-test-only":
        raise ArtifactError("UNSUPPORTED_SCOPE", "dataset scope is not supported")
    if dataset_manifest.operation != "training":
        raise ArtifactError(
            "OPERATION_NOT_PERMITTED", "dataset operation is not training"
        )
    if dataset_manifest.dataset_id != checked_manifest.dataset_id:
        raise ArtifactError("INCOMPATIBLE_DATASET", "dataset identity does not match")
    records = _retained_records(result)
    try:
        verify_split(result.split_manifest, records)
    except DatasetPreparationError as exc:
        raise ArtifactError(
            "SPLIT_INTEGRITY_FAILURE", "dataset split integrity check failed"
        ) from exc
    recomputed = dataset_integrity_hash(records)
    if recomputed != checked_manifest.dataset_integrity_hash:
        raise ArtifactError(
            "INCOMPATIBLE_DATASET", "dataset integrity hash does not match"
        )
    manifest_hash = dataset_manifest.record_integrity_hash
    if manifest_hash != checked_manifest.dataset_integrity_hash:
        raise ArtifactError(
            "INCOMPATIBLE_DATASET", "dataset integrity hash does not match"
        )
    if result.split_manifest.assignment_hash != (
        checked_manifest.split_assignment_hash
    ):
        raise ArtifactError(
            "INCOMPATIBLE_DATASET", "split assignment hash does not match"
        )
    try:
        verify_vocabulary(vocabulary, tokenizer_config=tokenizer_cfg)
    except Exception as exc:
        raise ArtifactError(
            "HASH_MISMATCH", "vocabulary integrity check failed"
        ) from exc
    if vocabulary.metadata.vocabulary_hash != checked_manifest.vocabulary_hash:
        raise ArtifactError("INCOMPATIBLE_VOCABULARY", "vocabulary hash does not match")
    if model_cfg.vocab_size != vocabulary.metadata.vocabulary_size:
        raise ArtifactError(
            "INCOMPATIBLE_VOCABULARY", "model vocabulary size does not match"
        )
    if vocabulary.metadata.tokenizer_config_hash != (
        checked_manifest.tokenizer_config_hash
    ):
        raise ArtifactError("INCOMPATIBLE_TOKENIZER", "tokenizer hash does not match")
    if _canonical_hash_fn(_tokenizer_canonical_dict(tokenizer_cfg)) != (
        checked_manifest.tokenizer_config_hash
    ):
        raise ArtifactError(
            "INCOMPATIBLE_TOKENIZER", "tokenizer configuration does not match"
        )
    return header


def write_artifact_files(
    directory: Path | str,
    *,
    content: bytes | bytearray,
    manifest: ArtifactManifest,
) -> tuple[Path, Path]:
    """Write checkpoint bytes and manifest JSON to explicit local paths."""
    checked = _checked_manifest(manifest)
    if not isinstance(content, (bytes, bytearray)):
        raise ArtifactError("INVALID_INPUT", "checkpoint content is invalid")
    raw = bytes(content)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ArtifactError("INVALID_INPUT", "checkpoint content is too large")
    target_dir = Path(directory)
    if not target_dir.is_dir():
        raise ArtifactError("INVALID_INPUT", "artifact directory is invalid")
    ckpt_path = target_dir / f"{checked.artifact_id}.ckpt"
    manifest_path = target_dir / f"{checked.artifact_id}.manifest.json"
    ckpt_path.write_bytes(raw)
    manifest_path.write_text(
        json.dumps(checked.model_dump(mode="json"), sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return ckpt_path, manifest_path


def load_artifact_files(
    checkpoint_path: Path | str, manifest_path: Path | str
) -> tuple[bytes, ArtifactManifest]:
    """Read checkpoint bytes and manifest from explicit local paths.

    Applies size caps and schema validation; performs no network access
    and no deserialization beyond JSON parsing and schema checks.
    """
    ckpt = Path(checkpoint_path)
    man = Path(manifest_path)
    if not ckpt.is_file() or not man.is_file():
        raise ArtifactError("INVALID_INPUT", "artifact files are invalid")
    if ckpt.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ArtifactError("INVALID_INPUT", "checkpoint file is too large")
    raw = ckpt.read_bytes()
    try:
        payload = json.loads(man.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ArtifactError("INVALID_MANIFEST", "artifact manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise ArtifactError("INVALID_MANIFEST", "artifact manifest is invalid")
    try:
        manifest = ArtifactManifest.model_validate(payload)
    except Exception as exc:
        raise ArtifactError("INVALID_MANIFEST", "artifact manifest is invalid") from exc
    return raw, manifest

"""Task 211: integrity-checked local checkpoints for native model artifacts.

Artifacts are canonical JSON, bounded in size, bound to the exact vocabulary,
training dataset and model configuration, and written atomically. Loading is
offline and fails closed on corruption or identity mismatch.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictStr,
    ValidationError,
    model_validator,
)

from rop.native_model import NativeModelParameters
from rop.native_training import NativeTrainingReport
from rop.schemas.native_model import NativeModelConfig
from rop.tokenization import Vocabulary

ARTIFACT_CONTRACT_VERSION = "1"
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class NativeArtifactError(Exception):
    """Canonical, privacy-safe artifact failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


class NativeParameterPayload(BaseModel):
    """Strict, bounded JSON projection of trainable parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding: tuple[tuple[StrictFloat, ...], ...] = Field(
        min_length=2, max_length=100000
    )
    head_weight: tuple[tuple[StrictFloat, ...], ...] = Field(
        min_length=2, max_length=32
    )
    head_bias: tuple[StrictFloat, ...] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def _finite_and_rectangular(self) -> NativeParameterPayload:
        if not self.embedding or not self.embedding[0]:
            raise ValueError("embedding dimensions must be nonempty")
        width = len(self.embedding[0])
        if any(len(row) != width for row in self.embedding):
            raise ValueError("embedding rows must have equal dimensions")
        if any(len(row) != width for row in self.head_weight):
            raise ValueError("head rows must match embedding dimensions")
        values = [value for row in self.embedding for value in row]
        values.extend(value for row in self.head_weight for value in row)
        values.extend(self.head_bias)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("parameters must be finite")
        if len(self.head_weight) != len(self.head_bias):
            raise ValueError("head weights and bias must have matching labels")
        return self

    @classmethod
    def from_parameters(
        cls, parameters: NativeModelParameters
    ) -> NativeParameterPayload:
        return cls(
            embedding=parameters.embedding,
            head_weight=parameters.head_weight,
            head_bias=parameters.head_bias,
        )

    def to_parameters(self) -> NativeModelParameters:
        return NativeModelParameters(
            embedding=self.embedding,
            head_weight=self.head_weight,
            head_bias=self.head_bias,
        )


class NativeModelArtifact(BaseModel):
    """Versioned model payload with content and lineage hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    model_config_payload: NativeModelConfig
    dataset_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    training_report: NativeTrainingReport
    parameters: NativeParameterPayload
    artifact_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _lineage_and_shape(self) -> NativeModelArtifact:
        config = self.model_config_payload
        if len(self.parameters.embedding) != config.vocab_size:
            raise ValueError("embedding row count must match vocabulary size")
        if any(len(row) != config.embedding_dim for row in self.parameters.embedding):
            raise ValueError("embedding width must match configured dimension")
        if len(self.parameters.head_weight) != config.num_labels:
            raise ValueError("head row count must match configured labels")
        if len(self.parameters.head_bias) != config.num_labels:
            raise ValueError("head bias count must match configured labels")
        if self.training_report.model_version != config.model_version:
            raise ValueError("training report model version mismatch")
        if self.training_report.initialization_seed != config.initialization_seed:
            raise ValueError("training report initialization seed mismatch")
        if self.training_report.dataset_fingerprint != self.dataset_fingerprint:
            raise ValueError("training report dataset fingerprint mismatch")
        if self.training_report.vocabulary_hash != self.vocabulary_hash:
            raise ValueError("training report vocabulary hash mismatch")
        if (
            _parameter_hash(self.parameters.to_parameters())
            != self.training_report.parameters_hash
        ):
            raise ValueError("training report parameter hash mismatch")
        if self.artifact_hash != _artifact_hash(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        ):
            raise ValueError("artifact hash does not match contents")
        return self


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _parameter_hash(parameters: NativeModelParameters) -> str:
    payload = {
        "embedding": parameters.embedding,
        "head_weight": parameters.head_weight,
        "head_bias": parameters.head_bias,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _artifact_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def create_native_artifact(
    *,
    model_config: NativeModelConfig,
    parameters: NativeModelParameters,
    training_report: NativeTrainingReport,
    vocabulary: Vocabulary,
) -> NativeModelArtifact:
    """Build a self-verifying artifact; no filesystem access occurs."""
    if vocabulary.training_fingerprint != training_report.dataset_fingerprint:
        raise NativeArtifactError(
            "DATASET_FINGERPRINT_MISMATCH",
            "vocabulary and training report are detached",
        )
    if vocabulary.vocabulary_hash != training_report.vocabulary_hash:
        raise NativeArtifactError(
            "VOCABULARY_HASH_MISMATCH", "vocabulary and training report are detached"
        )
    payload: dict[str, object] = {
        "contract_version": ARTIFACT_CONTRACT_VERSION,
        "model_config_payload": model_config.model_dump(mode="json"),
        "dataset_fingerprint": training_report.dataset_fingerprint,
        "vocabulary_hash": vocabulary.vocabulary_hash,
        "training_report": training_report.model_dump(mode="json"),
        "parameters": NativeParameterPayload.from_parameters(parameters).model_dump(
            mode="json"
        ),
    }
    payload["artifact_hash"] = _artifact_hash(payload)
    try:
        return NativeModelArtifact.model_validate(payload)
    except ValidationError:
        raise NativeArtifactError(
            "ARTIFACT_CONTRACT_INVALID", "model artifact violates the strict contract"
        ) from None


def serialize_native_artifact(artifact: NativeModelArtifact) -> str:
    """Canonical serialization after all artifact integrity checks."""
    return _canonical_json(artifact.model_dump(mode="json"))


def save_native_artifact(artifact: NativeModelArtifact, path: str | Path) -> None:
    """Atomically save one verified artifact to a caller-selected local path."""
    target = Path(path)
    payload = serialize_native_artifact(artifact).encode("utf-8")
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise NativeArtifactError(
            "ARTIFACT_TOO_LARGE", "serialized artifact exceeds the supported size"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=target.parent, prefix=".rop-artifact-", delete=False
        ) as stream:
            temporary_name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    except OSError:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        raise NativeArtifactError(
            "ARTIFACT_WRITE_FAILED", "artifact could not be saved atomically"
        ) from None


def load_native_artifact(
    path: str | Path,
    *,
    expected_vocabulary: Vocabulary,
    expected_dataset_fingerprint: str,
) -> NativeModelArtifact:
    """Load an offline artifact and verify its hashes and external bindings."""
    try:
        target = Path(path)
        # Bound the read itself: a file that grows after any earlier size
        # check can never push more than MAX_ARTIFACT_BYTES + 1 bytes into
        # memory, and any read beyond the limit is rejected.
        with target.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise NativeArtifactError(
                "ARTIFACT_TOO_LARGE", "artifact exceeds the supported size"
            )
        payload = json.loads(raw.decode("utf-8"))
        artifact = NativeModelArtifact.model_validate(payload)
    except NativeArtifactError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
        ValueError,
    ):
        raise NativeArtifactError(
            "ARTIFACT_INVALID", "artifact is missing, corrupt, or violates its contract"
        ) from None
    if (
        artifact.vocabulary_hash != expected_vocabulary.vocabulary_hash
        or artifact.model_config_payload.vocab_size != len(expected_vocabulary.tokens)
    ):
        raise NativeArtifactError(
            "VOCABULARY_BINDING_MISMATCH",
            "artifact does not match the supplied vocabulary",
        )
    if (
        artifact.dataset_fingerprint != expected_dataset_fingerprint
        or artifact.dataset_fingerprint != expected_vocabulary.training_fingerprint
    ):
        raise NativeArtifactError(
            "DATASET_BINDING_MISMATCH",
            "artifact does not match the expected training dataset",
        )
    return artifact


__all__ = [
    "ARTIFACT_CONTRACT_VERSION",
    "MAX_ARTIFACT_BYTES",
    "NativeArtifactError",
    "NativeModelArtifact",
    "NativeParameterPayload",
    "create_native_artifact",
    "load_native_artifact",
    "save_native_artifact",
    "serialize_native_artifact",
]

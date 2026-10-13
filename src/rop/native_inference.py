"""Task 212: offline CPU inference from integrity-checked local artifacts.

This is a narrow label-suggestion adapter. It has no network/provider
boundary and cannot create trusted evidence, diagnoses, or certification.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

from rop.native_artifacts import NativeModelArtifact
from rop.native_model import NativeModel, NativeModelParameters
from rop.native_training import (
    NativeTrainingError,
    canonical_label_mapping,
    label_space_hash,
)
from rop.tokenization import Vocabulary, encode_text

MAX_LABELS = 32


class NativeInferenceError(Exception):
    """Canonical inference failure without raw input echo."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def _model_from_verified_parameters(
    artifact: NativeModelArtifact,
) -> NativeModel:
    """Build a model directly from verified artifact parameters.

    No random initialization is performed and no second embedding table is
    allocated. Shapes and finiteness are re-checked here as defense in depth
    even though the artifact contract already enforces them.
    """
    config = artifact.model_config_payload
    parameters: NativeModelParameters = artifact.parameters.to_parameters()
    dimension = config.embedding_dim
    if (
        len(parameters.embedding) != config.vocab_size
        or len(parameters.head_weight) != config.num_labels
        or len(parameters.head_bias) != config.num_labels
        or any(len(row) != dimension for row in parameters.embedding)
        or any(len(row) != dimension for row in parameters.head_weight)
    ):
        raise NativeInferenceError(
            "ARTIFACT_SHAPE_MISMATCH", "artifact parameters do not match the model"
        )
    values = (
        [value for row in parameters.embedding for value in row]
        + [value for row in parameters.head_weight for value in row]
        + list(parameters.head_bias)
    )
    if not all(math.isfinite(value) for value in values):
        raise NativeInferenceError(
            "ARTIFACT_PARAMETER_INVALID", "artifact parameters must be finite"
        )
    model = NativeModel.__new__(NativeModel)
    model.config = config
    model.parameters = parameters
    return model


class NativeInferenceConfig(BaseModel):
    """Strict bounds for one local inference request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    top_k: StrictInt = Field(ge=1, le=MAX_LABELS)
    minimum_probability: StrictFloat = Field(ge=0.0, le=1.0)


class NativeLabelScore(BaseModel):
    """One untrusted advisory label score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr = Field(min_length=1, max_length=100)
    probability: StrictFloat = Field(ge=0.0, le=1.0)


class NativeInferenceResponse(BaseModel):
    """Privacy-safe inference result; explicitly advisory only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    model_version: StrictStr = Field(min_length=1, max_length=32)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    scores: tuple[NativeLabelScore, ...] = Field(max_length=MAX_LABELS)
    advisory_only: StrictBool = True

    @field_validator("scores")
    @classmethod
    def _canonical_scores(
        cls, value: tuple[NativeLabelScore, ...]
    ) -> tuple[NativeLabelScore, ...]:
        labels = [score.label for score in value]
        if len(set(labels)) != len(labels):
            raise ValueError("scores must use unique labels")
        if value != tuple(
            sorted(value, key=lambda item: (-item.probability, item.label))
        ):
            raise ValueError(
                "scores must be sorted by probability descending and label ascending"
            )
        return value


class NativeLocalInference:
    """Small deterministic CPU inference wrapper around one verified artifact."""

    def __init__(
        self,
        *,
        artifact: NativeModelArtifact,
        vocabulary: Vocabulary,
        labels: tuple[str, ...],
        config: NativeInferenceConfig,
    ) -> None:
        if artifact.vocabulary_hash != vocabulary.vocabulary_hash:
            raise NativeInferenceError(
                "VOCABULARY_BINDING_MISMATCH", "artifact and vocabulary do not match"
            )
        if artifact.model_config_payload.vocab_size != len(vocabulary.tokens):
            raise NativeInferenceError(
                "VOCABULARY_SHAPE_MISMATCH", "vocabulary size does not match the model"
            )
        if len(labels) != artifact.model_config_payload.num_labels:
            raise NativeInferenceError(
                "LABEL_SPACE_MISMATCH", "label count does not match the model output"
            )
        if len(set(labels)) != len(labels) or any(
            not isinstance(label, str) or not label.strip() for label in labels
        ):
            raise NativeInferenceError(
                "LABEL_SPACE_INVALID", "labels must be unique and nonblank"
            )
        # Head output i is always the i-th label of the canonical (sorted)
        # label space used by training; any other order would silently
        # relabel probabilities, so it is rejected rather than remapped.
        try:
            canonical_label_mapping(tuple(labels))
        except NativeTrainingError:
            raise NativeInferenceError(
                "LABEL_ORDER_NONCANONICAL",
                "labels must follow the canonical training label order",
            ) from None
        # Sortedness alone is not an identity: a different sorted label set of
        # the same size would silently relabel the head outputs. Require the
        # exact label space the artifact was trained against.
        if label_space_hash(tuple(labels)) != artifact.training_report.label_space_hash:
            raise NativeInferenceError(
                "LABEL_SPACE_BINDING_MISMATCH",
                "labels are not the label space the artifact was trained on",
            )
        self._artifact = artifact
        self._vocabulary = vocabulary
        self._labels = labels
        self._config = config
        self._model = _model_from_verified_parameters(artifact)

    @property
    def artifact(self) -> NativeModelArtifact:
        """The verified artifact bound at construction (read-only, immutable)."""
        return self._artifact

    @property
    def artifact_hash(self) -> str:
        """Hash of the already verified bound artifact (read-only)."""
        return self._artifact.artifact_hash

    @property
    def vocabulary(self) -> Vocabulary:
        """The vocabulary bound at construction (read-only)."""
        return self._vocabulary

    @property
    def labels(self) -> tuple[str, ...]:
        """The canonical label space bound to the artifact (read-only)."""
        return self._labels

    def predict_text(self, text: str) -> NativeInferenceResponse:
        """Tokenize and score locally; raw text is not retained or echoed."""
        if not isinstance(text, str):
            raise NativeInferenceError("INVALID_TEXT", "input text must be a string")
        try:
            token_ids = encode_text(text, self._vocabulary)
            if not token_ids:
                # Scores for no input would be the model's bias prior, not an
                # evaluation of the input; fail closed instead.
                raise NativeInferenceError(
                    "EMPTY_INPUT", "input produced no tokens and cannot be scored"
                )
            probabilities = self._model.predict(token_ids)
        except NativeInferenceError:
            raise
        except (ValueError, TypeError):
            raise NativeInferenceError(
                "INFERENCE_INPUT_INVALID", "input could not be processed"
            ) from None
        if len(probabilities) != len(self._labels) or not all(
            math.isfinite(value) and 0.0 <= value <= 1.0 for value in probabilities
        ):
            raise NativeInferenceError(
                "INFERENCE_OUTPUT_INVALID",
                "model output violates the bounded score contract",
            )
        candidates = sorted(
            (
                NativeLabelScore(label=label, probability=float(probability))
                for label, probability in zip(self._labels, probabilities, strict=True)
                if probability >= self._config.minimum_probability
            ),
            key=lambda item: (-item.probability, item.label),
        )[: self._config.top_k]
        return NativeInferenceResponse(
            model_version=self._artifact.model_config_payload.model_version,
            vocabulary_hash=self._vocabulary.vocabulary_hash,
            scores=tuple(candidates),
        )


__all__ = [
    "NativeInferenceConfig",
    "NativeInferenceError",
    "NativeInferenceResponse",
    "NativeLabelScore",
    "NativeLocalInference",
]

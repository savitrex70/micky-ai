"""Task 212: local CPU inference runtime implementation.

In-process CPU execution only. The caller explicitly selects a local
Task 211 checkpoint artifact; the runtime verifies it through the
Task 211 contracts, loads it with the approved safe checkpoint API
into an explicitly constructed Task 209 model, and runs bounded
forward inference with gradients disabled.

Model output is untrusted raw output. It is never evidence, never a
finding, and never a trusted result. No training, no checkpoint
writing, no serving loop, and no automatic artifact handling live
here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from rop.artifacts.checkpoints import (
    ArtifactError,
    apply_checkpoint_to_model,
    load_artifact_files,
    verify_artifact,
)
from rop.native_model.native_model import (
    NativeModel,
    NativeModelError,
    initialize_model,
)
from rop.schemas.artifact import ArtifactManifest
from rop.schemas.dataset_manifest import PreparationResult
from rop.schemas.inference import (
    MAX_INFERENCE_BATCH_SIZE,
    InferenceErrorCode,
    InferenceRequest,
    InferenceResult,
    InferenceSelection,
)
from rop.schemas.native_model import NativeModelConfig
from rop.schemas.tokenizer import PAD_ID, TokenizerConfig, Vocabulary
from rop.schemas.training import TrainingConfig

__all__ = [
    "InferenceError",
    "InferenceSession",
    "load_inference_session",
    "run_inference",
]


class InferenceError(Exception):
    """A typed inference failure with a safe, generic message."""

    def __init__(self, code: InferenceErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


@dataclass(frozen=True)
class InferenceSession:
    """A verified, loaded CPU inference session (Task 212).

    Created only by ``load_inference_session`` from an explicitly
    selected local artifact. Holds the model in evaluation mode on
    CPU; the runtime never trains through it.
    """

    model: NativeModel
    artifact_id: str
    vocab_size: int
    max_seq_len: int
    num_classes: int


def _checked_selection(selection: InferenceSelection) -> InferenceSelection:
    if not isinstance(selection, InferenceSelection):
        raise InferenceError("INVALID_INPUT", "artifact selection is invalid")
    try:
        return InferenceSelection.model_validate(selection.model_dump())
    except Exception as exc:
        raise InferenceError("INVALID_INPUT", "artifact selection is invalid") from exc


def _checked_output(
    logits: object, *, batch_size: int, num_classes: int
) -> list[list[float]]:
    """Validate raw model output before touching tensor properties.

    Requires a dense strided float32 CPU tensor of shape
    ``(batch_size, num_classes)`` with finite values. Anything else —
    including ``None``, non-tensor objects, unsupported dtypes or
    layouts, wrong rank or dimensions, and NaN or infinity — is
    rejected with ``INVALID_OUTPUT``. Invalid output is never cast,
    reshaped, clamped, or repaired.
    """
    if not isinstance(logits, torch.Tensor):
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    if logits.dtype != torch.float32:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    if logits.layout != torch.strided:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    if logits.dim() != 2:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    if logits.shape[0] != batch_size or logits.shape[1] != num_classes:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    try:
        finite = bool(torch.all(torch.isfinite(logits)).item())
    except Exception:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid") from None
    if not finite:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    try:
        values = logits.detach().cpu().tolist()
    except Exception:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid") from None
    if not isinstance(values, list) or len(values) != batch_size:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
    checked: list[list[float]] = []
    for row in values:
        if not isinstance(row, list) or len(row) != num_classes:
            raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
        checked_row: list[float] = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, float):
                raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
            if not math.isfinite(value):
                raise InferenceError("INVALID_OUTPUT", "inference output is invalid")
            checked_row.append(value)
        checked.append(checked_row)
    return checked


def _checked_request(request: InferenceRequest | Mapping[str, Any]) -> InferenceRequest:
    try:
        if isinstance(request, InferenceRequest):
            return InferenceRequest.model_validate(request.model_dump())
        if isinstance(request, Mapping):
            return InferenceRequest.model_validate(dict(request))
    except Exception as exc:
        raise InferenceError("INVALID_REQUEST", "inference request is invalid") from exc
    raise InferenceError("INVALID_REQUEST", "inference request is invalid")


def _artifact_error_code(exc: ArtifactError) -> str:
    if exc.code in (
        "INVALID_MANIFEST",
        "CORRUPT_CHECKPOINT",
        "HASH_MISMATCH",
        "MANIFEST_DIGEST_MISMATCH",
        "UNSUPPORTED_VERSION",
        "UNSUPPORTED_FORMAT",
        "WRONG_ARTIFACT_TYPE",
        "MISSING_METADATA",
    ):
        return "ARTIFACT_INVALID"
    return "INCOMPATIBLE_ARTIFACT"


def load_inference_session(
    *,
    selection: InferenceSelection,
    model_config: NativeModelConfig,
    training_config: TrainingConfig,
    result: PreparationResult,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig,
) -> InferenceSession:
    """Verify and load an explicitly selected local artifact for CPU inference.

    Steps, in order: validate the selection and lineage object types;
    read the checkpoint and manifest files from the given local paths;
    verify them with the Task 211 contract against the supplied
    authoritative lineage; construct the Task 209 model from its
    validated configuration; apply the checkpoint with the approved
    safe API; confirm CPU float32 parameters; leave the model in
    evaluation mode.
    """
    checked_selection = _checked_selection(selection)
    if not isinstance(model_config, NativeModelConfig):
        raise InferenceError("INVALID_INPUT", "model configuration is invalid")
    if not isinstance(training_config, TrainingConfig):
        raise InferenceError("INVALID_INPUT", "training configuration is invalid")
    if not isinstance(result, PreparationResult):
        raise InferenceError("INVALID_INPUT", "preparation result is invalid")
    if not isinstance(vocabulary, Vocabulary):
        raise InferenceError("INVALID_INPUT", "vocabulary is invalid")
    if not isinstance(tokenizer_config, TokenizerConfig):
        raise InferenceError("INVALID_INPUT", "tokenizer configuration is invalid")
    try:
        content, manifest = load_artifact_files(
            Path(checked_selection.checkpoint_path),
            Path(checked_selection.manifest_path),
        )
    except ArtifactError as exc:
        if exc.code == "INVALID_INPUT":
            raise InferenceError(
                "ARTIFACT_MISSING", "inference artifact is unavailable"
            ) from None
        raise InferenceError(
            "ARTIFACT_INVALID", "inference artifact is invalid"
        ) from None
    try:
        verify_artifact(
            content=content,
            manifest=manifest,
            model_config=model_config,
            training_config=training_config,
            result=result,
            vocabulary=vocabulary,
            tokenizer_config=tokenizer_config,
        )
    except ArtifactError as exc:
        raise InferenceError(
            _artifact_error_code(exc), "inference artifact is not accepted"
        ) from None
    try:
        model = initialize_model(model_config)
    except NativeModelError:
        raise InferenceError(
            "INCOMPATIBLE_ARTIFACT", "inference artifact is not accepted"
        ) from None
    try:
        apply_checkpoint_to_model(model, content)
    except ArtifactError as exc:
        raise InferenceError(
            _artifact_error_code(exc), "inference artifact is not accepted"
        ) from None
    for param in model.parameters():
        if param.dtype != torch.float32 or param.device.type != "cpu":
            raise InferenceError(
                "INCOMPATIBLE_ARTIFACT", "inference artifact is not accepted"
            )
    model.eval()
    checked_manifest: ArtifactManifest = manifest
    return InferenceSession(
        model=model,
        artifact_id=checked_manifest.artifact_id,
        vocab_size=model_config.vocab_size,
        max_seq_len=model_config.max_seq_len,
        num_classes=model_config.num_classes,
    )


def run_inference(
    session: InferenceSession,
    request: InferenceRequest | Mapping[str, Any],
) -> InferenceResult:
    """Run one bounded CPU forward pass and return raw model output.

    The request is validated before any tensor is allocated. Token IDs
    outside the vocabulary are rejected, never clamped. Output rank,
    dimensions, and finiteness are checked at the boundary. Model
    parameters are never updated.
    """
    if not isinstance(session, InferenceSession):
        raise InferenceError("INVALID_INPUT", "inference session is invalid")
    checked = _checked_request(request)
    sequences = checked.token_id_sequences
    if len(sequences) > MAX_INFERENCE_BATCH_SIZE:
        raise InferenceError("RESOURCE_LIMIT", "inference batch is too large")
    width = 0
    for sequence in sequences:
        if len(sequence) > session.max_seq_len:
            raise InferenceError("RESOURCE_LIMIT", "inference sequence is too long")
        width = max(width, len(sequence))
        for token_id in sequence:
            if not 0 <= token_id < session.vocab_size:
                raise InferenceError("INVALID_REQUEST", "inference request is invalid")
    rows = [
        list(sequence) + [PAD_ID] * (width - len(sequence)) for sequence in sequences
    ]
    token_ids = torch.tensor(rows, dtype=torch.long)
    model = session.model
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            try:
                raw_output = model(token_ids)
            except NativeModelError:
                raise InferenceError(
                    "INVALID_REQUEST", "inference request is invalid"
                ) from None
            except Exception:
                raise InferenceError(
                    "INVALID_OUTPUT", "inference output is invalid"
                ) from None
    finally:
        if was_training:
            model.train()
    values = _checked_output(
        raw_output, batch_size=len(sequences), num_classes=session.num_classes
    )
    try:
        return InferenceResult(
            artifact_id=session.artifact_id,
            batch_size=len(sequences),
            sequence_length=width,
            num_classes=session.num_classes,
            logits=tuple(tuple(row) for row in values),
        )
    except Exception as exc:
        raise InferenceError("INVALID_OUTPUT", "inference output is invalid") from exc

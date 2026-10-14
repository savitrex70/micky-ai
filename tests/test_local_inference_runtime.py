"""Task 212: local CPU inference runtime tests.

Synthetic fixtures only, temporary files only. No network access,
external serving, downloads, clinical data, or GPU.
"""

from __future__ import annotations

import re

import pytest
import torch
from pydantic import ValidationError

from rop.dataset_preparation import compose_test_registry, prepare_dataset
from rop.dataset_preparation.pipeline import partition_records
from rop.inference import (
    InferenceError,
    load_inference_session,
    run_inference,
)
from rop.inference import runtime as runtime_module
from rop.native_model import initialize_model
from rop.schemas.inference import (
    InferenceRequest,
    InferenceSelection,
)
from rop.schemas.native_model import NativeModelConfig
from rop.schemas.tokenizer import TokenizerConfig
from rop.schemas.training import TrainingConfig
from rop.tokenizer import build_vocabulary, encode_text

REGISTRY = compose_test_registry(
    [
        {
            "source_id": "synthetic-test-infer-1",
            "authorization_version": "1.0",
            "origin_description": "In-repo synthetic fixture source",
            "license_basis": "repo-internal-synthetic",
            "intended_purpose": "native-training",
            "permitted_operations": ("training",),
            "status": "APPROVED",
            "approval_reference": "approval-infer-1",
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
                "source_id": "synthetic-test-infer-1",
                "group_id": f"g-{index:02d}",
                "label": "alpha" if index % 2 == 1 else "beta",
                "content_text": f"synthetic {word} text sample {index}",
                "provenance_ref": "synthetic-in-repo-fixture-1",
            }
        )
    return prepare_dataset(
        records=records,
        authorizations=REGISTRY,
        dataset_id="synthetic-native-infer",
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


def _write_fixture(tmp_path, artifact_id="synthetic-infer-001"):
    from rop.artifacts import (
        build_artifact_manifest,
        build_checkpoint_bytes,
        write_artifact_files,
    )

    model = initialize_model(_MODEL_CONFIG)
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
    ckpt_path, manifest_path = write_artifact_files(
        tmp_path, content=content, manifest=manifest
    )
    return content, manifest, ckpt_path, manifest_path


def _load_session(tmp_path, artifact_id="synthetic-infer-001"):
    _, _, ckpt_path, manifest_path = _write_fixture(tmp_path, artifact_id)
    return load_inference_session(
        selection=InferenceSelection(
            checkpoint_path=str(ckpt_path), manifest_path=str(manifest_path)
        ),
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )


def _snapshot(model) -> dict[str, torch.Tensor]:
    return {name: p.detach().clone() for name, p in model.named_parameters()}


def test_successful_cpu_inference(tmp_path) -> None:
    session = _load_session(tmp_path)
    assert session.artifact_id == "synthetic-infer-001"
    for param in session.model.parameters():
        assert param.device.type == "cpu"
        assert param.dtype == torch.float32
    assert session.model.training is False
    request = InferenceRequest(token_id_sequences=[[2, 3, 4], [5, 6]])
    result = run_inference(session, request)
    assert result.artifact_id == "synthetic-infer-001"
    assert result.batch_size == 2
    assert result.sequence_length == 3
    assert result.num_classes == 2
    assert len(result.logits) == 2
    assert all(len(row) == 2 for row in result.logits)
    assert all(
        isinstance(v, float) and v == v and abs(v) != float("inf")
        for row in result.logits
        for v in row
    )
    expected = session.model(torch.tensor([[2, 3, 4], [5, 6, 0]], dtype=torch.long))
    got = torch.tensor(result.logits)
    assert got.dtype == torch.float32
    assert torch.allclose(got, expected.detach().cpu(), rtol=1e-6, atol=1e-7)


def test_repeatable_inference(tmp_path) -> None:
    session = _load_session(tmp_path)
    request = InferenceRequest(token_id_sequences=[[2, 3], [4, 5, 6]])
    first = run_inference(session, request)
    second = run_inference(session, request)
    assert first == second


def test_missing_checkpoint_and_manifest(tmp_path) -> None:
    _, _, ckpt_path, manifest_path = _write_fixture(tmp_path)
    missing = tmp_path / "absent.ckpt"
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(missing), manifest_path=str(manifest_path)
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "ARTIFACT_MISSING"
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(ckpt_path),
                manifest_path=str(tmp_path / "absent.json"),
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "ARTIFACT_MISSING"


def test_missing_artifact_before_model_construction(tmp_path, monkeypatch) -> None:
    def _fail(config):
        raise AssertionError("model must not be constructed for missing files")

    monkeypatch.setattr(runtime_module, "initialize_model", _fail)
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(tmp_path / "absent.ckpt"),
                manifest_path=str(tmp_path / "absent.json"),
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "ARTIFACT_MISSING"


def test_corrupt_checkpoint_rejected(tmp_path) -> None:
    content, _, ckpt_path, manifest_path = _write_fixture(tmp_path)
    tampered = bytearray(content)
    tampered[-1] ^= 0x01
    ckpt_path.write_bytes(bytes(tampered))
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(ckpt_path), manifest_path=str(manifest_path)
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "ARTIFACT_INVALID"


def test_altered_manifest_rejected(tmp_path) -> None:
    import json

    _, _, ckpt_path, manifest_path = _write_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifact_id"] = "synthetic-forged-id"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(ckpt_path), manifest_path=str(manifest_path)
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code in ("ARTIFACT_INVALID", "INCOMPATIBLE_ARTIFACT")


def test_content_hash_mismatch_rejected(tmp_path) -> None:
    from rop.artifacts import build_artifact_manifest, build_checkpoint_bytes

    model_a = initialize_model(_MODEL_CONFIG)
    content_a = build_checkpoint_bytes(model_a)
    model_b = initialize_model(_MODEL_CONFIG.model_copy(update={"init_seed": 43}))
    content_b = build_checkpoint_bytes(model_b)
    assert content_a != content_b
    manifest_a = build_artifact_manifest(
        artifact_id="synthetic-infer-001",
        content=content_a,
        model_config=_MODEL_CONFIG,
        training_config=_TRAINING_CONFIG,
        result=_RESULT,
        vocabulary=_VOCABULARY,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    from rop.artifacts import write_artifact_files

    ckpt_path, manifest_path = write_artifact_files(
        tmp_path, content=content_b, manifest=manifest_a
    )
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(ckpt_path), manifest_path=str(manifest_path)
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "ARTIFACT_INVALID"


def test_incompatible_lineage_rejected(tmp_path) -> None:
    session_base = _load_session(tmp_path, "synthetic-infer-base")
    assert session_base.artifact_id == "synthetic-infer-base"

    # Different model configuration.
    other_config = _MODEL_CONFIG.model_copy(update={"num_heads": 8})
    _, _, ckpt_path, manifest_path = _write_fixture(tmp_path, "synthetic-infer-x")
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(ckpt_path), manifest_path=str(manifest_path)
            ),
            model_config=other_config,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_ARTIFACT"

    # Different vocabulary object.
    _, _, ckpt_path2, manifest_path2 = _write_fixture(tmp_path, "synthetic-infer-y")
    other_words = tuple(f"otherword{i}" for i in range(12))
    records = []
    for index, word in enumerate(other_words, start=1):
        records.append(
            {
                "record_id": f"s-{index:02d}",
                "source_id": "synthetic-test-infer-1",
                "group_id": f"j-{index:02d}",
                "label": "alpha" if index % 2 == 1 else "beta",
                "content_text": f"synthetic {word} text sample {index}",
                "provenance_ref": "synthetic-in-repo-fixture-1",
            }
        )
    other_result = prepare_dataset(
        records=records,
        authorizations=REGISTRY,
        dataset_id="synthetic-native-infer",
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
    other_vocab = build_vocabulary(other_result, tokenizer_config=_TOKENIZER_CONFIG)
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(ckpt_path2), manifest_path=str(manifest_path2)
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=other_vocab,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert exc.value.code == "INCOMPATIBLE_ARTIFACT"


def test_malformed_requests_rejected(tmp_path) -> None:
    session = _load_session(tmp_path)
    vocab_size = session.vocab_size
    bad_requests = [
        "not-a-request",
        {"token_id_sequences": []},
        {"token_id_sequences": [[]]},
        {"token_id_sequences": [[-1, 2]]},
        {"token_id_sequences": [[vocab_size]]},
        {"token_id_sequences": [[99999]]},
        {"token_id_sequences": [[1.5, 2]]},
        {"token_id_sequences": [[True, 2]]},
        {"token_id_sequences": [["3", 2]]},
        {"token_id_sequences": [[2] * (session.max_seq_len + 1)]},
        {"token_id_sequences": [[2]] * 33},
    ]
    for bad in bad_requests:
        with pytest.raises(InferenceError) as exc:
            run_inference(session, bad)  # type: ignore[arg-type]
        assert exc.value.code in ("INVALID_REQUEST", "RESOURCE_LIMIT")
    with pytest.raises(InferenceError) as exc:
        run_inference("not-a-session", {"token_id_sequences": [[2]]})  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_INPUT"


def test_request_schema_strictness() -> None:
    with pytest.raises(ValidationError):
        InferenceRequest(token_id_sequences="abc")
    with pytest.raises(ValidationError):
        InferenceRequest(token_id_sequences=[[1]], extra_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        InferenceSelection(
            checkpoint_path="https://example.invalid/model.ckpt",
            manifest_path="manifest.json",
        )
    with pytest.raises(ValidationError):
        InferenceSelection(checkpoint_path="", manifest_path="manifest.json")


def test_non_finite_output_rejected(tmp_path, monkeypatch) -> None:
    session = _load_session(tmp_path)

    def _nan_forward(token_ids):
        return torch.full((token_ids.shape[0], 2), float("nan"))

    monkeypatch.setattr(session.model, "forward", _nan_forward)
    with pytest.raises(InferenceError) as exc:
        run_inference(session, {"token_id_sequences": [[2, 3]]})
    assert exc.value.code == "INVALID_OUTPUT"


def test_inference_does_not_update_parameters(tmp_path) -> None:
    session = _fresh_session(tmp_path)
    before = _snapshot(session.model)
    assert torch.is_grad_enabled() is True
    run_inference(session, {"token_id_sequences": [[2, 3, 4]]})
    run_inference(session, {"token_id_sequences": [[5]]})
    after = _snapshot(session.model)
    assert set(before) == set(after)
    for name in before:
        assert torch.equal(before[name], after[name])
    assert torch.is_grad_enabled() is True


def _fresh_session(tmp_path):
    return _load_session(tmp_path, "synthetic-infer-snap")


def test_cpu_only_no_gpu_requirement(tmp_path) -> None:
    session = _load_session(tmp_path)
    for param in session.model.parameters():
        assert param.device.type == "cpu"
    result = run_inference(session, {"token_id_sequences": [[2]]})
    assert result.batch_size == 1


def test_no_cuda_reference_in_runtime_source() -> None:
    import inspect

    source = inspect.getsource(runtime_module)
    assert "cuda" not in source.lower()


def test_deterministic_path_without_artifact() -> None:
    vocabulary = build_vocabulary(_RESULT, tokenizer_config=_TOKENIZER_CONFIG)
    ids = encode_text(
        "synthetic one text",
        vocabulary=vocabulary,
        tokenizer_config=_TOKENIZER_CONFIG,
    )
    assert len(ids) > 0
    assert all(0 <= i < vocabulary.metadata.vocabulary_size for i in ids)


def test_no_network_provider_or_fetching_in_runtime_source() -> None:
    import inspect

    for module in (runtime_module,):
        source = inspect.getsource(module).lower()
        for term in (
            "socket",
            "urllib",
            "requests",
            "openai",
            "anthropic",
            "gemini",
            "ollama",
            "transformers",
            "huggingface",
            "from_pretrained",
            "torch.hub",
            "provider",
            "download",
            "fetch",
        ):
            assert re.search(r"\b" + re.escape(term) + r"\b", source) is None
        assert "os.environ" not in source
        assert "getenv" not in source
        assert "environ" not in source


def test_remote_selection_rejected_without_access() -> None:
    with pytest.raises(ValidationError):
        InferenceSelection(
            checkpoint_path="https://example.invalid/model.ckpt",
            manifest_path="https://example.invalid/model.manifest.json",
        )


def test_safe_errors_hide_sensitive_values(tmp_path) -> None:
    session = _load_session(tmp_path)
    with pytest.raises(InferenceError) as exc:
        run_inference(session, {"token_id_sequences": [[99999]]})
    assert str(exc.value) == "[INVALID_REQUEST] inference request is invalid"
    assert "99999" not in str(exc.value)
    with pytest.raises(InferenceError) as exc:
        load_inference_session(
            selection=InferenceSelection(
                checkpoint_path=str(tmp_path / "absent.ckpt"),
                manifest_path=str(tmp_path / "absent.json"),
            ),
            model_config=_MODEL_CONFIG,
            training_config=_TRAINING_CONFIG,
            result=_RESULT,
            vocabulary=_VOCABULARY,
            tokenizer_config=_TOKENIZER_CONFIG,
        )
    assert str(exc.value) == "[ARTIFACT_MISSING] inference artifact is unavailable"

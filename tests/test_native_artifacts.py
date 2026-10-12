"""Task 211 artifact integrity tests using synthetic-only fixtures."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import rop.native_artifacts as native_artifacts
from rop.native_artifacts import (
    NativeArtifactError,
    NativeModelArtifact,
    create_native_artifact,
    load_native_artifact,
    save_native_artifact,
    serialize_native_artifact,
)
from tests.test_native_training import _fixture, _train


def _artifact():
    fixture = _fixture()
    vocabulary, model_config = fixture[2], fixture[3]
    result = _train(fixture)
    return (
        create_native_artifact(
            model_config=model_config,
            parameters=result.parameters,
            training_report=result.report,
            vocabulary=vocabulary,
        ),
        vocabulary,
    )


def test_artifact_serialization_is_canonical_and_round_trips(tmp_path):
    artifact, vocabulary = _artifact()
    assert serialize_native_artifact(artifact) == serialize_native_artifact(artifact)
    path = tmp_path / "model.json"
    save_native_artifact(artifact, path)
    loaded = load_native_artifact(
        path,
        expected_vocabulary=vocabulary,
        expected_dataset_fingerprint=artifact.dataset_fingerprint,
    )
    assert loaded == artifact


def test_artifact_loader_rejects_tampered_parameters(tmp_path):
    artifact, vocabulary = _artifact()
    payload = json.loads(serialize_native_artifact(artifact))
    payload["parameters"]["head_bias"][0] = 0.75
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NativeArtifactError) as caught:
        load_native_artifact(
            path,
            expected_vocabulary=vocabulary,
            expected_dataset_fingerprint=artifact.dataset_fingerprint,
        )
    assert caught.value.code == "ARTIFACT_INVALID"


def test_artifact_loader_rejects_detached_dataset_fingerprint(tmp_path):
    artifact, vocabulary = _artifact()
    path = tmp_path / "model.json"
    save_native_artifact(artifact, path)
    with pytest.raises(NativeArtifactError) as caught:
        load_native_artifact(
            path,
            expected_vocabulary=vocabulary,
            expected_dataset_fingerprint="0" * 64,
        )
    assert caught.value.code == "DATASET_BINDING_MISMATCH"


def test_artifact_loader_rejects_missing_file_without_leaking_path(tmp_path):
    artifact, vocabulary = _artifact()
    with pytest.raises(NativeArtifactError) as caught:
        load_native_artifact(
            tmp_path / "missing.json",
            expected_vocabulary=vocabulary,
            expected_dataset_fingerprint=artifact.dataset_fingerprint,
        )
    assert caught.value.code == "ARTIFACT_INVALID"
    assert str(tmp_path) not in str(caught.value)


def _load(path, artifact, vocabulary):
    return load_native_artifact(
        path,
        expected_vocabulary=vocabulary,
        expected_dataset_fingerprint=artifact.dataset_fingerprint,
    )


def _resealed(artifact, mutate):
    """Mutate a payload and recompute artifact_hash so only the contract can object."""
    payload = json.loads(serialize_native_artifact(artifact))
    mutate(payload)
    payload.pop("artifact_hash")
    payload["artifact_hash"] = native_artifacts._artifact_hash(payload)
    return payload


def test_seed_mismatch_is_rejected_even_when_hashes_and_shapes_are_consistent(tmp_path):
    artifact, vocabulary = _artifact()

    def mutate(payload):
        payload["training_report"]["initialization_seed"] += 1

    payload = _resealed(artifact, mutate)
    with pytest.raises(ValidationError) as caught:
        NativeModelArtifact.model_validate(payload)
    assert "initialization seed" in str(caught.value)
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(NativeArtifactError) as loaded:
        _load(path, artifact, vocabulary)
    assert loaded.value.code == "ARTIFACT_INVALID"


def test_creation_rejects_a_report_with_a_different_seed():
    artifact, vocabulary = _artifact()
    report = artifact.training_report.model_copy(
        update={"initialization_seed": artifact.training_report.initialization_seed + 1}
    )
    with pytest.raises(NativeArtifactError) as caught:
        create_native_artifact(
            model_config=artifact.model_config_payload,
            parameters=artifact.parameters.to_parameters(),
            training_report=report,
            vocabulary=vocabulary,
        )
    assert caught.value.code == "ARTIFACT_CONTRACT_INVALID"


def test_oversized_content_is_rejected_at_the_read_boundary(tmp_path, monkeypatch):
    artifact, vocabulary = _artifact()
    path = tmp_path / "model.json"
    save_native_artifact(artifact, path)
    size = path.stat().st_size
    monkeypatch.setattr(native_artifacts, "MAX_ARTIFACT_BYTES", size - 1)
    with pytest.raises(NativeArtifactError) as caught:
        _load(path, artifact, vocabulary)
    assert caught.value.code == "ARTIFACT_TOO_LARGE"
    monkeypatch.setattr(native_artifacts, "MAX_ARTIFACT_BYTES", size)
    assert _load(path, artifact, vocabulary) == artifact


def test_read_limit_holds_even_if_stat_reports_a_small_size(tmp_path, monkeypatch):
    artifact, vocabulary = _artifact()
    path = tmp_path / "grown.json"
    path.write_bytes(b" " * 4096)
    monkeypatch.setattr(native_artifacts, "MAX_ARTIFACT_BYTES", 1024)
    real_stat = type(path).stat

    class _Small:
        st_size = 1

    def lying_stat(self, *args, **kwargs):
        return _Small() if self == path else real_stat(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "stat", lying_stat)
    with pytest.raises(NativeArtifactError) as caught:
        _load(path, artifact, vocabulary)
    assert caught.value.code == "ARTIFACT_TOO_LARGE"


def test_reader_never_pulls_more_than_limit_plus_one_byte(tmp_path, monkeypatch):
    artifact, vocabulary = _artifact()
    path = tmp_path / "huge.json"
    path.write_bytes(b"x" * 100)
    monkeypatch.setattr(native_artifacts, "MAX_ARTIFACT_BYTES", 10)
    requested = []
    real_open = type(path).open

    def spying_open(self, *args, **kwargs):
        stream = real_open(self, *args, **kwargs)
        real_read = stream.read

        class _Spy:
            def read(self, size=-1):
                requested.append(size)
                return real_read(size)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                stream.close()
                return False

        return _Spy()

    monkeypatch.setattr(type(path), "open", spying_open)
    with pytest.raises(NativeArtifactError):
        _load(path, artifact, vocabulary)
    assert requested == [11]


@pytest.mark.parametrize("keep", [0, 1, 40, 200])
def test_truncated_json_is_rejected_safely(tmp_path, keep):
    artifact, vocabulary = _artifact()
    path = tmp_path / "truncated.json"
    path.write_bytes(serialize_native_artifact(artifact).encode("utf-8")[:keep])
    with pytest.raises(NativeArtifactError) as caught:
        _load(path, artifact, vocabulary)
    assert caught.value.code == "ARTIFACT_INVALID"
    assert "head_bias" not in str(caught.value)


def test_non_utf8_and_non_object_content_is_rejected(tmp_path):
    artifact, vocabulary = _artifact()
    for name, content in (("bin.json", b"\xff\xfe\x00"), ("list.json", b"[1,2,3]")):
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(NativeArtifactError) as caught:
            _load(path, artifact, vocabulary)
        assert caught.value.code == "ARTIFACT_INVALID"


def test_wrong_vocabulary_is_rejected(tmp_path):
    artifact, _ = _artifact()
    other_vocabulary = _fixture(train_count=5)[2]
    path = tmp_path / "model.json"
    save_native_artifact(artifact, path)
    with pytest.raises(NativeArtifactError) as caught:
        load_native_artifact(
            path,
            expected_vocabulary=other_vocabulary,
            expected_dataset_fingerprint=artifact.dataset_fingerprint,
        )
    assert caught.value.code == "VOCABULARY_BINDING_MISMATCH"


@pytest.mark.parametrize("field", ["embedding", "head_weight"])
def test_malformed_parameter_shapes_are_rejected_even_when_resealed(tmp_path, field):
    artifact, vocabulary = _artifact()

    def mutate(payload):
        payload["parameters"][field][-1] = payload["parameters"][field][-1][:-1]

    path = tmp_path / "shape.json"
    path.write_text(json.dumps(_resealed(artifact, mutate)), encoding="utf-8")
    with pytest.raises(NativeArtifactError) as caught:
        _load(path, artifact, vocabulary)
    assert caught.value.code == "ARTIFACT_INVALID"


def test_missing_embedding_row_is_rejected_even_when_resealed(tmp_path):
    artifact, vocabulary = _artifact()

    def mutate(payload):
        payload["parameters"]["embedding"].pop()

    path = tmp_path / "rows.json"
    path.write_text(json.dumps(_resealed(artifact, mutate)), encoding="utf-8")
    with pytest.raises(NativeArtifactError) as caught:
        _load(path, artifact, vocabulary)
    assert caught.value.code == "ARTIFACT_INVALID"


def test_saved_files_are_canonical_and_leave_no_temporary_files(tmp_path):
    artifact, _ = _artifact()
    path = tmp_path / "model.json"
    save_native_artifact(artifact, path)
    assert path.read_text(encoding="utf-8") == serialize_native_artifact(artifact)
    assert [item.name for item in tmp_path.iterdir()] == ["model.json"]

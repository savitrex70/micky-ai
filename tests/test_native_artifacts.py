"""Task 211 artifact integrity tests using synthetic-only fixtures."""

from __future__ import annotations

import json

import pytest

from rop.native_artifacts import (
    NativeArtifactError,
    create_native_artifact,
    load_native_artifact,
    save_native_artifact,
    serialize_native_artifact,
)
from rop.native_model import NativeModel
from rop.native_training import train_native_model
from test_native_training import _splits_and_manifest


def _artifact():
    splits, manifest, vocabulary, model_config, examples, training_config = _splits_and_manifest()
    result = train_native_model(
        model_config=model_config,
        training_config=training_config,
        initial_parameters=NativeModel.reproducible(model_config),
        examples=examples,
        splits=splits,
        manifest=manifest,
        vocabulary=vocabulary,
    )
    return create_native_artifact(
        model_config=model_config,
        parameters=result.parameters,
        training_report=result.report,
        vocabulary=vocabulary,
    ), vocabulary


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

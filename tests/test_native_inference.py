"""Task 212 local inference tests; fixtures are synthetic and offline."""

from __future__ import annotations

import pytest

from rop.native_inference import NativeInferenceConfig, NativeInferenceError, NativeLocalInference
from test_native_artifacts import _artifact


def _inference():
    artifact, vocabulary = _artifact()
    return NativeLocalInference(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=("ANION_GAP_HIGH", "POTASSIUM_HIGH"),
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )


def test_local_inference_is_deterministic_and_bounded():
    inference = _inference()
    first = inference.predict_text("synthetic token input")
    second = inference.predict_text("synthetic token input")
    assert first == second
    assert first.advisory_only is True
    assert len(first.scores) <= 2
    assert all(0.0 <= score.probability <= 1.0 for score in first.scores)


def test_local_inference_does_not_echo_input_text():
    secret = "private sentinel phrase"
    response = _inference().predict_text(secret)
    assert secret not in response.model_dump_json()


def test_local_inference_rejects_label_count_mismatch():
    artifact, vocabulary = _artifact()
    with pytest.raises(NativeInferenceError) as caught:
        NativeLocalInference(
            artifact=artifact,
            vocabulary=vocabulary,
            labels=("ONLY_ONE",),
            config=NativeInferenceConfig(top_k=1, minimum_probability=0.0),
        )
    assert caught.value.code == "LABEL_SPACE_MISMATCH"


def test_inference_config_rejects_unbounded_options():
    with pytest.raises(ValueError):
        NativeInferenceConfig(top_k=33, minimum_probability=0.0)
    with pytest.raises(ValueError):
        NativeInferenceConfig(top_k=1, minimum_probability=2.0)

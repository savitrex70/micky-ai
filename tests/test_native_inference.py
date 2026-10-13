"""Task 212 local inference tests; fixtures are synthetic and offline."""

from __future__ import annotations

import pytest

from rop.native_inference import (
    NativeInferenceConfig,
    NativeInferenceError,
    NativeLocalInference,
)
from rop.native_model import NativeModel
from rop.tokenization import encode_text
from tests.test_native_artifacts import _artifact
from tests.test_native_training import LABEL_SPACE, _fixture

CANONICAL = LABEL_SPACE


def _build(*, labels=CANONICAL, top_k=2, minimum_probability=0.0, artifact_pair=None):
    artifact, vocabulary = artifact_pair or _artifact()
    return NativeLocalInference(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=labels,
        config=NativeInferenceConfig(
            top_k=top_k, minimum_probability=minimum_probability
        ),
    )


def _inference():
    return _build()


def _code_of_construction(**kwargs) -> str:
    with pytest.raises(NativeInferenceError) as caught:
        _build(**kwargs)
    return caught.value.code


def test_local_inference_is_deterministic_and_bounded():
    inference = _inference()
    first = inference.predict_text("synthetic token input")
    second = inference.predict_text("synthetic token input")
    assert first == second
    assert first.advisory_only is True
    assert len(first.scores) <= 2
    assert all(0.0 <= score.probability <= 1.0 for score in first.scores)


def test_output_is_bounded_by_top_k():
    response = _build(top_k=1).predict_text("synthetic token input")
    assert len(response.scores) == 1


def test_local_inference_does_not_echo_input_text():
    secret = "private sentinel phrase"
    response = _inference().predict_text(secret)
    assert secret not in response.model_dump_json()


def test_local_inference_rejects_label_count_mismatch():
    assert _code_of_construction(labels=("ONLY_ONE",)) == "LABEL_SPACE_MISMATCH"


# --- label order binding ------------------------------------------------------


def test_canonical_label_order_succeeds_and_assigns_probabilities_to_head_order():
    artifact, vocabulary = _artifact()
    expected = NativeModel(artifact.model_config_payload)
    expected.parameters = artifact.parameters.to_parameters()
    response = _build(artifact_pair=(artifact, vocabulary)).predict_text(
        "synthetic token"
    )
    by_label = {score.label: score.probability for score in response.scores}
    assert set(by_label) == set(CANONICAL)
    # Head output i belongs to the i-th canonical label.
    encoded = encode_text("synthetic token", vocabulary)
    probabilities = expected.predict(encoded)
    assert by_label[CANONICAL[0]] == pytest.approx(probabilities[0])
    assert by_label[CANONICAL[1]] == pytest.approx(probabilities[1])


def test_noncanonical_label_order_is_rejected_rather_than_relabelled():
    swapped = tuple(reversed(CANONICAL))
    assert _code_of_construction(labels=swapped) == "LABEL_ORDER_NONCANONICAL"


def test_duplicate_blank_and_nonstring_labels_are_rejected():
    assert _code_of_construction(labels=("A_LABEL", "A_LABEL")) == "LABEL_SPACE_INVALID"
    assert _code_of_construction(labels=("A_LABEL", " ")) == "LABEL_SPACE_INVALID"


# --- empty input --------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "!!! ... ---"])
def test_empty_after_tokenization_input_is_rejected_even_with_zero_threshold(text):
    inference = _build(minimum_probability=0.0)
    with pytest.raises(NativeInferenceError) as caught:
        inference.predict_text(text)
    assert caught.value.code == "EMPTY_INPUT"


def test_non_string_input_is_rejected_safely():
    with pytest.raises(NativeInferenceError) as caught:
        _inference().predict_text(123)  # type: ignore[arg-type]
    assert caught.value.code == "INVALID_TEXT"


def test_errors_never_echo_input_text():
    with pytest.raises(NativeInferenceError) as caught:
        _inference().predict_text("   ")
    assert "   " not in str(caught.value).split("]", 1)[1].strip()


# --- construction without random initialization ---------------------------------


def test_construction_does_not_initialize_a_random_model(monkeypatch):
    artifact_pair = _artifact()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("random initialization must not run")

    monkeypatch.setattr(NativeModel, "_initialize", staticmethod(forbidden))
    inference = _build(artifact_pair=artifact_pair)
    response = inference.predict_text("synthetic token input")
    assert len(response.scores) == 2


def test_inference_uses_the_artifact_parameters_exactly():
    artifact, vocabulary = _artifact()
    inference = _build(artifact_pair=(artifact, vocabulary))
    assert inference._model.parameters == artifact.parameters.to_parameters()


# --- binding failures ----------------------------------------------------------


def test_vocabulary_mismatch_is_rejected():
    artifact, _ = _artifact()
    other_vocabulary = _fixture(train_count=5)[2]
    assert (
        _code_of_construction(artifact_pair=(artifact, other_vocabulary))
        == "VOCABULARY_BINDING_MISMATCH"
    )


def test_artifact_vocabulary_shape_mismatch_is_rejected():
    artifact, vocabulary = _artifact()
    smaller = vocabulary.model_copy(update={"tokens": vocabulary.tokens[:-1]})
    assert (
        _code_of_construction(artifact_pair=(artifact, smaller))
        == "VOCABULARY_SHAPE_MISMATCH"
    )


def test_inference_config_rejects_unbounded_options():
    with pytest.raises(ValueError):
        NativeInferenceConfig(top_k=33, minimum_probability=0.0)
    with pytest.raises(ValueError):
        NativeInferenceConfig(top_k=1, minimum_probability=2.0)


# --- Task 212 correction: exact label-set binding and artifact identity ----------


def test_a_different_sorted_label_set_of_the_same_size_is_rejected():
    # Sorted, unique, nonblank, and the right cardinality: only the label-set
    # identity can tell this apart from the trained label space.
    other = ("ANION_GAP_HIGH", "SODIUM_LOW")
    assert len(other) == len(CANONICAL) and other == tuple(sorted(other))
    assert _code_of_construction(labels=other) == "LABEL_SPACE_BINDING_MISMATCH"
    renamed = ("A_LABEL", "B_LABEL")
    assert _code_of_construction(labels=renamed) == "LABEL_SPACE_BINDING_MISMATCH"


def test_a_mismatched_recorded_label_hash_fails_for_the_same_artifact_identity():
    artifact, vocabulary = _artifact()
    report = artifact.training_report.model_copy(update={"label_space_hash": "3" * 64})
    detached = artifact.model_copy(update={"training_report": report})
    # Same artifact version, vocabulary and labels; only the recorded hash differs.
    assert detached.model_config_payload == artifact.model_config_payload
    assert detached.vocabulary_hash == artifact.vocabulary_hash
    assert (
        _code_of_construction(artifact_pair=(detached, vocabulary))
        == "LABEL_SPACE_BINDING_MISMATCH"
    )


def test_the_exact_trained_label_set_is_still_accepted():
    artifact, _ = _artifact()
    inference = _build()
    assert inference.labels == CANONICAL == artifact.training_report.label_map


def test_artifact_hash_property_matches_the_bound_artifact():
    artifact, vocabulary = _artifact()
    inference = _build(artifact_pair=(artifact, vocabulary))
    assert inference.artifact_hash == artifact.artifact_hash
    assert inference.artifact is artifact
    assert inference.vocabulary is vocabulary


def test_artifact_identity_accessors_are_read_only():
    inference = _inference()
    original = inference.artifact_hash
    for name in ("artifact", "artifact_hash", "vocabulary", "labels"):
        with pytest.raises(AttributeError):
            setattr(inference, name, getattr(inference, name))
    assert inference.artifact_hash == original


def test_the_bound_artifact_cannot_be_mutated_through_the_accessor():
    from pydantic import ValidationError

    inference = _inference()
    with pytest.raises(ValidationError):
        inference.artifact.artifact_hash = "0" * 64  # type: ignore[misc]
    assert inference.artifact_hash == inference.artifact.artifact_hash


def test_inference_still_rejects_empty_input_and_does_not_echo_text():
    inference = _inference()
    for blank in ("", "   ", "...", "!!!"):
        with pytest.raises(NativeInferenceError) as caught:
            inference.predict_text(blank)
        assert caught.value.code == "EMPTY_INPUT"

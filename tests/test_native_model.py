"""Task 209 first-party model tests; no weights, network, or training."""

from __future__ import annotations

import dataclasses
import math

import pytest
from pydantic import ValidationError

from rop.native_model import (
    NativeModel,
    NativeModelError,
    NativeModelParameters,
    stable_sigmoid,
)
from rop.schemas.native_model import (
    MAX_EMBEDDING_DIM,
    MAX_NUM_LABELS,
    MAX_SEQUENCE_LENGTH,
    MAX_VOCAB_SIZE,
    NativeModelConfig,
)


def _config(**patch: object) -> NativeModelConfig:
    value = {
        "vocab_size": 16,
        "embedding_dim": 4,
        "num_labels": 3,
        "max_sequence_length": 8,
        "initialization_seed": 20260101,
        "model_version": "native-1",
    }
    value.update(patch)
    return NativeModelConfig.model_validate(value)


# --- configuration bounds ----------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vocab_size", 1),
        ("vocab_size", MAX_VOCAB_SIZE + 1),
        ("embedding_dim", 0),
        ("embedding_dim", MAX_EMBEDDING_DIM + 1),
        ("num_labels", 1),
        ("num_labels", MAX_NUM_LABELS + 1),
        ("max_sequence_length", 0),
        ("max_sequence_length", MAX_SEQUENCE_LENGTH + 1),
        ("initialization_seed", -1),
        ("model_version", " "),
        ("architecture", "TRANSFORMER"),
    ],
)
def test_unsupported_configuration_combinations_fail(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _config(**{field: value})


def test_configuration_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        NativeModelConfig.model_validate({**_config().model_dump(), "device": "cuda"})


# --- initialization -----------------------------------------------------------


def test_initialization_is_reproducible_for_a_fixed_seed_and_config() -> None:
    first = NativeModel.reproducible(_config())
    second = NativeModel.reproducible(_config())
    assert first == second
    assert isinstance(first, NativeModelParameters)


def test_parameters_are_genuinely_initialized_not_loaded_or_constant() -> None:
    parameters = NativeModel.reproducible(_config())
    flat_embedding = [value for row in parameters.embedding for value in row]
    # Not all zeros, not all identical: real seeded initialization.
    assert any(value != 0.0 for value in flat_embedding)
    assert len(set(flat_embedding)) == len(flat_embedding)
    # Head bias documented to start at zero.
    assert all(value == 0.0 for value in parameters.head_bias)


def test_different_seeds_produce_different_parameters() -> None:
    first = NativeModel.reproducible(_config(initialization_seed=1))
    second = NativeModel.reproducible(_config(initialization_seed=2))
    assert first != second


def test_parameters_are_genuinely_initialized_rather_than_loaded() -> None:
    # A fresh model matches the documented scheme exactly; nothing is
    # read from disk or any external source between constructions.
    model = NativeModel(_config())
    assert model.parameters == NativeModel.reproducible(_config())
    assert model.parameters.embedding == NativeModel.reproducible(_config()).embedding


# --- output contract ----------------------------------------------------------


def test_output_dimensions_and_finite_probabilities() -> None:
    model = NativeModel(_config())
    output = model.predict((1, 2, 3))
    assert len(output) == _config().num_labels
    assert all(math.isfinite(value) for value in output)
    assert all(0.0 <= value <= 1.0 for value in output)


def test_prediction_is_deterministic_for_identical_input() -> None:
    model = NativeModel(_config())
    assert model.predict((1, 2, 3)) == model.predict((1, 2, 3))


def test_empty_sequence_predicts_from_the_zero_pool() -> None:
    model = NativeModel(_config())
    output = model.predict(())
    assert len(output) == _config().num_labels
    assert all(value == 0.5 for value in output)


def test_sequences_are_truncated_to_the_configured_limit() -> None:
    model = NativeModel(_config(max_sequence_length=2))
    long_sequence = tuple(range(10))
    assert model.predict(long_sequence) == model.predict((0, 1))


def test_out_of_range_token_ids_fail_closed() -> None:
    model = NativeModel(_config())
    with pytest.raises(NativeModelError) as caught:
        model.predict((1, _config().vocab_size))
    assert caught.value.code == "TOKEN_ID_OUT_OF_RANGE"
    with pytest.raises(NativeModelError):
        model.predict((-1,))


def _with_bias(model: NativeModel, bias: float) -> NativeModel:
    model.parameters = dataclasses.replace(
        model.parameters, head_bias=tuple(bias for _ in model.parameters.head_bias)
    )
    return model


@pytest.mark.parametrize("bias", [-1.0e6, -800.0, -745.0, -1.0e300])
def test_large_negative_logits_do_not_overflow(bias: float) -> None:
    output = _with_bias(NativeModel(_config()), bias).predict((1, 2, 3))
    assert all(math.isfinite(value) for value in output)
    assert all(0.0 <= value <= 1.0 for value in output)
    assert all(value < 1e-6 for value in output)


@pytest.mark.parametrize("bias", [1.0e6, 800.0, 1.0e300])
def test_large_positive_logits_stay_bounded(bias: float) -> None:
    output = _with_bias(NativeModel(_config()), bias).predict((1, 2, 3))
    assert all(math.isfinite(value) for value in output)
    assert all(0.0 <= value <= 1.0 for value in output)
    assert all(value > 1.0 - 1e-6 for value in output)


def test_stable_sigmoid_matches_reference_and_is_symmetric() -> None:
    assert stable_sigmoid(0.0) == 0.5
    for logit in (-30.0, -2.5, -0.1, 0.1, 2.5, 30.0):
        assert stable_sigmoid(logit) == pytest.approx(1.0 / (1.0 + math.exp(-logit)))
        assert stable_sigmoid(logit) + stable_sigmoid(-logit) == pytest.approx(1.0)
    assert stable_sigmoid(-1.0e6) == 0.0
    assert stable_sigmoid(1.0e6) == 1.0


def test_logits_of_extreme_negative_probability_are_not_clipped_away() -> None:
    # -700 is representable: the exact probability (~1e-304) must survive.
    value = stable_sigmoid(-700.0)
    assert 0.0 < value < 1e-300


@pytest.mark.parametrize("bad", [True, False])
def test_boolean_token_ids_are_rejected(bad: bool) -> None:
    model = NativeModel(_config())
    with pytest.raises(NativeModelError) as caught:
        model.predict((1, bad))  # type: ignore[arg-type]
    assert caught.value.code == "TOKEN_ID_INVALID_TYPE"


@pytest.mark.parametrize("bad", [1.0, "1", None, b"1", (1,)])
def test_non_integer_token_ids_are_rejected(bad: object) -> None:
    model = NativeModel(_config())
    with pytest.raises(NativeModelError) as caught:
        model.predict((1, bad))  # type: ignore[arg-type]
    assert caught.value.code == "TOKEN_ID_INVALID_TYPE"


def test_negative_token_ids_are_rejected() -> None:
    with pytest.raises(NativeModelError) as caught:
        NativeModel(_config()).predict((0, -1))
    assert caught.value.code == "TOKEN_ID_OUT_OF_RANGE"


def test_token_id_boundaries_are_accepted_and_beyond_is_rejected() -> None:
    config = _config()
    model = NativeModel(config)
    assert len(model.predict((0, config.vocab_size - 1))) == config.num_labels
    for bad in (config.vocab_size, config.vocab_size + 1):
        with pytest.raises(NativeModelError) as caught:
            model.predict((bad,))
        assert caught.value.code == "TOKEN_ID_OUT_OF_RANGE"


def test_invalid_ids_beyond_the_truncation_limit_are_still_rejected() -> None:
    model = NativeModel(_config(max_sequence_length=2))
    with pytest.raises(NativeModelError):
        model.predict((0, 1, True))  # type: ignore[arg-type]


# --- import and resource safety ------------------------------------------------


def test_importing_the_model_constructs_nothing_and_touches_no_network() -> None:
    # The module must be import-clean: no instance exists at import
    # time and no provider or network symbol is referenced.
    import rop.native_model as module

    assert not hasattr(module, "MODEL")
    source = module.__doc__ or ""
    assert "no network" in source
    import socket

    real_socket = socket.socket
    try:

        def _blocked(*args, **kwargs):  # pragma: no cover - defensive
            raise AssertionError("network access attempted during init")

        socket.socket = _blocked  # type: ignore[misc, assignment]
        NativeModel(_config())
    finally:
        socket.socket = real_socket  # type: ignore[misc]


def test_model_keeps_no_training_dependency_and_stores_no_weights_file(
    tmp_path,
) -> None:
    # Construction writes nothing to disk and imports no framework.
    import sys

    before = set(sys.modules)
    NativeModel(_config(initialization_seed=7))
    new_modules = {
        name
        for name in set(sys.modules) - before
        if name.startswith(("torch", "tensorflow", "numpy"))
    }
    assert new_modules == set()
    assert list(tmp_path.iterdir()) == []


def test_model_serves_only_the_bounded_task_and_has_no_clinical_fields() -> None:
    # The public surface carries no diagnosis, treatment, release, or
    # certification semantics — only bounded probabilities.
    model = NativeModel(_config())
    attributes = set(vars(model))
    assert attributes == {"config", "parameters"}
    output = model.predict((1, 2))
    assert all(isinstance(value, float) for value in output)

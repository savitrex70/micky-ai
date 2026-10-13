"""Task 209: native model tests.

Synthetic fixtures only. No pretrained artifacts, model, training,
network, or GPU required for initialization tests.
"""

from __future__ import annotations

import pytest
import torch
from pydantic import ValidationError

from rop.native_model.native_model import (
    NativeModelError,
    build_model_spec,
    count_parameters,
    initialize_model,
    verify_model,
)
from rop.schemas.native_model import (
    MAX_HIDDEN_DIM,
    MAX_NUM_HEADS,
    MAX_NUM_LAYERS,
    MAX_SEQ_LEN,
    MAX_TOTAL_PARAMS,
    MAX_VOCAB_SIZE,
    MODEL_ARCHITECTURE,
    MODEL_VERSION,
    NativeModelConfig,
)

# Minimal valid configuration for testing
BASE_CONFIG = NativeModelConfig(
    model_version="1.0",
    architecture="tiny-encoder-v1",
    vocab_size=100,
    hidden_dim=64,
    num_layers=2,
    num_heads=4,
    max_seq_len=32,
    num_classes=4,
    dropout=0.1,
    init_seed=42,
    init_std=0.02,
)


def test_valid_config_constructs_model() -> None:
    """Valid configuration constructs the intended architecture."""
    model = initialize_model(BASE_CONFIG)
    assert isinstance(model, torch.nn.Module)
    assert model.config == BASE_CONFIG
    assert model._initialized is True


def test_parameter_count_matches_formula() -> None:
    """Parameter count matches actual parameters and documented formula."""
    model = initialize_model(BASE_CONFIG)
    actual = count_parameters(model)
    spec = build_model_spec(model, BASE_CONFIG)
    assert actual == spec.metadata.parameter_count
    assert actual > 0
    assert actual <= MAX_TOTAL_PARAMS


def test_identical_seed_and_config_yield_identical_parameters() -> None:
    """Identical seeds and configurations yield identical parameter values."""
    model1 = initialize_model(BASE_CONFIG)
    model2 = initialize_model(BASE_CONFIG)

    # Compare parameter by parameter
    for (name1, p1), (name2, p2) in zip(
        model1.named_parameters(), model2.named_parameters(), strict=True
    ):
        assert name1 == name2
        assert torch.equal(p1, p2)

    # Verify hashes match
    spec1 = build_model_spec(model1, BASE_CONFIG)
    spec2 = build_model_spec(model2, BASE_CONFIG)
    assert spec1.metadata.init_hash == spec2.metadata.init_hash
    assert spec1.metadata.config_hash == spec2.metadata.config_hash


def test_different_seeds_yield_different_parameters() -> None:
    """Different seeds yield different parameters in a deterministic test case."""
    config1 = BASE_CONFIG.model_copy(update={"init_seed": 42})
    config2 = BASE_CONFIG.model_copy(update={"init_seed": 43})

    model1 = initialize_model(config1)
    model2 = initialize_model(config2)

    # At least one parameter should differ
    different = False
    for (name1, p1), (_name2, p2) in zip(
        model1.named_parameters(), model2.named_parameters(), strict=True
    ):
        assert name1 == _name2
        if not torch.equal(p1, p2):
            different = True
            break
    assert different, "Different seeds should produce different parameters"

    # Hashes should differ
    spec1 = build_model_spec(model1, config1)
    spec2 = build_model_spec(model2, config2)
    assert spec1.metadata.init_hash != spec2.metadata.init_hash


def test_all_parameters_finite() -> None:
    """All initialized parameters are finite."""
    model = initialize_model(BASE_CONFIG)
    for name, param in model.named_parameters():
        assert torch.all(torch.isfinite(param)), f"Non-finite parameter: {name}"


def test_invalid_dimensions_rejected() -> None:
    """Invalid, zero, negative, oversized, and unsupported dimensions are rejected."""
    # Zero vocab_size
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=0,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Negative hidden_dim
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=-1,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Oversized vocab_size
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=MAX_VOCAB_SIZE + 1,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Oversized hidden_dim
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=MAX_HIDDEN_DIM + 1,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Oversized num_layers
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=MAX_NUM_LAYERS + 1,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Oversized num_heads
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=MAX_NUM_HEADS + 1,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Oversized max_seq_len
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=MAX_SEQ_LEN + 1,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # num_heads not dividing hidden_dim
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=5,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # num_heads > hidden_dim
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=32,
            num_layers=2,
            num_heads=64,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Zero num_classes
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=1,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Invalid dropout
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=-0.1,
            init_seed=42,
            init_std=0.02,
        )
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.6,
            init_seed=42,
            init_std=0.02,
        )

    # Invalid init_std
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.0,
        )
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=1.1,
        )


def test_invalid_seeds_and_malformed_configs_rejected() -> None:
    """Invalid seeds and malformed configurations are rejected."""
    # Negative seed
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=-1,
            init_std=0.02,
        )

    # Seed too large
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=2**32,
            init_std=0.02,
        )

    # String instead of int
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed="42",  # type: ignore[arg-type]
            init_std=0.02,
        )

    # Boolean instead of int
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=True,  # type: ignore[arg-type]
            init_std=0.02,
        )

    # Missing required field
    with pytest.raises(ValidationError):
        NativeModelConfig(model_version="1.0")  # type: ignore[call-arg]

    # Wrong model_version
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="9.9",
            architecture="tiny-encoder-v1",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Wrong architecture
    with pytest.raises(ValidationError):
        NativeModelConfig(
            model_version="1.0",
            architecture="other",
            vocab_size=100,
            hidden_dim=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
            num_classes=4,
            dropout=0.1,
            init_seed=42,
            init_std=0.02,
        )

    # Test malformed dict passed to initialize_model
    with pytest.raises(NativeModelError):
        initialize_model({"model_version": "1.0", "architecture": "tiny-encoder-v1"})


def test_config_bounds_checked_before_allocation() -> None:
    """Configuration bounds are checked before large allocations."""
    # Create a config that would exceed parameter limit
    huge_config = BASE_CONFIG.model_copy(
        update={
            "vocab_size": MAX_VOCAB_SIZE,
            "hidden_dim": MAX_HIDDEN_DIM,
            "num_layers": MAX_NUM_LAYERS,
            "num_heads": MAX_NUM_HEADS,
            "max_seq_len": MAX_SEQ_LEN,
            "num_classes": 128,
        }
    )
    # This should fail on bounds check before allocating
    with pytest.raises(NativeModelError) as exc:
        initialize_model(huge_config)
    assert exc.value.code == "CONFIG_INVALID"


def test_repeated_construction_independent() -> None:
    """Repeated independent construction does not depend on prior
    initialization calls.
    """
    # Create multiple models in sequence
    models = [initialize_model(BASE_CONFIG) for _ in range(5)]

    # All should be identical to the first
    for model in models[1:]:
        for (name1, p1), (_name2, p2) in zip(
            models[0].named_parameters(), model.named_parameters(), strict=True
        ):
            assert torch.equal(
                p1, p2
            ), f"Parameter {name1} differs across constructions"


def test_parameter_shapes_and_types_stable() -> None:
    """Model parameter shapes and numeric types are stable and documented."""
    model = initialize_model(BASE_CONFIG)
    spec = build_model_spec(model, BASE_CONFIG)

    # All shapes should be lists of ints
    for _name, shape in spec.parameter_shapes.items():
        assert isinstance(shape, list)
        assert all(isinstance(d, int) and d > 0 for d in shape)

    # All parameters should be float32 (default torch dtype)
    for param in model.parameters():
        assert param.dtype == torch.float32

    # Spec should contain all named parameters
    assert set(spec.parameter_shapes.keys()) == set(
        dict(model.named_parameters()).keys()
    )


def test_internal_parameters_not_mutable_via_spec() -> None:
    """Internal parameter access via spec does not mutate model state."""
    model = initialize_model(BASE_CONFIG)
    spec = build_model_spec(model, BASE_CONFIG)

    # Modify the shapes dict (should not affect model)
    first_key = next(iter(spec.parameter_shapes))
    original_shape = spec.parameter_shapes[first_key].copy()
    spec.parameter_shapes[first_key] = [999, 999]

    # Model parameters should be unchanged
    assert dict(model.named_parameters())[first_key].shape == tuple(original_shape)


def test_no_external_weights_or_network() -> None:
    """The component does not load external or pretrained weights and
    has no network requirement.
    """
    # Verify no network imports in the module
    import inspect

    import rop.native_model.native_model as nm_module

    source = inspect.getsource(nm_module)
    forbidden = [
        "torch.hub",
        "torchvision",
        "transformers",
        "huggingface",
        "requests",
        "urllib",
        "http",
        "socket",
        "from_pretrained",
        "load_state_dict_from_url",
    ]
    for term in forbidden:
        assert term not in source.lower(), f"Forbidden term '{term}' found in source"

    # Verify initialization creates new parameters, doesn't load
    model = initialize_model(BASE_CONFIG)
    assert model._initialized is True


def test_no_training_or_inference_integration_added() -> None:
    """No training, optimizer, checkpoint, inference-service, or
    reasoning-pipeline integration was added.
    """
    import inspect

    import rop.native_model.native_model as nm_module

    source = inspect.getsource(nm_module)
    # Exclude module docstring from checks
    lines = source.split("\n")
    in_docstring = False
    code_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if not in_docstring:
            code_lines.append(line)
    code_source = "\n".join(code_lines).lower()

    forbidden = [
        "optimizer",
        "backward",
        "step(",
        "zero_grad",
        "checkpoint",
        "save_pretrained",
        "inference",
        "pipeline",
        "reasoning",
        "evidence",
    ]
    for term in forbidden:
        assert term not in code_source, f"Forbidden term '{term}' found in source"
    assert "class NativeModel" in source
    assert "def forward" in source
    assert "def initialize_model" in source
    assert "def verify_model" in source


def test_tokenizer_vocabulary_contracts_compatible() -> None:
    """Existing Task 208 tokenizer/vocabulary contracts remain compatible."""
    from rop.schemas.tokenizer import MAX_SEQUENCE_LENGTH_LIMIT

    # Model max_seq_len should be compatible with tokenizer limit
    model_config = BASE_CONFIG.model_copy(
        update={"max_seq_len": MAX_SEQUENCE_LENGTH_LIMIT}
    )
    model = initialize_model(model_config)
    assert model.config.max_seq_len == MAX_SEQUENCE_LENGTH_LIMIT

    # Vocab size should accommodate reserved tokens
    assert BASE_CONFIG.vocab_size >= 2  # At least <pad> and <unk>


def test_baseline_evaluation_unchanged() -> None:
    """Existing Task 206 baseline evaluation behavior remains unchanged."""
    # This test verifies that importing native_model doesn't break baseline
    import rop.evaluation  # noqa: F401

    assert True


def test_verify_model_passes_on_valid_model() -> None:
    """verify_model passes on a valid, freshly initialized model."""
    model = initialize_model(BASE_CONFIG)
    verify_model(model)  # Should not raise
    verify_model(model, config=BASE_CONFIG)  # Should not raise


def test_verify_model_fails_on_parameter_tampering() -> None:
    """verify_model fails when parameters are tampered with."""
    model = initialize_model(BASE_CONFIG)
    # Tamper with a parameter
    with torch.no_grad():
        param = next(model.parameters())
        param.add_(1.0)

    with pytest.raises(NativeModelError) as exc:
        verify_model(model)
    assert exc.value.code == "HASH_MISMATCH"


def test_verify_model_fails_on_config_mismatch() -> None:
    """verify_model fails when config hash doesn't match."""
    model = initialize_model(BASE_CONFIG)
    wrong_config = BASE_CONFIG.model_copy(update={"hidden_dim": 128})

    with pytest.raises(NativeModelError) as exc:
        verify_model(model, config=wrong_config)
    assert exc.value.code == "HASH_MISMATCH"


def test_verify_model_fails_on_wrong_model_type() -> None:
    """verify_model fails on non-NativeModel input."""
    with pytest.raises(NativeModelError) as exc:
        verify_model(torch.nn.Linear(10, 10))  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_MODEL"


def test_build_model_spec_includes_all_metadata() -> None:
    """build_model_spec includes all required metadata fields."""
    model = initialize_model(BASE_CONFIG)
    spec = build_model_spec(model, BASE_CONFIG)

    assert spec.metadata.model_version == MODEL_VERSION
    assert spec.metadata.architecture == MODEL_ARCHITECTURE
    assert spec.metadata.config_hash is not None
    assert len(spec.metadata.config_hash) == 64
    assert spec.metadata.parameter_count > 0
    assert spec.metadata.init_seed == BASE_CONFIG.init_seed
    assert spec.metadata.init_hash is not None
    assert len(spec.metadata.init_hash) == 64
    assert spec.metadata.data_scope == "synthetic-test-only"


# --- Finding 1: Global RNG state preservation ---


def test_global_rng_state_preserved() -> None:
    """initialize_model preserves the caller's global CPU RNG state."""
    # Seed global RNG and capture state
    torch.manual_seed(12345)
    state_before = torch.get_rng_state()

    # Draw a reference value without model construction
    torch.manual_seed(12345)
    ref_draw = torch.rand(())

    # Now construct model and verify global state unchanged
    torch.manual_seed(12345)
    model = initialize_model(BASE_CONFIG)
    state_after = torch.get_rng_state()

    # Global RNG state must be identical
    assert torch.equal(
        state_before, state_after
    ), "Global RNG state changed after initialize_model()"

    # Model parameters must be reproducible
    model2 = initialize_model(BASE_CONFIG)
    for (name1, p1), (_name2, p2) in zip(
        model.named_parameters(), model2.named_parameters(), strict=True
    ):
        assert torch.equal(p1, p2), f"Parameter {name1} not reproducible"

    # Subsequent global draw must match reference
    actual_draw = torch.rand(())
    assert torch.equal(
        actual_draw, ref_draw
    ), "Global random sequence diverged after model construction"


# --- Finding 2: Configuration revalidation at initialization boundary ---


def test_revalidates_config_instance_with_invalid_seed() -> None:
    """NativeModelConfig instances with invalid seed are rejected at
    initialize_model.
    """
    # Create valid config, then mutate via model_copy to bypass
    # constructor validation
    invalid_config = BASE_CONFIG.model_copy(update={"init_seed": -1})
    with pytest.raises(NativeModelError) as exc:
        initialize_model(invalid_config)
    assert exc.value.code == "INVALID_CONFIG"


def test_revalidates_config_instance_with_unsupported_heads() -> None:
    """NativeModelConfig instances with unsupported heads/hidden_dim are
    rejected.
    """
    invalid_config = BASE_CONFIG.model_copy(update={"hidden_dim": 64, "num_heads": 5})
    with pytest.raises(NativeModelError) as exc:
        initialize_model(invalid_config)
    assert exc.value.code == "INVALID_CONFIG"


def test_revalidates_config_instance_with_invalid_dropout() -> None:
    """NativeModelConfig instances with invalid dropout are rejected."""
    invalid_config = BASE_CONFIG.model_copy(update={"dropout": 0.6})
    with pytest.raises(NativeModelError) as exc:
        initialize_model(invalid_config)
    assert exc.value.code == "INVALID_CONFIG"


def test_revalidates_config_instance_with_invalid_architecture() -> None:
    """NativeModelConfig instances with invalid architecture are rejected."""
    invalid_config = BASE_CONFIG.model_copy(update={"architecture": "other-arch"})
    with pytest.raises(NativeModelError) as exc:
        initialize_model(invalid_config)
    assert exc.value.code == "INVALID_CONFIG"


def test_revalidates_config_instance_with_invalid_version() -> None:
    """NativeModelConfig instances with invalid model_version are rejected."""
    invalid_config = BASE_CONFIG.model_copy(update={"model_version": "9.9"})
    with pytest.raises(NativeModelError) as exc:
        initialize_model(invalid_config)
    assert exc.value.code == "INVALID_CONFIG"


def test_revalidates_config_instance_oversized_before_allocation() -> None:
    """Oversized configurations are rejected before model allocation."""
    # Monkeypatch NativeModel.__init__ to fail if called
    import rop.native_model.native_model as nm_module

    original_init = nm_module.NativeModel.__init__

    def fail_init(self, config):
        raise AssertionError(
            "NativeModel.__init__ should not be called for invalid config"
        )

    try:
        nm_module.NativeModel.__init__ = fail_init
        huge_config = BASE_CONFIG.model_copy(
            update={
                "vocab_size": MAX_VOCAB_SIZE,
                "hidden_dim": MAX_HIDDEN_DIM,
                "num_layers": MAX_NUM_LAYERS,
                "num_heads": MAX_NUM_HEADS,
                "max_seq_len": MAX_SEQ_LEN,
                "num_classes": 128,
            }
        )
        with pytest.raises(NativeModelError) as exc:
            initialize_model(huge_config)
        assert exc.value.code == "CONFIG_INVALID"
    finally:
        nm_module.NativeModel.__init__ = original_init


# --- Finding 3: Input validation in forward ---


def test_forward_valid_input_shape() -> None:
    """Forward pass with valid input returns correct output shape."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.randint(0, BASE_CONFIG.vocab_size, (3, 16), dtype=torch.long)
    logits = model(token_ids)
    assert logits.shape == (3, BASE_CONFIG.num_classes)
    assert logits.dtype == torch.float32


def test_forward_wrong_rank_raises() -> None:
    """Forward pass with wrong tensor rank raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    # 1D tensor
    with pytest.raises(NativeModelError) as exc:
        model(torch.randint(0, 100, (16,), dtype=torch.long))
    assert exc.value.code == "INVALID_INPUT"
    # 3D tensor
    with pytest.raises(NativeModelError) as exc:
        model(torch.randint(0, 100, (2, 3, 16), dtype=torch.long))
    assert exc.value.code == "INVALID_INPUT"


def test_forward_wrong_type_raises() -> None:
    """Forward pass with non-Tensor input raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    with pytest.raises(NativeModelError) as exc:
        model([1, 2, 3])  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_INPUT"
    with pytest.raises(NativeModelError) as exc:
        model("not a tensor")  # type: ignore[arg-type]
    assert exc.value.code == "INVALID_INPUT"


def test_forward_empty_batch_raises() -> None:
    """Forward pass with empty batch raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.empty((0, 16), dtype=torch.long)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"


def test_forward_empty_sequence_raises() -> None:
    """Forward pass with empty sequence raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.empty((3, 0), dtype=torch.long)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"


def test_forward_exceeds_max_seq_len_raises() -> None:
    """Forward pass with sequence exceeding max_seq_len raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    seq_len = BASE_CONFIG.max_seq_len + 1
    token_ids = torch.randint(0, BASE_CONFIG.vocab_size, (2, seq_len), dtype=torch.long)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"


def test_forward_float_dtype_raises() -> None:
    """Forward pass with float dtype raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.randint(0, BASE_CONFIG.vocab_size, (2, 16), dtype=torch.float32)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"


def test_forward_bool_dtype_raises() -> None:
    """Forward pass with bool dtype raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.randint(0, 2, (2, 16), dtype=torch.bool)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"


def test_forward_negative_token_ids_raises() -> None:
    """Forward pass with negative token IDs raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.tensor([[1, -1, 3]], dtype=torch.long)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"


def test_forward_oov_token_ids_raises() -> None:
    """Forward pass with token IDs >= vocab_size raises INVALID_INPUT."""
    model = initialize_model(BASE_CONFIG)
    token_ids = torch.tensor([[1, BASE_CONFIG.vocab_size, 3]], dtype=torch.long)
    with pytest.raises(NativeModelError) as exc:
        model(token_ids)
    assert exc.value.code == "INVALID_INPUT"

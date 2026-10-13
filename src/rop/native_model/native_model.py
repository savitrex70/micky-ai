"""Task 209: project-owned randomly initialized native model.

A compact encoder-style Transformer for a narrow synthetic classification
task. All parameters are randomly initialized from a documented seed.
No pretrained weights, tokenizer, vocabulary, or downloaded artifact
exists in this path.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import torch
import torch.nn as nn

from rop.schemas.native_model import (
    MAX_TOTAL_PARAMS,
    MODEL_ARCHITECTURE,
    MODEL_VERSION,
    NativeModelConfig,
    NativeModelMetadata,
    NativeModelSpec,
)

__all__ = [
    "NativeModelError",
    "NativeModel",
    "initialize_model",
    "verify_model",
    "count_parameters",
]


class NativeModelError(Exception):
    """A typed native model failure with a safe, generic message."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def _canonical_config_dict(config: NativeModelConfig) -> dict[str, Any]:
    """Canonical model configuration representation (v1.0)."""
    return {
        "model_version": config.model_version,
        "architecture": config.architecture,
        "vocab_size": config.vocab_size,
        "hidden_dim": config.hidden_dim,
        "num_layers": config.num_layers,
        "num_heads": config.num_heads,
        "max_seq_len": config.max_seq_len,
        "num_classes": config.num_classes,
        "dropout": config.dropout,
        "init_seed": config.init_seed,
        "init_std": config.init_std,
    }


def _canonical_hash(canonical: dict[str, Any]) -> str:
    """SHA-256 over sorted-key compact JSON (Task 104 scheme)."""
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _checked_config(config: NativeModelConfig | dict[str, Any]) -> NativeModelConfig:
    """Validate a model configuration mapping eagerly and strictly."""
    if isinstance(config, NativeModelConfig):
        return config
    if not isinstance(config, dict):
        raise NativeModelError("INVALID_CONFIG", "model configuration is invalid")
    try:
        return NativeModelConfig.model_validate(config)
    except Exception as exc:
        raise NativeModelError(
            "INVALID_CONFIG", "model configuration is invalid"
        ) from exc


class _EmbeddingLayer(nn.Module):
    """Token and positional embeddings."""

    def __init__(
        self, vocab_size: int, hidden_dim: int, max_seq_len: int, dropout: float
    ):
        super().__init__()
        self.token_embedding = nn.Embedding(vocab_size, hidden_dim)
        self.position_embedding = nn.Embedding(max_seq_len, hidden_dim)
        self.dropout = nn.Dropout(dropout)
        self.register_buffer("positions", torch.arange(max_seq_len), persistent=False)

    def forward(self, token_ids: torch.Tensor) -> torch.Tensor:
        seq_len = token_ids.size(1)
        positions = self.positions[:seq_len].unsqueeze(0)
        x = self.token_embedding(token_ids) + self.position_embedding(positions)
        return self.dropout(x)


class _FeedForward(nn.Module):
    """Position-wise feed-forward network."""

    def __init__(self, hidden_dim: int, dropout: float):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(hidden_dim, 4 * hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * hidden_dim, hidden_dim),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class _EncoderBlock(nn.Module):
    """Single Transformer encoder block."""

    def __init__(self, hidden_dim: int, num_heads: int, dropout: float):
        super().__init__()
        self.attention = nn.MultiheadAttention(
            hidden_dim, num_heads, dropout=dropout, batch_first=True
        )
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.ff = _FeedForward(hidden_dim, dropout)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self, x: torch.Tensor, attn_mask: torch.Tensor | None = None
    ) -> torch.Tensor:
        # Self-attention with residual
        attn_out, _ = self.attention(x, x, x, attn_mask=attn_mask, need_weights=False)
        x = self.norm1(x + self.dropout(attn_out))
        # Feed-forward with residual
        ff_out = self.ff(x)
        x = self.norm2(x + ff_out)
        return x


class NativeModel(nn.Module):
    """Compact encoder-style Transformer for synthetic classification.

    Parameters are initialized by `initialize_model()`; do not instantiate
    directly with random weights.
    """

    def __init__(self, config: NativeModelConfig):
        super().__init__()
        self.config = config
        self.embeddings = _EmbeddingLayer(
            config.vocab_size, config.hidden_dim, config.max_seq_len, config.dropout
        )
        self.encoder_layers = nn.ModuleList(
            [
                _EncoderBlock(config.hidden_dim, config.num_heads, config.dropout)
                for _ in range(config.num_layers)
            ]
        )
        self.classifier = nn.Linear(config.hidden_dim, config.num_classes)
        self._initialized = False
        # Stored at initialization time for verification
        self._init_hash: str | None = None
        self._config_hash: str | None = None

    def forward(self, token_ids: torch.Tensor) -> torch.Tensor:
        """Forward pass returning class logits.

        Args:
            token_ids: Tensor of shape (batch_size, seq_len) with token IDs.

        Returns:
            Logits of shape (batch_size, num_classes).
        """
        if token_ids.dim() != 2:
            raise NativeModelError("INVALID_INPUT", "token_ids must be 2D tensor")
        if token_ids.size(1) > self.config.max_seq_len:
            raise NativeModelError("INVALID_INPUT", "sequence length exceeds maximum")

        x = self.embeddings(token_ids)
        for layer in self.encoder_layers:
            x = layer(x)
        # Use [CLS]-like pooling: take first token representation
        cls_repr = x[:, 0]
        logits = self.classifier(cls_repr)
        return logits


def _initialize_parameters(model: NativeModel, config: NativeModelConfig) -> None:
    """Initialize all model parameters deterministically from config.init_seed.

    Uses a dedicated generator to avoid affecting global random state.
    """
    generator = torch.Generator()
    generator.manual_seed(config.init_seed)

    std = config.init_std
    with torch.no_grad():
        # Embeddings
        model.embeddings.token_embedding.weight.normal_(
            mean=0.0, std=std, generator=generator
        )
        model.embeddings.position_embedding.weight.normal_(
            mean=0.0, std=std, generator=generator
        )

        # Encoder layers
        for layer in model.encoder_layers:
            # MultiheadAttention in PyTorch uses in_proj_weight/bias and out_proj
            nn.init.normal_(
                layer.attention.in_proj_weight, mean=0.0, std=std, generator=generator
            )
            if layer.attention.in_proj_bias is not None:
                nn.init.zeros_(layer.attention.in_proj_bias)
            nn.init.normal_(
                layer.attention.out_proj.weight, mean=0.0, std=std, generator=generator
            )
            if layer.attention.out_proj.bias is not None:
                nn.init.zeros_(layer.attention.out_proj.bias)

            # LayerNorms
            nn.init.ones_(layer.norm1.weight)
            nn.init.zeros_(layer.norm1.bias)
            nn.init.ones_(layer.norm2.weight)
            nn.init.zeros_(layer.norm2.bias)

            # Feed-forward
            nn.init.normal_(
                layer.ff.net[0].weight, mean=0.0, std=std, generator=generator
            )
            nn.init.zeros_(layer.ff.net[0].bias)
            nn.init.normal_(
                layer.ff.net[3].weight, mean=0.0, std=std, generator=generator
            )
            nn.init.zeros_(layer.ff.net[3].bias)

        # Classifier
        nn.init.normal_(model.classifier.weight, mean=0.0, std=std, generator=generator)
        nn.init.zeros_(model.classifier.bias)

    # Verify all parameters are finite
    for param in model.parameters():
        if not torch.all(torch.isfinite(param)):
            raise NativeModelError(
                "INIT_FAILED", "non-finite parameter after initialization"
            )

    # Store original hashes for later verification
    model._init_hash = _parameter_init_hash(model)
    model._config_hash = _canonical_hash(_canonical_config_dict(config))

    model._initialized = True


def initialize_model(config: NativeModelConfig | dict[str, Any]) -> NativeModel:
    """Construct and deterministically initialize a NativeModel.

    Validates configuration before allocating parameters. Identical config
    and seed always produce identical initial parameter values.

    Args:
        config: Model configuration (validated NativeModelConfig or dict).

    Returns:
        Initialized NativeModel in eval mode.

    Raises:
        NativeModelError: If configuration is invalid or initialization fails.
    """
    validated = _checked_config(config)

    # Validate parameter count bound before allocation
    estimated = _estimate_parameter_count(validated)
    if estimated > MAX_TOTAL_PARAMS:
        raise NativeModelError(
            "CONFIG_INVALID",
            f"estimated parameter count {estimated} exceeds maximum {MAX_TOTAL_PARAMS}",
        )

    model = NativeModel(validated)
    _initialize_parameters(model, validated)
    model.eval()
    return model


def _estimate_parameter_count(config: NativeModelConfig) -> int:
    """Estimate parameter count from configuration without allocating model.

    Formula (verified against actual model):
    - token_emb = vocab_size * hidden
    - pos_emb = max_seq_len * hidden
    - per_layer = 12*hidden^2 + 13*hidden
      - attn: in_proj (3*hidden^2 + 3*hidden) + out_proj (hidden^2 + hidden)
        = 4*hidden^2 + 4*hidden
      - ln: 2 LayerNorms * 2*hidden = 4*hidden
      - ff: Linear(hidden, 4*hidden) + Linear(4*hidden, hidden)
        = 8*hidden^2 + 5*hidden
    - classifier = hidden * num_classes + num_classes
    """
    vocab_size = config.vocab_size
    hidden = config.hidden_dim
    layers = config.num_layers
    seq_len = config.max_seq_len
    classes = config.num_classes

    # Embeddings
    token_emb = vocab_size * hidden
    pos_emb = seq_len * hidden

    # Per encoder layer: 12*hidden^2 + 13*hidden
    per_layer = 12 * hidden * hidden + 13 * hidden

    # Classifier
    classifier_params = hidden * classes + classes

    total = token_emb + pos_emb + layers * per_layer + classifier_params
    return total


def count_parameters(model: NativeModel) -> int:
    """Count total trainable parameters in the model."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def _parameter_shapes(model: NativeModel) -> dict[str, list[int]]:
    """Extract parameter shapes as a JSON-serializable dict."""
    return {name: list(param.shape) for name, param in model.named_parameters()}


def _parameter_init_hash(model: NativeModel) -> str:
    """Compute deterministic hash of all parameter values.

    Serializes parameters in a canonical order (sorted by name) to bytes.
    """
    parts = []
    for name in sorted(dict(model.named_parameters()).keys()):
        param = dict(model.named_parameters())[name]
        # Convert to CPU numpy, then to bytes in a deterministic way
        arr = param.detach().cpu().numpy()
        parts.append(name.encode())
        parts.append(arr.tobytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def build_model_spec(model: NativeModel, config: NativeModelConfig) -> NativeModelSpec:
    """Build a complete NativeModelSpec from an initialized model."""
    if not isinstance(model, NativeModel):
        raise NativeModelError("INVALID_MODEL", "model is not a NativeModel")
    if not model._initialized:
        raise NativeModelError("INVALID_MODEL", "model is not initialized")

    param_count = count_parameters(model)
    config_hash = _canonical_hash(_canonical_config_dict(config))
    init_hash = _parameter_init_hash(model)

    metadata = NativeModelMetadata(
        model_version=MODEL_VERSION,
        architecture=MODEL_ARCHITECTURE,
        config_hash=config_hash,
        parameter_count=param_count,
        init_seed=config.init_seed,
        init_hash=init_hash,
        data_scope="synthetic-test-only",
    )

    return NativeModelSpec(metadata=metadata, parameter_shapes=_parameter_shapes(model))


def verify_model(
    model: NativeModel, config: NativeModelConfig | dict[str, Any] | None = None
) -> None:
    """Verify a model's integrity against its configuration and recorded hashes.

    Recomputes parameter count and init hash; never trusts caller-supplied
    values. If config is provided, also verifies the configuration hash.

    Args:
        model: The NativeModel to verify.
        config: Optional configuration to verify against.

    Raises:
        NativeModelError: If verification fails.
    """
    if not isinstance(model, NativeModel):
        raise NativeModelError("INVALID_MODEL", "model is not a NativeModel")
    if not model._initialized:
        raise NativeModelError("INVALID_MODEL", "model is not initialized")
    if model._init_hash is None or model._config_hash is None:
        raise NativeModelError("INVALID_MODEL", "model missing stored hashes")

    # Verify parameter count
    actual_count = count_parameters(model)
    # Recompute expected count from config
    expected_count = _estimate_parameter_count(model.config)
    if actual_count != expected_count:
        raise NativeModelError(
            "PARAMETER_COUNT_MISMATCH", "parameter count does not match"
        )

    # Verify init hash against stored hash
    actual_hash = _parameter_init_hash(model)
    if actual_hash != model._init_hash:
        raise NativeModelError("HASH_MISMATCH", "initialization hash does not match")

    # Verify config hash if config provided
    if config is not None:
        validated = _checked_config(config)
        expected_config_hash = _canonical_hash(_canonical_config_dict(validated))
        if expected_config_hash != model._config_hash:
            raise NativeModelError("HASH_MISMATCH", "configuration hash does not match")

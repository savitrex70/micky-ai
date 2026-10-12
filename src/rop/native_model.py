"""Task 209 smallest justified first-party model, initialized randomly.

The architecture is a token-embedding table, mean pooling, and one
linear multi-label head — the smallest design justified by the bounded
Task 206 label-suggestion task and by a non-neural baseline comparison
(documented in the Task 209 PR). A Transformer is rejected by the
configuration contract as unjustified at this scale.

Every trainable parameter is initialized from this project's documented
scheme with a recorded seed; no weights are ever loaded from disk, no
pretrained asset is referenced, and importing this module constructs
nothing and touches no network. The model serves only the bounded
label-suggestion task: it makes no clinical decisions, publishes no
evidence, assigns no identity, and declares no certification. Pure
Python on purpose: no numerical framework is required at this scale,
so ordinary ROP runtime gains no training dependency.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from rop.schemas.native_model import NativeModelConfig

# Documented initialization: uniform fan-in scaled bounds for both the
# embedding table and the linear head; the head bias starts at zero.
_INIT_BOUND_DIVISOR = 2.0


class NativeModelError(Exception):
    """Typed model failure; carries only canonical, non-sensitive text."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


@dataclass(frozen=True)
class NativeModelParameters:
    """Immutable snapshot of every trainable parameter."""

    embedding: tuple[tuple[float, ...], ...]  # (vocab_size, embedding_dim)
    head_weight: tuple[tuple[float, ...], ...]  # (num_labels, embedding_dim)
    head_bias: tuple[float, ...]  # (num_labels,)


class NativeModel:
    """Deterministic, randomly initialized bounded label-suggestion model."""

    def __init__(self, config: NativeModelConfig) -> None:
        self.config = config
        self.parameters = self._initialize(config)

    @staticmethod
    def _initialize(config: NativeModelConfig) -> NativeModelParameters:
        """Initialize every parameter from the documented seeded scheme.

        Deterministic for a fixed (seed, config) pair; genuinely random
        across seeds; never loaded from any external source.
        """
        generator = random.Random(config.initialization_seed)
        embedding_bound = _INIT_BOUND_DIVISOR / math.sqrt(config.embedding_dim)
        head_bound = _INIT_BOUND_DIVISOR / math.sqrt(config.embedding_dim)
        embedding = tuple(
            tuple(
                generator.uniform(-embedding_bound, embedding_bound)
                for _ in range(config.embedding_dim)
            )
            for _ in range(config.vocab_size)
        )
        head_weight = tuple(
            tuple(
                generator.uniform(-head_bound, head_bound)
                for _ in range(config.embedding_dim)
            )
            for _ in range(config.num_labels)
        )
        head_bias = tuple(0.0 for _ in range(config.num_labels))

        parameters = NativeModelParameters(
            embedding=embedding, head_weight=head_weight, head_bias=head_bias
        )
        NativeModel._require_finite(parameters)
        return parameters

    @staticmethod
    def _require_finite(parameters: NativeModelParameters) -> None:
        """Fail closed if any parameter is NaN or infinite."""
        values = (
            [value for row in parameters.embedding for value in row]
            + [value for row in parameters.head_weight for value in row]
            + list(parameters.head_bias)
        )
        if not all(math.isfinite(value) for value in values):
            raise NativeModelError(
                "NON_FINITE_PARAMETER",
                "initialization produced a non-finite parameter",
            )

    def predict(self, token_ids: tuple[int, ...]) -> tuple[float, ...]:
        """Return one bounded probability per label for one token sequence.

        Deterministic, side-effect free, and bounded to [0, 1] per label.
        Token identifiers outside the configured vocabulary are rejected;
        sequences longer than the configured limit are deterministically
        truncated. This output is an untrusted advisory suggestion, never
        evidence or a conclusion.
        """
        if any(not isinstance(token_id, int) or token_id < 0 for token_id in token_ids):
            raise NativeModelError(
                "TOKEN_ID_OUT_OF_RANGE",
                "token identifiers must be non-negative integers",
            )
        if any(token_id >= self.config.vocab_size for token_id in token_ids):
            raise NativeModelError(
                "TOKEN_ID_OUT_OF_RANGE",
                "a token identifier exceeds the configured vocabulary",
            )
        truncated = token_ids[: self.config.max_sequence_length]
        dimension = self.config.embedding_dim
        if truncated:
            pooled = tuple(
                sum(self.parameters.embedding[token_id][axis] for token_id in truncated)
                / len(truncated)
                for axis in range(dimension)
            )
        else:
            pooled = tuple(0.0 for _ in range(dimension))
        logits = tuple(
            sum(weight * value for weight, value in zip(row, pooled, strict=True))
            + self.parameters.head_bias[label]
            for label, row in enumerate(self.parameters.head_weight)
        )
        return tuple(1.0 / (1.0 + math.exp(-logit)) for logit in logits)

    @staticmethod
    def reproducible(
        config: NativeModelConfig,
    ) -> NativeModelParameters:
        """Parameters for a configuration, without keeping an instance."""
        return NativeModel._initialize(config)


__all__ = [
    "NativeModel",
    "NativeModelConfig",
    "NativeModelError",
    "NativeModelParameters",
]

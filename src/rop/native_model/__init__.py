"""Task 209: project-owned native model package.

A compact, randomly initialized encoder-style Transformer for a narrow
synthetic classification task. No pretrained weights, tokenizer,
vocabulary, or downloaded artifact exists in this path.
"""

from rop.native_model.native_model import (
    NativeModel,
    NativeModelError,
    build_model_spec,
    count_parameters,
    initialize_model,
    verify_model,
)

__all__ = [
    "NativeModel",
    "NativeModelError",
    "build_model_spec",
    "count_parameters",
    "initialize_model",
    "verify_model",
]

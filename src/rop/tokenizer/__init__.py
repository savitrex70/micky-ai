"""Task 208: project-controlled tokenizer package.

Deterministic text-to-token-sequence transformation and
training-partition vocabulary construction over standard-library
facilities only. No pretrained tokenizer, vocabulary, merge table,
downloaded artifact, model, training, network, or GPU lives here.
"""

from rop.tokenizer.tokenizer import (
    TokenizerError,
    tokenize_text,
)
from rop.tokenizer.vocabulary import (
    VOCABULARY_POLICY_VERSION,
    VocabularyPolicy,
    build_vocabulary,
    encode_text,
    verify_vocabulary,
)

__all__ = [
    "VOCABULARY_POLICY_VERSION",
    "TokenizerError",
    "VocabularyPolicy",
    "build_vocabulary",
    "encode_text",
    "tokenize_text",
    "verify_vocabulary",
]

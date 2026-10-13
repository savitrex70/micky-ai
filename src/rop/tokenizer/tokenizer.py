"""Task 208: deterministic project-owned tokenization (v1.0).

Tokenization rules, all explicit and versioned with
``TOKENIZER_VERSION``:

- Unicode NFC normalization (consistent with the Task 207
  normalized-text contract); case preserved exactly.
- Whitespace runs (spaces, tabs, newlines) separate words and
  produce no tokens; empty and whitespace-only inputs yield zero
  tokens, which is valid.
- Alphanumeric runs (Unicode letters and digits, excluding
  underscore) form one token each: words, numbers, and mixed
  runs such as ``abc123`` stay whole.
- An ASCII apostrophe between two alphanumerics stays inside the
  word (``don't`` is one token); any other apostrophe is a
  single-character punctuation token. Non-ASCII apostrophes are
  always punctuation.
- Every other non-whitespace character -- punctuation, symbols,
  underscore, emoji -- is one token each. CJK Unified Ideographs
  (extensions A–F and compatibility ranges) are always individual
  tokens in v1: CJK text without spaces tokenizes per character
  (documented v1 limitation).
- Literal reserved spellings such as ``<pad>`` tokenize as
  ordinary punctuation and word pieces; spelling can never
  produce a reserved ID. Reserved IDs arise only from the
  reserved entries (padding, if ever used) and unknown-token
  mapping, which the encoder layer assigns, not this splitter.

Malformed Unicode (lone surrogates) and non-string inputs are
rejected with a typed, safe error: no encoding traceback leaks
and nothing is silently coerced or repaired.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["TokenizerError", "tokenize_text"]

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_APOSTROPHE = "'"

_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x20000, 0x2A6DF),  # Extension B
    (0x2A700, 0x2B73F),  # Extension C
    (0x2B740, 0x2B81F),  # Extension D
    (0x2B820, 0x2CEAF),  # Extension E
    (0x2CEB0, 0x2EBEF),  # Extension F
    (0xF900, 0xFAFF),  # Compatibility Ideographs
    (0x2F800, 0x2FA1F),  # Compatibility Ideographs Supplement
)


def _is_cjk_ideograph(char: str) -> bool:
    """Whether a single character is a CJK ideograph (v1 policy)."""
    codepoint = ord(char)
    return any(low <= codepoint <= high for low, high in _CJK_RANGES)


def _split_cjk(run: str) -> list[str]:
    """Split a word run so each CJK ideograph is its own token (v1).

    Non-CJK letters and digits stay together: ``日本語abc``
    yields ``日``, ``本``, ``語abc``.
    """
    parts: list[str] = []
    buffer: list[str] = []
    for char in run:
        if _is_cjk_ideograph(char):
            if buffer:
                parts.append("".join(buffer))
                buffer = []
            parts.append(char)
        else:
            buffer.append(char)
    if buffer:
        parts.append("".join(buffer))
    return parts


class TokenizerError(Exception):
    """A typed tokenizer failure with a safe, generic message."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def _check_text(text: object) -> str:
    """Require a genuine string; never stringify arbitrary objects."""
    if not isinstance(text, str):
        raise TokenizerError("INVALID_INPUT", "tokenizer input is invalid")
    try:
        text.encode("utf-8")
    except (UnicodeEncodeError, ValueError):
        raise TokenizerError("INVALID_INPUT", "tokenizer input is invalid") from None
    return text


def tokenize_text(text: str) -> tuple[str, ...]:
    """Split validated text into word and punctuation tokens.

    Pure and deterministic: identical inputs always yield
    identical token tuples. Empty and whitespace-only inputs
    yield ``()``.
    """
    checked = _check_text(text)
    normalized = unicodedata.normalize("NFC", checked)
    tokens: list[str] = []
    for piece in normalized.split():
        tokens.extend(_tokenize_word(piece))
    return tuple(tokens)


def _tokenize_word(piece: str) -> list[str]:
    """Split one whitespace-free piece into tokens."""
    tokens: list[str] = []
    position = 0
    while position < len(piece):
        match = _WORD_RE.match(piece, position)
        if match is not None:
            end = match.end()
            # Interior ASCII apostrophe stays inside the word when
            # another alphanumeric run follows it directly.
            while (
                end < len(piece)
                and piece[end] == _APOSTROPHE
                and end + 1 < len(piece)
                and piece[end + 1].isalnum()
            ):
                continuation = _WORD_RE.match(piece, end + 1)
                if continuation is None:
                    # Alphanumeric but not word-shaped (e.g. some
                    # numeric symbols): stop the word here instead
                    # of attaching the apostrophe to it.
                    break
                end = continuation.end()
            tokens.extend(_split_cjk(piece[position:end]))
            position = end
        else:
            tokens.append(piece[position])
            position += 1
    return tokens

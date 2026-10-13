"""Task 203: strict native evidence record and provenance contracts.

Deterministic data-contract layer only. This module represents what
information was received, where it came from, how it is identified,
and whether its integrity can be checked. It does not decide what
evidence means, derive conclusions, bind evidence to reasoning
requests (Task 204), run inference, train models, or touch the
network or database.

Design notes (narrowest defensible choices):

- ``evidence_type`` is limited to ``OBSERVATION`` and ``ASSERTION``,
  the two normalized source-level kinds named by the architecture
  (section 4.2). Stance (supporting/contradicting) is an
  interpretation and belongs to later tasks, not to this record.
- ``content_text`` is a plain string (never a dict/list) so there
  are no nested mutable structures to freeze. All fields are
  immutable scalars; ``frozen=True`` therefore gives deep
  immutability.
- ``content_digest`` is the SHA-256 hex digest of the exact UTF-8
  bytes of ``content_text`` (stdlib ``hashlib`` only, matching the
  project's existing SHA-256 practice). Validation recomputes the
  digest and rejects any mismatch, so every valid instance is
  content-verified by construction. This verifies integrity of the
  supplied bytes only; it never proves the underlying real-world
  source is authentic or trustworthy.
- ``provenance_id`` and ``source_reference`` are syntactically
  validated only. Acceptance means "well-formed", never "verified
  against a trusted registry". There is deliberately no
  ``is_trusted``/``is_verified`` boolean: trust cannot be asserted
  by the caller and unknown fields are rejected.
- ``availability`` distinguishes ``AVAILABLE`` (content captured)
  from ``UNREADABLE`` (source referenced but content could not be
  read; ``content_text`` is then exactly ``""`` with the matching
  empty-string digest, rather than fabricated content).
- ``uncertainty`` is source-reported uncertainty metadata carried
  with the record, not a derived conclusion.
- Every collection-free field marked required is required at
  construction; ``*_source`` identifiers must be supplied
  explicitly, never silently inserted.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NATIVE_EVIDENCE_SOURCE_TASK_203 = "NATIVE_EVIDENCE_TASK_203"

_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_PROVENANCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SOURCE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,254}")

MAX_SOURCE_REF_LENGTH = 255
MAX_PROVENANCE_ID_LENGTH = 128
MAX_CONTENT_LENGTH = 2000

NativeEvidenceType = Literal["OBSERVATION", "ASSERTION"]
NativeEvidenceAvailability = Literal["AVAILABLE", "UNREADABLE"]

_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


def compute_native_evidence_digest(content_text: str) -> str:
    """Compute the canonical content digest for native evidence.

    SHA-256 over the exact UTF-8 bytes of ``content_text``. Pure
    and deterministic; stdlib only.
    """
    return hashlib.sha256(content_text.encode("utf-8")).hexdigest()


def _rejects_unsafe_reference(value: str) -> bool:
    """Return True when a source reference must be refused.

    Besides the allow-list pattern, explicitly refuse parent
    traversal, absolute filesystem paths (POSIX and Windows), and
    control characters, without echoing the value.
    """
    if "\n" in value or "\r" in value or "\x00" in value:
        return True
    if ".." in value:
        return True
    if value.startswith("/"):
        return True
    if "\\" in value:
        return True
    if len(value) >= 2 and value[1] == ":":
        return True
    return False


class NativeEvidenceRecord(BaseModel):
    """Strict immutable native evidence record (Task 203)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    session_id: UUID
    context_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_type: NativeEvidenceType
    source_reference: str = Field(min_length=1, max_length=MAX_SOURCE_REF_LENGTH)
    provenance_id: str = Field(min_length=1, max_length=MAX_PROVENANCE_ID_LENGTH)
    content_text: str = Field(max_length=MAX_CONTENT_LENGTH)
    content_digest: str = Field(min_length=64, max_length=64)
    availability: NativeEvidenceAvailability
    uncertainty: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    evidence_source: Literal["NATIVE_EVIDENCE_TASK_203"]

    @field_validator("uncertainty", mode="before")
    @classmethod
    def _reject_ambiguous_uncertainty(cls, value: object) -> object:
        # Pydantic's lax float parsing would silently convert numeric
        # strings ("0.2") and booleans (True -> 1.0). Reject those
        # ambiguous inputs here with a generic message; genuine JSON
        # numbers (int or float) pass through to range/finiteness
        # checks unchanged.
        if isinstance(value, bool) or isinstance(value, str):
            raise ValueError("uncertainty is invalid")
        return value

    @model_validator(mode="after")
    def _strict_record(self) -> NativeEvidenceRecord:
        if not _FINGERPRINT_RE.fullmatch(self.context_fingerprint):
            raise ValueError("context_fingerprint is invalid")
        if not _PROVENANCE_ID_RE.fullmatch(self.provenance_id):
            raise ValueError("provenance_id is invalid")
        if not _SOURCE_REF_RE.fullmatch(self.source_reference):
            raise ValueError("source_reference is invalid")
        if _rejects_unsafe_reference(self.source_reference):
            raise ValueError("source_reference is invalid")
        if self.availability == "AVAILABLE":
            if not 1 <= len(self.content_text) <= MAX_CONTENT_LENGTH:
                raise ValueError("content_text is invalid")
        else:
            if self.content_text != "":
                raise ValueError("content_text is invalid")
        if not _FINGERPRINT_RE.fullmatch(self.content_digest):
            raise ValueError("content_digest is invalid")
        if compute_native_evidence_digest(self.content_text) != self.content_digest:
            raise ValueError("content_digest is invalid")
        return self


__all__ = [
    "MAX_CONTENT_LENGTH",
    "MAX_PROVENANCE_ID_LENGTH",
    "MAX_SOURCE_REF_LENGTH",
    "NATIVE_EVIDENCE_SOURCE_TASK_203",
    "NativeEvidenceAvailability",
    "NativeEvidenceRecord",
    "NativeEvidenceType",
    "compute_native_evidence_digest",
]

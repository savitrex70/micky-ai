"""Task 202: strict native reasoning request/result/error contracts.

Contract-only boundary for ROP's first-party native reasoning. No
model, tokenizer, training code, inference engine, provider SDK,
network call, persistence, or clinical decision-making lives here.

Three immutable Pydantic contracts:

1. ``NativeReasoningRequest`` -- strictly validated caller input that
   binds a request identity to one session, one context fingerprint,
   one narrow task, and a bounded set of evidence references. The
   evidence records themselves are Task 203; this contract carries
   only well-formed references so later composition (Task 204) can
   resolve them against a trusted input set.

2. ``NativeReasoningResult`` -- strictly validated deterministic
   outcome. Statuses follow the architecture document section 4.3:
   SUPPORTED, CONTRADICTED, INSUFFICIENT, ABSTAINED, UNAVAILABLE.
   Abstention is explicit and never a disguised success. Reason codes
   are bound to statuses by an explicit compatibility matrix.
   Uncertainty is always present and bounded. Advisory suggestion
   text, when present, is clearly labelled and never evidence.

3. ``NativeReasoningError`` -- stable public error with a bounded
   code set, canonical safe messages (no exception text, paths,
   secrets, or request contents), and a defensible retryability
   flag per code.

All models use ``extra="forbid"`` and ``frozen=True`` so unknown
fields are rejected and field reassignment is prohibited. Collection
fields are tuples (not lists) so validated instances are also deeply
immutable: JSON arrays are still accepted on input and still
serialize as arrays in ``mode="json"``, but in-place mutation such
as ``append`` is impossible. Validators emit generic messages that
never echo input values.

Required-field rationale: request/response identity, fingerprints,
task/status/reason/uncertainty, every evidence and missing-information
collection, and each ``*_source`` structural identifier are explicit
contract fields and therefore required at construction. Omission is
rejected rather than silently defaulting to an empty collection or
an inserted source value. Only ``rule_id``/``suggestion_text`` (result)
and ``request_id``/``session_id`` (error) are genuinely optional.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

NATIVE_REASONING_REQUEST_SOURCE_TASK_202 = "NATIVE_REASONING_REQUEST_TASK_202"
NATIVE_REASONING_RESULT_SOURCE_TASK_202 = "NATIVE_REASONING_RESULT_TASK_202"
NATIVE_REASONING_ERROR_SOURCE_TASK_202 = "NATIVE_REASONING_ERROR_TASK_202"

_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_TASK_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_RULE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_MISSING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")

MAX_EVIDENCE_REFS = 64
MAX_MISSING_IDS = 32
MAX_TASK_ID_LENGTH = 64
MAX_RULE_ID_LENGTH = 64
MAX_MISSING_ID_LENGTH = 64
MAX_SUGGESTION_LENGTH = 500

NativeReasoningStatus = Literal[
    "SUPPORTED", "CONTRADICTED", "INSUFFICIENT", "ABSTAINED", "UNAVAILABLE"
]

NativeReasoningReasonCode = Literal[
    "RULE_MATCH",
    "RULE_CONTRADICTION_FOUND",
    "EVIDENCE_MISSING",
    "EVIDENCE_UNBOUND",
    "NO_JUSTIFIED_BASIS",
    "INPUT_UNAVAILABLE",
    "ENGINE_UNAVAILABLE",
]

_STATUS_REASON_MATRIX: dict[str, frozenset[str]] = {
    "SUPPORTED": frozenset({"RULE_MATCH"}),
    "CONTRADICTED": frozenset({"RULE_CONTRADICTION_FOUND"}),
    "INSUFFICIENT": frozenset({"EVIDENCE_MISSING", "EVIDENCE_UNBOUND"}),
    "ABSTAINED": frozenset({"NO_JUSTIFIED_BASIS"}),
    "UNAVAILABLE": frozenset({"INPUT_UNAVAILABLE", "ENGINE_UNAVAILABLE"}),
}

NativeReasoningErrorCode = Literal[
    "INVALID_REQUEST", "CONTRACT_VIOLATION", "UNAVAILABLE", "ENGINE_FAILED"
]

_ERROR_MESSAGES: dict[str, str] = {
    "INVALID_REQUEST": "native reasoning request is invalid",
    "CONTRACT_VIOLATION": "native reasoning result violates the contract",
    "UNAVAILABLE": "native reasoning is unavailable",
    "ENGINE_FAILED": "native reasoning engine failed",
}

_ERROR_RETRYABILITY: dict[str, bool] = {
    "INVALID_REQUEST": False,
    "CONTRACT_VIOLATION": False,
    "UNAVAILABLE": True,
    "ENGINE_FAILED": False,
}


def _is_sorted_unique_uuids(values: Sequence[UUID]) -> bool:
    texts = [str(v) for v in values]
    return len(set(texts)) == len(texts) and texts == sorted(texts)


def _is_sorted_unique_strs(values: Sequence[str]) -> bool:
    items = list(values)
    return len(set(items)) == len(items) and items == sorted(items)


class NativeReasoningRequest(BaseModel):
    """Strict immutable native reasoning request (Task 202).

    Binds one request identity to one session, one context
    fingerprint, one narrow task, and a bounded evidence-reference
    set. Evidence records are resolved by later tasks; only
    well-formed UUID references travel here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    session_id: UUID
    context_fingerprint: str = Field(min_length=64, max_length=64)
    task_id: str = Field(min_length=1, max_length=MAX_TASK_ID_LENGTH)
    evidence_ids: tuple[UUID, ...] = Field(max_length=MAX_EVIDENCE_REFS)
    request_source: Literal["NATIVE_REASONING_REQUEST_TASK_202"]

    @model_validator(mode="after")
    def _strict_request(self) -> NativeReasoningRequest:
        if not _FINGERPRINT_RE.fullmatch(self.context_fingerprint):
            raise ValueError("context_fingerprint is invalid")
        if not _TASK_ID_RE.fullmatch(self.task_id):
            raise ValueError("task_id is invalid")
        if not _is_sorted_unique_uuids(self.evidence_ids):
            raise ValueError("evidence_ids must be unique and sorted")
        return self


class NativeReasoningResult(BaseModel):
    """Strict immutable native reasoning result (Task 202).

    Status semantics follow the architecture document: SUPPORTED
    (backed by explicit evidence), CONTRADICTED (readable
    incompatibility), INSUFFICIENT (necessary evidence missing or
    unbound), ABSTAINED (no justified basis -- explicit abstention),
    UNAVAILABLE (could not be evaluated). The advisory suggestion,
    when present, is not evidence and never promotes an
    unsupported conclusion.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_id: UUID
    request_id: UUID
    session_id: UUID
    context_fingerprint: str = Field(min_length=64, max_length=64)
    status: NativeReasoningStatus
    reason_code: NativeReasoningReasonCode
    uncertainty: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    supporting_evidence_ids: tuple[UUID, ...] = Field(max_length=MAX_EVIDENCE_REFS)
    contradicting_evidence_ids: tuple[UUID, ...] = Field(max_length=MAX_EVIDENCE_REFS)
    missing_information_ids: tuple[str, ...] = Field(max_length=MAX_MISSING_IDS)
    rule_id: str | None = Field(default=None, max_length=MAX_RULE_ID_LENGTH)
    suggestion_text: str | None = Field(default=None, max_length=MAX_SUGGESTION_LENGTH)
    result_source: Literal["NATIVE_REASONING_RESULT_TASK_202"]

    @model_validator(mode="after")
    def _strict_result(self) -> NativeReasoningResult:
        if not _FINGERPRINT_RE.fullmatch(self.context_fingerprint):
            raise ValueError("context_fingerprint is invalid")
        allowed = _STATUS_REASON_MATRIX.get(self.status, frozenset())
        if self.reason_code not in allowed:
            raise ValueError("reason_code is not allowed for status")
        if not _is_sorted_unique_uuids(self.supporting_evidence_ids):
            raise ValueError("supporting_evidence_ids must be unique and sorted")
        if not _is_sorted_unique_uuids(self.contradicting_evidence_ids):
            raise ValueError("contradicting_evidence_ids must be unique and sorted")
        if not _is_sorted_unique_strs(self.missing_information_ids):
            raise ValueError("missing_information_ids must be unique and sorted")
        for missing_id in self.missing_information_ids:
            if len(missing_id) > MAX_MISSING_ID_LENGTH:
                raise ValueError("missing_information_ids entry is invalid")
            if not _MISSING_ID_RE.fullmatch(missing_id):
                raise ValueError("missing_information_ids entry is invalid")
        supporting = {str(v) for v in self.supporting_evidence_ids}
        contradicting = {str(v) for v in self.contradicting_evidence_ids}
        if supporting & contradicting:
            raise ValueError("evidence ids must not overlap across stances")
        if self.rule_id is not None:
            if not _RULE_ID_RE.fullmatch(self.rule_id):
                raise ValueError("rule_id is invalid")
        if self.suggestion_text is not None:
            if not 1 <= len(self.suggestion_text) <= MAX_SUGGESTION_LENGTH:
                raise ValueError("suggestion_text is invalid")
            if "\n" in self.suggestion_text or "\r" in self.suggestion_text:
                raise ValueError("suggestion_text is invalid")

        status = self.status
        has_supporting = len(self.supporting_evidence_ids) > 0
        has_contradicting = len(self.contradicting_evidence_ids) > 0
        has_missing = len(self.missing_information_ids) > 0

        if status == "SUPPORTED":
            if not has_supporting or has_contradicting or has_missing:
                raise ValueError("SUPPORTED has an invalid field combination")
            if self.rule_id is None:
                raise ValueError("SUPPORTED requires rule_id")
        elif status == "CONTRADICTED":
            if not has_supporting or not has_contradicting or has_missing:
                raise ValueError("CONTRADICTED has an invalid field combination")
            if self.rule_id is None:
                raise ValueError("CONTRADICTED requires rule_id")
        elif status == "INSUFFICIENT":
            if has_contradicting or not has_missing:
                raise ValueError("INSUFFICIENT has an invalid field combination")
            if self.rule_id is not None:
                raise ValueError("INSUFFICIENT must not carry rule_id")
        elif status == "ABSTAINED":
            if has_supporting or has_contradicting:
                raise ValueError("ABSTAINED must not carry evidence")
            if self.rule_id is not None:
                raise ValueError("ABSTAINED must not carry rule_id")
        elif status == "UNAVAILABLE":
            if has_supporting or has_contradicting or has_missing:
                raise ValueError("UNAVAILABLE must not carry evidence")
            if self.rule_id is not None:
                raise ValueError("UNAVAILABLE must not carry rule_id")
            if self.suggestion_text is not None:
                raise ValueError("UNAVAILABLE must not carry a suggestion")
        return self


class NativeReasoningError(BaseModel):
    """Stable public native reasoning error (Task 202).

    Messages are canonical per code so no exception text, path,
    secret, or request content can leak. Retryability is fixed per
    code: only UNAVAILABLE (inputs may become available) is
    retryable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_code: NativeReasoningErrorCode
    message: str = Field(min_length=1, max_length=300)
    retryable: bool
    request_id: UUID | None = None
    session_id: UUID | None = None
    error_source: Literal["NATIVE_REASONING_ERROR_TASK_202"]

    @model_validator(mode="after")
    def _strict_error(self) -> NativeReasoningError:
        expected_message = _ERROR_MESSAGES.get(self.error_code)
        if expected_message is None or self.message != expected_message:
            raise ValueError("message is not the canonical message for error_code")
        expected_retryable = _ERROR_RETRYABILITY.get(self.error_code)
        if self.retryable is not expected_retryable:
            raise ValueError("retryable does not match error_code")
        return self


__all__ = [
    "MAX_EVIDENCE_REFS",
    "MAX_MISSING_IDS",
    "MAX_SUGGESTION_LENGTH",
    "NATIVE_REASONING_ERROR_SOURCE_TASK_202",
    "NATIVE_REASONING_REQUEST_SOURCE_TASK_202",
    "NATIVE_REASONING_RESULT_SOURCE_TASK_202",
    "NativeReasoningError",
    "NativeReasoningErrorCode",
    "NativeReasoningReasonCode",
    "NativeReasoningRequest",
    "NativeReasoningResult",
    "NativeReasoningStatus",
]

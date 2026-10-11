"""Task 202 strict contracts for native reasoning; data-only, no runtime."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

CONTRACT_VERSION = "1"
MAX_EVIDENCE_REFERENCES = 256
MAX_REASON_CODES = 64
MAX_SUGGESTIONS = 32
MAX_MISSING_INFORMATION_ITEMS = 64


class NativeReasoningTask(StrEnum):
    CLASSIFY = "CLASSIFY"
    COMPARE = "COMPARE"
    EVALUATE_EVIDENCE = "EVALUATE_EVIDENCE"


class NativeReasoningStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNAVAILABLE = "UNAVAILABLE"
    ABSTAINED = "ABSTAINED"
    UNKNOWN = "UNKNOWN"


class NativeReasoningUncertainty(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNASSESSED = "UNASSESSED"


class NativeReasonCode(StrEnum):
    RULE_MATCH = "RULE_MATCH"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_UNREADABLE = "EVIDENCE_UNREADABLE"
    EVIDENCE_NOT_BOUND = "EVIDENCE_NOT_BOUND"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    EXPLICIT_ABSTENTION = "EXPLICIT_ABSTENTION"
    NO_APPLICABLE_RULE = "NO_APPLICABLE_RULE"


class NativeReasoningSuggestionKind(StrEnum):
    CANDIDATE_LABEL = "CANDIDATE_LABEL"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    EVIDENCE_TAG = "EVIDENCE_TAG"
    ALTERNATIVE_INTERPRETATION = "ALTERNATIVE_INTERPRETATION"


class NativeReasoningErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"


class NativeReasoningRequest(BaseModel):
    """Shape contract only; callers validate identity and evidence binding."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1"]
    request_id: UUID
    session_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    task: NativeReasoningTask
    evidence_ids: list[UUID] = Field(max_length=MAX_EVIDENCE_REFERENCES)
    input_summary: StrictStr = Field(min_length=1, max_length=4000)

    @field_validator("input_summary")
    @classmethod
    def _nonblank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input_summary must not be blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def _unique_evidence_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("evidence_ids must not contain duplicates")
        return value


class NativeReasoningSuggestion(BaseModel):
    """Explicitly advisory; this record is not evidence or a conclusion."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: NativeReasoningSuggestionKind
    value: StrictStr = Field(min_length=1, max_length=1000)
    reason_code: NativeReasonCode
    uncertainty: NativeReasoningUncertainty
    advisory_only: Literal[True]

    @field_validator("value")
    @classmethod
    def _nonblank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("suggestion value must not be blank")
        return value


class NativeReasoningResult(BaseModel):
    """Deterministic result envelope; references are not verified by this schema."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal["1"]
    request_id: UUID
    session_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: NativeReasoningStatus
    conclusion: StrictStr | None = Field(max_length=4000)
    reason_codes: list[NativeReasonCode] = Field(max_length=MAX_REASON_CODES)
    evidence_ids: list[UUID] = Field(max_length=MAX_EVIDENCE_REFERENCES)
    missing_information: list[StrictStr] = Field(max_length=MAX_MISSING_INFORMATION_ITEMS)
    uncertainty: NativeReasoningUncertainty
    abstention_reason: StrictStr | None = Field(max_length=1000)
    suggestions: list[NativeReasoningSuggestion] = Field(max_length=MAX_SUGGESTIONS)

    @field_validator("conclusion", "abstention_reason")
    @classmethod
    def _optional_text_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional text must not be blank when present")
        return value

    @field_validator("missing_information")
    @classmethod
    def _canonical_missing_information(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError("missing-information items must be nonblank and <= 500 chars")
        if len(set(value)) != len(value) or value != sorted(value):
            raise ValueError("missing_information must be sorted and unique")
        return value

    @model_validator(mode="after")
    def _coherent_result(self) -> NativeReasoningResult:
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must not contain duplicates")
        if self.reason_codes != sorted(self.reason_codes, key=lambda item: item.value):
            raise ValueError("reason_codes must be sorted by canonical value")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must not contain duplicates")
        if self.evidence_ids != sorted(self.evidence_ids, key=str):
            raise ValueError("evidence_ids must be sorted by canonical UUID")

        conclusive = self.status in (
            NativeReasoningStatus.SUPPORTED,
            NativeReasoningStatus.CONTRADICTED,
        )
        if conclusive:
            if self.conclusion is None or not self.evidence_ids:
                raise ValueError("conclusive results require conclusion and evidence")
            if self.status == NativeReasoningStatus.CONTRADICTED and len(self.evidence_ids) < 2:
                raise ValueError("CONTRADICTED requires at least two evidence references")
            if self.uncertainty == NativeReasoningUncertainty.UNASSESSED:
                raise ValueError("conclusive results require assessed uncertainty")
        elif self.conclusion is not None:
            raise ValueError("non-conclusive statuses must not publish a conclusion")

        has_conflict = NativeReasonCode.CONFLICTING_EVIDENCE in self.reason_codes
        if (self.status == NativeReasoningStatus.CONTRADICTED) != has_conflict:
            raise ValueError("CONFLICTING_EVIDENCE is required only for CONTRADICTED")

        if self.status == NativeReasoningStatus.INSUFFICIENT_EVIDENCE:
            if not self.missing_information:
                raise ValueError("INSUFFICIENT_EVIDENCE requires missing_information")
            if not {
                NativeReasonCode.EVIDENCE_MISSING,
                NativeReasonCode.INSUFFICIENT_SUPPORT,
            }.intersection(self.reason_codes):
                raise ValueError("insufficient evidence requires an insufficiency reason")
        elif self.missing_information and self.status not in (
            NativeReasoningStatus.UNAVAILABLE,
            NativeReasoningStatus.ABSTAINED,
            NativeReasoningStatus.UNKNOWN,
        ):
            raise ValueError("missing_information is invalid for this status")

        if self.status == NativeReasoningStatus.ABSTAINED:
            if self.abstention_reason is None:
                raise ValueError("ABSTAINED requires abstention_reason")
            if NativeReasonCode.EXPLICIT_ABSTENTION not in self.reason_codes:
                raise ValueError("ABSTAINED requires EXPLICIT_ABSTENTION")
        elif self.abstention_reason is not None:
            raise ValueError("abstention_reason is only valid for ABSTAINED")

        if self.status in (NativeReasoningStatus.UNAVAILABLE, NativeReasoningStatus.UNKNOWN):
            if not self.reason_codes:
                raise ValueError(f"{self.status.value} requires a reason code")
        return self


class NativeReasoningError(BaseModel):
    """Safe error envelope; raw exception text and arbitrary payloads are excluded."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal["1"]
    request_id: UUID | None
    code: NativeReasoningErrorCode
    message: StrictStr = Field(min_length=1, max_length=500)
    retryable: StrictBool

    @field_validator("message")
    @classmethod
    def _nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value

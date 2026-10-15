"""Task 213: strict advisory adapter contracts.

Data-only contracts for the boundary that validates untrusted Task 212
``InferenceResult`` records and converts an admissible model suggestion
into an explicitly advisory-only record. No runtime, no model, no
network, and no identity or provenance derived from model output.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

ADVISORY_CONTRACT_VERSION = "1"
MAX_MAPPING_ENTRIES = 64
MAX_LABEL_LENGTH = 100
MAX_APPROVED_LABELS = 256


class AdvisoryErrorCode(StrEnum):
    """Stable, sanitized adapter failure codes (Task 213)."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"


class AdvisoryRejectionReason(StrEnum):
    """Why an otherwise well-formed model output is not admissible.

    Rejection is not failure: it is the explicit, truthful alternative
    to admitting a suggestion the deterministic context cannot support.
    """

    CONTEXT_CONTRADICTED = "CONTEXT_CONTRADICTED"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"
    CONTEXT_ABSTAINED = "CONTEXT_ABSTAINED"
    CONTEXT_UNKNOWN = "CONTEXT_UNKNOWN"
    UNMAPPED_WINNING_CLASS = "UNMAPPED_WINNING_CLASS"


def _is_valid_label(value: str) -> bool:
    return value == value.strip() and value.isprintable()


class AdvisoryClassLabelEntry(BaseModel):
    """One explicitly configured class index to label entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    class_index: StrictInt = Field(ge=0)
    label: StrictStr = Field(min_length=1, max_length=MAX_LABEL_LENGTH)

    @field_validator("label")
    @classmethod
    def _nonblank_label(cls, value: str) -> str:
        if not value.strip() or not _is_valid_label(value):
            raise ValueError("mapping label is invalid")
        return value


class AdvisoryClassLabelMapping(BaseModel):
    """Explicit, versioned class-index to label configuration.

    This is caller-supplied configuration, not model output and not an
    approved semantic claim. No production class-label mapping is
    approved by the project yet (see docs/task-213-advisory-adapter.md);
    without an approved mapping instance the adapter produces no labels.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    mapping_id: StrictStr = Field(min_length=1, max_length=100)
    num_classes: StrictInt = Field(ge=2)
    entries: tuple[AdvisoryClassLabelEntry, ...] = Field(
        min_length=1, max_length=MAX_MAPPING_ENTRIES
    )

    @field_validator("mapping_id")
    @classmethod
    def _nonblank_mapping_id(cls, value: str) -> str:
        if not value.strip() or not _is_valid_label(value):
            raise ValueError("mapping_id is invalid")
        return value

    @field_validator("entries")
    @classmethod
    def _canonical_entries(
        cls, value: tuple[AdvisoryClassLabelEntry, ...]
    ) -> tuple[AdvisoryClassLabelEntry, ...]:
        indices = [entry.class_index for entry in value]
        labels = [entry.label for entry in value]
        if len(set(indices)) != len(indices):
            raise ValueError("mapping class indices must be unique")
        if len(set(labels)) != len(labels):
            raise ValueError("mapping labels must be unique")
        if value != tuple(sorted(value, key=lambda entry: entry.class_index)):
            raise ValueError("mapping entries must be sorted by class_index")
        return value

    @model_validator(mode="after")
    def _indices_within_model(self) -> AdvisoryClassLabelMapping:
        for entry in self.entries:
            if entry.class_index >= self.num_classes:
                raise ValueError("mapping class index exceeds the model class count")
        return self


class AdvisoryModelSuggestion(BaseModel):
    """A validated candidate label. Advisory-only by construction.

    The Task 202 ``NativeReasoningSuggestion`` contract was designed
    for rule-produced suggestions and its reason-code vocabulary has no
    honest value for a model-derived label, so this separate advisory
    contract is used instead of weakening the existing schema. It
    carries no evidence references, no identity fields, and no status:
    a suggestion is not evidence and not a finding.

    ``softmax_score`` is a relative normalized model-output score, not a
    calibrated confidence or a true probability that the candidate is
    correct.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_label: StrictStr = Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    softmax_score: StrictFloat = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Normalized relative model-output score; not calibrated confidence "
            "or probability that the candidate is correct."
        ),
    )
    advisory_only: Literal[True]


class AdvisoryAdapterResult(BaseModel):
    """The adapter's published record, bound to trusted caller identity.

    ``request_id``, ``session_id`` and ``context_fingerprint`` are
    copied from the validated caller request, never from model output:
    raw logits carry no identity, so this binding is caller-supplied
    association established at the adapter boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    artifact_id: StrictStr = Field(min_length=1, max_length=64)
    request_id: UUID
    session_id: UUID
    context_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    admissible: StrictBool
    suggestion: AdvisoryModelSuggestion | None = None
    rejection_reason: AdvisoryRejectionReason | None = None

    @model_validator(mode="after")
    def _admissibility_is_unambiguous(self) -> AdvisoryAdapterResult:
        if self.admissible:
            if self.suggestion is None or self.rejection_reason is not None:
                raise ValueError("an admissible result requires exactly one suggestion")
        else:
            if self.suggestion is not None or self.rejection_reason is None:
                raise ValueError(
                    "a non-admissible result requires exactly one rejection reason"
                )
        return self


__all__ = [
    "ADVISORY_CONTRACT_VERSION",
    "AdvisoryAdapterResult",
    "AdvisoryClassLabelEntry",
    "AdvisoryClassLabelMapping",
    "AdvisoryErrorCode",
    "AdvisoryModelSuggestion",
    "AdvisoryRejectionReason",
]

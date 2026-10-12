"""Task 213: strict validation for advisory model suggestions.

Model output remains untrusted. This boundary checks identity, label-space,
ordering, threshold and score constraints but never converts suggestions into
evidence, diagnoses, conclusions, or authorization.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr, field_validator, model_validator

from rop.native_inference import NativeInferenceResponse, NativeLabelScore

MAX_LABELS = 32


class SuggestionValidationError(Exception):
    """Stable, privacy-safe suggestion validation failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


class SuggestionValidationPolicy(BaseModel):
    """Predeclared validation policy for one candidate task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    task_id: StrictStr = Field(min_length=1, max_length=100)
    expected_model_version: StrictStr = Field(min_length=1, max_length=32)
    expected_vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_labels: tuple[StrictStr, ...] = Field(min_length=2, max_length=MAX_LABELS)
    minimum_probability: StrictFloat = Field(ge=0.0, le=1.0)
    maximum_suggestions: int = Field(ge=1, le=MAX_LABELS)

    @field_validator("allowed_labels")
    @classmethod
    def _canonical_label_space(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not label.strip() for label in value) or len(set(value)) != len(value):
            raise ValueError("allowed labels must be unique and nonblank")
        if value != tuple(sorted(value)):
            raise ValueError("allowed labels must be sorted canonically")
        return value


class ValidatedSuggestion(BaseModel):
    """A structurally validated but still untrusted suggestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr = Field(min_length=1, max_length=100)
    probability: StrictFloat = Field(ge=0.0, le=1.0)


class ValidatedSuggestionSet(BaseModel):
    """Safe projection for downstream advisory display only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    task_id: StrictStr = Field(min_length=1, max_length=100)
    model_version: StrictStr = Field(min_length=1, max_length=32)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    suggestions: tuple[ValidatedSuggestion, ...] = Field(max_length=MAX_LABELS)
    result_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["ADVISORY"] = "ADVISORY"
    trusted_evidence: Literal[False] = False
    clinical_decision: Literal[False] = False

    @model_validator(mode="after")
    def _canonical_suggestions(self) -> ValidatedSuggestionSet:
        labels = [item.label for item in self.suggestions]
        if len(set(labels)) != len(labels):
            raise ValueError("suggestions must use unique labels")
        if self.suggestions != tuple(sorted(self.suggestions, key=lambda item: (-item.probability, item.label))):
            raise ValueError("suggestions must be canonically ordered")
        return self


def validate_suggestion_response(
    response: NativeInferenceResponse,
    policy: SuggestionValidationPolicy,
) -> ValidatedSuggestionSet:
    """Validate one inference response against a predeclared task policy."""
    if response.advisory_only is not True:
        raise SuggestionValidationError("ADVISORY_FLAG_REQUIRED", "model output must remain advisory-only")
    if response.model_version != policy.expected_model_version:
        raise SuggestionValidationError("MODEL_VERSION_MISMATCH", "model version does not match the declared policy")
    if response.vocabulary_hash != policy.expected_vocabulary_hash:
        raise SuggestionValidationError("VOCABULARY_HASH_MISMATCH", "vocabulary hash does not match the declared policy")
    if len(response.scores) > policy.maximum_suggestions:
        raise SuggestionValidationError("TOO_MANY_SUGGESTIONS", "response exceeds the declared suggestion limit")
    allowed = set(policy.allowed_labels)
    labels = [score.label for score in response.scores]
    if len(set(labels)) != len(labels):
        raise SuggestionValidationError("DUPLICATE_LABEL", "response contains duplicate labels")
    if any(label not in allowed for label in labels):
        raise SuggestionValidationError("LABEL_OUT_OF_SPACE", "response contains a label outside the declared task")
    if any(score.probability < policy.minimum_probability for score in response.scores):
        raise SuggestionValidationError("BELOW_THRESHOLD", "response contains a score below the declared threshold")
    if response.scores != tuple(sorted(response.scores, key=lambda item: (-item.probability, item.label))):
        raise SuggestionValidationError("NONCANONICAL_ORDER", "response scores are not canonically ordered")
    suggestions = tuple(
        ValidatedSuggestion(label=score.label, probability=score.probability)
        for score in response.scores
    )
    payload = {
        "task_id": policy.task_id,
        "model_version": response.model_version,
        "vocabulary_hash": response.vocabulary_hash,
        "suggestions": [item.model_dump(mode="json") for item in suggestions],
        "status": "ADVISORY",
        "trusted_evidence": False,
        "clinical_decision": False,
    }
    result_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ValidatedSuggestionSet(
        task_id=policy.task_id,
        model_version=response.model_version,
        vocabulary_hash=response.vocabulary_hash,
        suggestions=suggestions,
        result_hash=result_hash,
    )


__all__ = [
    "SuggestionValidationError",
    "SuggestionValidationPolicy",
    "ValidatedSuggestion",
    "ValidatedSuggestionSet",
    "validate_suggestion_response",
]

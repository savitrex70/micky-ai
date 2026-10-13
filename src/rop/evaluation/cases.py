"""Task 206: strict versioned evaluation case contracts.

A case set is a versioned JSON document of independently authored
cases. Structural validation lives here; composition-rule
strictness stays with the service dataclasses, which the loader
invokes eagerly so a malformed file fails whole before any
evaluation runs. No model, network, or database involvement.
"""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rop.schemas.native_binding import NativeEvidenceBinding

CASE_SET_VERSION = "1.0"

_CASE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")

EvaluationCategory = Literal[
    "supported", "contradiction", "insufficient", "abstention", "invalid-input"
]

ExpectedStatus = Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT", "ABSTAINED"]

ExpectedReason = Literal[
    "RULE_MATCH", "RULE_CONTRADICTION_FOUND", "EVIDENCE_MISSING", "NO_JUSTIFIED_BASIS"
]

# A valid case's scenario label must agree with its expected
# outcome; contradictory labels are rejected at load, before any
# evaluation begins. Reason codes are bound to statuses by the same
# compatibility matrix the Task 202 contract enforces.
_CATEGORY_STATUS: dict[str, str] = {
    "supported": "SUPPORTED",
    "contradiction": "CONTRADICTED",
    "insufficient": "INSUFFICIENT",
    "abstention": "ABSTAINED",
}

_STATUS_REASON: dict[str, str] = {
    "SUPPORTED": "RULE_MATCH",
    "CONTRADICTED": "RULE_CONTRADICTION_FOUND",
    "INSUFFICIENT": "EVIDENCE_MISSING",
    "ABSTAINED": "NO_JUSTIFIED_BASIS",
}


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


def _sorted_unique_uuids(values: tuple[UUID, ...], field_name: str) -> None:
    texts = [str(value) for value in values]
    if len(set(texts)) != len(texts) or texts != sorted(texts):
        raise ValueError(f"{field_name} is invalid")


class ConditionDecl(BaseModel):
    """Declared support-rule condition, mirroring the service contract shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    min_evidence_count: int
    expected_content: str = Field(min_length=1, max_length=2000)

    @field_validator("min_evidence_count", mode="before")
    @classmethod
    def _strict_count(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "count")


class SupportRuleDecl(BaseModel):
    """Declared support rule; strictness enforced by the service class at load."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=64)
    condition: ConditionDecl
    uncertainty: float

    @field_validator("uncertainty", mode="before")
    @classmethod
    def _strict_uncertainty(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "uncertainty")


class ContradictionRuleDecl(BaseModel):
    """Declared contradiction-pair rule; strictness enforced at load."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=64)
    affirming_content: str = Field(min_length=1, max_length=2000)
    denying_content: str = Field(min_length=1, max_length=2000)
    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    min_evidence_count: int
    uncertainty: float

    @field_validator("min_evidence_count", mode="before")
    @classmethod
    def _strict_count(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "count")

    @field_validator("uncertainty", mode="before")
    @classmethod
    def _strict_uncertainty(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "uncertainty")


class RequirementDecl(BaseModel):
    """Declared missing-information requirement; strictness enforced at load."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=64)
    task_id: str = Field(min_length=1, max_length=64)
    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    expected_content: str = Field(min_length=1, max_length=2000)


class EvaluationCase(BaseModel):
    """One independently authored evaluation case (Task 206).

    Valid cases carry a validated binding, an explicit composition
    configuration, and exact expected outcomes. The scenario
    ``category`` must agree with ``expected_status`` (supported →
    SUPPORTED, contradiction → CONTRADICTED, insufficient →
    INSUFFICIENT, abstention → ABSTAINED), and the expected reason
    code must be the compatible one for that status; inconsistent
    labels are rejected at load. Invalid-input cases carry a raw
    payload plus the expected typed-error invariant and are scored
    separately from predictions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=64)
    case_set_version: Literal["1.0"]
    category: EvaluationCategory
    description: str = Field(min_length=1, max_length=280)
    binding: NativeEvidenceBinding | None = None
    raw_binding: dict | None = None
    support_rules: tuple[SupportRuleDecl, ...] = ()
    contradiction_rules: tuple[ContradictionRuleDecl, ...] = ()
    requirements: tuple[RequirementDecl, ...] = ()
    expected_status: ExpectedStatus | None = None
    expected_reason: ExpectedReason | None = None
    expected_supporting: tuple[UUID, ...] = ()
    expected_contradicting: tuple[UUID, ...] = ()
    expected_missing: tuple[str, ...] = ()
    expect_error: Literal["INVALID_BINDING"] | None = None

    @model_validator(mode="after")
    def _strict_case(self) -> EvaluationCase:
        if not _CASE_ID_RE.fullmatch(self.case_id):
            raise ValueError("case_id is invalid")
        if self.category == "invalid-input":
            if self.raw_binding is None or not isinstance(self.raw_binding, dict):
                raise ValueError("raw_binding is invalid")
            if self.binding is not None:
                raise ValueError("binding is invalid")
            if self.expect_error is None:
                raise ValueError("expect_error is invalid")
            if self.expected_status is not None or self.expected_reason is not None:
                raise ValueError("expected outcome is invalid")
            if self.expected_supporting or self.expected_contradicting:
                raise ValueError("expected outcome is invalid")
            if self.expected_missing:
                raise ValueError("expected outcome is invalid")
            if self.support_rules or self.contradiction_rules or self.requirements:
                raise ValueError("composition configuration is invalid")
        else:
            if self.binding is None:
                raise ValueError("binding is invalid")
            if self.raw_binding is not None:
                raise ValueError("raw_binding is invalid")
            if self.expect_error is not None:
                raise ValueError("expect_error is invalid")
            if self.expected_status is None or self.expected_reason is None:
                raise ValueError("expected outcome is invalid")
            if _CATEGORY_STATUS[self.category] != self.expected_status:
                raise ValueError("category and expected status are inconsistent")
            if _STATUS_REASON[self.expected_status] != self.expected_reason:
                raise ValueError("expected status and reason are inconsistent")
            _sorted_unique_uuids(self.expected_supporting, "expected_supporting")
            _sorted_unique_uuids(self.expected_contradicting, "expected_contradicting")
        return self


class EvaluationCaseSet(BaseModel):
    """One versioned set of evaluation cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_set_id: str = Field(min_length=1, max_length=64)
    case_set_version: Literal["1.0"]
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _strict_set(self) -> EvaluationCaseSet:
        if not _CASE_ID_RE.fullmatch(self.case_set_id):
            raise ValueError("case_set_id is invalid")
        seen = {case.case_id for case in self.cases}
        if len(seen) != len(self.cases):
            raise ValueError("case identifiers must be unique")
        return self


__all__ = [
    "CASE_SET_VERSION",
    "ConditionDecl",
    "ContradictionRuleDecl",
    "EvaluationCase",
    "EvaluationCaseSet",
    "EvaluationCategory",
    "ExpectedReason",
    "ExpectedStatus",
    "RequirementDecl",
    "SupportRuleDecl",
]

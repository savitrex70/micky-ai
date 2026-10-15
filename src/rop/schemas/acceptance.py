"""Task 215: end-to-end evaluation acceptance gate contracts.

Data-only contracts for the deterministic, fail-closed acceptance
decision over an existing Task 214 benchmark report and an existing
Task 206 baseline evaluation report. No inference, no model, no
network, and no clinical logic live here.

Acceptance means every mandatory criterion evaluated to pass on the
supplied validated evidence. The ``evaluation-thresholds`` criterion
always includes the Task 206 baseline integrity gates named in
``MANDATORY_EVALUATION_THRESHOLD_IDS``; a policy can only add
requirements to that set, never replace or omit it. Acceptance is not
a claim of model accuracy, safety, clinical utility, or readiness: the
underlying evidence is synthetic-scope, resource measurements describe
only the exercised code path, and traced Python memory is not process
RSS. Model-evaluation thresholds legitimately remain ``pending`` and
are never required to pass here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

ACCEPTANCE_CONTRACT_VERSION = "1"
MAX_CRITERIA = 16
MAX_BLOCKER_LENGTH = 120

AcceptanceCriterionId = Literal[
    "benchmark-contract-version",
    "benchmark-report-integrity",
    "benchmark-report-pinned",
    "benchmark-identity",
    "benchmark-budget-within",
    "benchmark-offline-mode",
    "evaluation-contract-version",
    "evaluation-report-integrity",
    "evaluation-report-pinned",
    "evaluation-identity",
    "evaluation-run-valid",
    "evaluation-thresholds",
    "evaluation-determinism",
    "no-clinical-or-acceptance-claim",
    "evidence-scope-synthetic",
]

MANDATORY_CRITERIA: tuple[str, ...] = (
    "benchmark-contract-version",
    "benchmark-report-integrity",
    "benchmark-report-pinned",
    "benchmark-identity",
    "benchmark-budget-within",
    "benchmark-offline-mode",
    "evaluation-contract-version",
    "evaluation-report-integrity",
    "evaluation-report-pinned",
    "evaluation-identity",
    "evaluation-run-valid",
    "evaluation-thresholds",
    "evaluation-determinism",
    "no-clinical-or-acceptance-claim",
    "evidence-scope-synthetic",
)

AcceptanceDecision = Literal["PASS", "FAIL"]

MANDATORY_EVALUATION_THRESHOLD_IDS: tuple[str, ...] = (
    "determinism",
    "invalid-input-all-pass",
    "run-valid",
    "baseline-self-consistency",
    "unsupported-references-zero",
)
"""Task 206 baseline gates the gate always requires to have ``passed``.

These are the versioned, non-model baseline integrity thresholds the
Task 206 harness actually emits with a real ``passed``/``failed``
status. Requiring them at the gate level keeps an acceptance policy
from weakening the baseline by omitting them from its own
``required_threshold_ids``; caller-supplied threshold requirements
are only ever additive. The pending model thresholds are deliberately
excluded: they have no passable status yet and must never be
fabricated as satisfied for synthetic evidence.
"""


class AcceptanceErrorCode(StrEnum):
    """Stable, sanitized acceptance failure codes (Task 215)."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_POLICY = "INVALID_POLICY"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    REPORT_INCONSISTENT = "REPORT_INCONSISTENT"


class AcceptancePolicy(BaseModel):
    """Versioned acceptance criteria and exact evidence expectations.

    Identity and digest expectations are checked against the validated
    reports; the report binds the actual validated values, never these
    caller-supplied expectations. Report-hash expectations pin the
    exact evidence the policy accepts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = ACCEPTANCE_CONTRACT_VERSION
    expected_artifact_id: StrictStr = Field(min_length=1, max_length=64)
    expected_vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_benchmark_config_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_case_set_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_benchmark_report_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_evaluation_case_set_id: StrictStr = Field(min_length=1, max_length=200)
    expected_evaluation_case_set_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    expected_evaluation_report_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    required_threshold_ids: tuple[StrictStr, ...] = Field(min_length=1, max_length=64)

    @field_validator("required_threshold_ids")
    @classmethod
    def _canonical_thresholds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for threshold_id in value:
            if not 1 <= len(threshold_id) <= 100:
                raise ValueError("required threshold id is invalid")
        if len(set(value)) != len(value):
            raise ValueError("required threshold ids must be unique")
        if value != tuple(sorted(value)):
            raise ValueError("required threshold ids must be sorted")
        return value


class CriterionOutcome(BaseModel):
    """One evaluated mandatory criterion and its disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: AcceptanceCriterionId
    passed: StrictBool
    reason: StrictStr = Field(min_length=1, max_length=MAX_BLOCKER_LENGTH)


class AcceptanceReport(BaseModel):
    """Validated, immutable acceptance decision with bounded results.

    Identity fields are copied from the validated evidence reports,
    never from caller strings. ``gate_digest`` binds the policy, the
    exact evidence hashes, and the criterion outcomes so the decision
    can be independently rechecked.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = ACCEPTANCE_CONTRACT_VERSION
    decision: AcceptanceDecision
    artifact_id: StrictStr = Field(min_length=1, max_length=64)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_config_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    case_set_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_report_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_case_set_id: StrictStr = Field(min_length=1, max_length=200)
    evaluation_case_set_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_report_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    criteria: tuple[CriterionOutcome, ...] = Field(
        min_length=len(MANDATORY_CRITERIA), max_length=MAX_CRITERIA
    )
    limitations: tuple[StrictStr, ...] = Field(min_length=1, max_length=32)
    gate_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _decision_is_truthful(self) -> AcceptanceReport:
        seen = [outcome.criterion_id for outcome in self.criteria]
        if sorted(seen) != sorted(MANDATORY_CRITERIA) or len(set(seen)) != len(seen):
            raise ValueError(
                "acceptance criteria must cover every mandatory criterion exactly once"
            )
        expected = all(outcome.passed for outcome in self.criteria)
        if (self.decision == "PASS") is not expected:
            raise ValueError("acceptance decision contradicts the criterion outcomes")
        return self


__all__ = [
    "ACCEPTANCE_CONTRACT_VERSION",
    "MANDATORY_CRITERIA",
    "MANDATORY_EVALUATION_THRESHOLD_IDS",
    "AcceptanceCriterionId",
    "AcceptanceDecision",
    "AcceptanceErrorCode",
    "AcceptancePolicy",
    "AcceptanceReport",
    "CriterionOutcome",
]

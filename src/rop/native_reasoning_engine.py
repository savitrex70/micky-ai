"""Pure, deterministic composition for project-owned native reasoning rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
)

from rop.schemas.native_evidence import (
    NativeEvidenceBundle,
    NativeEvidenceRecord,
    validate_native_evidence_binding,
)
from rop.schemas.native_reasoning import (
    ALLOWED_REASON_CODES_BY_STATUS,
    MAX_MISSING_INFORMATION_ITEMS,
    RETRYABLE_BY_ERROR_CODE,
    NativeReasonCode,
    NativeReasoningError,
    NativeReasoningErrorCode,
    NativeReasoningErrorMessage,
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
    NativeReasoningTask,
    NativeReasoningUncertainty,
    assert_conclusive_reason_codes,
)

# Task 205 deterministic status precedence for composing rule findings.
# Contradictions outrank insufficiency; explicit abstention only survives as
# the sole semantics. Disagreements that survive the matrix degrade to
# INSUFFICIENT_EVIDENCE + INSUFFICIENT_SUPPORT (see _compose).
TASK_205_STATUS_PRIORITY: dict[NativeReasoningStatus, int] = {
    NativeReasoningStatus.SUPPORTED: 0,
    NativeReasoningStatus.CONTRADICTED: 1,
    NativeReasoningStatus.ABSTAINED: 2,
    NativeReasoningStatus.INSUFFICIENT_EVIDENCE: 3,
    NativeReasoningStatus.UNAVAILABLE: 4,
    NativeReasoningStatus.UNKNOWN: 5,
}

MAX_NATIVE_REASONING_RULES = 128
_RULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# Stable, bounded, static text; never derived from rule output or exceptions.
_RULE_DISAGREEMENT_MISSING_INFORMATION = (
    "Applicable rule outputs disagree; the disagreement cannot be classified "
    "under the current reasoning contract."
)
_UNCERTAINTY_ORDER = {
    NativeReasoningUncertainty.NONE: 0,
    NativeReasoningUncertainty.LOW: 1,
    NativeReasoningUncertainty.MODERATE: 2,
    NativeReasoningUncertainty.HIGH: 3,
    NativeReasoningUncertainty.UNASSESSED: 4,
}


class NativeRuleFinding(BaseModel):
    """One rule's proposed finding, validated before composition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: NativeReasoningStatus
    conclusion: StrictStr | None
    reason_codes: tuple[NativeReasonCode, ...] = Field(max_length=64)
    evidence_ids: tuple[UUID, ...] = Field(max_length=256)
    missing_information: tuple[StrictStr, ...] = Field(max_length=64)
    uncertainty: NativeReasoningUncertainty
    abstention_reason: StrictStr | None

    @field_validator("conclusion", "abstention_reason")
    @classmethod
    def _nonblank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("optional text must not be blank when present")
        return value

    @field_validator("reason_codes")
    @classmethod
    def _canonical_reason_codes(
        cls, value: tuple[NativeReasonCode, ...]
    ) -> tuple[NativeReasonCode, ...]:
        if len(set(value)) != len(value):
            raise ValueError("rule reason codes must not contain duplicates")
        if value != tuple(sorted(value, key=lambda item: item.value)):
            raise ValueError("rule reason codes must be canonically sorted")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def _canonical_evidence_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("rule evidence references must not contain duplicates")
        if value != tuple(sorted(value, key=str)):
            raise ValueError("rule evidence references must be canonically sorted")
        return value

    @field_validator("missing_information")
    @classmethod
    def _canonical_missing_information(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() or len(item) > 500 for item in value):
            raise ValueError(
                "missing-information items must be nonblank and <= 500 chars"
            )
        if len(set(value)) != len(value):
            raise ValueError("missing-information items must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("missing-information items must be canonically sorted")
        return value


class NativeReasoningRule(Protocol):
    """Explicitly injected deterministic rule; no discovery or global registry."""

    rule_id: str
    tasks: frozenset[NativeReasoningTask]

    def evaluate(
        self,
        request: NativeReasoningRequest,
        evidence: tuple[NativeEvidenceRecord, ...],
    ) -> NativeRuleFinding | None:
        """Return a finding when applicable, otherwise None."""


@dataclass(frozen=True)
class NativeReasoningExecution:
    """Immutable result plus the stable identifiers of rules that contributed."""

    result: NativeReasoningResult
    applied_rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class _BoundRule:
    rule_id: str
    tasks: frozenset[NativeReasoningTask]
    implementation: NativeReasoningRule


class NativeReasoningCompositionError(Exception):
    """Carries a safe, canonical error contract without raw exception text."""

    def __init__(self, error: NativeReasoningError) -> None:
        super().__init__(error.message.value)
        self.error = error


class NativeReasoningEngine:
    """Compose injected rules over bound evidence without persistence or networking."""

    def __init__(self, rules: Sequence[NativeReasoningRule]) -> None:
        if len(rules) > MAX_NATIVE_REASONING_RULES:
            raise ValueError("too many native reasoning rules")

        bound_rules: list[_BoundRule] = []
        rule_ids: list[str] = []
        for rule in rules:
            rule_id = getattr(rule, "rule_id", None)
            tasks = getattr(rule, "tasks", None)
            if not isinstance(rule_id, str) or not _RULE_ID_PATTERN.fullmatch(rule_id):
                raise ValueError("every rule must have a canonical rule_id")
            if not isinstance(tasks, frozenset) or not tasks:
                raise ValueError("every rule must declare a nonempty task set")
            if any(not isinstance(task, NativeReasoningTask) for task in tasks):
                raise ValueError("rule tasks must use NativeReasoningTask values")
            rule_ids.append(rule_id)
            bound_rules.append(_BoundRule(rule_id, tasks, rule))

        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule_id values must be unique")
        self._rules = tuple(sorted(bound_rules, key=lambda rule: rule.rule_id))

    def evaluate(
        self,
        request: NativeReasoningRequest,
        evidence_bundle: NativeEvidenceBundle,
    ) -> NativeReasoningResult:
        """Evaluate request-bound evidence and return a validated result."""
        return self.evaluate_with_trace(request, evidence_bundle).result

    def evaluate_with_trace(
        self,
        request: NativeReasoningRequest,
        evidence_bundle: NativeEvidenceBundle,
    ) -> NativeReasoningExecution:
        """Return a result with deterministic rule identifiers, without shared state."""
        # Errors are raised outside every `except` block so the original
        # exception is neither chained (__cause__) nor implicitly attached
        # (__context__); its text can never surface in a formatted traceback.
        binding_failed = False
        try:
            validate_native_evidence_binding(request, evidence_bundle)
        except ValueError:
            binding_failed = True
        if binding_failed:
            raise self._error(
                request.request_id, NativeReasoningErrorCode.INPUT_UNAVAILABLE
            )

        requested_ids = set(request.evidence_ids)
        evidence = tuple(
            sorted(
                (
                    record
                    for record in evidence_bundle.records
                    if record.evidence_id in requested_ids
                ),
                key=lambda record: str(record.evidence_id),
            )
        )
        findings: list[NativeRuleFinding] = []
        applied_rule_ids: list[str] = []
        for bound_rule in self._rules:
            if request.task not in bound_rule.tasks:
                continue
            failure: NativeReasoningErrorCode | None = None
            finding = None
            try:
                finding = bound_rule.implementation.evaluate(request, evidence)
            except ValidationError:
                failure = NativeReasoningErrorCode.CONTRACT_VIOLATION
            except Exception:
                failure = NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE
            if failure is not None:
                raise self._error(request.request_id, failure)
            if finding is None:
                continue
            if not isinstance(finding, NativeRuleFinding):
                raise self._error(
                    request.request_id, NativeReasoningErrorCode.CONTRACT_VIOLATION
                )
            if not set(finding.evidence_ids).issubset(requested_ids):
                raise self._error(
                    request.request_id, NativeReasoningErrorCode.CONTRACT_VIOLATION
                )
            finding_invalid = False
            try:
                self._result_from_finding(request, finding)
            except (ValidationError, ValueError):
                finding_invalid = True
            if finding_invalid:
                raise self._error(
                    request.request_id, NativeReasoningErrorCode.CONTRACT_VIOLATION
                )
            findings.append(finding)
            applied_rule_ids.append(bound_rule.rule_id)

        if not findings:
            result = self._result(
                request,
                status=NativeReasoningStatus.UNKNOWN,
                reason_codes=(NativeReasonCode.NO_APPLICABLE_RULE,),
                evidence_ids=(),
                missing_information=(),
                uncertainty=NativeReasoningUncertainty.UNASSESSED,
            )
        else:
            composed: NativeReasoningResult | None = None
            try:
                composed = self._compose(request, findings)
            except (ValidationError, ValueError):
                composed = None
            if composed is None:
                raise self._error(
                    request.request_id, NativeReasoningErrorCode.CONTRACT_VIOLATION
                )
            result = composed

        return NativeReasoningExecution(
            result=result,
            applied_rule_ids=tuple(applied_rule_ids),
        )

    def _compose(
        self,
        request: NativeReasoningRequest,
        findings: list[NativeRuleFinding],
    ) -> NativeReasoningResult:
        statuses = {finding.status for finding in findings}
        conclusions = {finding.conclusion for finding in findings}
        missing_information = tuple(
            sorted(
                {item for finding in findings for item in finding.missing_information}
            )
        )
        evidence_ids = tuple(
            sorted(
                {item for finding in findings for item in finding.evidence_ids},
                key=str,
            )
        )
        reason_codes = {code for finding in findings for code in finding.reason_codes}
        uncertainties = [finding.uncertainty for finding in findings]
        uncertainty = max(uncertainties, key=_UNCERTAINTY_ORDER.__getitem__)

        same_semantics = (
            len(statuses) == 1
            and len(conclusions) == 1
            and len({finding.abstention_reason for finding in findings}) == 1
        )
        if same_semantics:
            status = findings[0].status
            conclusion = findings[0].conclusion
            abstention_reason = findings[0].abstention_reason
            if status == NativeReasoningStatus.CONTRADICTED:
                reason_codes.add(NativeReasonCode.CONFLICTING_EVIDENCE)
            if status == NativeReasoningStatus.SUPPORTED:
                reason_codes.add(NativeReasonCode.RULE_MATCH)
            return self._result(
                request,
                status=status,
                conclusion=conclusion,
                reason_codes=tuple(reason_codes),
                evidence_ids=evidence_ids,
                missing_information=missing_information,
                uncertainty=uncertainty,
                abstention_reason=abstention_reason,
            )

        # Task 205 deterministic status precedence for a genuine disagreement.
        # A readable contradiction is never demoted to INSUFFICIENT_EVIDENCE
        # merely because another finding was insufficient; both statuses keep
        # their reason codes so the result stays distinguishable.
        top_priority = min(
            TASK_205_STATUS_PRIORITY[finding.status] for finding in findings
        )
        top_candidates = [
            finding
            for finding in findings
            if TASK_205_STATUS_PRIORITY[finding.status] == top_priority
        ]

        if len(top_candidates) == 1:
            winner = top_candidates[0]
            # Task 205: the winning status publishes only reason codes the
            # Task 202 matrix allows; loser evidence stays visible in
            # evidence_ids/missing_information but must not pollute the codes.
            winner_codes = (
                set(winner.reason_codes)
                & ALLOWED_REASON_CODES_BY_STATUS[winner.status.value]
            )
            if winner.status == NativeReasoningStatus.CONTRADICTED:
                winner_codes.add(NativeReasonCode.CONFLICTING_EVIDENCE)
                assert_conclusive_reason_codes(
                    winner.status,
                    winner_codes,
                    ALLOWED_REASON_CODES_BY_STATUS[winner.status.value],
                )
            elif winner.status == NativeReasoningStatus.SUPPORTED:
                winner_codes.add(NativeReasonCode.RULE_MATCH)
                assert_conclusive_reason_codes(
                    winner.status,
                    winner_codes,
                    ALLOWED_REASON_CODES_BY_STATUS[winner.status.value],
                )
            elif winner.status == NativeReasoningStatus.ABSTAINED:
                winner_codes.add(NativeReasonCode.EXPLICIT_ABSTENTION)
                assert_conclusive_reason_codes(
                    winner.status,
                    winner_codes,
                    ALLOWED_REASON_CODES_BY_STATUS[winner.status.value],
                )
            # Task 202 forbids missing_information on SUPPORTED/CONTRADICTED:
            # loser insufficiencies stay visible through evidence_ids/ finding
            # trace, not through a status-incompatible field.
            if winner.status in (
                NativeReasoningStatus.SUPPORTED,
                NativeReasoningStatus.CONTRADICTED,
            ):
                composed_missing_information: tuple[str, ...] = ()
            elif len(missing_information) > MAX_MISSING_INFORMATION_ITEMS:
                composed_missing_information = missing_information[
                    :MAX_MISSING_INFORMATION_ITEMS
                ]
            else:
                composed_missing_information = missing_information
            # Uncertainty: conclusive winners must quote an assessed level,
            # so UNASSESSED from non-conclusive losers is ignored for them.
            if winner.status in (
                NativeReasoningStatus.SUPPORTED,
                NativeReasoningStatus.CONTRADICTED,
            ):
                composed_uncertainty = max(
                    (
                        finding.uncertainty
                        for finding in top_candidates
                        if finding.uncertainty != NativeReasoningUncertainty.UNASSESSED
                    ),
                    key=_UNCERTAINTY_ORDER.__getitem__,
                    default=NativeReasoningUncertainty.HIGH,
                )
            else:
                composed_uncertainty = uncertainty
            return self._result(
                request,
                status=winner.status,
                conclusion=winner.conclusion,
                abstention_reason=winner.abstention_reason,
                reason_codes=tuple(winner_codes),
                evidence_ids=evidence_ids,
                missing_information=composed_missing_information,
                uncertainty=composed_uncertainty,
            )

        # Disagreement within the same precedence tier is not automatically a
        # contradiction. Task 205 keeps rule-disagreement conservative: the
        # composition fails closed with INSUFFICIENT_EVIDENCE and flags the
        # disagreement rather than inventing a contradiction or a false READY.
        retained = sorted(
            {
                item
                for item in missing_information
                if item != _RULE_DISAGREEMENT_MISSING_INFORMATION
            }
        )[: MAX_MISSING_INFORMATION_ITEMS - 1]
        return self._result(
            request,
            status=NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
            reason_codes=(NativeReasonCode.INSUFFICIENT_SUPPORT,),
            evidence_ids=evidence_ids,
            missing_information=(*retained, _RULE_DISAGREEMENT_MISSING_INFORMATION),
            uncertainty=NativeReasoningUncertainty.HIGH,
        )

    def _result_from_finding(
        self,
        request: NativeReasoningRequest,
        finding: NativeRuleFinding,
    ) -> NativeReasoningResult:
        return self._result(
            request,
            status=finding.status,
            conclusion=finding.conclusion,
            reason_codes=finding.reason_codes,
            evidence_ids=finding.evidence_ids,
            missing_information=finding.missing_information,
            uncertainty=finding.uncertainty,
            abstention_reason=finding.abstention_reason,
        )

    def _result(
        self,
        request: NativeReasoningRequest,
        *,
        status: NativeReasoningStatus,
        reason_codes: Sequence[NativeReasonCode],
        evidence_ids: Sequence[UUID],
        missing_information: Sequence[str],
        uncertainty: NativeReasoningUncertainty,
        conclusion: str | None = None,
        abstention_reason: str | None = None,
    ) -> NativeReasoningResult:
        return NativeReasoningResult.model_validate(
            {
                "contract_version": "1",
                "request_id": request.request_id,
                "session_id": request.session_id,
                "context_fingerprint": request.context_fingerprint,
                "status": status,
                "conclusion": conclusion,
                "reason_codes": sorted(set(reason_codes), key=lambda code: code.value),
                "evidence_ids": sorted(set(evidence_ids), key=str),
                "missing_information": sorted(set(missing_information)),
                "uncertainty": uncertainty,
                "abstention_reason": abstention_reason,
                "suggestions": [],
            }
        )

    @staticmethod
    def _error(
        request_id: UUID,
        code: NativeReasoningErrorCode,
    ) -> NativeReasoningCompositionError:
        return NativeReasoningCompositionError(
            NativeReasoningError(
                contract_version="1",
                request_id=request_id,
                code=code,
                message=NativeReasoningErrorMessage[code.name],
                retryable=RETRYABLE_BY_ERROR_CODE[code.value],
            )
        )

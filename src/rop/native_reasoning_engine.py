"""Pure, deterministic composition for project-owned native reasoning rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from rop.schemas.native_evidence import (
    NativeEvidenceBundle,
    NativeEvidenceRecord,
    validate_native_evidence_binding,
)
from rop.schemas.native_reasoning import (
    NativeReasonCode,
    NativeReasoningError,
    NativeReasoningErrorCode,
    NativeReasoningErrorMessage,
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
    NativeReasoningTask,
    NativeReasoningUncertainty,
)

MAX_NATIVE_REASONING_RULES = 128
_RULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
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
    conclusion: str | None
    reason_codes: tuple[NativeReasonCode, ...]
    evidence_ids: tuple[UUID, ...]
    missing_information: tuple[str, ...]
    uncertainty: NativeReasoningUncertainty
    abstention_reason: str | None


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

        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule_id values must be unique")
        self._rules = tuple(sorted(rules, key=lambda rule: rule.rule_id))

    def evaluate(
        self,
        request: NativeReasoningRequest,
        evidence_bundle: NativeEvidenceBundle,
    ) -> NativeReasoningResult:
        """Evaluate request-bound evidence and return a validated result."""
        try:
            validate_native_evidence_binding(request, evidence_bundle)
        except ValueError as exc:
            raise self._error(
                request.request_id, NativeReasoningErrorCode.INPUT_UNAVAILABLE
            ) from exc

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
        for rule in self._rules:
            if request.task not in rule.tasks:
                continue
            try:
                finding = rule.evaluate(request, evidence)
            except Exception as exc:
                raise self._error(
                    request.request_id, NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE
                ) from exc
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
            try:
                self._result_from_finding(request, finding)
            except (ValidationError, ValueError) as exc:
                raise self._error(
                    request.request_id, NativeReasoningErrorCode.CONTRACT_VIOLATION
                ) from exc
            findings.append(finding)

        if not findings:
            return self._result(
                request,
                status=NativeReasoningStatus.UNKNOWN,
                reason_codes=(NativeReasonCode.NO_APPLICABLE_RULE,),
                evidence_ids=(),
                missing_information=(),
                uncertainty=NativeReasoningUncertainty.UNASSESSED,
            )

        return self._compose(request, findings)

    def _compose(
        self,
        request: NativeReasoningRequest,
        findings: list[NativeRuleFinding],
    ) -> NativeReasoningResult:
        statuses = {finding.status for finding in findings}
        conclusions = {finding.conclusion for finding in findings}
        missing_information = tuple(
            sorted(
                {
                    item
                    for finding in findings
                    for item in finding.missing_information
                }
            )
        )
        evidence_ids = tuple(
            sorted(
                {item for finding in findings for item in finding.evidence_ids},
                key=str,
            )
        )
        reason_codes = {
            code for finding in findings for code in finding.reason_codes
        }
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

        # Disagreement is not automatically a contradiction. Task 205 defines
        # contradiction semantics; until then, composition fails conservatively.
        reason_codes.discard(NativeReasonCode.CONFLICTING_EVIDENCE)
        reason_codes.add(NativeReasonCode.INSUFFICIENT_SUPPORT)
        return self._result(
            request,
            status=NativeReasoningStatus.UNKNOWN,
            reason_codes=tuple(reason_codes),
            evidence_ids=evidence_ids,
            missing_information=missing_information,
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
                retryable=False,
            )
        )

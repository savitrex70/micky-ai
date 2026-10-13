"""Task 204 correction: deterministic native reasoning composition.

Task 205: explicit contradiction, missing-information, and
abstention semantics over validated Task 204 request/evidence
bindings. Consumes ``NativeEvidenceBinding`` and produces
``NativeReasoningResult``-shaped dictionaries using only supplied
evidence and explicitly injected rules. No model, provider,
network, persistence, training, or global mutable registry lives
here, and none is needed: the default service (no rules
registered) honestly abstains on every binding.

Rule model (explicit configuration, not hidden knowledge):

- Rules are frozen dataclasses supplied by the caller at
  construction. The shipped codebase registers no built-in rules,
  so no clinical or domain claim is manufactured here. Tests use
  synthetic task/rule identifiers.
- A support rule declares the single ``task_id`` it serves, a
  stable ``rule_id``, a fixed uncertainty, and one explicit
  ``NativeCompositionCondition``. The condition names the single
  evidence type the rule handles, the minimum number of justifying
  records required, and the exact content expectation. It is
  actually evaluated against the validated binding: a rule fires
  only when the task matches and at least the required number of
  supplied records both have the required type and byte-exact
  matching content. Structural eligibility (task, type, count)
  alone never establishes a finding -- see below.
- Why exact content match: the Task 203 record carries free-form
  normalized text with no labels, values, or structured fields, so
  no domain predicate (keyword, threshold, label) can be
  represented without inventing interpretation. Byte-equality
  against an explicitly configured expectation is the narrowest
  content-level predicate available: it proves the validated bytes
  are exactly what the project configured, not that any clinical
  claim is true. Findings therefore mean "the configured content
  expectation was met by exactly these records".
- A ``SUPPORTED`` result references only the records satisfying
  the predicate. Present-but-unsatisfying records are excluded,
  never promoted to supporting evidence.
- A contradiction rule (``NativeContradictionRule``) declares two
  exact content expectations configured as mutually exclusive for
  one task, plus the required evidence type and a per-side minimum
  count. The Task 203 schema encodes no claim-level structure, so
  incompatibility cannot be inferred from text: it is asserted by
  explicit configuration and detected by byte-exact positive
  matches on both sides. Different text alone never contradicts;
  a missing, unreadable, or unbound side never contradicts.
- A missing-information requirement (``NativeEvidenceRequirement``)
  declares one symbolic requirement identifier, its task, the
  required evidence type, and the exact content that would satisfy
  it. An unmet requirement yields ``INSUFFICIENT`` with the stable
  symbolic identifier; requirements never invent records.
- Outcome precedence is fixed and documented: contradiction first
  (an established finding about present evidence is reported, not
  collapsed), then insufficiency (a configured necessary input is
  absent), then support, then abstention. Each outcome carries only
  the references its own justification establishes.
- Anything else -- no matching rule, empty evidence, an uncovered
  type, unmet count, or no content match -- yields an explicit
  ``ABSTAINED`` result (``NO_JUSTIFIED_BASIS``), never a
  fabricated conclusion.

Configuration is locked at construction: the stored rule tuples
cannot be replaced afterwards, and there is no global registry,
environment selection, or post-construction mutation path.

Determinism: rule selection is first-match in registration order
within each phase, output references preserve the binding's sorted
order verbatim, missing identifiers are sorted, and ``result_id``
is a UUID5 derived from the binding identity and the outcome, so
equivalent inputs yield equivalent outputs with no timestamps,
randomness, or process state.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from rop.schemas.native_binding import MAX_BINDING_RECORDS, NativeEvidenceBinding
from rop.schemas.native_evidence import MAX_CONTENT_LENGTH, NativeEvidenceRecord
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    NativeReasoningResult,
)

__all__ = [
    "ABSTAIN_UNCERTAINTY",
    "INSUFFICIENT_UNCERTAINTY",
    "NativeCompositionCondition",
    "NativeCompositionContractError",
    "NativeCompositionRule",
    "NativeCompositionService",
    "NativeContradictionRule",
    "NativeEvidenceRequirement",
]

# Identifier syntax mirrors the Task 202 request contract, which owns
# identifier rules. The composition service does not invent syntax.
_TASK_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_RULE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_MISSING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")

ABSTAIN_UNCERTAINTY = 1.0
"""Uncertainty reported on abstained composition results."""

INSUFFICIENT_UNCERTAINTY = 1.0
"""Uncertainty reported on insufficient composition results.

The unmet requirement is established, but the conclusion the
requirement would support cannot be assessed: maximum uncertainty.
"""

_RESULT_ID_NAMESPACE = uuid.NAMESPACE_URL
_RESULT_ID_DOMAIN = "native-composition-task-204"


def _checked_uncertainty(value: object) -> float:
    """Validate an uncertainty declaration and normalize its representation.

    Rejects booleans, strings, non-numeric values, non-finite
    values, and out-of-range values with a generic message.
    Integer inputs are normalized to float so equivalent
    configurations always compare and serialize identically.
    """
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError("uncertainty is invalid")
    if not isinstance(value, (int, float)):
        raise ValueError("uncertainty is invalid")
    if not math.isfinite(value):
        raise ValueError("uncertainty is invalid")
    if not 0.0 <= value <= 1.0:
        raise ValueError("uncertainty is invalid")
    return float(value)


@dataclass(frozen=True)
class NativeCompositionCondition:
    """One explicit deterministic rule condition (Task 204).

    Names the single evidence type a rule handles, the minimum
    number of justifying records required, and the exact content
    expectation. Evaluated by :meth:`matching` against validated
    binding evidence only: structural eligibility without content
    satisfaction never establishes a finding. There is exactly one
    condition kind; anything else is rejected at construction
    rather than interpreted.
    """

    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    min_evidence_count: int
    expected_content: str

    def __post_init__(self) -> None:
        if self.required_evidence_type not in ("OBSERVATION", "ASSERTION"):
            raise ValueError("required_evidence_type is invalid")
        if isinstance(self.min_evidence_count, bool) or not isinstance(
            self.min_evidence_count, int
        ):
            raise ValueError("min_evidence_count is invalid")
        if not 1 <= self.min_evidence_count <= MAX_BINDING_RECORDS:
            raise ValueError("min_evidence_count is invalid")
        if not isinstance(self.expected_content, str):
            raise ValueError("expected_content is invalid")
        if not 1 <= len(self.expected_content) <= MAX_CONTENT_LENGTH:
            raise ValueError("expected_content is invalid")

    def matching(
        self, evidence: tuple[NativeEvidenceRecord, ...]
    ) -> tuple[NativeEvidenceRecord, ...]:
        """Select the records satisfying this condition, in order.

        Returns the validated records that both have the required
        type and byte-exact matching content, preserving binding
        order. Foreign or unsatisfying values are excluded, never
        coerced or repaired; an empty result means the predicate is
        false, which abstains.
        """
        return tuple(
            record
            for record in evidence
            if isinstance(record, NativeEvidenceRecord)
            and record.evidence_type == self.required_evidence_type
            and record.content_text == self.expected_content
        )


@dataclass(frozen=True)
class NativeCompositionRule:
    """One explicitly configured deterministic composition rule.

    Fires only for bindings whose request names ``task_id`` and for
    which ``condition.matching`` selects at least
    ``min_evidence_count`` records. Carries no behavior beyond this
    declaration; evaluation semantics live in the condition and
    ``NativeCompositionService`` so invalid outcomes cannot arise
    from caller-supplied callables.
    """

    rule_id: str
    task_id: str
    condition: NativeCompositionCondition
    uncertainty: float

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not _RULE_ID_RE.fullmatch(self.rule_id):
            raise ValueError("rule_id is invalid")
        if not isinstance(self.task_id, str) or not _TASK_ID_RE.fullmatch(self.task_id):
            raise ValueError("task_id is invalid")
        if not isinstance(self.condition, NativeCompositionCondition):
            raise ValueError("condition is invalid")
        object.__setattr__(self, "uncertainty", _checked_uncertainty(self.uncertainty))


@dataclass(frozen=True)
class NativeContradictionRule:
    """One explicit deterministic contradiction rule (Task 205).

    Declares two exact content expectations configured as mutually
    exclusive for one task, the single evidence type either side
    must have, a per-side minimum count, a stable ``rule_id``, and
    a fixed uncertainty. Incompatibility is asserted by this
    configuration -- never inferred from text difference -- and is
    detected by byte-exact positive matches on both sides. A
    missing, unreadable, or unbound side cannot contradict, and
    the two expectations must differ so no record can satisfy both.
    """

    rule_id: str
    task_id: str
    affirming_content: str
    denying_content: str
    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    min_evidence_count: int
    uncertainty: float

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not _RULE_ID_RE.fullmatch(self.rule_id):
            raise ValueError("rule_id is invalid")
        if not isinstance(self.task_id, str) or not _TASK_ID_RE.fullmatch(self.task_id):
            raise ValueError("task_id is invalid")
        for field_name in ("affirming_content", "denying_content"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise ValueError(f"{field_name} is invalid")
            if not 1 <= len(value) <= MAX_CONTENT_LENGTH:
                raise ValueError(f"{field_name} is invalid")
        if self.affirming_content == self.denying_content:
            raise ValueError("contradiction expectations must differ")
        if self.required_evidence_type not in ("OBSERVATION", "ASSERTION"):
            raise ValueError("required_evidence_type is invalid")
        if isinstance(self.min_evidence_count, bool) or not isinstance(
            self.min_evidence_count, int
        ):
            raise ValueError("min_evidence_count is invalid")
        if not 1 <= self.min_evidence_count <= MAX_BINDING_RECORDS:
            raise ValueError("min_evidence_count is invalid")
        object.__setattr__(self, "uncertainty", _checked_uncertainty(self.uncertainty))

    def matching_pair(
        self, evidence: tuple[NativeEvidenceRecord, ...]
    ) -> tuple[tuple[NativeEvidenceRecord, ...], tuple[NativeEvidenceRecord, ...]]:
        """Select both contradiction sides, in binding order.

        Returns ``(affirming, denying)`` record tuples. Only
        validated records of the required type with byte-exact
        matching content are selected on either side; anything else
        is excluded. An empty side means no contradiction.
        """
        affirming: list[NativeEvidenceRecord] = []
        denying: list[NativeEvidenceRecord] = []
        for record in evidence:
            if not isinstance(record, NativeEvidenceRecord):
                continue
            if record.evidence_type != self.required_evidence_type:
                continue
            if record.content_text == self.affirming_content:
                affirming.append(record)
            elif record.content_text == self.denying_content:
                denying.append(record)
        return tuple(affirming), tuple(denying)


@dataclass(frozen=True)
class NativeEvidenceRequirement:
    """One explicit missing-information requirement (Task 205).

    Declares a stable symbolic ``requirement_id`` (reported in
    ``missing_information_ids`` when unmet), its task, the required
    evidence type, and the exact content that would satisfy it.
    Satisfied only by a validated bound record of the required type
    with byte-exact matching content; nothing is invented when the
    requirement is unmet.
    """

    requirement_id: str
    task_id: str
    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    expected_content: str

    def __post_init__(self) -> None:
        if not isinstance(self.requirement_id, str) or not _MISSING_ID_RE.fullmatch(
            self.requirement_id
        ):
            raise ValueError("requirement_id is invalid")
        if not isinstance(self.task_id, str) or not _TASK_ID_RE.fullmatch(self.task_id):
            raise ValueError("task_id is invalid")
        if self.required_evidence_type not in ("OBSERVATION", "ASSERTION"):
            raise ValueError("required_evidence_type is invalid")
        if not isinstance(self.expected_content, str):
            raise ValueError("expected_content is invalid")
        if not 1 <= len(self.expected_content) <= MAX_CONTENT_LENGTH:
            raise ValueError("expected_content is invalid")

    def satisfied_by(self, evidence: tuple[NativeEvidenceRecord, ...]) -> bool:
        """Return True when a validated record satisfies this requirement."""
        return any(
            isinstance(record, NativeEvidenceRecord)
            and record.evidence_type == self.required_evidence_type
            and record.content_text == self.expected_content
            for record in evidence
        )


class NativeCompositionContractError(Exception):
    """A deterministic composition boundary failure.

    Raised for invalid or incompatible composition inputs and for
    result-construction failures. Never raised for honest abstention,
    which is a valid result. Public messages are generic and carry
    no request content, evidence, or validation internals.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class NativeCompositionService:
    """Deterministic native reasoning composition (Task 204).

    Pure orchestration over validated bindings. Dependencies (rules)
    are supplied explicitly at construction; nothing is discovered,
    downloaded, selected from the environment, or shared globally.
    The stored rule configuration is locked at construction and
    cannot be replaced afterwards.
    """

    _LOCKED_ATTRS = frozenset(
        {"_rules", "_contradiction_rules", "_requirements", "_rules_locked"}
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._LOCKED_ATTRS and self.__dict__.get("_rules_locked", False):
            raise NativeCompositionContractError(
                "INVALID_CONFIGURATION", "service configuration is immutable"
            )
        super().__setattr__(name, value)

    def __init__(
        self,
        rules: Sequence[NativeCompositionRule] | NativeCompositionRule | None = None,
        contradiction_rules: (
            Sequence[NativeContradictionRule] | NativeContradictionRule | None
        ) = None,
        requirements: (
            Sequence[NativeEvidenceRequirement] | NativeEvidenceRequirement | None
        ) = None,
    ) -> None:
        self._rules = self._checked_rules(rules, NativeCompositionRule, "INVALID_RULES")
        contradictions = self._checked_rules(
            contradiction_rules, NativeContradictionRule, "INVALID_RULES"
        )
        required = self._checked_rules(
            requirements, NativeEvidenceRequirement, "INVALID_REQUIREMENTS"
        )
        seen: set[str] = set()
        for rule in (*self._rules, *contradictions):
            if rule.rule_id in seen:
                raise NativeCompositionContractError(
                    "INVALID_RULES", "composition rules are invalid"
                )
            seen.add(rule.rule_id)
        seen_requirements: set[str] = set()
        for requirement in required:
            if requirement.requirement_id in seen_requirements:
                raise NativeCompositionContractError(
                    "INVALID_REQUIREMENTS", "composition requirements are invalid"
                )
            seen_requirements.add(requirement.requirement_id)
        self._contradiction_rules = contradictions
        self._requirements = required
        self._rules_locked = True

    @staticmethod
    def _checked_rules(rules: object, kind: type, invariant: str) -> tuple:  # type: ignore[type-arg]
        """Normalize one explicit rule collection, rejecting anything else."""
        if rules is None:
            return ()
        if isinstance(rules, kind):
            return (rules,)
        try:
            collected = tuple(rules)  # type: ignore[arg-type]
        except TypeError as exc:
            raise NativeCompositionContractError(
                invariant, "composition configuration is invalid"
            ) from exc
        for rule in collected:
            if not isinstance(rule, kind):
                raise NativeCompositionContractError(
                    invariant, "composition configuration is invalid"
                )
        return collected

    @property
    def rules(self) -> tuple[NativeCompositionRule, ...]:
        """The explicitly configured support rules, in registration order."""
        return self._rules

    @property
    def contradiction_rules(self) -> tuple[NativeContradictionRule, ...]:
        """The explicitly configured contradiction rules, in order."""
        return self._contradiction_rules

    @property
    def requirements(self) -> tuple[NativeEvidenceRequirement, ...]:
        """The explicitly configured missing-information requirements, in order."""
        return self._requirements

    def compose(
        self, binding: NativeEvidenceBinding | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Compose a validated binding into a result dictionary.

        Accepts a ``NativeEvidenceBinding`` or its JSON-compatible
        mapping form. Returns the ``NativeReasoningResult`` contract
        as a JSON-mode dictionary. Outcome precedence is fixed:
        contradiction, then insufficiency, then support, then
        abstention. Raises ``NativeCompositionContractError`` for
        invalid inputs instead of repairing them.
        """
        validated = self._validated_binding(binding)
        contradicted = self._contradicted_result(validated)
        if contradicted is not None:
            return contradicted
        insufficient = self._insufficient_result(validated)
        if insufficient is not None:
            return insufficient
        rule = self._select_rule(validated)
        if rule is not None:
            matched = rule.condition.matching(validated.evidence)
            if len(matched) >= rule.condition.min_evidence_count:
                return self._supported_result(validated, rule, matched)
        return self._abstained_result(validated)

    def _validated_binding(
        self, binding: NativeEvidenceBinding | Mapping[str, Any]
    ) -> NativeEvidenceBinding:
        if isinstance(binding, NativeEvidenceBinding):
            return binding
        if isinstance(binding, Mapping):
            try:
                return NativeEvidenceBinding.model_validate(dict(binding))
            except ValidationError as exc:
                raise NativeCompositionContractError(
                    "INVALID_BINDING", "composition binding is invalid"
                ) from exc
        raise NativeCompositionContractError(
            "INVALID_BINDING", "composition binding is invalid"
        )

    def _select_rule(
        self, binding: NativeEvidenceBinding
    ) -> NativeCompositionRule | None:
        for rule in self._rules:
            if rule.task_id == binding.request.task_id:
                return rule
        return None

    def _contradicted_result(
        self, binding: NativeEvidenceBinding
    ) -> dict[str, Any] | None:
        """Return a contradiction result for the first satisfied pair rule."""
        for rule in self._contradiction_rules:
            if rule.task_id != binding.request.task_id:
                continue
            affirming, denying = rule.matching_pair(binding.evidence)
            if len(affirming) < rule.min_evidence_count:
                continue
            if len(denying) < rule.min_evidence_count:
                continue
            return self._contradiction_result(binding, rule, affirming, denying)
        return None

    def _insufficient_result(
        self, binding: NativeEvidenceBinding
    ) -> dict[str, Any] | None:
        """Return an insufficiency result when a configured requirement is unmet."""
        task_requirements = [
            requirement
            for requirement in self._requirements
            if requirement.task_id == binding.request.task_id
        ]
        if not task_requirements:
            return None
        unmet = sorted(
            requirement.requirement_id
            for requirement in task_requirements
            if not requirement.satisfied_by(binding.evidence)
        )
        if not unmet:
            return None
        met_contents = {
            (requirement.required_evidence_type, requirement.expected_content)
            for requirement in task_requirements
            if requirement.satisfied_by(binding.evidence)
        }
        supporting = tuple(
            record.evidence_id
            for record in binding.evidence
            if (record.evidence_type, record.content_text) in met_contents
        )
        request = binding.request
        return self._build_result(
            request_id=request.request_id,
            session_id=request.session_id,
            context_fingerprint=request.context_fingerprint,
            status="INSUFFICIENT",
            reason_code="EVIDENCE_MISSING",
            uncertainty=INSUFFICIENT_UNCERTAINTY,
            supporting=supporting,
            contradicting=(),
            missing=tuple(unmet),
            rule_id=None,
            result_tag="|".join(
                [
                    str(request.request_id),
                    str(request.session_id),
                    request.context_fingerprint,
                    request.task_id,
                    "insufficient",
                    ",".join(unmet),
                    ",".join(str(value) for value in supporting),
                ]
            ),
        )

    def _contradiction_result(
        self,
        binding: NativeEvidenceBinding,
        rule: NativeContradictionRule,
        affirming: tuple[NativeEvidenceRecord, ...],
        denying: tuple[NativeEvidenceRecord, ...],
    ) -> dict[str, Any]:
        request = binding.request
        supporting = tuple(record.evidence_id for record in affirming)
        contradicting = tuple(record.evidence_id for record in denying)
        return self._build_result(
            request_id=request.request_id,
            session_id=request.session_id,
            context_fingerprint=request.context_fingerprint,
            status="CONTRADICTED",
            reason_code="RULE_CONTRADICTION_FOUND",
            uncertainty=rule.uncertainty,
            supporting=supporting,
            contradicting=contradicting,
            missing=(),
            rule_id=rule.rule_id,
            result_tag="|".join(
                [
                    str(request.request_id),
                    str(request.session_id),
                    request.context_fingerprint,
                    request.task_id,
                    rule.rule_id,
                    rule.required_evidence_type,
                    str(rule.min_evidence_count),
                    rule.affirming_content,
                    rule.denying_content,
                    ",".join(str(value) for value in supporting),
                    ",".join(str(value) for value in contradicting),
                ]
            ),
        )

    def _abstained_result(self, binding: NativeEvidenceBinding) -> dict[str, Any]:
        request = binding.request
        supplied = sorted(str(record.evidence_id) for record in binding.evidence)
        return self._build_result(
            request_id=request.request_id,
            session_id=request.session_id,
            context_fingerprint=request.context_fingerprint,
            status="ABSTAINED",
            reason_code="NO_JUSTIFIED_BASIS",
            uncertainty=ABSTAIN_UNCERTAINTY,
            supporting=(),
            contradicting=(),
            missing=(),
            rule_id=None,
            result_tag="|".join(
                [
                    str(request.request_id),
                    str(request.session_id),
                    request.context_fingerprint,
                    request.task_id,
                    "abstain",
                    ",".join(supplied),
                ]
            ),
        )

    def _supported_result(
        self,
        binding: NativeEvidenceBinding,
        rule: NativeCompositionRule,
        matched: tuple[NativeEvidenceRecord, ...],
    ) -> dict[str, Any]:
        request = binding.request
        supporting = tuple(record.evidence_id for record in matched)
        return self._build_result(
            request_id=request.request_id,
            session_id=request.session_id,
            context_fingerprint=request.context_fingerprint,
            status="SUPPORTED",
            reason_code="RULE_MATCH",
            uncertainty=rule.uncertainty,
            supporting=supporting,
            contradicting=(),
            missing=(),
            rule_id=rule.rule_id,
            result_tag="|".join(
                [
                    str(request.request_id),
                    str(request.session_id),
                    request.context_fingerprint,
                    request.task_id,
                    rule.rule_id,
                    rule.condition.required_evidence_type,
                    str(rule.condition.min_evidence_count),
                    rule.condition.expected_content,
                    ",".join(str(value) for value in supporting),
                ]
            ),
        )

    @staticmethod
    def _build_result(
        *,
        request_id: UUID,
        session_id: UUID,
        context_fingerprint: str,
        status: Literal["SUPPORTED", "CONTRADICTED", "INSUFFICIENT", "ABSTAINED"],
        reason_code: Literal[
            "RULE_MATCH",
            "RULE_CONTRADICTION_FOUND",
            "EVIDENCE_MISSING",
            "NO_JUSTIFIED_BASIS",
        ],
        uncertainty: float,
        supporting: tuple[UUID, ...],
        contradicting: tuple[UUID, ...],
        missing: tuple[str, ...],
        rule_id: str | None,
        result_tag: str,
    ) -> dict[str, Any]:
        try:
            result = NativeReasoningResult.model_validate(
                {
                    "result_id": uuid.uuid5(
                        _RESULT_ID_NAMESPACE, f"{_RESULT_ID_DOMAIN}|{result_tag}"
                    ),
                    "request_id": request_id,
                    "session_id": session_id,
                    "context_fingerprint": context_fingerprint,
                    "status": status,
                    "reason_code": reason_code,
                    "uncertainty": uncertainty,
                    "supporting_evidence_ids": list(supporting),
                    "contradicting_evidence_ids": list(contradicting),
                    "missing_information_ids": list(missing),
                    "rule_id": rule_id,
                    "suggestion_text": None,
                    "result_source": NATIVE_REASONING_RESULT_SOURCE_TASK_202,
                }
            )
        except ValidationError as exc:
            raise NativeCompositionContractError(
                "RESULT_CONSTRUCTION_FAILED", "composition result is invalid"
            ) from exc
        return result.model_dump(mode="json")

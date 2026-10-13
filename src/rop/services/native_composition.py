"""Task 204 correction: deterministic native reasoning composition.

Project-owned deterministic composition over validated Task 204
request/evidence bindings. Consumes ``NativeEvidenceBinding`` and
produces ``NativeReasoningResult``-shaped dictionaries using only
supplied evidence and explicitly injected rules. No model, provider,
network, persistence, training, or global mutable registry lives
here, and none is needed: the default service (no rules registered)
honestly abstains on every binding.

Rule model (explicit configuration, not hidden knowledge):

- Rules are frozen dataclasses supplied by the caller at
  construction. The shipped codebase registers no built-in rules,
  so no clinical or domain claim is manufactured here. Tests use
  synthetic task/rule identifiers.
- A rule declares the single ``task_id`` it serves, the single
  evidence type it handles, a stable ``rule_id``, and a fixed
  uncertainty. A rule fires only when the binding's task matches
  and every supplied record has the required type.
- Anything else -- no matching rule, empty evidence, or a type the
  rule does not cover -- yields an explicit ``ABSTAINED`` result
  (``NO_JUSTIFIED_BASIS``), never a fabricated conclusion.
  Contradiction handling and missing-information policy belong to
  Task 205 and are not implemented here.

Determinism: rule selection is first-match in registration order,
output references preserve the binding's sorted order verbatim,
and ``result_id`` is a UUID5 derived from the binding identity and
the outcome, so equivalent inputs yield equivalent outputs with no
timestamps, randomness, or process state.
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

from rop.schemas.native_binding import NativeEvidenceBinding
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    NativeReasoningResult,
)

__all__ = [
    "ABSTAIN_UNCERTAINTY",
    "NativeCompositionContractError",
    "NativeCompositionRule",
    "NativeCompositionService",
]

# Identifier syntax mirrors the Task 202 request contract, which owns
# identifier rules. The composition service does not invent syntax.
_TASK_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_RULE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

ABSTAIN_UNCERTAINTY = 1.0
"""Uncertainty reported on abstained composition results."""

_RESULT_ID_NAMESPACE = uuid.NAMESPACE_URL
_RESULT_ID_DOMAIN = "native-composition-task-204"


@dataclass(frozen=True)
class NativeCompositionRule:
    """One explicitly configured deterministic composition rule.

    Fires only for bindings whose request names ``task_id`` and whose
    every supplied record has ``required_evidence_type``. Carries no
    behavior beyond this declaration; evaluation semantics live in
    ``NativeCompositionService`` so invalid outcomes cannot arise
    from caller-supplied callables.
    """

    rule_id: str
    task_id: str
    required_evidence_type: Literal["OBSERVATION", "ASSERTION"]
    uncertainty: float

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not _RULE_ID_RE.fullmatch(self.rule_id):
            raise ValueError("rule_id is invalid")
        if not isinstance(self.task_id, str) or not _TASK_ID_RE.fullmatch(self.task_id):
            raise ValueError("task_id is invalid")
        if self.required_evidence_type not in ("OBSERVATION", "ASSERTION"):
            raise ValueError("required_evidence_type is invalid")
        if isinstance(self.uncertainty, bool) or isinstance(self.uncertainty, str):
            raise ValueError("uncertainty is invalid")
        if not isinstance(self.uncertainty, (int, float)):
            raise ValueError("uncertainty is invalid")
        if not math.isfinite(self.uncertainty):
            raise ValueError("uncertainty is invalid")
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("uncertainty is invalid")


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
    """

    def __init__(
        self,
        rules: Sequence[NativeCompositionRule] | NativeCompositionRule | None = None,
    ) -> None:
        if rules is None:
            collected: tuple[NativeCompositionRule, ...] = ()
        elif isinstance(rules, NativeCompositionRule):
            collected = (rules,)
        else:
            try:
                collected = tuple(rules)
            except TypeError as exc:
                raise NativeCompositionContractError(
                    "INVALID_RULES", "composition rules are invalid"
                ) from exc
        for rule in collected:
            if not isinstance(rule, NativeCompositionRule):
                raise NativeCompositionContractError(
                    "INVALID_RULES", "composition rules are invalid"
                )
        seen: set[str] = set()
        for rule in collected:
            if rule.rule_id in seen:
                raise NativeCompositionContractError(
                    "INVALID_RULES", "composition rules are invalid"
                )
            seen.add(rule.rule_id)
        self._rules = collected

    @property
    def rules(self) -> tuple[NativeCompositionRule, ...]:
        """The explicitly configured rules, in registration order."""
        return self._rules

    def compose(
        self, binding: NativeEvidenceBinding | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Compose a validated binding into a result dictionary.

        Accepts a ``NativeEvidenceBinding`` or its JSON-compatible
        mapping form. Returns the ``NativeReasoningResult`` contract
        as a JSON-mode dictionary. Raises
        ``NativeCompositionContractError`` for invalid inputs instead
        of repairing them.
        """
        validated = self._validated_binding(binding)
        rule = self._select_rule(validated)
        if rule is not None and self._rule_covers(rule, validated):
            return self._supported_result(validated, rule)
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

    @staticmethod
    def _rule_covers(
        rule: NativeCompositionRule, binding: NativeEvidenceBinding
    ) -> bool:
        if not binding.evidence:
            return False
        return all(
            record.evidence_type == rule.required_evidence_type
            for record in binding.evidence
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
        self, binding: NativeEvidenceBinding, rule: NativeCompositionRule
    ) -> dict[str, Any]:
        request = binding.request
        supporting = tuple(record.evidence_id for record in binding.evidence)
        return self._build_result(
            request_id=request.request_id,
            session_id=request.session_id,
            context_fingerprint=request.context_fingerprint,
            status="SUPPORTED",
            reason_code="RULE_MATCH",
            uncertainty=rule.uncertainty,
            supporting=supporting,
            rule_id=rule.rule_id,
            result_tag="|".join(
                [
                    str(request.request_id),
                    str(request.session_id),
                    request.context_fingerprint,
                    request.task_id,
                    rule.rule_id,
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
        status: Literal["SUPPORTED", "ABSTAINED"],
        reason_code: Literal["RULE_MATCH", "NO_JUSTIFIED_BASIS"],
        uncertainty: float,
        supporting: tuple[UUID, ...],
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
                    "contradicting_evidence_ids": [],
                    "missing_information_ids": [],
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

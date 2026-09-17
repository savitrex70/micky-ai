from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_input_bundle import DecisionInputBundleService

POLICY_SOURCE_DECISION_POLICY_TASK_038 = "DECISION_POLICY_TASK_038"
"""Fixed structural-contract identifier for Task 038 results."""

POLICY_ID_DEFAULT = "DECISION_POLICY_DEFAULT"
POLICY_VERSION_DEFAULT = "1.0.0"
POLICY_NAME_DEFAULT = "Default Decision Policy"

SELECTION_MODE_SINGLE_CANDIDATE = "SINGLE_CANDIDATE"
SELECTION_MODE_MULTIPLE_CANDIDATES = "MULTIPLE_CANDIDATES"
SELECTION_MODE_NO_CANDIDATE = "NO_CANDIDATE"
SELECTION_MODE_UNRESOLVED = "UNRESOLVED"

_ALLOWED_SELECTION_MODES = frozenset(
    {
        SELECTION_MODE_SINGLE_CANDIDATE,
        SELECTION_MODE_MULTIPLE_CANDIDATES,
        SELECTION_MODE_NO_CANDIDATE,
        SELECTION_MODE_UNRESOLVED,
    }
)

REQUIRED_CRITERIA_MUST_ALL_BE_SATISFIED = "MUST_ALL_BE_SATISFIED"
REQUIRED_CRITERIA_MUST_BE_CONSIDERED = "MUST_BE_CONSIDERED"

_ALLOWED_REQUIRED_CRITERIA_BEHAVIORS = frozenset(
    {
        REQUIRED_CRITERIA_MUST_ALL_BE_SATISFIED,
        REQUIRED_CRITERIA_MUST_BE_CONSIDERED,
    }
)

TIE_BEHAVIOR_MUST_RETURN_UNRESOLVED = "MUST_RETURN_UNRESOLVED"
TIE_BEHAVIOR_MUST_APPLY_EXPLICIT_TIEBREAKER = "MUST_APPLY_EXPLICIT_TIEBREAKER"

_ALLOWED_TIE_BEHAVIORS = frozenset(
    {
        TIE_BEHAVIOR_MUST_RETURN_UNRESOLVED,
        TIE_BEHAVIOR_MUST_APPLY_EXPLICIT_TIEBREAKER,
    }
)

INSUFFICIENT_INPUT_MUST_RETURN_UNAVAILABLE = "MUST_RETURN_UNAVAILABLE"
INSUFFICIENT_INPUT_MUST_REJECT = "MUST_REJECT"

_ALLOWED_INSUFFICIENT_INPUT_BEHAVIORS = frozenset(
    {
        INSUFFICIENT_INPUT_MUST_RETURN_UNAVAILABLE,
        INSUFFICIENT_INPUT_MUST_REJECT,
    }
)

INCOMPLETE_INPUT_MUST_RETURN_INCONSISTENT = "MUST_RETURN_INCONSISTENT"
INCOMPLETE_INPUT_MUST_REJECT = "MUST_REJECT"

_ALLOWED_INCOMPLETE_INPUT_BEHAVIORS = frozenset(
    {
        INCOMPLETE_INPUT_MUST_RETURN_INCONSISTENT,
        INCOMPLETE_INPUT_MUST_REJECT,
    }
)

_REQUIRED_STRING_FIELDS = (
    "policy_id",
    "policy_version",
    "policy_name",
    "allowed_selection_mode",
    "required_criteria_behavior",
    "tie_behavior",
    "insufficient_input_behavior",
    "incomplete_input_behavior",
    "policy_source",
)

_REQUIRED_FIELDS = _REQUIRED_STRING_FIELDS + ("required_candidate_count",)


class DecisionPolicyContractError(Exception):
    """Task 038: internal derivation bug in the policy contract.

    Raised only when the assembled policy structure violates its own
    contract. The policy is a static, session-independent contract --
    it is never raised for a normal unavailable-bundle state.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionPolicyService:
    """Task 038: deterministic decision policy contract.

    Defines the rules a future decision-execution layer is permitted
    to apply to a Task 037 ``DecisionInputBundleRead``. The policy is
    a static, deterministic contract that does not depend on session
    state, does not execute any selection rule, does not rank, rerank,
    rescore, or break ties, and never produces a decision.
    """

    def __init__(
        self,
        decision_input_bundle_service: DecisionInputBundleService | None = None,
    ) -> None:
        self.decision_input_bundle_service = (
            decision_input_bundle_service or DecisionInputBundleService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Validate the Task 037 boundary, then return the fixed policy.

        The policy itself is session-independent: the same static
        contract applies to every session that has a constructible
        decision input. This method calls Task 037's
        ``build_for_session`` once to confirm the session-level boundary
        is reachable (the precondition for applying a decision policy),
        then returns the fixed policy. It does not walk Tasks 031-036
        itself and does not embed session data in the policy.
        """
        self.decision_input_bundle_service.build_for_session(
            db, session_id, candidates
        )
        return self.build()

    def build(self) -> dict[str, Any]:
        """Return the fixed decision policy contract. Pure and deterministic."""
        policy: dict[str, Any] = {
            "policy_id": POLICY_ID_DEFAULT,
            "policy_version": POLICY_VERSION_DEFAULT,
            "policy_name": POLICY_NAME_DEFAULT,
            "required_candidate_count": 1,
            "allowed_selection_mode": SELECTION_MODE_SINGLE_CANDIDATE,
            "required_criteria_behavior": (
                REQUIRED_CRITERIA_MUST_ALL_BE_SATISFIED
            ),
            "tie_behavior": TIE_BEHAVIOR_MUST_RETURN_UNRESOLVED,
            "insufficient_input_behavior": (
                INSUFFICIENT_INPUT_MUST_RETURN_UNAVAILABLE
            ),
            "incomplete_input_behavior": (
                INCOMPLETE_INPUT_MUST_RETURN_INCONSISTENT
            ),
            "policy_source": POLICY_SOURCE_DECISION_POLICY_TASK_038,
        }
        self._validate_policy(policy)
        return policy

    @staticmethod
    def _validate_policy(policy: Mapping[str, Any]) -> None:
        """Verify the policy contract. Rejects malformed structures."""
        for field in _REQUIRED_FIELDS:
            if field not in policy:
                raise DecisionPolicyContractError(
                    "MISSING_POLICY_FIELD", f"policy has no {field}"
                )
        for field in _REQUIRED_STRING_FIELDS:
            value = policy[field]
            if not isinstance(value, str) or not value:
                raise DecisionPolicyContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not a non-empty string: {value!r}",
                )
        count = policy["required_candidate_count"]
        if count is not None:
            if not isinstance(count, int) or isinstance(count, bool):
                raise DecisionPolicyContractError(
                    "REQUIRED_CANDIDATE_COUNT_TYPE",
                    f"required_candidate_count is not int/None: {count!r}",
                )
            if count < 0:
                raise DecisionPolicyContractError(
                    "REQUIRED_CANDIDATE_COUNT_NEGATIVE",
                    f"required_candidate_count is negative: {count!r}",
                )
        if policy["allowed_selection_mode"] not in _ALLOWED_SELECTION_MODES:
            raise DecisionPolicyContractError(
                "INVALID_SELECTION_MODE",
                "allowed_selection_mode is not a valid mode: "
                f"{policy['allowed_selection_mode']!r}",
            )
        if (
            policy["required_criteria_behavior"]
            not in _ALLOWED_REQUIRED_CRITERIA_BEHAVIORS
        ):
            raise DecisionPolicyContractError(
                "INVALID_REQUIRED_CRITERIA_BEHAVIOR",
                "required_criteria_behavior is not a valid behavior: "
                f"{policy['required_criteria_behavior']!r}",
            )
        if policy["tie_behavior"] not in _ALLOWED_TIE_BEHAVIORS:
            raise DecisionPolicyContractError(
                "INVALID_TIE_BEHAVIOR",
                f"tie_behavior is not a valid behavior: "
                f"{policy['tie_behavior']!r}",
            )
        if (
            policy["insufficient_input_behavior"]
            not in _ALLOWED_INSUFFICIENT_INPUT_BEHAVIORS
        ):
            raise DecisionPolicyContractError(
                "INVALID_INSUFFICIENT_INPUT_BEHAVIOR",
                "insufficient_input_behavior is not a valid behavior: "
                f"{policy['insufficient_input_behavior']!r}",
            )
        if (
            policy["incomplete_input_behavior"]
            not in _ALLOWED_INCOMPLETE_INPUT_BEHAVIORS
        ):
            raise DecisionPolicyContractError(
                "INVALID_INCOMPLETE_INPUT_BEHAVIOR",
                "incomplete_input_behavior is not a valid behavior: "
                f"{policy['incomplete_input_behavior']!r}",
            )
        if policy["policy_source"] != POLICY_SOURCE_DECISION_POLICY_TASK_038:
            raise DecisionPolicyContractError(
                "INVALID_POLICY_SOURCE",
                "policy_source is not the Task 038 identifier: "
                f"{policy['policy_source']!r}",
            )

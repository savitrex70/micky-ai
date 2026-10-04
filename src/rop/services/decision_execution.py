from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_input_bundle import (
    INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037,
    DecisionInputBundleContractError,
    DecisionInputBundleService,
)
from rop.services.decision_policy import (
    POLICY_SOURCE_DECISION_POLICY_TASK_038,
    DecisionPolicyService,
)

DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039 = "DECISION_EXECUTION_TASK_039"
"""Fixed structural-contract identifier for Task 039 results."""

OUTCOME_SELECTED = "SELECTED"
OUTCOME_NO_ELIGIBLE_CANDIDATE = "NO_ELIGIBLE_CANDIDATE"
OUTCOME_UNRESOLVED = "UNRESOLVED"
OUTCOME_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
OUTCOME_INPUT_INCONSISTENT = "INPUT_INCONSISTENT"

_OUTCOMES = frozenset(
    {
        OUTCOME_SELECTED,
        OUTCOME_NO_ELIGIBLE_CANDIDATE,
        OUTCOME_UNRESOLVED,
        OUTCOME_INPUT_UNAVAILABLE,
        OUTCOME_INPUT_INCONSISTENT,
    }
)

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "candidate_set",
    "assessment_set",
    "candidate_count",
    "candidate_order_preserved",
    "candidate_assessment_alignment_complete",
    "input_structure_consistent",
    "input_source",
)

_BUNDLE_BOOLEAN_FIELDS = (
    "available",
    "candidate_order_preserved",
    "candidate_assessment_alignment_complete",
    "input_structure_consistent",
)

_POLICY_REQUIRED_FIELDS = (
    "policy_id",
    "policy_version",
    "policy_name",
    "required_candidate_count",
    "allowed_selection_mode",
    "required_criteria_behavior",
    "tie_behavior",
    "insufficient_input_behavior",
    "incomplete_input_behavior",
    "policy_source",
)

# The exact default policy semantics Task 039 is permitted to execute.
# Any deviation is rejected as UNSUPPORTED_POLICY_VALUES rather than
# silently introducing behavior Task 038 did not authorize.
_REQUIRED_POLICY_VALUES = {
    "allowed_selection_mode": "SINGLE_CANDIDATE",
    "required_candidate_count": 1,
    "required_criteria_behavior": "MUST_ALL_BE_SATISFIED",
    "tie_behavior": "MUST_RETURN_UNRESOLVED",
    "insufficient_input_behavior": "MUST_RETURN_UNAVAILABLE",
    "incomplete_input_behavior": "MUST_RETURN_INCONSISTENT",
}


class DecisionExecutionContractError(Exception):
    """Task 039: malformed upstream input or an internal derivation bug.

    Raised only when the Task 037 decision-input bundle or the Task 038
    policy is not shaped like its own established contract, when the
    policy differs from the values Task 039 is permitted to execute, or
    when this service's own derivation produced an internally
    contradictory result. It is never raised for a normal executed
    outcome -- SELECTED, NO_ELIGIBLE_CANDIDATE, UNRESOLVED,
    INPUT_UNAVAILABLE, and INPUT_INCONSISTENT are all valid, fully
    typed responses.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionExecutionService:
    """Task 039: deterministic execution of the Task 038 decision policy.

    The first boundary permitted to select a candidate. Consumes the
    Task 037 ``DecisionInputBundleRead`` and the Task 038
    ``DecisionPolicyRead`` unchanged, evaluates eligibility from the
    existing Task 036 criterion results (required criteria only),
    identifies the highest existing upstream rank among eligible
    candidates, and returns a fixed outcome identifier. It introduces
    no new scoring, ranking, evidence interpretation, or domain-specific
    reasoning; performs no persistence; mutates no input.
    """

    def __init__(
        self,
        decision_input_bundle_service: DecisionInputBundleService | None = None,
        decision_policy_service: DecisionPolicyService | None = None,
    ) -> None:
        self.decision_input_bundle_service = (
            decision_input_bundle_service or DecisionInputBundleService()
        )
        self.decision_policy_service = (
            decision_policy_service or DecisionPolicyService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Compose the established Task 037 and Task 038 boundaries.

        Delegates the upstream pipeline to Task 037's
        ``build_for_session`` and the policy contract to Task 038's
        ``build`` -- it does not walk Tasks 031-036 itself. Then
        executes the policy via this service's ``build``.
        """
        bundle = self.decision_input_bundle_service.build_for_session(
            db, session_id, candidates
        )
        policy = self.decision_policy_service.build()
        return self.build(bundle, policy)

    def build(
        self,
        bundle: Mapping[str, Any] | None,
        policy: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute the policy against the bundle. Pure and deterministic."""
        bundle = self._validate_bundle(bundle)
        policy = self._validate_policy(policy)

        policy_id = policy["policy_id"]
        policy_version = policy["policy_version"]

        # Structural inconsistency is checked first: Task 037 folds
        # input_structure_consistent into its `available` field, so
        # checking availability first would mask the inconsistent case
        # entirely. The distinction between "unavailable" and
        # "inconsistent" must survive to the execution outcome.
        if not bundle["input_structure_consistent"]:
            return self._make_unavailable_result(
                OUTCOME_INPUT_INCONSISTENT, policy_id, policy_version
            )
        if not bundle["available"]:
            return self._make_unavailable_result(
                OUTCOME_INPUT_UNAVAILABLE, policy_id, policy_version
            )

        assessments = bundle["assessment_set"]["assessments"]
        eligible = self._compute_eligible(assessments)

        result = self._execute_default_policy(
            assessments, eligible, policy_id, policy_version
        )
        self._validate_result(result, bundle, policy, assessments, eligible)
        return result

    @staticmethod
    def _validate_bundle(
        bundle: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if bundle is None:
            raise DecisionExecutionContractError("MISSING_BUNDLE", "bundle is required")
        if not isinstance(bundle, Mapping):
            raise DecisionExecutionContractError(
                "BUNDLE_TYPE",
                f"bundle is not a mapping: {type(bundle).__name__}",
            )
        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in bundle:
                raise DecisionExecutionContractError(
                    "MISSING_BUNDLE_FIELD", f"bundle has no {field}"
                )
        for field in _BUNDLE_BOOLEAN_FIELDS:
            if not isinstance(bundle[field], bool):
                raise DecisionExecutionContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {bundle[field]!r}",
                )
        count = bundle["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionExecutionContractError(
                "BUNDLE_COUNT_TYPE",
                f"candidate_count is not an int: {count!r}",
            )
        if count < 0:
            raise DecisionExecutionContractError(
                "BUNDLE_COUNT_NEGATIVE",
                f"candidate_count is negative: {count!r}",
            )
        if bundle["input_source"] != INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037:
            raise DecisionExecutionContractError(
                "INVALID_BUNDLE_SOURCE",
                "input_source is not the Task 037 identifier: "
                f"{bundle['input_source']!r}",
            )
        cs = bundle["candidate_set"]
        aset = bundle["assessment_set"]
        if not isinstance(cs, Mapping):
            raise DecisionExecutionContractError(
                "CANDIDATE_SET_TYPE",
                f"candidate_set is not a mapping: {type(cs).__name__}",
            )
        if not isinstance(aset, Mapping):
            raise DecisionExecutionContractError(
                "ASSESSMENT_SET_TYPE",
                f"assessment_set is not a mapping: {type(aset).__name__}",
            )
        if not isinstance(cs.get("candidates"), list):
            raise DecisionExecutionContractError(
                "CANDIDATES_TYPE",
                "candidate_set.candidates is not a list",
            )
        if not isinstance(aset.get("assessments"), list):
            raise DecisionExecutionContractError(
                "ASSESSMENTS_TYPE",
                "assessment_set.assessments is not a list",
            )

        # Reuse Task 037's own validation boundary rather than
        # duplicating its rules. Any failure there means the supplied
        # bundle is not a valid Task 037 result and must not be
        # executed against.
        try:
            DecisionInputBundleService._validate_candidate_set(cs)
            DecisionInputBundleService._validate_assessment_set(aset)
            DecisionInputBundleService._check_alignment(cs, aset)
            DecisionInputBundleService._validate_result(bundle, cs, aset)
        except DecisionInputBundleContractError as exc:
            raise DecisionExecutionContractError(
                "INVALID_BUNDLE_STRUCTURE",
                "supplied bundle failed the Task 037 contract: " f"{exc}",
            ) from exc
        return bundle

    @staticmethod
    def _validate_policy(
        policy: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if policy is None:
            raise DecisionExecutionContractError("MISSING_POLICY", "policy is required")
        if not isinstance(policy, Mapping):
            raise DecisionExecutionContractError(
                "POLICY_TYPE",
                f"policy is not a mapping: {type(policy).__name__}",
            )
        for field in _POLICY_REQUIRED_FIELDS:
            if field not in policy:
                raise DecisionExecutionContractError(
                    "MISSING_POLICY_FIELD", f"policy has no {field}"
                )
        for field in ("policy_id", "policy_version"):
            if not isinstance(policy[field], str) or not policy[field]:
                raise DecisionExecutionContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not a non-empty string: {policy[field]!r}",
                )
        if policy["policy_source"] != POLICY_SOURCE_DECISION_POLICY_TASK_038:
            raise DecisionExecutionContractError(
                "INVALID_POLICY_SOURCE",
                "policy_source is not the Task 038 identifier: "
                f"{policy['policy_source']!r}",
            )
        for field, required_value in _REQUIRED_POLICY_VALUES.items():
            if policy[field] != required_value:
                raise DecisionExecutionContractError(
                    "UNSUPPORTED_POLICY_VALUES",
                    f"Task 039 only executes the default policy; "
                    f"{field} is {policy[field]!r}, expected "
                    f"{required_value!r}",
                )
        return policy

    @staticmethod
    def _compute_eligible(
        assessments: list[Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        eligible: list[Mapping[str, Any]] = []
        for a in assessments:
            if not isinstance(a, Mapping):
                raise DecisionExecutionContractError(
                    "MALFORMED_ASSESSMENT",
                    f"assessment is not a mapping: {type(a).__name__}",
                )
            criteria = a.get("criteria")
            if not isinstance(criteria, list):
                raise DecisionExecutionContractError(
                    "MISSING_ASSESSMENT_CRITERIA",
                    "assessment has no criteria list",
                )
            all_required_satisfied = True
            for c in criteria:
                if not isinstance(c, Mapping):
                    raise DecisionExecutionContractError(
                        "MALFORMED_CRITERION",
                        f"criterion is not a mapping: {type(c).__name__}",
                    )
                if "required" not in c or "satisfied" not in c:
                    raise DecisionExecutionContractError(
                        "MISSING_CRITERION_FIELD",
                        "criterion missing required or satisfied",
                    )
                if not isinstance(c["required"], bool) or not isinstance(
                    c["satisfied"], bool
                ):
                    raise DecisionExecutionContractError(
                        "CRITERION_FIELD_TYPE",
                        "required/satisfied are not booleans",
                    )
                if c["required"] and not c["satisfied"]:
                    all_required_satisfied = False
                    # Do not break: continue validating the remaining
                    # criteria so a malformed criterion later in the
                    # assessment is still detected.
            if all_required_satisfied:
                eligible.append(a)
        return eligible

    def _execute_default_policy(
        self,
        assessments: list[Mapping[str, Any]],
        eligible: list[Mapping[str, Any]],
        policy_id: str,
        policy_version: str,
    ) -> dict[str, Any]:
        del assessments  # kept for symmetry / future multi-mode policies
        eligible_ids = [a["hypothesis_id"] for a in eligible]
        eligible_count = len(eligible_ids)

        if eligible_count == 0:
            outcome = OUTCOME_NO_ELIGIBLE_CANDIDATE
            selected = None
        else:
            highest_rank = min(a["rank"] for a in eligible)
            at_highest = [a for a in eligible if a["rank"] == highest_rank]
            if len(at_highest) == 1:
                outcome = OUTCOME_SELECTED
                winner = at_highest[0]
                selected = {
                    "hypothesis_id": winner["hypothesis_id"],
                    "hypothesis_name": winner["hypothesis_name"],
                    "rank": winner["rank"],
                    "score": winner["score"],
                }
            else:
                outcome = OUTCOME_UNRESOLVED
                selected = None

        return {
            "available": True,
            "outcome": outcome,
            "selected_candidate": selected,
            "eligible_candidate_count": eligible_count,
            "eligible_candidate_ids": list(eligible_ids),
            "policy_id": policy_id,
            "policy_version": policy_version,
            "decision_execution_source": (
                DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
            ),
        }

    def _make_unavailable_result(
        self, outcome: str, policy_id: str, policy_version: str
    ) -> dict[str, Any]:
        return {
            "available": False,
            "outcome": outcome,
            "selected_candidate": None,
            "eligible_candidate_count": 0,
            "eligible_candidate_ids": [],
            "policy_id": policy_id,
            "policy_version": policy_version,
            "decision_execution_source": (
                DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
            ),
        }

    def _validate_result(
        self,
        result: dict[str, Any],
        bundle: Mapping[str, Any],
        policy: Mapping[str, Any],
        assessments: list[Mapping[str, Any]],
        eligible: list[Mapping[str, Any]],
    ) -> None:
        if not isinstance(result["available"], bool):
            raise DecisionExecutionContractError(
                "AVAILABLE_TYPE",
                f"available is not boolean: {result['available']!r}",
            )
        if result["outcome"] not in _OUTCOMES:
            raise DecisionExecutionContractError(
                "INVALID_OUTCOME",
                f"outcome is not a known identifier: {result['outcome']!r}",
            )
        count = result["eligible_candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionExecutionContractError(
                "COUNT_TYPE", f"count is not int: {count!r}"
            )
        if count < 0:
            raise DecisionExecutionContractError(
                "COUNT_NEGATIVE", f"count is negative: {count!r}"
            )
        ids = result["eligible_candidate_ids"]
        if not isinstance(ids, list):
            raise DecisionExecutionContractError(
                "IDS_TYPE", f"ids is not a list: {type(ids).__name__}"
            )
        for hid in ids:
            if not isinstance(hid, UUID):
                raise DecisionExecutionContractError(
                    "INVALID_ID", f"id is not a UUID: {type(hid).__name__}"
                )
        if len(set(ids)) != len(ids):
            raise DecisionExecutionContractError(
                "DUPLICATE_ID", f"ids contains duplicates: {ids!r}"
            )
        if count != len(ids):
            raise DecisionExecutionContractError(
                "COUNT_MISMATCH",
                f"count {count} != ids length {len(ids)}",
            )

        # Eligible IDs must be exactly the eligible assessments, in order.
        expected_eligible_ids = [a["hypothesis_id"] for a in eligible]
        if ids != expected_eligible_ids:
            raise DecisionExecutionContractError(
                "ELIGIBLE_IDS_MISMATCH",
                "eligible_candidate_ids does not match the computed "
                "eligible set in upstream order",
            )

        outcome = result["outcome"]
        selected = result["selected_candidate"]

        if result["policy_id"] != policy["policy_id"]:
            raise DecisionExecutionContractError(
                "POLICY_ID_MISMATCH",
                "policy_id does not match upstream policy: "
                f"{result['policy_id']!r} != {policy['policy_id']!r}",
            )
        if result["policy_version"] != policy["policy_version"]:
            raise DecisionExecutionContractError(
                "POLICY_VERSION_MISMATCH",
                "policy_version does not match upstream policy: "
                f"{result['policy_version']!r} != "
                f"{policy['policy_version']!r}",
            )
        if (
            result["decision_execution_source"]
            != DECISION_EXECUTION_SOURCE_DECISION_EXECUTION_TASK_039
        ):
            raise DecisionExecutionContractError(
                "INVALID_SOURCE",
                "decision_execution_source is not the Task 039 identifier: "
                f"{result['decision_execution_source']!r}",
            )

        if outcome in (
            OUTCOME_INPUT_UNAVAILABLE,
            OUTCOME_INPUT_INCONSISTENT,
        ):
            if result["available"] is not False:
                raise DecisionExecutionContractError(
                    "UNAVAILABLE_AVAILABLE_MISMATCH",
                    f"outcome {outcome!r} requires available=False",
                )
            if selected is not None:
                raise DecisionExecutionContractError(
                    "SELECTED_FORBIDDEN",
                    f"outcome {outcome!r} forbids selected_candidate",
                )
            if ids or count != 0:
                raise DecisionExecutionContractError(
                    "ELIGIBLE_IDS_FORBIDDEN",
                    f"outcome {outcome!r} forbids eligible ids",
                )
            if outcome == OUTCOME_INPUT_UNAVAILABLE:
                if bundle["available"] is not False:
                    raise DecisionExecutionContractError(
                        "INPUT_UNAVAILABLE_MISMATCH",
                        "INPUT_UNAVAILABLE requires bundle.available=False",
                    )
            else:  # INPUT_INCONSISTENT
                if bundle["available"] is True:
                    if bundle["input_structure_consistent"] is True:
                        raise DecisionExecutionContractError(
                            "INPUT_INCONSISTENT_MISMATCH",
                            "INPUT_INCONSISTENT requires either "
                            "bundle.available=False or "
                            "bundle.input_structure_consistent=False",
                        )
            return

        # From here on, bundle must have been available and consistent.
        if result["available"] is not True:
            raise DecisionExecutionContractError(
                "AVAILABLE_MISMATCH",
                f"outcome {outcome!r} requires available=True",
            )

        if outcome == OUTCOME_NO_ELIGIBLE_CANDIDATE:
            if count != 0:
                raise DecisionExecutionContractError(
                    "NO_ELIGIBLE_MISMATCH",
                    "NO_ELIGIBLE_CANDIDATE requires eligible_count == 0",
                )
            if selected is not None:
                raise DecisionExecutionContractError(
                    "SELECTED_FORBIDDEN",
                    "NO_ELIGIBLE_CANDIDATE forbids selected_candidate",
                )
            return

        if outcome == OUTCOME_UNRESOLVED:
            if selected is not None:
                raise DecisionExecutionContractError(
                    "SELECTED_FORBIDDEN",
                    "UNRESOLVED forbids selected_candidate",
                )
            if count < 2:
                raise DecisionExecutionContractError(
                    "UNRESOLVED_NEEDS_TIE",
                    "UNRESOLVED requires at least two eligible candidates",
                )
            highest_rank = min(a["rank"] for a in eligible)
            at_highest = [a for a in eligible if a["rank"] == highest_rank]
            if len(at_highest) < 2:
                raise DecisionExecutionContractError(
                    "UNRESOLVED_NOT_TIED",
                    "UNRESOLVED requires at least two eligible candidates "
                    "sharing the highest eligible rank",
                )
            return

        # outcome == SELECTED
        if selected is None:
            raise DecisionExecutionContractError(
                "SELECTED_MISSING",
                "outcome SELECTED requires selected_candidate",
            )
        if not isinstance(selected, Mapping):
            raise DecisionExecutionContractError(
                "SELECTED_TYPE",
                f"selected_candidate is not a mapping: " f"{type(selected).__name__}",
            )
        for field in (
            "hypothesis_id",
            "hypothesis_name",
            "rank",
            "score",
        ):
            if field not in selected:
                raise DecisionExecutionContractError(
                    "SELECTED_MISSING_FIELD",
                    f"selected_candidate has no {field}",
                )
        if not isinstance(selected["hypothesis_id"], UUID):
            raise DecisionExecutionContractError(
                "SELECTED_ID_TYPE",
                "selected hypothesis_id is not a UUID",
            )
        if selected["hypothesis_id"] not in ids:
            raise DecisionExecutionContractError(
                "SELECTED_NOT_ELIGIBLE",
                "selected_candidate is not in the eligible set",
            )
        highest_rank = min(a["rank"] for a in eligible)
        at_highest = [a for a in eligible if a["rank"] == highest_rank]
        if len(at_highest) != 1:
            raise DecisionExecutionContractError(
                "SELECTED_NOT_UNIQUE_HIGHEST",
                "SELECTED requires exactly one eligible candidate at the "
                "highest eligible rank",
            )
        winner = at_highest[0]
        if selected["hypothesis_id"] != winner["hypothesis_id"]:
            raise DecisionExecutionContractError(
                "SELECTED_NOT_HIGHEST",
                "selected_candidate is not the unique highest-ranked "
                "eligible candidate",
            )
        if selected["hypothesis_name"] != winner["hypothesis_name"]:
            raise DecisionExecutionContractError(
                "SELECTED_NAME_MISMATCH",
                "selected hypothesis_name does not match upstream",
            )
        if selected["rank"] != winner["rank"]:
            raise DecisionExecutionContractError(
                "SELECTED_RANK_MISMATCH",
                "selected rank does not match upstream",
            )
        if selected["score"] != winner["score"]:
            raise DecisionExecutionContractError(
                "SELECTED_SCORE_MISMATCH",
                "selected score does not match upstream",
            )

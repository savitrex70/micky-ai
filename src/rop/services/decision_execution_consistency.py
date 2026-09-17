from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.decision_execution import (
    DecisionExecutionService,
)
from rop.services.decision_input_bundle import (
    INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037,
    DecisionInputBundleContractError,
    DecisionInputBundleService,
)
from rop.services.decision_policy import (
    POLICY_SOURCE_DECISION_POLICY_TASK_038,
    DecisionPolicyContractError,
    DecisionPolicyService,
)

DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040 = (
    "DECISION_EXECUTION_CONSISTENCY_TASK_040"
)
"""Fixed structural-contract identifier for Task 040 results."""

_EXECUTION_SOURCE_TASK_039 = "DECISION_EXECUTION_TASK_039"

_OUTCOME_SELECTED = "SELECTED"
_OUTCOME_NO_ELIGIBLE = "NO_ELIGIBLE_CANDIDATE"
_OUTCOME_UNRESOLVED = "UNRESOLVED"
_OUTCOME_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
_OUTCOME_INPUT_INCONSISTENT = "INPUT_INCONSISTENT"

_ALL_OUTCOMES = frozenset(
    {
        _OUTCOME_SELECTED,
        _OUTCOME_NO_ELIGIBLE,
        _OUTCOME_UNRESOLVED,
        _OUTCOME_INPUT_UNAVAILABLE,
        _OUTCOME_INPUT_INCONSISTENT,
    }
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

# Only the approved Task 038 default policy is auditable -- consistent
# with Task 039, which refuses to execute any other policy.
_REQUIRED_POLICY_VALUES = {
    "allowed_selection_mode": "SINGLE_CANDIDATE",
    "required_candidate_count": 1,
    "required_criteria_behavior": "MUST_ALL_BE_SATISFIED",
    "tie_behavior": "MUST_RETURN_UNRESOLVED",
    "insufficient_input_behavior": "MUST_RETURN_UNAVAILABLE",
    "incomplete_input_behavior": "MUST_RETURN_INCONSISTENT",
}

_EXECUTION_REQUIRED_FIELDS = (
    "available",
    "outcome",
    "selected_candidate",
    "eligible_candidate_count",
    "eligible_candidate_ids",
    "policy_id",
    "policy_version",
    "decision_execution_source",
)

_EXECUTION_SELECTED_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "rank",
    "score",
)

# Deterministic output order for consistency_issues. Only issues
# present in the audit are emitted, in this stable order.
_ISSUE_ORDER = (
    "INVALID_EXECUTION_SOURCE",
    "POLICY_ID_MISMATCH",
    "POLICY_VERSION_MISMATCH",
    "ELIGIBLE_COUNT_MISMATCH",
    "ELIGIBLE_IDS_MISMATCH",
    "DUPLICATE_ELIGIBLE_ID",
    "OUTCOME_MISMATCH",
    "SELECTED_MISSING",
    "SELECTED_FORBIDDEN",
    "SELECTED_NOT_ELIGIBLE",
    "SELECTED_NOT_HIGHEST",
    "SELECTED_NOT_UNIQUE_HIGHEST",
    "SELECTED_METADATA_MISMATCH",
    "UNRESOLVED_NOT_TIED",
    "NO_ELIGIBLE_MISMATCH",
    "AVAILABLE_MISMATCH",
)


class DecisionExecutionConsistencyContractError(Exception):
    """Task 040: malformed upstream input.

    Raised only when the Task 037 bundle, Task 038 policy, or Task 039
    execution result is not shaped like its own established contract.
    It is never raised for a valid but inconsistent execution result --
    inconsistent executions are the normal, fully typed subject of this
    audit.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionExecutionConsistencyService:
    """Task 040: independent audit of a Task 039 execution result.

    Consumes Task 037's bundle, Task 038's policy, and Task 039's
    execution result. Independently re-derives the expected eligible
    candidate set and expected outcome from the bundle and policy, then
    compares the execution result field by field. Introduces no new
    decision, ranking, scoring, or selection logic; performs no
    persistence; mutates no input.
    """

    def __init__(
        self,
        decision_input_bundle_service: DecisionInputBundleService | None = None,
        decision_policy_service: DecisionPolicyService | None = None,
        decision_execution_service: DecisionExecutionService | None = None,
    ) -> None:
        self.decision_input_bundle_service = (
            decision_input_bundle_service or DecisionInputBundleService()
        )
        self.decision_policy_service = (
            decision_policy_service or DecisionPolicyService()
        )
        self.decision_execution_service = (
            decision_execution_service or DecisionExecutionService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Compose Tasks 037-039, then audit the result.

        Delegates the upstream pipeline to Task 037's
        ``build_for_session``, the policy contract to Task 038's
        ``build``, the execution to Task 039's ``build``, then runs
        this service's pure ``build``. It does not walk Tasks 031-036
        itself.
        """
        bundle = self.decision_input_bundle_service.build_for_session(
            db, session_id, candidates
        )
        policy = self.decision_policy_service.build()
        execution = self.decision_execution_service.build(bundle, policy)
        return self.build(bundle, policy, execution)

    def build(
        self,
        bundle: Mapping[str, Any] | None,
        policy: Mapping[str, Any] | None,
        execution_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Audit the execution result against independently derived expectations."""
        bundle = self._validate_bundle(bundle)
        policy = self._validate_policy(policy)
        execution = self._validate_execution(execution_result)

        expected_eligible = self._compute_expected_eligible(bundle)
        expected_eligible_ids = [
            a["hypothesis_id"] for a in expected_eligible
        ]
        expected_outcome = self._derive_expected_outcome(
            bundle, expected_eligible
        )

        issues: list[str] = []

        # Source check on the audited execution result.
        if execution["decision_execution_source"] != _EXECUTION_SOURCE_TASK_039:
            issues.append("INVALID_EXECUTION_SOURCE")

        # Policy metadata preservation.
        if execution["policy_id"] != policy["policy_id"]:
            issues.append("POLICY_ID_MISMATCH")
        if execution["policy_version"] != policy["policy_version"]:
            issues.append("POLICY_VERSION_MISMATCH")

        # Eligibility audit.
        exec_ids = list(execution["eligible_candidate_ids"])
        if len(set(exec_ids)) != len(exec_ids):
            issues.append("DUPLICATE_ELIGIBLE_ID")
        if execution["eligible_candidate_count"] != len(expected_eligible_ids):
            issues.append("ELIGIBLE_COUNT_MISMATCH")
        if exec_ids != expected_eligible_ids:
            issues.append("ELIGIBLE_IDS_MISMATCH")

        # Outcome audit.
        if execution["outcome"] != expected_outcome:
            issues.append("OUTCOME_MISMATCH")

        # Selection audit, driven by the execution's own outcome.
        self._audit_selection(
            issues, execution, expected_eligible, bundle
        )

        # Deterministic ordering, no duplicates.
        unique_issues = set(issues)
        ordered_issues = [
            i for i in _ISSUE_ORDER if i in unique_issues
        ]
        # Any issue not in _ISSUE_ORDER (shouldn't happen) is appended
        # in sorted order so the output stays deterministic.
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        source_consistent = "INVALID_EXECUTION_SOURCE" not in unique_issues
        metadata_consistent = not any(
            i in unique_issues
            for i in ("POLICY_ID_MISMATCH", "POLICY_VERSION_MISMATCH")
        )
        eligibility_consistent = not any(
            i in unique_issues
            for i in (
                "ELIGIBLE_COUNT_MISMATCH",
                "ELIGIBLE_IDS_MISMATCH",
                "DUPLICATE_ELIGIBLE_ID",
            )
        )
        outcome_consistent = "OUTCOME_MISMATCH" not in unique_issues
        selection_consistent = not any(
            i in unique_issues
            for i in (
                "SELECTED_MISSING",
                "SELECTED_FORBIDDEN",
                "SELECTED_NOT_ELIGIBLE",
                "SELECTED_NOT_HIGHEST",
                "SELECTED_NOT_UNIQUE_HIGHEST",
                "SELECTED_METADATA_MISMATCH",
                "UNRESOLVED_NOT_TIED",
                "NO_ELIGIBLE_MISMATCH",
                "AVAILABLE_MISMATCH",
            )
        )
        execution_consistent = not ordered_issues

        result: dict[str, Any] = {
            "available": True,
            "execution_consistent": execution_consistent,
            "outcome_consistent": outcome_consistent,
            "eligibility_consistent": eligibility_consistent,
            "selection_consistent": selection_consistent,
            "metadata_consistent": metadata_consistent,
            "source_consistent": source_consistent,
            "consistency_issues": ordered_issues,
            "execution_source": (
                DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040
            ),
        }
        self._validate_result(result)
        return result

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_bundle(
        bundle: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if bundle is None:
            raise DecisionExecutionConsistencyContractError(
                "MISSING_BUNDLE", "bundle is required"
            )
        if not isinstance(bundle, Mapping):
            raise DecisionExecutionConsistencyContractError(
                "BUNDLE_TYPE",
                f"bundle is not a mapping: {type(bundle).__name__}",
            )
        if (
            bundle.get("input_source")
            != INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037
        ):
            raise DecisionExecutionConsistencyContractError(
                "INVALID_BUNDLE_SOURCE",
                "bundle.input_source is not the Task 037 identifier: "
                f"{bundle.get('input_source')!r}",
            )
        cs = bundle.get("candidate_set")
        aset = bundle.get("assessment_set")
        if not isinstance(cs, Mapping) or not isinstance(aset, Mapping):
            raise DecisionExecutionConsistencyContractError(
                "BUNDLE_NESTED_TYPE",
                "candidate_set and assessment_set must be mappings",
            )
        try:
            DecisionInputBundleService._validate_candidate_set(cs)
            DecisionInputBundleService._validate_assessment_set(aset)
            DecisionInputBundleService._check_alignment(cs, aset)
            DecisionInputBundleService._validate_result(bundle, cs, aset)
        except DecisionInputBundleContractError as exc:
            raise DecisionExecutionConsistencyContractError(
                "INVALID_BUNDLE_STRUCTURE",
                f"bundle failed the Task 037 contract: {exc}",
            ) from exc
        return bundle

    @staticmethod
    def _validate_policy(
        policy: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if policy is None:
            raise DecisionExecutionConsistencyContractError(
                "MISSING_POLICY", "policy is required"
            )
        if not isinstance(policy, Mapping):
            raise DecisionExecutionConsistencyContractError(
                "POLICY_TYPE",
                f"policy is not a mapping: {type(policy).__name__}",
            )
        # Reuse Task 038's own validation boundary rather than
        # partially recreating it -- otherwise a policy such as
        # {"required_candidate_count": True} would slip through because
        # True == 1, and non-string policy_name values would pass too.
        try:
            DecisionPolicyService._validate_policy(policy)
        except DecisionPolicyContractError as exc:
            raise DecisionExecutionConsistencyContractError(
                "INVALID_POLICY_STRUCTURE",
                f"policy failed the Task 038 contract: {exc}",
            ) from exc
        for field, required_value in _REQUIRED_POLICY_VALUES.items():
            if policy[field] != required_value:
                raise DecisionExecutionConsistencyContractError(
                    "UNSUPPORTED_POLICY_VALUES",
                    "Task 040 only audits executions of the default policy; "
                    f"{field} is {policy[field]!r}, expected "
                    f"{required_value!r}",
                )
        return policy

    @staticmethod
    def _validate_execution(
        execution_result: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if execution_result is None:
            raise DecisionExecutionConsistencyContractError(
                "MISSING_EXECUTION", "execution_result is required"
            )
        if not isinstance(execution_result, Mapping):
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_TYPE",
                "execution_result is not a mapping: "
                f"{type(execution_result).__name__}",
            )
        for field in _EXECUTION_REQUIRED_FIELDS:
            if field not in execution_result:
                raise DecisionExecutionConsistencyContractError(
                    "MISSING_EXECUTION_FIELD",
                    f"execution_result has no {field}",
                )
        if not isinstance(execution_result["available"], bool):
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_AVAILABLE_TYPE",
                "execution_result.available is not boolean: "
                f"{execution_result['available']!r}",
            )
        outcome = execution_result["outcome"]
        if outcome not in _ALL_OUTCOMES:
            raise DecisionExecutionConsistencyContractError(
                "INVALID_OUTCOME",
                f"outcome is not a known identifier: {outcome!r}",
            )
        count = execution_result["eligible_candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool):
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_COUNT_TYPE",
                f"eligible_candidate_count is not int: {count!r}",
            )
        if count < 0:
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_COUNT_NEGATIVE",
                f"eligible_candidate_count is negative: {count!r}",
            )
        ids = execution_result["eligible_candidate_ids"]
        if not isinstance(ids, list):
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_IDS_TYPE",
                f"eligible_candidate_ids is not a list: "
                f"{type(ids).__name__}",
            )
        for hid in ids:
            if not isinstance(hid, UUID):
                raise DecisionExecutionConsistencyContractError(
                    "EXECUTION_ID_TYPE",
                    f"eligible_candidate_id is not a UUID: "
                    f"{type(hid).__name__}",
                )
        for field in ("policy_id", "policy_version"):
            if not isinstance(execution_result[field], str) or not (
                execution_result[field]
            ):
                raise DecisionExecutionConsistencyContractError(
                    f"EXECUTION_{field.upper()}_TYPE",
                    f"{field} is not a non-empty string: "
                    f"{execution_result[field]!r}",
                )
        if not isinstance(
            execution_result["decision_execution_source"], str
        ):
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_SOURCE_TYPE",
                "decision_execution_source is not a string: "
                f"{execution_result['decision_execution_source']!r}",
            )
        selected = execution_result["selected_candidate"]
        if selected is not None:
            if not isinstance(selected, Mapping):
                raise DecisionExecutionConsistencyContractError(
                    "SELECTED_TYPE",
                    f"selected_candidate is not a mapping: "
                    f"{type(selected).__name__}",
                )
            for field in _EXECUTION_SELECTED_FIELDS:
                if field not in selected:
                    raise DecisionExecutionConsistencyContractError(
                        "SELECTED_MISSING_FIELD",
                        f"selected_candidate has no {field}",
                    )
            if not isinstance(selected["hypothesis_id"], UUID):
                raise DecisionExecutionConsistencyContractError(
                    "SELECTED_ID_TYPE",
                    "selected hypothesis_id is not a UUID",
                )
            if not isinstance(selected["hypothesis_name"], str):
                raise DecisionExecutionConsistencyContractError(
                    "SELECTED_NAME_TYPE",
                    "selected hypothesis_name is not a string",
                )
            if not isinstance(selected["rank"], int) or isinstance(
                selected["rank"], bool
            ):
                raise DecisionExecutionConsistencyContractError(
                    "SELECTED_RANK_TYPE",
                    "selected rank is not an int",
                )
            score = selected["score"]
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise DecisionExecutionConsistencyContractError(
                    "SELECTED_SCORE_TYPE",
                    "selected score is not numeric",
                )
        return execution_result

    # ------------------------------------------------------------------
    # Independent derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_expected_eligible(
        bundle: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        """Re-derive the eligible set from individual criterion entries.

        Task 040 must not trust the pre-computed counts on each
        assessment; it walks the criterion list directly, exactly as
        Task 039 does.
        """
        assessments = bundle["assessment_set"]["assessments"]
        eligible: list[Mapping[str, Any]] = []
        for a in assessments:
            criteria = a["criteria"]
            all_required_satisfied = True
            for c in criteria:
                if c["required"] and not c["satisfied"]:
                    all_required_satisfied = False
            if all_required_satisfied:
                eligible.append(a)
        return eligible

    @staticmethod
    def _derive_expected_outcome(
        bundle: Mapping[str, Any],
        expected_eligible: list[Mapping[str, Any]],
    ) -> str:
        # Structure first: Task 037 folds input_structure_consistent
        # into available, so checking available first would mask the
        # inconsistent case entirely.
        if not bundle["input_structure_consistent"]:
            return _OUTCOME_INPUT_INCONSISTENT
        if not bundle["available"]:
            return _OUTCOME_INPUT_UNAVAILABLE
        if not expected_eligible:
            return _OUTCOME_NO_ELIGIBLE
        min_rank = min(a["rank"] for a in expected_eligible)
        at_min = [a for a in expected_eligible if a["rank"] == min_rank]
        if len(at_min) == 1:
            return _OUTCOME_SELECTED
        return _OUTCOME_UNRESOLVED

    def _audit_selection(
        self,
        issues: list[str],
        execution: Mapping[str, Any],
        expected_eligible: list[Mapping[str, Any]],
        bundle: Mapping[str, Any],
    ) -> None:
        outcome = execution["outcome"]
        selected = execution["selected_candidate"]
        exec_ids = execution["eligible_candidate_ids"]
        exec_count = execution["eligible_candidate_count"]

        if outcome == _OUTCOME_SELECTED:
            if execution["available"] is not True:
                issues.append("AVAILABLE_MISMATCH")
            if selected is None:
                issues.append("SELECTED_MISSING")
                return
            if selected["hypothesis_id"] not in exec_ids:
                issues.append("SELECTED_NOT_ELIGIBLE")
            if not expected_eligible:
                return
            min_rank = min(a["rank"] for a in expected_eligible)
            at_min = [a for a in expected_eligible if a["rank"] == min_rank]
            if len(at_min) != 1:
                issues.append("SELECTED_NOT_UNIQUE_HIGHEST")
            else:
                winner = at_min[0]
                if selected["hypothesis_id"] != winner["hypothesis_id"]:
                    issues.append("SELECTED_NOT_HIGHEST")
                # Selected metadata must match upstream.
                if (
                    selected["hypothesis_name"] != winner["hypothesis_name"]
                    or selected["rank"] != winner["rank"]
                    or selected["score"] != winner["score"]
                ):
                    issues.append("SELECTED_METADATA_MISMATCH")

        elif outcome == _OUTCOME_UNRESOLVED:
            if execution["available"] is not True:
                issues.append("AVAILABLE_MISMATCH")
            if selected is not None:
                issues.append("SELECTED_FORBIDDEN")
            if not expected_eligible:
                issues.append("UNRESOLVED_NOT_TIED")
                return
            min_rank = min(a["rank"] for a in expected_eligible)
            at_min = [a for a in expected_eligible if a["rank"] == min_rank]
            if len(at_min) < 2:
                issues.append("UNRESOLVED_NOT_TIED")

        elif outcome == _OUTCOME_NO_ELIGIBLE:
            if execution["available"] is not True:
                issues.append("AVAILABLE_MISMATCH")
            if selected is not None:
                issues.append("SELECTED_FORBIDDEN")
            if exec_count != 0 or exec_ids:
                issues.append("NO_ELIGIBLE_MISMATCH")

        elif outcome == _OUTCOME_INPUT_UNAVAILABLE:
            if execution["available"] is not False:
                issues.append("AVAILABLE_MISMATCH")
            if selected is not None:
                issues.append("SELECTED_FORBIDDEN")
            if exec_count != 0 or exec_ids:
                issues.append("NO_ELIGIBLE_MISMATCH")

        elif outcome == _OUTCOME_INPUT_INCONSISTENT:
            if execution["available"] is not False:
                issues.append("AVAILABLE_MISMATCH")
            if selected is not None:
                issues.append("SELECTED_FORBIDDEN")
            if exec_count != 0 or exec_ids:
                issues.append("NO_ELIGIBLE_MISMATCH")

    # ------------------------------------------------------------------
    # Output validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in (
            "available",
            "execution_consistent",
            "outcome_consistent",
            "eligibility_consistent",
            "selection_consistent",
            "metadata_consistent",
            "source_consistent",
        ):
            if not isinstance(result[field], bool):
                raise DecisionExecutionConsistencyContractError(
                    "RESULT_FIELD_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise DecisionExecutionConsistencyContractError(
                "ISSUES_TYPE",
                f"consistency_issues is not a list: "
                f"{type(issues).__name__}",
            )
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                raise DecisionExecutionConsistencyContractError(
                    "ISSUE_TYPE",
                    f"issue is not a non-empty string: {issue!r}",
                )
        if len(set(issues)) != len(issues):
            raise DecisionExecutionConsistencyContractError(
                "DUPLICATE_ISSUE",
                f"consistency_issues contains duplicates: {issues!r}",
            )
        # Deterministic order check.
        ordered = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order = ordered + leftovers
        if issues != expected_order:
            raise DecisionExecutionConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in the fixed order: "
                f"{issues!r}",
            )
        if (
            result["execution_source"]
            != DECISION_EXECUTION_CONSISTENCY_SOURCE_TASK_040
        ):
            raise DecisionExecutionConsistencyContractError(
                "INVALID_SOURCE",
                "execution_source is not the Task 040 identifier: "
                f"{result['execution_source']!r}",
            )
        # Cross-check that execution_consistent is the AND of all flags.
        expected_consistent = (
            result["outcome_consistent"]
            and result["eligibility_consistent"]
            and result["selection_consistent"]
            and result["metadata_consistent"]
            and result["source_consistent"]
        )
        if result["execution_consistent"] != expected_consistent:
            raise DecisionExecutionConsistencyContractError(
                "EXECUTION_CONSISTENT_MISMATCH",
                "execution_consistent does not match the AND of the "
                f"individual flags: {result['execution_consistent']!r} "
                f"!= {expected_consistent!r}",
            )
        # Cross-check that no issues <=> execution_consistent True.
        if (not issues) != result["execution_consistent"]:
            raise DecisionExecutionConsistencyContractError(
                "ISSUES_CONSISTENT_MISMATCH",
                "consistency_issues and execution_consistent disagree",
            )

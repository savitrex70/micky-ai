from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.differential_decision_readiness import (
    DifferentialDecisionReadinessService,
)

CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031 = "DECISION_CONTEXT_TASK_031"
"""Fixed structural-contract identifier for the Task 031 decision context.

Names *which* contract produced the package. It is not a score, a
probability, a confidence, or a recommendation.
"""

_REQUIRED_RANKED_FIELDS = (
    "rank",
    "hypothesis_id",
    "hypothesis_score",
    "is_tied",
    "tie_group_size",
    "score_gap_to_next_higher",
    "score_gap_to_next_lower",
)

_REQUIRED_SUMMARY_FIELDS = (
    "total_candidates",
    "distinct_score_groups",
    "top_rank",
    "highest_score",
    "lowest_score",
    "score_range",
    "tied_candidate_count",
    "tie_group_count",
    "largest_tie_group_size",
    "has_any_ties",
)

_REQUIRED_CONSISTENCY_FIELDS = (
    "consistent",
    "candidate_count_matches",
    "score_groups_match",
    "tie_statistics_match",
    "score_range_matches",
    "rank_structure_matches",
    "separation_metadata_matches",
    "summary_consistent",
)

_REQUIRED_READINESS_FIELDS = (
    "ready",
    "consistency_verified",
    "has_candidates",
    "ranking_available",
    "summary_available",
    "separation_metadata_available",
    "has_score_separation",
    "has_unresolved_ties",
    "evidence_present_for_any_candidate",
)

_CONTEXT_BOOLEAN_FIELDS = (
    "context_available",
    "decision_ready",
    "consistency_verified",
)


class DecisionContextContractError(Exception):
    """Task 031: structurally unusable or internally contradictory input.

    Raised in two situations, both distinct from a normal "not ready"
    state:

    1. A required nested component is absent or cannot be structurally
       interpreted — ``None`` in place of the differential, the
       summary, the consistency result, or the readiness result; a
       ranked entry, summary, consistency result, or readiness result
       missing a required field.
    2. The assembled context contradicts itself —
       ``candidate_count != len(differential)``,
       ``decision_ready != decision_readiness.ready``,
       ``consistency_verified != differential_consistency.consistent``,
       or ``context_available`` disagreeing with its own definition.
       Task 031 packages Tasks 027-030's outputs; it never gets to
       disagree with them, so any mismatch between the top-level
       convenience fields and the nested contract they were copied
       from means something upstream corrupted the package.

    A normal "not decision-ready" state (``decision_ready = False``,
    ``context_available = False``) is never this error — it's a valid,
    fully typed response. Like the Task 025-030 contract errors, this
    must never be exposed verbatim to API clients; the API layer
    converts it to a generic 500.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DecisionContextService:
    """Task 031: the first stable input contract for a future decision engine.

    ROP's differential layers now stack as::

        025 -> Hypothesis Score Contract
        026 -> Differential Ranking
        027 -> Separation Metadata
        028 -> Differential Structural Summary
        029 -> Differential Consistency Verification
        030 -> Differential Decision Readiness

    This service does nothing new structurally. It packages the
    already-validated outputs of Tasks 027-030 into one deterministic,
    read-only ``DecisionContext`` so a future decision engine can
    consume a single object instead of reaching backward into raw
    scoring, ranking, summary, consistency, or readiness services.

    It computes no score, runs no ranking algorithm, and re-derives
    nothing from evidence. The only things it adds are: a
    ``candidate_count`` mirror of ``len(differential)``, a
    ``decision_ready`` mirror of ``decision_readiness.ready``, a
    ``consistency_verified`` mirror of
    ``differential_consistency.consistent``, and the
    ``context_available`` verdict described below. Every nested
    component — the full Task 027 differential, the Task 028 summary,
    the Task 029 consistency result, the Task 030 readiness result —
    is preserved exactly, unmutated, and fully typed.

    ``context_available`` means *a complete, internally consistent
    decision-context package has been assembled*. It does not mean a
    decision exists, a diagnosis is known, or a winner exists. It is
    the conjunction of ``decision_ready``, ``consistency_verified``,
    and a non-zero ``candidate_count``. ``decision_ready`` is never
    redefined here — it is taken verbatim from Task 030's own
    readiness verdict, the same way Task 030 took Task 029's
    ``consistent`` verbatim.

    Read-only throughout: nothing is persisted, and the four upstream
    structures are defensively deep-copied rather than mutated in
    place or returned by reference.
    """

    def __init__(
        self,
        readiness_service: DifferentialDecisionReadinessService | None = None,
    ) -> None:
        self.readiness_service = (
            readiness_service or DifferentialDecisionReadinessService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Return the session's decision context.

        Walks the established dependency chain rather than bypassing
        it: the Task 027 ranked differential, Task 028 summary, Task
        029 consistency result, and Task 030 readiness result are each
        reached through the service directly below it, so one ranking
        result feeds every layer. Never recomputes a hypothesis score
        and never introduces a second ranking or scoring engine.
        Read-only: no database writes, no persistence.
        """
        consistency_service = self.readiness_service.consistency_service
        summary_service = consistency_service.summary_service
        ranking_service = summary_service.ranking_service

        ranked = ranking_service.rank_session(db, session_id, candidates)
        summary = summary_service.summarize_ranked(ranked)
        consistency_result = consistency_service.check_consistency(ranked, summary)
        readiness_result = self.readiness_service.evaluate(
            ranked, summary, consistency_result
        )

        return self.build(ranked, summary, consistency_result, readiness_result)

    def build(
        self,
        differential: list[dict[str, Any]] | None,
        differential_summary: Mapping[str, Any] | None,
        differential_consistency: Mapping[str, Any] | None,
        decision_readiness: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Package an already-produced 027/028/029/030 quadruple.

        Kept separate from ``build_for_session`` so packaging can be
        exercised directly against hand-built structures, without going
        through the full evidence/scoring/ranking/summary/consistency/
        readiness pipeline.

        Every nested component is defensively deep-copied before being
        packaged: the objects the caller passed in are never the
        objects mutated or returned, so the caller's originals are
        provably unaffected by anything this method does.
        """
        self._validate_component_presence(
            differential,
            differential_summary,
            differential_consistency,
            decision_readiness,
        )

        differential_copy = copy.deepcopy(differential)
        summary_copy = copy.deepcopy(dict(differential_summary))
        consistency_copy = copy.deepcopy(dict(differential_consistency))
        readiness_copy = copy.deepcopy(dict(decision_readiness))

        result = {
            "context_available": False,
            "decision_ready": readiness_copy["ready"],
            "consistency_verified": consistency_copy["consistent"],
            "candidate_count": len(differential_copy),
            "differential": differential_copy,
            "differential_summary": summary_copy,
            "differential_consistency": consistency_copy,
            "decision_readiness": readiness_copy,
            "context_source": CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031,
        }
        result["context_available"] = (
            result["decision_ready"]
            and result["consistency_verified"]
            and result["candidate_count"] > 0
        )

        self._validate_context(result)
        return result

    # ------------------------------------------------------------------
    # Structural usability of the inputs
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_component_presence(
        differential: list[dict[str, Any]] | None,
        differential_summary: Mapping[str, Any] | None,
        differential_consistency: Mapping[str, Any] | None,
        decision_readiness: Mapping[str, Any] | None,
    ) -> None:
        """Reject a quadruple missing any required nested component.

        All four components are required. Task 031 never silently
        reconstructs a missing one — an absent differential, summary,
        consistency result, or readiness result leaves nothing to
        package, so it raises rather than substituting a default.
        """
        if differential is None:
            raise DecisionContextContractError(
                "MISSING_DIFFERENTIAL", "differential is required"
            )
        if not isinstance(differential, list):
            raise DecisionContextContractError(
                "DIFFERENTIAL_TYPE",
                f"differential is not a list: {type(differential).__name__}",
            )
        for entry in differential:
            if not isinstance(entry, Mapping):
                raise DecisionContextContractError(
                    "RANKED_ENTRY_TYPE",
                    f"ranked entry is not a mapping: {type(entry).__name__}",
                )
            for field in _REQUIRED_RANKED_FIELDS:
                if field not in entry:
                    raise DecisionContextContractError(
                        "MISSING_RANKED_FIELD", f"ranked entry has no {field}"
                    )

        if differential_summary is None:
            raise DecisionContextContractError(
                "MISSING_SUMMARY", "differential_summary is required"
            )
        DecisionContextService._require_mapping_fields(
            differential_summary, _REQUIRED_SUMMARY_FIELDS, "SUMMARY"
        )

        if differential_consistency is None:
            raise DecisionContextContractError(
                "MISSING_CONSISTENCY", "differential_consistency is required"
            )
        DecisionContextService._require_mapping_fields(
            differential_consistency, _REQUIRED_CONSISTENCY_FIELDS, "CONSISTENCY"
        )

        if decision_readiness is None:
            raise DecisionContextContractError(
                "MISSING_READINESS", "decision_readiness is required"
            )
        DecisionContextService._require_mapping_fields(
            decision_readiness, _REQUIRED_READINESS_FIELDS, "READINESS"
        )

    @staticmethod
    def _require_mapping_fields(
        value: Mapping[str, Any], fields: tuple[str, ...], label: str
    ) -> None:
        if not isinstance(value, Mapping):
            raise DecisionContextContractError(
                f"{label}_TYPE",
                f"{label.lower()} is not a mapping: {type(value).__name__}",
            )
        for field in fields:
            if field not in value:
                raise DecisionContextContractError(
                    f"MISSING_{label}_FIELD", f"{label.lower()} has no {field}"
                )

    # ------------------------------------------------------------------
    # The decision-context contract itself
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_context(result: Mapping[str, Any]) -> None:
        """Task 031: verify the assembled decision-context invariants.

        None of these fields are ever accepted from a caller — they
        are always derived by ``build`` — but this validator is the
        guard that makes a drifted or forged context impossible to
        return, exactly like Task 030's ``_validate_readiness``. It is
        also exercised directly by tests against hand-built context
        dicts, so a mismatch introduced anywhere upstream is caught
        the same way whether it reaches here through ``build`` or
        through a test. Never repairs a value; raises
        ``DecisionContextContractError`` naming the violated
        invariant. Checks:

        1. ``context_available``, ``decision_ready``, and
           ``consistency_verified`` are all ``bool``, and
           ``candidate_count`` is an ``int``.
        2. ``context_source`` is the fixed Task 031 identifier.
        3. All four nested components (``differential``,
           ``differential_summary``, ``differential_consistency``,
           ``decision_readiness``) are present.
        4. ``candidate_count == len(differential)``.
        5. ``decision_ready == decision_readiness.ready`` — Task 031
           never redefines Task 030's readiness.
        6. ``consistency_verified == differential_consistency.consistent``
           — Task 031 never redefines Task 029's consistency verdict.
        7. ``context_available`` equals the conjunction of
           ``decision_ready``, ``consistency_verified``, and
           ``candidate_count > 0`` — never accepted as given.
        """
        for field in _CONTEXT_BOOLEAN_FIELDS:
            if field not in result:
                raise DecisionContextContractError(
                    "MISSING_CONTEXT_FIELD", f"context result has no {field}"
                )
            if not isinstance(result[field], bool):
                raise DecisionContextContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )

        if "candidate_count" not in result:
            raise DecisionContextContractError(
                "MISSING_CONTEXT_FIELD", "context result has no candidate_count"
            )
        candidate_count = result["candidate_count"]
        if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
            raise DecisionContextContractError(
                "CANDIDATE_COUNT_TYPE",
                f"candidate_count is not an int: {candidate_count!r}",
            )

        source = result.get("context_source")
        if source != CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031:
            raise DecisionContextContractError(
                "CONTEXT_SOURCE",
                f"context_source is not the Task 031 identifier: {source!r}",
            )

        differential = result.get("differential")
        summary = result.get("differential_summary")
        consistency = result.get("differential_consistency")
        readiness = result.get("decision_readiness")

        if differential is None or not isinstance(differential, list):
            raise DecisionContextContractError(
                "MISSING_DIFFERENTIAL",
                "context result has no valid differential component",
            )
        if not isinstance(summary, Mapping) or "total_candidates" not in summary:
            raise DecisionContextContractError(
                "MISSING_SUMMARY",
                "context result has no valid differential_summary component",
            )
        if not isinstance(consistency, Mapping) or "consistent" not in consistency:
            raise DecisionContextContractError(
                "MISSING_CONSISTENCY",
                "context result has no valid differential_consistency component",
            )
        if not isinstance(readiness, Mapping) or "ready" not in readiness:
            raise DecisionContextContractError(
                "MISSING_READINESS",
                "context result has no valid decision_readiness component",
            )

        if candidate_count != len(differential):
            raise DecisionContextContractError(
                "CANDIDATE_COUNT_MISMATCH",
                "candidate_count does not match len(differential): "
                f"{candidate_count} != {len(differential)}",
            )

        if result["decision_ready"] != readiness["ready"]:
            raise DecisionContextContractError(
                "READINESS_MISMATCH",
                "decision_ready does not match decision_readiness.ready",
            )

        if result["consistency_verified"] != consistency["consistent"]:
            raise DecisionContextContractError(
                "CONSISTENCY_MISMATCH",
                "consistency_verified does not match "
                "differential_consistency.consistent",
            )

        expected_available = (
            result["decision_ready"]
            and result["consistency_verified"]
            and candidate_count > 0
        )
        if result["context_available"] != expected_available:
            raise DecisionContextContractError(
                "CONTEXT_AVAILABLE_MISMATCH",
                f"context_available ({result['context_available']}) does not "
                f"match its derivation ({expected_available})",
            )

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.differential_ranking_consistency import (
    DifferentialRankingConsistencyService,
)

READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030 = (
    "DIFFERENTIAL_DECISION_READINESS_TASK_030"
)
"""Fixed structural-contract identifier for the Task 030 readiness read.

Names *which* structural contract produced the result. It is not a
confidence, a probability, a score, or a clinical judgement.
"""

_SEPARATION_FIELDS = (
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

_SUMMARY_COUNT_FIELDS = (
    "total_candidates",
    "distinct_score_groups",
    "tied_candidate_count",
    "tie_group_count",
    "largest_tie_group_size",
)

_READINESS_BOOLEAN_FIELDS = (
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

_READY_PREREQUISITES = (
    "consistency_verified",
    "has_candidates",
    "ranking_available",
    "summary_available",
    "separation_metadata_available",
)


class DifferentialDecisionReadinessContractError(Exception):
    """Task 030: structurally unusable input, not a client error.

    Raised only when the ranked differential or the Task 029
    consistency result cannot be *structurally interpreted* at all — a
    missing ``hypothesis_score``, a non-boolean ``is_tied``, a
    consistency result with no ``consistent`` field — or when a derived
    readiness result violates its own contract.

    An *absent* input is not an error. A missing summary yields
    ``summary_available = False``; a ranked entry missing a Task 027
    separation field yields ``separation_metadata_available = False``.
    Both are valid, fully typed responses with ``ready = False``. The
    distinction mirrors Task 029's: absence and disagreement are
    reportable states, uninterpretable data is not.

    Like the Task 025–029 contract errors, this must never be exposed
    verbatim to API clients; the API layer converts it to a generic 500.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DifferentialDecisionReadinessService:
    """Task 030: structural decision-readiness over Tasks 027–029.

    ROP's differential layers now stack as::

        025 -> Hypothesis Score Contract
        026 -> Differential Ranking
        027 -> Separation Metadata
        028 -> Differential Structural Summary
        029 -> Differential Consistency Verification

    This service answers exactly one question: *is the current
    differential structurally complete and internally consistent enough
    for a later decision layer to consume?* It is the hand-off boundary
    — a future decision engine can read this contract instead of
    reaching backward into raw evidence or scoring internals.

    It is emphatically **not** a decision engine. It introduces no
    ``is_winner``, no ``selected_hypothesis``, no diagnosis, no
    probability, no confidence, no recommendation, no treatment, no
    action, no threshold declaring a hypothesis correct, no candidate
    removal, no LLM call, and no persistence.

    Three structural facts are deliberately reported but excluded from
    ``ready``:

    * ``has_score_separation`` — an all-tied differential is still a
      structurally valid differential. Requiring separation would
      quietly turn readiness into a "a winner exists" test.
    * ``has_unresolved_ties`` — a tied differential is still a valid
      ranked differential. This is a structural property, never
      uncertainty, diagnostic ambiguity, or confidence.
    * ``evidence_present_for_any_candidate`` — a candidate set may
      legitimately exist before evidence has been evaluated. Requiring
      evidence would make evidence presence a hidden decision
      threshold.

    ``ready`` therefore means "structurally valid and internally
    consistent enough for the next layer". It does not mean the
    diagnosis is known, and it does not mean a decision can safely be
    made.

    Read-only throughout: the ranked differential, the summary, and the
    consistency result are never mutated, and nothing is persisted.
    """

    def __init__(
        self,
        consistency_service: DifferentialRankingConsistencyService | None = None,
    ) -> None:
        self.consistency_service = (
            consistency_service or DifferentialRankingConsistencyService()
        )

    def evaluate_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Return the session's differential decision-readiness contract.

        Walks the established dependency chain rather than bypassing
        it: the Task 027 ranked differential comes from
        ``DifferentialRankingService.rank_session``, the Task 028
        summary from ``DifferentialRankingSummaryService``, and the
        Task 029 verdict from
        ``DifferentialRankingConsistencyService`` — each reached
        through the injected service below it, so one ranking result
        feeds all three layers. Never recomputes a hypothesis score and
        never introduces a second ranking engine. Read-only: no
        database writes, no persistence.
        """
        summary_service = self.consistency_service.summary_service
        ranking_service = summary_service.ranking_service

        ranked = ranking_service.rank_session(db, session_id, candidates)
        summary = summary_service.summarize_ranked(ranked)
        consistency_result = self.consistency_service.check_consistency(ranked, summary)

        return self.evaluate(ranked, summary, consistency_result)

    def evaluate(
        self,
        ranked: list[dict[str, Any]],
        summary: Mapping[str, Any] | None,
        consistency_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Derive readiness from an already-produced 027/028/029 triple.

        Kept separate from ``evaluate_session`` so readiness can be
        exercised directly against hand-built (and deliberately
        degraded) structures, without going through the full evidence/
        scoring/ranking/summary pipeline.

        The Task 028 summary is passed in explicitly and is never
        silently reconstructed here — if the caller has no valid
        summary, that absence is reported as
        ``summary_available = False`` rather than papered over.
        """
        self._validate_ranked_input(ranked)
        self._validate_consistency_input(consistency_result)

        # Task 029's verdict is taken verbatim. Task 030 never
        # independently redefines, reinterprets, or repairs it.
        consistency_verified = consistency_result["consistent"]

        has_candidates = len(ranked) > 0
        scores = [entry["hypothesis_score"] for entry in ranked]
        distinct_scores = set(scores)

        result = {
            "ready": False,
            "consistency_verified": consistency_verified,
            "has_candidates": has_candidates,
            # Structural availability of the ranking, not its quality:
            # a ranking exists exactly when there are candidates in it.
            "ranking_available": has_candidates,
            "summary_available": self._summary_is_available(summary),
            "separation_metadata_available": self._separation_is_available(ranked),
            "has_score_separation": len(distinct_scores) > 1,
            "has_unresolved_ties": len(distinct_scores) < len(scores),
            "evidence_present_for_any_candidate": any(
                entry["has_evidence"] for entry in ranked
            ),
            "readiness_source": READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030,
        }
        result["ready"] = all(result[field] for field in _READY_PREREQUISITES)

        self._validate_readiness(result)
        return result

    # ------------------------------------------------------------------
    # Availability of the upstream structures
    # ------------------------------------------------------------------

    @staticmethod
    def _summary_is_available(summary: Mapping[str, Any] | None) -> bool:
        """Report whether a structurally valid Task 028 summary exists.

        Absence is a reportable state, never an error: ``None``, a
        non-mapping, a summary missing a contract field, or one whose
        field types are wrong all yield ``False``. Task 030 never
        constructs a replacement summary to fill the gap.
        """
        if not isinstance(summary, Mapping):
            return False

        for field in _REQUIRED_SUMMARY_FIELDS:
            if field not in summary:
                return False

        for field in _SUMMARY_COUNT_FIELDS:
            value = summary[field]
            if not isinstance(value, int) or isinstance(value, bool):
                return False

        if not isinstance(summary["has_any_ties"], bool):
            return False

        top_rank = summary["top_rank"]
        if top_rank is not None and (
            not isinstance(top_rank, int) or isinstance(top_rank, bool)
        ):
            return False

        for field in ("highest_score", "lowest_score", "score_range"):
            value = summary[field]
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False

        return True

    @staticmethod
    def _separation_is_available(ranked: list[dict[str, Any]]) -> bool:
        """Report whether every entry carries the full Task 027 contract.

        An empty differential returns ``True`` — there are no candidate
        entries, so none are missing metadata. A missing field is
        reported as unavailable rather than filled in; Task 030 never
        reconstructs separation metadata on Task 027's behalf.
        """
        for entry in ranked:
            for field in _SEPARATION_FIELDS:
                if field not in entry:
                    return False
        return True

    # ------------------------------------------------------------------
    # Structural usability of the inputs
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_ranked_input(ranked: list[dict[str, Any]]) -> None:
        """Reject a ranked differential that cannot be interpreted.

        Presence-and-type only, and deliberately narrower than Task
        029's equivalent: a *missing* Task 027 separation field is an
        availability answer (``separation_metadata_available = False``),
        whereas a field present with a nonsense type leaves nothing to
        interpret and raises.
        """
        if not isinstance(ranked, list):
            raise DifferentialDecisionReadinessContractError(
                "RANKED_INPUT_TYPE",
                f"ranked differential is not a list: {type(ranked).__name__}",
            )

        for entry in ranked:
            if not isinstance(entry, Mapping):
                raise DifferentialDecisionReadinessContractError(
                    "RANKED_ENTRY_TYPE",
                    f"ranked entry is not a mapping: {type(entry).__name__}",
                )

            if "hypothesis_score" not in entry:
                raise DifferentialDecisionReadinessContractError(
                    "MISSING_HYPOTHESIS_SCORE",
                    "ranked entry has no hypothesis_score",
                )
            score = entry["hypothesis_score"]
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise DifferentialDecisionReadinessContractError(
                    "NON_NUMERIC_SCORE",
                    f"hypothesis_score is not numeric: {score!r}",
                )

            if "has_evidence" not in entry:
                raise DifferentialDecisionReadinessContractError(
                    "MISSING_HAS_EVIDENCE",
                    "ranked entry has no has_evidence",
                )
            if not isinstance(entry["has_evidence"], bool):
                raise DifferentialDecisionReadinessContractError(
                    "HAS_EVIDENCE_TYPE",
                    f"has_evidence is not boolean: {entry['has_evidence']!r}",
                )

            # Present-but-malformed separation metadata is unusable.
            # Absent separation metadata is handled as availability.
            if "is_tied" in entry and not isinstance(entry["is_tied"], bool):
                raise DifferentialDecisionReadinessContractError(
                    "IS_TIED_TYPE",
                    f"is_tied is not boolean: {entry['is_tied']!r}",
                )
            if "tie_group_size" in entry and (
                not isinstance(entry["tie_group_size"], int)
                or isinstance(entry["tie_group_size"], bool)
            ):
                raise DifferentialDecisionReadinessContractError(
                    "TIE_GROUP_SIZE_TYPE",
                    f"tie_group_size is not an int: {entry['tie_group_size']!r}",
                )
            for gap_field in (
                "score_gap_to_next_higher",
                "score_gap_to_next_lower",
            ):
                if gap_field not in entry:
                    continue
                gap = entry[gap_field]
                if gap is None:
                    continue
                if not isinstance(gap, (int, float)) or isinstance(gap, bool):
                    raise DifferentialDecisionReadinessContractError(
                        "SCORE_GAP_TYPE",
                        f"{gap_field} is neither None nor numeric: {gap!r}",
                    )

    @staticmethod
    def _validate_consistency_input(consistency_result: Mapping[str, Any]) -> None:
        """Reject a Task 029 result that cannot be interpreted.

        ``consistent = False`` is a perfectly usable verdict — it is
        carried straight through to ``consistency_verified`` and
        suppresses ``ready``. Only a missing or non-boolean
        ``consistent`` raises.
        """
        if not isinstance(consistency_result, Mapping):
            raise DifferentialDecisionReadinessContractError(
                "CONSISTENCY_INPUT_TYPE",
                "consistency result is not a mapping: "
                f"{type(consistency_result).__name__}",
            )
        if "consistent" not in consistency_result:
            raise DifferentialDecisionReadinessContractError(
                "MISSING_CONSISTENT",
                "consistency result has no consistent field",
            )
        if not isinstance(consistency_result["consistent"], bool):
            raise DifferentialDecisionReadinessContractError(
                "CONSISTENT_TYPE",
                "consistency result consistent is not boolean: "
                f"{consistency_result['consistent']!r}",
            )

    # ------------------------------------------------------------------
    # The readiness contract itself
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_readiness(result: Mapping[str, Any]) -> None:
        """Task 030: verify the readiness contract invariants.

        ``ready`` is always derived, never accepted. This validator is
        the guard that makes a forged or drifted ``ready`` value
        impossible to return, exactly like Task 025's
        ``_validate_score_result``. Never repairs a value; raises
        ``DifferentialDecisionReadinessContractError`` naming the
        violated invariant. Checks:

        1. Every readiness field is a ``bool``.
        2. ``readiness_source`` is the fixed Task 030 identifier.
        3. ``has_candidates == ranking_available`` — a ranking exists
           exactly when candidates do.
        4. With no candidates, ``has_score_separation``,
           ``has_unresolved_ties``, and
           ``evidence_present_for_any_candidate`` are all ``False``.
        5. ``ready`` equals the conjunction of its five structural
           prerequisites — and of nothing else, so ties and absent
           evidence can never suppress it.
        """
        for field in _READINESS_BOOLEAN_FIELDS:
            if field not in result:
                raise DifferentialDecisionReadinessContractError(
                    "MISSING_READINESS_FIELD", f"readiness result has no {field}"
                )
            if not isinstance(result[field], bool):
                raise DifferentialDecisionReadinessContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )

        source = result.get("readiness_source")
        if source != READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030:
            raise DifferentialDecisionReadinessContractError(
                "READINESS_SOURCE",
                f"readiness_source is not the Task 030 identifier: {source!r}",
            )

        if result["has_candidates"] != result["ranking_available"]:
            raise DifferentialDecisionReadinessContractError(
                "RANKING_AVAILABILITY_MISMATCH",
                "has_candidates and ranking_available must agree",
            )

        if not result["has_candidates"]:
            for field in (
                "has_score_separation",
                "has_unresolved_ties",
                "evidence_present_for_any_candidate",
            ):
                if result[field]:
                    raise DifferentialDecisionReadinessContractError(
                        "EMPTY_DIFFERENTIAL_FIELD",
                        f"{field} must be False with no candidates",
                    )

        expected_ready = all(result[field] for field in _READY_PREREQUISITES)
        if result["ready"] != expected_ready:
            raise DifferentialDecisionReadinessContractError(
                "READY_MISMATCH",
                f"ready ({result['ready']}) does not match the conjunction "
                f"of its structural prerequisites ({expected_ready})",
            )

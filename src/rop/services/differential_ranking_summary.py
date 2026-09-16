from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.differential_ranking import DifferentialRankingService

_SCORE_PRECISION = 4


class DifferentialRankingSummaryContractError(Exception):
    """Task 028: an internal architectural regression, not a client error.

    Raised only by ``_validate_summary`` when a derived summary
    violates one of the summary invariants documented on that method.
    This signals a bug in the summary layer itself — never a property
    of the underlying clinical data — so it must never be exposed
    verbatim to API clients. The API layer catches this and converts
    it to a generic 500 response, the same way it already does for
    ``DifferentialRankingContractError``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DifferentialRankingSummaryService:
    """Task 028: deterministic structural summary over Task 027's ranking.

    Consumes the already-ranked, already-annotated Task 027 result
    produced by ``DifferentialRankingService`` — it never
    re-evaluates evidence, recomputes scores, recomputes ranks, or
    duplicates the ranking/tie logic. It only aggregates
    ``hypothesis_score`` (and the ``rank`` of the first entry) across
    the ranked list into a compact, session-level description of the
    differential's shape.

    It is explicitly NOT diagnosis selection, winner selection,
    decision-making, treatment recommendation, medical probability,
    confidence calibration, or AI/LLM reasoning. No hypothesis is
    ever called "correct", none are deleted or filtered, and nothing
    is persisted — the summary is a derived, read-only view over the
    current ranked state, answering only "what does the current
    differential ranking look like structurally?".

    An empty ranking (no candidates) still produces a fully defined
    summary: every count is ``0``/``False`` and every score-derived
    field is ``None`` — this is a valid contract state, never an
    error.
    """

    def __init__(
        self, ranking_service: DifferentialRankingService | None = None
    ) -> None:
        self.ranking_service = ranking_service or DifferentialRankingService()

    def summarize_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Return the session's differential ranking summary.

        Obtains the Task 027 ranked differential for ``candidates``
        via ``DifferentialRankingService.rank_session`` — already
        validated against the ranking/separation contracts — and
        derives the structural summary from it. Never recalculates
        evidence, scores, ranks, or tie/gap metadata. Read-only: never
        writes to the database, and never persists a summary table.
        """
        ranked = self.ranking_service.rank_session(db, session_id, candidates)
        return self.summarize_ranked(ranked)

    def summarize_ranked(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
        """Derive a structural summary from an already-ranked differential.

        Kept separate from ``summarize_session`` so summarization
        logic can be exercised directly against hand-built ranked
        entries, without going through evidence evaluation/
        aggregation/scoring/ranking. Returns the fully defined empty
        contract for an empty input — a session with no candidates is
        a valid, non-error state.
        """
        if not ranked:
            summary = self._empty_summary()
            self._validate_summary(summary)
            return summary

        scores = [entry["hypothesis_score"] for entry in ranked]
        distinct_scores = sorted(set(scores), reverse=True)

        highest_score = distinct_scores[0]
        lowest_score = distinct_scores[-1]
        score_range = round(highest_score - lowest_score, _SCORE_PRECISION)

        tie_group_size_by_score: dict[float, int] = {}
        for score in scores:
            tie_group_size_by_score[score] = tie_group_size_by_score.get(score, 0) + 1

        tied_candidate_count = sum(
            size for size in tie_group_size_by_score.values() if size > 1
        )
        tie_group_count = sum(
            1 for size in tie_group_size_by_score.values() if size > 1
        )
        largest_tie_group_size = max(tie_group_size_by_score.values())

        summary = {
            "total_candidates": len(ranked),
            "distinct_score_groups": len(distinct_scores),
            "top_rank": ranked[0]["rank"],
            "highest_score": highest_score,
            "lowest_score": lowest_score,
            "score_range": score_range,
            "tied_candidate_count": tied_candidate_count,
            "tie_group_count": tie_group_count,
            "largest_tie_group_size": largest_tie_group_size,
            "has_any_ties": tied_candidate_count > 0,
        }
        self._validate_summary(summary)
        return summary

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        """The fully defined summary contract for an empty ranking."""
        return {
            "total_candidates": 0,
            "distinct_score_groups": 0,
            "top_rank": None,
            "highest_score": None,
            "lowest_score": None,
            "score_range": None,
            "tied_candidate_count": 0,
            "tie_group_count": 0,
            "largest_tie_group_size": 0,
            "has_any_ties": False,
        }

    @staticmethod
    def _validate_summary(summary: dict[str, Any]) -> None:
        """Task 028: verify the summary contract invariants.

        Recomputes nothing about the underlying ranking — this is a
        structural consistency check on the already-derived summary
        values, exactly like Task 026/027's validators. Never repairs
        a bad value; raises ``DifferentialRankingSummaryContractError``
        naming the violated invariant. Checks:

        1. Every count field (``total_candidates``,
           ``distinct_score_groups``, ``tied_candidate_count``,
           ``tie_group_count``, ``largest_tie_group_size``) is an
           ``int`` >= 0.
        2. ``has_any_ties`` is a ``bool`` and agrees with
           ``tied_candidate_count > 0``.
        3. For a non-empty summary (``total_candidates > 0``):
           ``distinct_score_groups >= 1``; ``top_rank``,
           ``highest_score``, ``lowest_score``, and ``score_range``
           are all not ``None``; ``highest_score >= lowest_score``;
           ``score_range >= 0``; and ``score_range`` equals
           ``highest_score - lowest_score`` under the four-decimal
           normalization contract.
        4. For an empty summary (``total_candidates == 0``):
           ``top_rank``, ``highest_score``, ``lowest_score``, and
           ``score_range`` are all ``None``.
        """
        for field in (
            "total_candidates",
            "distinct_score_groups",
            "tied_candidate_count",
            "tie_group_count",
            "largest_tie_group_size",
        ):
            value = summary[field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise DifferentialRankingSummaryContractError(
                    f"{field.upper()}_TYPE", f"{field} is not an int: {value!r}"
                )
            if value < 0:
                raise DifferentialRankingSummaryContractError(
                    f"{field.upper()}_BOUNDS", f"{field} must be >= 0, got {value}"
                )

        has_any_ties = summary["has_any_ties"]
        if not isinstance(has_any_ties, bool):
            raise DifferentialRankingSummaryContractError(
                "HAS_ANY_TIES_TYPE",
                f"has_any_ties is not boolean: {has_any_ties!r}",
            )
        if has_any_ties != (summary["tied_candidate_count"] > 0):
            raise DifferentialRankingSummaryContractError(
                "HAS_ANY_TIES_MISMATCH",
                "has_any_ties does not agree with tied_candidate_count > 0",
            )

        total_candidates = summary["total_candidates"]
        top_rank = summary["top_rank"]
        highest_score = summary["highest_score"]
        lowest_score = summary["lowest_score"]
        score_range = summary["score_range"]

        distinct_score_groups = summary["distinct_score_groups"]
        tied_candidate_count = summary["tied_candidate_count"]
        tie_group_count = summary["tie_group_count"]
        largest_tie_group_size = summary["largest_tie_group_size"]

        if total_candidates > 0:
            if distinct_score_groups < 1:
                raise DifferentialRankingSummaryContractError(
                    "DISTINCT_SCORE_GROUPS_BOUNDS",
                    "distinct_score_groups must be >= 1 for a non-empty " "ranking",
                )
            for field_name, value in (
                ("top_rank", top_rank),
                ("highest_score", highest_score),
                ("lowest_score", lowest_score),
                ("score_range", score_range),
            ):
                if value is None:
                    raise DifferentialRankingSummaryContractError(
                        "NON_EMPTY_FIELD_MISSING",
                        f"{field_name} must not be None for a non-empty " "ranking",
                    )

            # Task 026's competition ranking always assigns the first
            # (highest-scoring) entry rank 1 — this is an exact
            # property of a valid ranking, not merely a plausible
            # value, so it is checked directly rather than only for
            # type/None-ness above.
            if top_rank != 1:
                raise DifferentialRankingSummaryContractError(
                    "TOP_RANK_INVALID",
                    f"top_rank must be 1 for a non-empty ranking, got {top_rank}",
                )

            if highest_score < lowest_score:
                raise DifferentialRankingSummaryContractError(
                    "SCORE_BOUNDS",
                    "highest_score must be >= lowest_score",
                )
            if score_range < 0:
                raise DifferentialRankingSummaryContractError(
                    "SCORE_RANGE_NEGATIVE",
                    f"score_range is negative: {score_range}",
                )
            expected_range = round(highest_score - lowest_score, _SCORE_PRECISION)
            if score_range != expected_range:
                raise DifferentialRankingSummaryContractError(
                    "SCORE_RANGE_MISMATCH",
                    f"score_range ({score_range}) does not match "
                    f"highest_score - lowest_score ({expected_range})",
                )

            if tied_candidate_count > total_candidates:
                raise DifferentialRankingSummaryContractError(
                    "TIED_CANDIDATE_COUNT_BOUNDS",
                    "tied_candidate_count must not exceed total_candidates",
                )
            if tie_group_count > distinct_score_groups:
                raise DifferentialRankingSummaryContractError(
                    "TIE_GROUP_COUNT_BOUNDS",
                    "tie_group_count must not exceed distinct_score_groups",
                )

            # Exact structural identity: every distinct score group is
            # either a tie group (size > 1) or a singleton (size 1).
            # The singleton groups equal the non-tied candidates, so
            # distinct_score_groups == tie_group_count + singleton
            # candidates. This ties tie_group_count and
            # tied_candidate_count together independently of how each
            # was derived, catching e.g. a tie_group_count that does
            # not correspond to any consistent partition of the
            # candidates.
            expected_distinct_groups = tie_group_count + (
                total_candidates - tied_candidate_count
            )
            if distinct_score_groups != expected_distinct_groups:
                raise DifferentialRankingSummaryContractError(
                    "DISTINCT_SCORE_GROUPS_MISMATCH",
                    f"distinct_score_groups ({distinct_score_groups}) is "
                    "inconsistent with tie_group_count "
                    f"({tie_group_count}) and tied_candidate_count "
                    f"({tied_candidate_count}); expected "
                    f"{expected_distinct_groups}",
                )

            if tie_group_count == 0:
                if largest_tie_group_size != 1:
                    raise DifferentialRankingSummaryContractError(
                        "LARGEST_TIE_GROUP_SIZE_MISMATCH",
                        "largest_tie_group_size must be 1 when "
                        "tie_group_count is 0 for a non-empty ranking, "
                        f"got {largest_tie_group_size}",
                    )
            else:
                if largest_tie_group_size < 2:
                    raise DifferentialRankingSummaryContractError(
                        "LARGEST_TIE_GROUP_SIZE_MISMATCH",
                        "largest_tie_group_size must be >= 2 when "
                        f"tie_group_count > 0, got {largest_tie_group_size}",
                    )
                if largest_tie_group_size > tied_candidate_count:
                    raise DifferentialRankingSummaryContractError(
                        "LARGEST_TIE_GROUP_SIZE_MISMATCH",
                        "largest_tie_group_size must not exceed "
                        "tied_candidate_count",
                    )
        else:
            for field_name, value in (
                ("top_rank", top_rank),
                ("highest_score", highest_score),
                ("lowest_score", lowest_score),
                ("score_range", score_range),
            ):
                if value is not None:
                    raise DifferentialRankingSummaryContractError(
                        "EMPTY_FIELD_NOT_NONE",
                        f"{field_name} must be None for an empty ranking",
                    )

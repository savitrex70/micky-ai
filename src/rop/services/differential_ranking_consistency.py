from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.differential_ranking_summary import DifferentialRankingSummaryService

_SCORE_PRECISION = 4

CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029 = "DIFFERENTIAL_RANKING_TASK_029"
"""Fixed structural-contract identifier for the Task 029 consistency read.

Names *which* structural contract produced the result. It is not a
confidence, a probability, a score, or a quality rating.
"""


class DifferentialRankingConsistencyContractError(Exception):
    """Task 029: the inputs handed to the consistency service are unusable.

    Raised only when the Task 027 ranked differential or the Task 028
    summary is structurally malformed in a way that makes independent
    re-derivation impossible — a missing ``hypothesis_score``, a
    missing ``rank``, a non-numeric score, or a metadata field of the
    wrong type. This is never raised for an ordinary, well-formed
    mismatch between the two layers (that is a normal
    ``consistent=False`` response, not an exception). This signals a
    bug upstream of the consistency check itself, so it must never be
    exposed verbatim to API clients — the API layer catches it and
    converts it to a generic 500 response, the same way it already
    does for ``DifferentialRankingContractError`` and
    ``DifferentialRankingSummaryContractError``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DifferentialRankingConsistencyService:
    """Task 029: verify Task 027's ranking agrees with Task 028's summary.

    This service introduces no new ranking or scoring logic. It
    consumes the already-produced Task 027 ranked differential
    (``DifferentialRankingService``) and the already-produced Task 028
    structural summary (``DifferentialRankingSummaryService``) and
    checks that they describe the *same* differential state, by
    independently re-deriving each summary/separation value directly
    from the ranked entries and comparing it against what Tasks
    027/028 already reported.

    It is explicitly NOT diagnosis selection, winner selection,
    decision-making, treatment recommendation, medical probability,
    confidence calibration, or AI/LLM reasoning. Nothing is mutated —
    neither the ranked entries nor the summary — and nothing is
    persisted; this is a derived, read-only structural check.

    A genuine mismatch between the two layers is a normal, valid
    response (``consistent=False``) and never raises. Only
    structurally unusable input (a missing field, a non-numeric
    score, a metadata value of the wrong type) raises
    ``DifferentialRankingConsistencyContractError`` — see
    ``_validate_ranked_entries`` and ``_validate_summary_shape``.
    """

    def __init__(
        self, summary_service: DifferentialRankingSummaryService | None = None
    ) -> None:
        self.summary_service = summary_service or DifferentialRankingSummaryService()

    def check_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> dict[str, Any]:
        """Return the session's differential-ranking consistency contract.

        Obtains the Task 027 ranked differential and the Task 028
        summary for ``candidates`` via
        ``DifferentialRankingSummaryService`` (which itself obtains the
        ranking via ``DifferentialRankingService``) — already validated
        against their own contracts — and checks them against each
        other. Never recalculates evidence, scores, ranks, or summary
        aggregates directly; only re-derives them for comparison.
        Read-only: never writes to the database, and never persists a
        consistency-result table.
        """
        ranking_service = self.summary_service.ranking_service
        ranked = ranking_service.rank_session(db, session_id, candidates)
        summary = self.summary_service.summarize_ranked(ranked)
        return self.check_consistency(ranked, summary)

    def check_consistency(
        self, ranked: list[dict[str, Any]], summary: dict[str, Any]
    ) -> dict[str, Any]:
        """Cross-check an already-ranked differential against its summary.

        Kept separate from ``check_session`` so the consistency logic
        can be exercised directly against hand-built ranked entries
        and summaries, without going through the full evidence/
        scoring/ranking/summary pipeline. An empty ranked list paired
        with the fully defined empty Task 028 summary is a valid
        state: every field is ``True``, because two empty structures
        trivially agree.
        """
        self._validate_ranked_entries(ranked)
        self._validate_summary_shape(summary)

        derived = self._derive_expected(ranked)

        candidate_count_matches = (
            derived["total_candidates"] == summary["total_candidates"]
        )
        score_groups_match = (
            derived["distinct_score_groups"] == summary["distinct_score_groups"]
        )
        tie_statistics_match = (
            derived["tied_candidate_count"] == summary["tied_candidate_count"]
            and derived["tie_group_count"] == summary["tie_group_count"]
            and derived["largest_tie_group_size"] == summary["largest_tie_group_size"]
            and derived["has_any_ties"] == summary["has_any_ties"]
        )
        score_range_matches = (
            derived["highest_score"] == summary["highest_score"]
            and derived["lowest_score"] == summary["lowest_score"]
            and derived["score_range"] == summary["score_range"]
        )
        rank_structure_matches = self._rank_structure_matches(ranked)
        separation_metadata_matches = self._separation_metadata_matches(ranked)

        summary_consistent = (
            candidate_count_matches
            and score_groups_match
            and tie_statistics_match
            and score_range_matches
            and rank_structure_matches
            and separation_metadata_matches
        )

        return {
            "consistent": summary_consistent,
            "candidate_count_matches": candidate_count_matches,
            "score_groups_match": score_groups_match,
            "tie_statistics_match": tie_statistics_match,
            "score_range_matches": score_range_matches,
            "rank_structure_matches": rank_structure_matches,
            "separation_metadata_matches": separation_metadata_matches,
            "summary_consistent": summary_consistent,
            "consistency_source": CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029,
        }

    # ------------------------------------------------------------------
    # Independent re-derivation (mirrors Task 028's aggregation, but is
    # never called by Task 028 or vice versa — this is a second,
    # independent computation used only for comparison).
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_expected(ranked: list[dict[str, Any]]) -> dict[str, Any]:
        if not ranked:
            return {
                "total_candidates": 0,
                "distinct_score_groups": 0,
                "highest_score": None,
                "lowest_score": None,
                "score_range": None,
                "tied_candidate_count": 0,
                "tie_group_count": 0,
                "largest_tie_group_size": 0,
                "has_any_ties": False,
            }

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

        return {
            "total_candidates": len(ranked),
            "distinct_score_groups": len(distinct_scores),
            "highest_score": highest_score,
            "lowest_score": lowest_score,
            "score_range": score_range,
            "tied_candidate_count": tied_candidate_count,
            "tie_group_count": tie_group_count,
            "largest_tie_group_size": largest_tie_group_size,
            "has_any_ties": tied_candidate_count > 0,
        }

    @staticmethod
    def _rank_structure_matches(ranked: list[dict[str, Any]]) -> bool:
        """Independently verify Task 026's competition-ranking structure.

        Assumes ``ranked`` is already in ranked (score-descending)
        order, as produced by ``DifferentialRankingService`` — this
        never re-sorts the input. Recomputes the expected rank
        sequence from the scores in that order and compares it against
        the actual ``rank`` values, also verifying scores never
        increase down the list and that every rank stays within
        ``[1, total_candidates]``.
        """
        if not ranked:
            return True

        total_candidates = len(ranked)
        previous_score: float | None = None
        previous_rank = 0

        for index, entry in enumerate(ranked):
            score = entry["hypothesis_score"]
            rank = entry["rank"]

            if previous_score is not None and score > previous_score:
                return False

            if previous_score is not None and score == previous_score:
                expected_rank = previous_rank
            else:
                expected_rank = index + 1

            if rank != expected_rank:
                return False
            if rank < 1 or rank > total_candidates:
                return False

            previous_score = score
            previous_rank = rank

        return ranked[0]["rank"] == 1

    @staticmethod
    def _separation_metadata_matches(ranked: list[dict[str, Any]]) -> bool:
        """Independently re-derive Task 027's per-entry separation metadata.

        Recomputes ``is_tied``, ``tie_group_size``,
        ``score_gap_to_next_higher``, and ``score_gap_to_next_lower``
        directly from the ranked entries' scores and compares every
        value against what Task 027 already annotated on each entry.
        Never trusts the existing values as ground truth.
        """
        if not ranked:
            return True

        distinct_scores = sorted(
            {entry["hypothesis_score"] for entry in ranked}, reverse=True
        )

        higher_gap_by_score: dict[float, float | None] = {}
        lower_gap_by_score: dict[float, float | None] = {}
        for index, score in enumerate(distinct_scores):
            next_higher = distinct_scores[index - 1] if index > 0 else None
            next_lower = (
                distinct_scores[index + 1] if index < len(distinct_scores) - 1 else None
            )
            higher_gap_by_score[score] = (
                round(next_higher - score, _SCORE_PRECISION)
                if next_higher is not None
                else None
            )
            lower_gap_by_score[score] = (
                round(score - next_lower, _SCORE_PRECISION)
                if next_lower is not None
                else None
            )

        tie_group_size_by_score: dict[float, int] = {}
        for entry in ranked:
            score = entry["hypothesis_score"]
            tie_group_size_by_score[score] = tie_group_size_by_score.get(score, 0) + 1

        for entry in ranked:
            score = entry["hypothesis_score"]
            expected_tie_group_size = tie_group_size_by_score[score]
            expected_is_tied = expected_tie_group_size > 1
            expected_gap_higher = higher_gap_by_score[score]
            expected_gap_lower = lower_gap_by_score[score]

            if entry["is_tied"] != expected_is_tied:
                return False
            if entry["tie_group_size"] != expected_tie_group_size:
                return False
            if entry["score_gap_to_next_higher"] != expected_gap_higher:
                return False
            if entry["score_gap_to_next_lower"] != expected_gap_lower:
                return False

        return True

    # ------------------------------------------------------------------
    # Input-shape validation (contract errors, never a data-driven
    # False result).
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_ranked_entries(ranked: list[dict[str, Any]]) -> None:
        """Task 029: verify the ranked differential is structurally usable.

        Never repairs a bad value and never recomputes a score or
        rank on behalf of the caller — it only confirms every entry
        carries the fields this service must independently re-derive
        against. Raises
        ``DifferentialRankingConsistencyContractError`` naming the
        violated invariant on failure.
        """
        for entry in ranked:
            if "hypothesis_score" not in entry or entry["hypothesis_score"] is None:
                raise DifferentialRankingConsistencyContractError(
                    "MISSING_HYPOTHESIS_SCORE",
                    "ranked entry has no hypothesis_score",
                )
            score = entry["hypothesis_score"]
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise DifferentialRankingConsistencyContractError(
                    "NON_NUMERIC_SCORE",
                    f"hypothesis_score is not numeric: {score!r}",
                )

            if "rank" not in entry or entry["rank"] is None:
                raise DifferentialRankingConsistencyContractError(
                    "MISSING_RANK", "ranked entry has no rank"
                )
            rank = entry["rank"]
            if not isinstance(rank, int) or isinstance(rank, bool):
                raise DifferentialRankingConsistencyContractError(
                    "INVALID_RANK_TYPE", f"rank is not an int: {rank!r}"
                )

            is_tied = entry.get("is_tied")
            if not isinstance(is_tied, bool):
                raise DifferentialRankingConsistencyContractError(
                    "INVALID_METADATA_TYPE",
                    f"is_tied is not boolean: {is_tied!r}",
                )

            tie_group_size = entry.get("tie_group_size")
            if not isinstance(tie_group_size, int) or isinstance(tie_group_size, bool):
                raise DifferentialRankingConsistencyContractError(
                    "INVALID_METADATA_TYPE",
                    f"tie_group_size is not an int: {tie_group_size!r}",
                )

            for gap_field in (
                "score_gap_to_next_higher",
                "score_gap_to_next_lower",
            ):
                if gap_field not in entry:
                    raise DifferentialRankingConsistencyContractError(
                        "INVALID_METADATA_TYPE",
                        f"ranked entry is missing {gap_field}",
                    )
                gap_value = entry[gap_field]
                if gap_value is not None and (
                    not isinstance(gap_value, (int, float))
                    or isinstance(gap_value, bool)
                ):
                    raise DifferentialRankingConsistencyContractError(
                        "INVALID_METADATA_TYPE",
                        f"{gap_field} is not numeric or None: {gap_value!r}",
                    )

    @staticmethod
    def _validate_summary_shape(summary: dict[str, Any]) -> None:
        """Task 029: verify the Task 028 summary is structurally usable."""
        required_int_fields = (
            "total_candidates",
            "distinct_score_groups",
            "tied_candidate_count",
            "tie_group_count",
            "largest_tie_group_size",
        )
        for field in required_int_fields:
            if field not in summary:
                raise DifferentialRankingConsistencyContractError(
                    "MISSING_SUMMARY_FIELD", f"summary is missing {field}"
                )
            value = summary[field]
            if not isinstance(value, int) or isinstance(value, bool):
                raise DifferentialRankingConsistencyContractError(
                    "INVALID_METADATA_TYPE", f"{field} is not an int: {value!r}"
                )

        if "has_any_ties" not in summary or not isinstance(
            summary["has_any_ties"], bool
        ):
            raise DifferentialRankingConsistencyContractError(
                "INVALID_METADATA_TYPE",
                f"has_any_ties is not boolean: {summary.get('has_any_ties')!r}",
            )

        for field in ("highest_score", "lowest_score", "score_range"):
            if field not in summary:
                raise DifferentialRankingConsistencyContractError(
                    "MISSING_SUMMARY_FIELD", f"summary is missing {field}"
                )
            value = summary[field]
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise DifferentialRankingConsistencyContractError(
                    "INVALID_METADATA_TYPE",
                    f"{field} is not numeric or None: {value!r}",
                )

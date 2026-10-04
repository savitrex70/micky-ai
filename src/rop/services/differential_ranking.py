from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.hypothesis_scoring import HypothesisScoringService

_SCORE_PRECISION = 4


class DifferentialRankingContractError(Exception):
    """Task 026: an internal architectural regression, not a client error.

    Raised only by ``_validate_ranking_input`` when the Task 025 score
    results handed to the ranking service violate one of the ranking
    input invariants (see that method's docstring). This signals a bug
    upstream of ranking — never a property of the underlying clinical
    data — so it must never be exposed verbatim to API clients. The API
    layer catches this and converts it to a generic 500 response, the
    same way it already does for ``HypothesisScoreContractError``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class DifferentialRankingService:
    """Task 026: deterministic differential ranking over Task 025 scores.

    This is the first ROP layer allowed to compare hypotheses against
    one another — but only their already-computed, unchanged
    ``hypothesis_score`` values. It never re-evaluates evidence,
    recomputes contributions, inspects observations/entities, or
    calls ``HypothesisScoringService`` internals directly; it consumes
    ``HypothesisScoringService.score_session`` (Task 025) exactly as
    produced and only orders/ranks that result.

    It is explicitly NOT diagnosis selection, winner selection,
    decision-making, treatment recommendation, medical probability,
    Bayesian inference, confidence calibration, or AI/LLM reasoning.
    No hypothesis is ever called "correct", none are deleted, and
    nothing is persisted — ranking is a derived, read-only view over
    the current score state.

    Ranking rule: sort by ``hypothesis_score`` descending. Ties use
    competition ranking (1, 1, 3 — never dense 1, 1, 2): tied
    candidates share a rank, and the next distinct score resumes at
    its 1-based position in the sorted list. Because tied candidates
    still need a deterministic position in the returned list (never
    arbitrary database order), a documented stable secondary key
    breaks ties for ordering purposes only, without changing the
    shared rank: ``hypothesis_name.casefold()`` ascending, then
    ``str(hypothesis_id)`` ascending.

    Task 027 extends every ranked entry with derived separation
    metadata (``is_tied``, ``tie_group_size``,
    ``score_gap_to_next_higher``, ``score_gap_to_next_lower``) that
    describes how candidates are separated from one another by score.
    This is still purely structural: no new scoring formula, no
    winner, no probability, no decision. See
    ``_assign_separation_metadata`` for the derivation and
    ``_validate_separation_metadata`` for the contract it must
    satisfy.
    """

    def __init__(self, scoring_service: HypothesisScoringService | None = None) -> None:
        self.scoring_service = scoring_service or HypothesisScoringService()

    def rank_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> list[dict[str, Any]]:
        """Return the session's differential ranking, in ranked order.

        Obtains Task 025 scores for ``candidates`` via
        ``HypothesisScoringService.score_session`` — already validated
        against the hypothesis-score contract — and ranks that result.
        Never recalculates evidence or scores. Read-only: never writes
        to the database, and never persists a ranking table.
        """
        score_results = self.scoring_service.score_session(db, session_id, candidates)
        return self.rank_score_results(score_results)

    def rank_score_results(
        self, score_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Order and rank already-produced Task 025 score results.

        Kept separate from ``rank_session`` so ranking logic can be
        exercised directly against hand-built score-result dicts,
        without going through evidence evaluation/aggregation/scoring.
        Returns ``[]`` unchanged for an empty input — an empty ranking
        is valid when a session genuinely has no candidates.
        """
        self._validate_ranking_input(score_results)
        if not score_results:
            return []

        ordered = sorted(
            score_results,
            key=lambda result: (
                -result["hypothesis_score"],
                result["hypothesis_name"].casefold(),
                str(result["hypothesis_id"]),
            ),
        )
        ranked = self._assign_ranks(ordered)
        annotated = self._assign_separation_metadata(ranked)
        self._validate_separation_metadata(annotated)
        return annotated

    @staticmethod
    def _assign_ranks(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Assign competition ranks to an already score-sorted list.

        ``ordered`` must already be sorted by ``hypothesis_score``
        descending (with the documented secondary key breaking ties
        for list position only). A tied candidate receives the same
        rank as the previous entry; a candidate with a new, lower
        score receives its 1-based position in the list — producing
        competition ranking (e.g. 1, 1, 3), never dense ranking
        (1, 1, 2). Each returned entry is a new dict (the Task 025
        ``dict``/``HypothesisScoreRead``-shaped input is never
        mutated); ``rank`` is added without altering any preserved
        Task 025 field.
        """
        ranked: list[dict[str, Any]] = []
        previous_score: float | None = None
        previous_rank = 0

        for index, result in enumerate(ordered):
            score = result["hypothesis_score"]
            if previous_score is not None and score == previous_score:
                rank = previous_rank
            else:
                rank = index + 1

            entry = dict(result)
            entry["rank"] = rank
            ranked.append(entry)

            previous_score = score
            previous_rank = rank

        return ranked

    @staticmethod
    def _assign_separation_metadata(
        ranked: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Task 027: derive how ranked candidates are separated by score.

        Operates only on ``hypothesis_score`` values already present in
        ``ranked`` (which must already carry ``rank`` from
        ``_assign_ranks``) — no evidence, contribution, or score is
        recomputed here. For each entry adds:

        * ``is_tied`` — ``True`` when another entry shares its exact
          normalized score.
        * ``tie_group_size`` — count of entries sharing that exact
          score (always >= 1; > 1 only when ``is_tied``).
        * ``score_gap_to_next_higher`` — ``next_higher_distinct_score -
          this_score``, or ``None`` for the highest distinct score.
        * ``score_gap_to_next_lower`` — ``this_score -
          next_lower_distinct_score``, or ``None`` for the lowest
          distinct score.

        Gaps are computed over *distinct* scores, so tied candidates
        correctly skip over their own tie group rather than reporting
        a gap of 0 to a tied peer. Every gap is rounded to Task
        025/026's four-decimal precision to avoid floating-point
        artifacts (e.g. ``2.9999999997`` instead of ``3.0``).

        Deterministic by construction: ``distinct_scores`` is built
        with ``sorted()`` over a set (never relying on set iteration
        order), and per-score aggregates are built by iterating
        ``ranked`` in its already-deterministic order.
        """
        if not ranked:
            return []

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

        annotated: list[dict[str, Any]] = []
        for entry in ranked:
            score = entry["hypothesis_score"]
            tie_group_size = tie_group_size_by_score[score]
            new_entry = dict(entry)
            new_entry["is_tied"] = tie_group_size > 1
            new_entry["tie_group_size"] = tie_group_size
            new_entry["score_gap_to_next_higher"] = higher_gap_by_score[score]
            new_entry["score_gap_to_next_lower"] = lower_gap_by_score[score]
            annotated.append(new_entry)

        return annotated

    @staticmethod
    def _validate_separation_metadata(ranked: list[dict[str, Any]]) -> None:
        """Task 027: verify the separation-metadata contract invariants.

        Recomputes the expected tie/gap values independently of
        ``_assign_separation_metadata`` and compares — a structural
        consistency check on already-computed metadata, exactly like
        Task 025's ``_validate_score_result``. Never repairs a bad
        value; raises ``DifferentialRankingContractError`` naming the
        violated invariant. Checks:

        1. ``is_tied`` is a bool.
        2. ``tie_group_size >= 1``.
        3. ``is_tied`` implies ``tie_group_size > 1``, and vice versa
           (``tie_group_size == 1`` implies ``not is_tied``).
        4. ``tie_group_size`` matches the actual count of entries
           sharing that exact score.
        5. ``score_gap_to_next_higher`` is ``None`` only for the
           highest distinct score, and matches the recomputed gap
           otherwise.
        6. ``score_gap_to_next_lower`` is ``None`` only for the lowest
           distinct score, and matches the recomputed gap otherwise.
        7. Every non-null gap is >= 0 and rounded to four-decimal
           precision.
        """
        if not ranked:
            return

        distinct_scores = sorted(
            {entry["hypothesis_score"] for entry in ranked}, reverse=True
        )
        highest_score = distinct_scores[0]
        lowest_score = distinct_scores[-1]

        expected_higher_gap: dict[float, float | None] = {}
        expected_lower_gap: dict[float, float | None] = {}
        for index, score in enumerate(distinct_scores):
            next_higher = distinct_scores[index - 1] if index > 0 else None
            next_lower = (
                distinct_scores[index + 1] if index < len(distinct_scores) - 1 else None
            )
            expected_higher_gap[score] = (
                round(next_higher - score, _SCORE_PRECISION)
                if next_higher is not None
                else None
            )
            expected_lower_gap[score] = (
                round(score - next_lower, _SCORE_PRECISION)
                if next_lower is not None
                else None
            )

        expected_tie_group_size: dict[float, int] = {}
        for entry in ranked:
            score = entry["hypothesis_score"]
            expected_tie_group_size[score] = expected_tie_group_size.get(score, 0) + 1

        for entry in ranked:
            score = entry["hypothesis_score"]
            is_tied = entry["is_tied"]
            tie_group_size = entry["tie_group_size"]
            gap_higher = entry["score_gap_to_next_higher"]
            gap_lower = entry["score_gap_to_next_lower"]

            if not isinstance(is_tied, bool):
                raise DifferentialRankingContractError(
                    "IS_TIED_TYPE", f"is_tied is not boolean: {is_tied!r}"
                )

            if tie_group_size < 1:
                raise DifferentialRankingContractError(
                    "TIE_GROUP_SIZE_BOUNDS",
                    f"tie_group_size must be >= 1, got {tie_group_size}",
                )
            if is_tied and tie_group_size <= 1:
                raise DifferentialRankingContractError(
                    "TIE_GROUP_SIZE_CONSISTENCY",
                    "is_tied is True but tie_group_size is not > 1",
                )
            if not is_tied and tie_group_size != 1:
                raise DifferentialRankingContractError(
                    "TIE_GROUP_SIZE_CONSISTENCY",
                    "is_tied is False but tie_group_size != 1",
                )
            if tie_group_size != expected_tie_group_size[score]:
                raise DifferentialRankingContractError(
                    "TIE_GROUP_SIZE_MISMATCH",
                    f"tie_group_size ({tie_group_size}) does not match the "
                    f"actual number of entries sharing score {score} "
                    f"({expected_tie_group_size[score]})",
                )

            # Boundary + independent sign/precision checks come first —
            # these are structural properties of the value itself and
            # must hold regardless of whether it also happens to match
            # the recomputed expectation below.
            if score == highest_score and gap_higher is not None:
                raise DifferentialRankingContractError(
                    "SCORE_GAP_BOUNDARY",
                    "score_gap_to_next_higher must be None for the "
                    "highest distinct score",
                )
            if score == lowest_score and gap_lower is not None:
                raise DifferentialRankingContractError(
                    "SCORE_GAP_BOUNDARY",
                    "score_gap_to_next_lower must be None for the "
                    "lowest distinct score",
                )

            for gap_name, gap_value in (
                ("score_gap_to_next_higher", gap_higher),
                ("score_gap_to_next_lower", gap_lower),
            ):
                if gap_value is None:
                    continue
                if gap_value < 0:
                    raise DifferentialRankingContractError(
                        "SCORE_GAP_NEGATIVE",
                        f"{gap_name} is negative: {gap_value}",
                    )
                if round(gap_value, _SCORE_PRECISION) != gap_value:
                    raise DifferentialRankingContractError(
                        "ROUNDING_PRECISION",
                        f"{gap_name} ({gap_value}) is not rounded to "
                        f"{_SCORE_PRECISION} decimal places",
                    )

            # Cross-field consistency: the value must also match what
            # independent recomputation over the distinct-score ladder
            # produces.
            if score != highest_score and gap_higher != expected_higher_gap[score]:
                raise DifferentialRankingContractError(
                    "SCORE_GAP_MISMATCH",
                    f"score_gap_to_next_higher ({gap_higher}) does not match "
                    f"the expected value ({expected_higher_gap[score]})",
                )
            if score != lowest_score and gap_lower != expected_lower_gap[score]:
                raise DifferentialRankingContractError(
                    "SCORE_GAP_MISMATCH",
                    f"score_gap_to_next_lower ({gap_lower}) does not match "
                    f"the expected value ({expected_lower_gap[score]})",
                )

    @staticmethod
    def _validate_ranking_input(score_results: list[dict[str, Any]]) -> None:
        """Task 026: verify the ranking-input invariants.

        This validates structural fitness of the already-produced
        Task 025 results for ranking — it never recomputes a score,
        never repairs a bad value, and never silently discards a
        candidate. On any violation it raises
        ``DifferentialRankingContractError`` identifying which
        invariant failed. Checks:

        1. Every result carries a ``hypothesis_id``.
        2. Every ``hypothesis_id`` is unique across the input.
        3. Every result carries a ``hypothesis_score`` that is numeric
           (not missing, not a bool, not a non-numeric type).
        4. Every ``hypothesis_score`` is already normalized to Task
           025's precision (4 decimal places) — ranking uses exact
           comparison of that normalized value, never a fresh
           floating-point epsilon.
        5. Every result carries a non-null ``hypothesis_name`` (needed
           for the documented deterministic secondary ordering).
        """
        seen_ids: set[Any] = set()

        for result in score_results:
            hypothesis_id = result.get("hypothesis_id")
            if hypothesis_id is None:
                raise DifferentialRankingContractError(
                    "MISSING_HYPOTHESIS_ID",
                    "ranking input entry has no hypothesis_id",
                )
            if hypothesis_id in seen_ids:
                raise DifferentialRankingContractError(
                    "DUPLICATE_HYPOTHESIS_ID",
                    f"hypothesis_id {hypothesis_id} appears more than once "
                    "in ranking input",
                )
            seen_ids.add(hypothesis_id)

            score = result.get("hypothesis_score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise DifferentialRankingContractError(
                    "NON_NUMERIC_SCORE",
                    f"hypothesis_score is not numeric: {score!r}",
                )
            if round(float(score), _SCORE_PRECISION) != float(score):
                raise DifferentialRankingContractError(
                    "ROUNDING_PRECISION",
                    f"hypothesis_score ({score}) is not rounded to "
                    f"{_SCORE_PRECISION} decimal places",
                )

            name = result.get("hypothesis_name")
            if not name:
                raise DifferentialRankingContractError(
                    "MISSING_HYPOTHESIS_NAME",
                    "ranking input entry has no hypothesis_name",
                )

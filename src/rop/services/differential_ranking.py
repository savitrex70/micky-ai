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
        return self._assign_ranks(ordered)

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

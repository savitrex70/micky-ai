from pydantic import BaseModel, ConfigDict


class DifferentialDecisionReadinessRead(BaseModel):
    """Task 030: structural decision-readiness contract.

    A derived view over Task 027's ranked differential, Task 028's
    structural summary, and Task 029's consistency verdict. It reports
    whether the current differential is structurally complete and
    internally consistent enough for a *future* decision layer to
    consume — the clean hand-off point at which that layer can read
    this contract instead of reaching backward into raw evidence or
    scoring internals.

    It is not a decision. There is no winner, no selected hypothesis,
    no diagnosis, no probability, no confidence, no recommendation, and
    no treatment. ``readiness_source`` is a fixed structural-contract
    identifier, never a confidence value.

    ``has_score_separation``, ``has_unresolved_ties``, and
    ``evidence_present_for_any_candidate`` are reported but
    deliberately excluded from ``ready``: an all-tied differential is
    still structurally valid, and a candidate set may legitimately
    exist before evidence has been evaluated. ``has_unresolved_ties``
    in particular describes score structure, never uncertainty or
    diagnostic ambiguity.

    An empty differential is valid but not ready — empty is not the
    same as structurally corrupt.
    """

    model_config = ConfigDict(from_attributes=True)

    ready: bool
    consistency_verified: bool
    has_candidates: bool
    ranking_available: bool
    summary_available: bool
    separation_metadata_available: bool
    has_score_separation: bool
    has_unresolved_ties: bool
    evidence_present_for_any_candidate: bool
    readiness_source: str

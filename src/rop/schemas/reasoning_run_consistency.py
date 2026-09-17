from pydantic import BaseModel, ConfigDict


class ReasoningRunConsistencyRead(BaseModel):
    """Task 043: independent consistency/audit of a Task 042 reasoning run.

    Audits Task 042's composed reasoning-run representation against the
    session's actual underlying state and against the approved Task 041
    pipeline contract. Independently derives expected values and reports
    twelve consistency flags plus a deterministic ordered list of
    machine-readable consistency_issues. This is an audit contract only
    -- it does not select, rank, score, diagnose, recommend, or alter
    any upstream result. ``run_consistency_source`` is a fixed
    structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    run_consistent: bool
    session_consistent: bool
    observations_consistent: bool
    entities_consistent: bool
    missing_information_consistent: bool
    template_context_consistent: bool
    candidate_state_consistent: bool
    candidate_count_consistent: bool
    candidate_generation_consistent: bool
    pipeline_consistent: bool
    stage_structure_consistent: bool
    source_consistency: bool
    metadata_consistency: bool
    consistency_issues: list[str]
    run_consistency_source: str

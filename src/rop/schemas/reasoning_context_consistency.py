from pydantic import BaseModel, ConfigDict


class ReasoningContextConsistencyRead(BaseModel):
    """Task 056: independent consistency/audit of a Task 055 context.

    Audits the supplied Task 055 ``ReasoningContextRead`` against its
    own declared contract and against the nested Task 042 / Task 043
    contracts. Audit-only: it does not build, select, rank, score,
    diagnose, recommend, or alter any upstream result, and never
    calls an LLM. ``context_consistency_source`` is a fixed structural
    identifier.

    ``context_consistent`` here means "the supplied Task 055 package
    satisfies the independently audited Task 056 contract" -- it
    deliberately does NOT mirror Task 055's own ``context_consistent``
    flag. A package may legitimately contain a Task 042 run and Task
    043 audit whose own ``run_consistent`` is False; Task 056 audits
    the package relationship, not whether the underlying reasoning
    succeeded.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    context_consistent: bool
    session_consistent: bool
    nested_reasoning_run_consistent: bool
    nested_reasoning_run_audit_consistent: bool
    candidate_state_consistent: bool
    candidate_count_consistent: bool
    audit_provenance_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    context_consistency_source: str

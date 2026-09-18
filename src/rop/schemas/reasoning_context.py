from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.candidate_hypothesis import CandidateHypothesisRead
from rop.schemas.entity import EntityRead
from rop.schemas.missing_information import MissingInformationRead
from rop.schemas.observation import ObservationRead
from rop.schemas.reasoning_run import ReasoningRunRead
from rop.schemas.reasoning_run_consistency import (
    ReasoningRunConsistencyRead,
)
from rop.schemas.template_match import TemplateMatchRead


class ReasoningContextRead(BaseModel):
    """Task 055: canonical deterministic reasoning context.

    Packages the session's already-established reasoning state --
    observations, entities, missing information, template context,
    candidate state -- alongside the exact canonical Task 042
    ``ReasoningRunRead`` and Task 043 ``ReasoningRunConsistencyRead``
    outputs. This is an assembly contract only: it does not generate,
    rerank, rescore, filter, or reinterpret anything, and it never
    calls an LLM or performs reasoning.

    ``context_consistent`` means "is this Task 055 context package
    internally consistent with the supplied Task 042 and Task 043
    contracts?". It never means medically correct, diagnostically
    correct, decision-ready, LLM-ready, or that reasoning succeeded.

    ``context_source`` is a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    context_consistent: bool
    session_id: UUID
    observations: list[ObservationRead]
    entities: list[EntityRead]
    missing_information: list[MissingInformationRead]
    template_context: list[TemplateMatchRead]
    candidate_state: list[CandidateHypothesisRead]
    reasoning_pipeline: ReasoningRunRead
    reasoning_run_consistency: ReasoningRunConsistencyRead
    context_source: str

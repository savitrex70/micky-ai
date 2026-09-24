from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.database import get_db
from rop.models import (
    CandidateHypothesis,
    Evidence,
    Hypothesis,
    MissingInformation,
    Observation,
    ReasoningSession,
    ReasoningStep,
    TemplateMatch,
)
from rop.schemas import (
    CandidateHypothesisRead,
    DecisionCandidateAssessmentSetRead,
    DecisionCandidateEvaluationRead,
    DecisionCandidateSetRead,
    DecisionContextRead,
    DecisionEvaluationConsistencyRead,
    DecisionExecutionConsistencyRead,
    DecisionExecutionRead,
    DecisionInputBundleRead,
    DecisionInputEligibilityRead,
    DecisionPolicyRead,
    DifferentialDecisionReadinessRead,
    DifferentialRankingConsistencyRead,
    DifferentialRankingSummaryRead,
    DifferentialRankRead,
    EvidenceConsistencyRead,
    EvidenceCreate,
    EvidenceRead,
    EvidenceSummaryRead,
    EvidenceUpdate,
    HypothesisCreate,
    HypothesisRead,
    HypothesisScoreRead,
    HypothesisUpdate,
    MissingInformationRead,
    ObservationCreate,
    ObservationExtractionRequest,
    ObservationExtractionResponse,
    ObservationRead,
    ReasoningHandoffApiAuditBundleRead,
    ReasoningHandoffRead,
    ReasoningPipelineRead,
    ReasoningRunConsistencyRead,
    ReasoningRunExecutionAuditPackageRead,
    ReasoningRunExecutionBundleRead,
    ReasoningRunExecutionRead,
    ReasoningRunRead,
    ReasoningSessionCreate,
    ReasoningSessionRead,
    ReasoningStepCreate,
    ReasoningStepRead,
    TemplateMatchRead,
)
from rop.schemas.api import (
    EvidenceCreateRequest,
    HypothesisCreateRequest,
    ObservationCreateRequest,
    ReasoningStepCreateRequest,
)
from rop.services import (
    CandidateGenerationService,
    DecisionCandidateAssessmentContractError,
    DecisionCandidateAssessmentService,
    DecisionCandidateEvaluationContractError,
    DecisionCandidateEvaluationService,
    DecisionCandidateSetContractError,
    DecisionCandidateSetService,
    DecisionContextContractError,
    DecisionContextService,
    DecisionEvaluationConsistencyContractError,
    DecisionEvaluationConsistencyService,
    DecisionExecutionConsistencyContractError,
    DecisionExecutionConsistencyService,
    DecisionExecutionContractError,
    DecisionExecutionService,
    DecisionInputBundleContractError,
    DecisionInputBundleService,
    DecisionInputEligibilityContractError,
    DecisionInputEligibilityService,
    DecisionPolicyContractError,
    DecisionPolicyService,
    DifferentialDecisionReadinessContractError,
    DifferentialDecisionReadinessService,
    DifferentialRankingConsistencyContractError,
    DifferentialRankingConsistencyService,
    DifferentialRankingContractError,
    DifferentialRankingService,
    DifferentialRankingSummaryContractError,
    DifferentialRankingSummaryService,
    EntityService,
    EvidenceAggregationService,
    EvidenceEvaluationService,
    EvidenceService,
    HypothesisScoreContractError,
    HypothesisScoringService,
    HypothesisService,
    MissingInformationService,
    ObservationExtractionService,
    ObservationService,
    ReasoningContextConsistencyContractError,
    ReasoningContextContractError,
    ReasoningHandoffApiAuditBundleContractError,
    ReasoningHandoffApiAuditPackageConsistencyContractError,
    ReasoningHandoffApiAuditPackageContractError,
    ReasoningHandoffApiConsistencyContractError,
    ReasoningHandoffApiService,
    ReasoningHandoffContractError,
    ReasoningHandoffFullyAuditedApiService,
    ReasoningPipelineContractError,
    ReasoningPipelineService,
    ReasoningRunConsistencyContractError,
    ReasoningRunConsistencyService,
    ReasoningRunContractError,
    ReasoningRunExecutionAuditPackageContractError,
    ReasoningRunExecutionAuditPackageService,
    ReasoningRunExecutionBundleContractError,
    ReasoningRunExecutionBundleService,
    ReasoningRunExecutionContractError,
    ReasoningRunExecutionService,
    ReasoningRunService,
    ReasoningSessionService,
    ReasoningStepService,
    TemplateMatchService,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
session_service = ReasoningSessionService()
observation_service = ObservationService()
observation_extraction_service = ObservationExtractionService()
missing_information_service = MissingInformationService()
template_match_service = TemplateMatchService()
entity_service = EntityService()
hypothesis_service = HypothesisService()
evidence_service = EvidenceService()
reasoning_step_service = ReasoningStepService()
candidate_generation_service = CandidateGenerationService()
evidence_evaluation_service = EvidenceEvaluationService()
evidence_aggregation_service = EvidenceAggregationService()
hypothesis_scoring_service = HypothesisScoringService(evidence_aggregation_service)
differential_ranking_service = DifferentialRankingService(hypothesis_scoring_service)
differential_ranking_summary_service = DifferentialRankingSummaryService(
    differential_ranking_service
)
differential_ranking_consistency_service = DifferentialRankingConsistencyService(
    differential_ranking_summary_service
)
differential_decision_readiness_service = DifferentialDecisionReadinessService(
    differential_ranking_consistency_service
)
decision_context_service = DecisionContextService(
    differential_decision_readiness_service
)
decision_candidate_evaluation_service = DecisionCandidateEvaluationService(
    decision_context_service
)
decision_evaluation_consistency_service = DecisionEvaluationConsistencyService(
    decision_candidate_evaluation_service
)
decision_input_eligibility_service = DecisionInputEligibilityService(
    decision_evaluation_consistency_service
)
decision_candidate_set_service = DecisionCandidateSetService(
    decision_input_eligibility_service
)
decision_candidate_assessment_service = DecisionCandidateAssessmentService(
    decision_candidate_set_service
)
decision_input_bundle_service = DecisionInputBundleService(
    decision_candidate_set_service,
    decision_candidate_assessment_service,
)
decision_policy_service = DecisionPolicyService(decision_input_bundle_service)
decision_execution_service = DecisionExecutionService(
    decision_input_bundle_service,
    decision_policy_service,
)
decision_execution_consistency_service = DecisionExecutionConsistencyService(
    decision_input_bundle_service,
    decision_policy_service,
    decision_execution_service,
)
reasoning_pipeline_service = ReasoningPipelineService()
reasoning_run_service = ReasoningRunService()
reasoning_run_consistency_service = ReasoningRunConsistencyService()
reasoning_run_execution_service = ReasoningRunExecutionService()
reasoning_run_execution_bundle_service = ReasoningRunExecutionBundleService()
reasoning_run_execution_audit_package_service = (
    ReasoningRunExecutionAuditPackageService()
)
reasoning_handoff_api_service = ReasoningHandoffApiService()
reasoning_handoff_fully_audited_api_service = ReasoningHandoffFullyAuditedApiService()


@router.post(
    "",
    response_model=ReasoningSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: ReasoningSessionCreate,
    db: Session = Depends(get_db),
) -> ReasoningSession:
    return session_service.create(db, payload)


@router.get("", response_model=list[ReasoningSessionRead])
def list_sessions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ReasoningSession]:
    return session_service.list(db, offset=offset, limit=limit)


@router.get("/{session_id}", response_model=ReasoningSessionRead)
def get_session(session_id: UUID, db: Session = Depends(get_db)) -> ReasoningSession:
    session = session_service.get(db, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: UUID, db: Session = Depends(get_db)) -> None:
    if not session_service.delete(db, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )


@router.post(
    "/{session_id}/observations",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_observation(
    session_id: UUID,
    payload: ObservationCreateRequest,
    db: Session = Depends(get_db),
) -> Observation:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    observation = ObservationCreate(session_id=session_id, **payload.model_dump())
    return observation_service.create(db, observation)


@router.get(
    "/{session_id}/observations",
    response_model=list[ObservationRead],
)
def list_observations(
    session_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Observation]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return observation_service.list_by_session(
        db, session_id, offset=offset, limit=limit
    )


@router.post(
    "/{session_id}/extract-observations",
    response_model=ObservationExtractionResponse,
    status_code=status.HTTP_201_CREATED,
)
def extract_observations(
    session_id: UUID,
    payload: ObservationExtractionRequest,
    db: Session = Depends(get_db),
) -> ObservationExtractionResponse:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    observations = observation_extraction_service.extract_and_store(
        db, session_id, payload.text
    )
    return ObservationExtractionResponse.model_validate({"observations": observations})


@router.post(
    "/{session_id}/detect-missing-information",
    response_model=list[MissingInformationRead],
    status_code=status.HTTP_201_CREATED,
)
def detect_missing_information(
    session_id: UUID,
    profile: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> list[MissingInformation]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    observations = observation_service.list_by_session(
        db, session_id, offset=0, limit=1000
    )
    return missing_information_service.detect_and_store(
        db, session_id, observations, profile_name=profile
    )


@router.post(
    "/{session_id}/match-template",
    response_model=TemplateMatchRead,
    status_code=status.HTTP_201_CREATED,
)
def match_template(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> TemplateMatch:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    observations = observation_service.list_by_session(
        db, session_id, offset=0, limit=1000
    )
    entities = entity_service.list_by_session(db, session_id, offset=0, limit=1000)
    return template_match_service.match(db, session_id, observations, entities)


@router.post(
    "/{session_id}/hypotheses",
    response_model=HypothesisRead,
    status_code=status.HTTP_201_CREATED,
)
def create_hypothesis(
    session_id: UUID,
    payload: HypothesisCreateRequest,
    db: Session = Depends(get_db),
) -> Hypothesis:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = HypothesisCreate(session_id=session_id, **payload.model_dump())
    return hypothesis_service.create(db, hypothesis)


@router.get(
    "/{session_id}/hypotheses",
    response_model=list[HypothesisRead],
)
def list_hypotheses(
    session_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Hypothesis]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return hypothesis_service.list_by_session(
        db, session_id, offset=offset, limit=limit
    )


@router.get(
    "/{session_id}/hypotheses/{hypothesis_id}",
    response_model=HypothesisRead,
)
def get_hypothesis(
    session_id: UUID,
    hypothesis_id: UUID,
    db: Session = Depends(get_db),
) -> Hypothesis:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )
    return hypothesis


@router.put(
    "/{session_id}/hypotheses/{hypothesis_id}",
    response_model=HypothesisRead,
)
def update_hypothesis(
    session_id: UUID,
    hypothesis_id: UUID,
    payload: HypothesisUpdate,
    db: Session = Depends(get_db),
) -> Hypothesis:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    updated = hypothesis_service.update(db, hypothesis_id, payload)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )
    return updated


@router.delete(
    "/{session_id}/hypotheses/{hypothesis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_hypothesis(
    session_id: UUID,
    hypothesis_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    hypothesis_service.delete(db, hypothesis_id)


@router.post(
    "/{session_id}/hypotheses/{hypothesis_id}/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence(
    session_id: UUID,
    hypothesis_id: UUID,
    payload: EvidenceCreateRequest,
    db: Session = Depends(get_db),
) -> Evidence:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    evidence = EvidenceCreate(
        hypothesis_id=hypothesis_id,
        session_id=session_id,
        **payload.model_dump(),
    )
    return evidence_service.create(db, evidence)


@router.get(
    "/{session_id}/hypotheses/{hypothesis_id}/evidence",
    response_model=list[EvidenceRead],
)
def list_evidence_by_hypothesis(
    session_id: UUID,
    hypothesis_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Evidence]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    return evidence_service.list_by_hypothesis(
        db, hypothesis_id, offset=offset, limit=limit
    )


@router.get(
    "/{session_id}/evidence",
    response_model=list[EvidenceRead],
)
def list_evidence_by_session(
    session_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Evidence]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    return evidence_service.list_by_session(db, session_id, offset=offset, limit=limit)


@router.get(
    "/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}",
    response_model=EvidenceRead,
)
def get_evidence(
    session_id: UUID,
    hypothesis_id: UUID,
    evidence_id: UUID,
    db: Session = Depends(get_db),
) -> Evidence:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    evidence = evidence_service.get(db, evidence_id)
    if evidence is None or evidence.hypothesis_id != hypothesis_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found"
        )
    return evidence


@router.put(
    "/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}",
    response_model=EvidenceRead,
)
def update_evidence(
    session_id: UUID,
    hypothesis_id: UUID,
    evidence_id: UUID,
    payload: EvidenceUpdate,
    db: Session = Depends(get_db),
) -> Evidence:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    evidence = evidence_service.get(db, evidence_id)
    if evidence is None or evidence.hypothesis_id != hypothesis_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found"
        )

    updated = evidence_service.update(db, evidence_id, payload)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found"
        )
    return updated


@router.delete(
    "/{session_id}/hypotheses/{hypothesis_id}/evidence/{evidence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_evidence(
    session_id: UUID,
    hypothesis_id: UUID,
    evidence_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    hypothesis = hypothesis_service.get(db, hypothesis_id)
    if hypothesis is None or hypothesis.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hypothesis not found"
        )

    evidence = evidence_service.get(db, evidence_id)
    if evidence is None or evidence.hypothesis_id != hypothesis_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found"
        )

    evidence_service.delete(db, evidence_id)


@router.post(
    "/{session_id}/steps",
    response_model=ReasoningStepRead,
    status_code=status.HTTP_201_CREATED,
)
def create_reasoning_step(
    session_id: UUID,
    payload: ReasoningStepCreateRequest,
    db: Session = Depends(get_db),
) -> ReasoningStep:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    step = ReasoningStepCreate(session_id=session_id, **payload.model_dump())
    return reasoning_step_service.create(db, step)


@router.get(
    "/{session_id}/steps",
    response_model=list[ReasoningStepRead],
)
def list_reasoning_steps(
    session_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ReasoningStep]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return reasoning_step_service.list_by_session(
        db, session_id, offset=offset, limit=limit
    )


@router.get(
    "/{session_id}/steps/{step_id}",
    response_model=ReasoningStepRead,
)
def get_reasoning_step(
    session_id: UUID,
    step_id: UUID,
    db: Session = Depends(get_db),
) -> ReasoningStep:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    step = reasoning_step_service.get(db, step_id)
    if step is None or step.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reasoning step not found"
        )
    return step


@router.get(
    "/{session_id}/replay",
    response_model=list[ReasoningStepRead],
)
def replay_session(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[ReasoningStep]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return reasoning_step_service.replay(db, session_id)


@router.post(
    "/{session_id}/generate-candidates",
    response_model=list[CandidateHypothesisRead],
    status_code=status.HTTP_201_CREATED,
)
def generate_candidates(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[CandidateHypothesis]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    observations = observation_service.list_by_session(
        db, session_id, offset=0, limit=1000
    )
    entities = entity_service.list_by_session(db, session_id, offset=0, limit=1000)

    from rop.models import TemplateMatch

    latest_match = db.execute(
        select(TemplateMatch)
        .where(TemplateMatch.session_id == session_id)
        .order_by(TemplateMatch.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    template = None
    if latest_match:
        from rop.templates import load_templates

        templates = load_templates()
        template = next(
            (t for t in templates if t.name == latest_match.template_name),
            None,
        )

    missing_info = missing_information_service.list_by_session(db, session_id)

    return candidate_generation_service.generate(
        db=db,
        session_id=session_id,
        observations=observations,
        entities=entities,
        template=template,
        missing_information=missing_info,
    )


@router.post(
    "/{session_id}/evaluate-evidence",
    response_model=list[dict[str, Any]],
    status_code=status.HTTP_200_OK,
)
def evaluate_evidence(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    observations = observation_service.list_by_session(
        db, session_id, offset=0, limit=1000
    )
    entities = entity_service.list_by_session(db, session_id, offset=0, limit=1000)
    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    evidence_evaluation_service.evaluate_session(
        db=db,
        session_id=session_id,
        candidates=candidates,
        observations=observations,
        entities=entities,
    )

    return evidence_evaluation_service.group_by_hypothesis(db, session_id, candidates)


@router.get(
    "/{session_id}/evidence-summary",
    response_model=list[EvidenceSummaryRead],
    status_code=status.HTTP_200_OK,
)
def get_evidence_summary(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Read-only, deterministic evidence summary per candidate hypothesis.

    Consumes the evidence already persisted by ``/evaluate-evidence``
    (Task 020) — it does not evaluate evidence itself, so call
    ``/evaluate-evidence`` first if the session's evidence is stale or
    has never been evaluated. Never writes to the database.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    return evidence_aggregation_service.summarize_session(db, session_id, candidates)


@router.get(
    "/{session_id}/evidence-analysis",
    response_model=list[EvidenceConsistencyRead],
    status_code=status.HTTP_200_OK,
)
def get_evidence_analysis(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Task 022: read-only evidence consistency/quality analysis.

    Consumes the same persisted ``EvaluatedEvidence`` rows as
    ``/evidence-summary`` (Task 021), but returns one entry per candidate
    hypothesis in the session — including candidates with no evidence yet
    — plus a structural consistency signal (support-only, contradiction-
    only, mixed, neutral-only, or no evidence) and ratios. Never
    evaluates evidence or writes to the database.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    return evidence_aggregation_service.analyze_session_consistency(
        db, session_id, candidates=candidates
    )


@router.get(
    "/{session_id}/hypothesis-scores",
    response_model=list[HypothesisScoreRead],
    status_code=status.HTTP_200_OK,
)
def get_hypothesis_scores(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Task 023: read-only deterministic hypothesis score per candidate.

    Consumes the same persisted ``EvaluatedEvidence`` rows as
    ``/evidence-analysis`` (Task 022), via ``EvidenceAggregationService``
    — it does not evaluate evidence, generate candidates, or write to
    the database. ``hypothesis_score`` currently equals Task 021's
    ``net_contribution`` unchanged; this is a scoring foundation, not a
    ranked differential, a diagnosis, or a probability. Candidates with
    no persisted evidence still receive a result, scored 0.0 with
    ``evidence_consistency == "NO_EVIDENCE"``.

    Task 024 extends the response with a structural interpretation
    layer (``score_direction``, ``evidence_coverage_ratio`` — TEMPORARY,
    see the service docstring, ``informative_evidence_ratio``,
    ``support_to_contradiction_ratio``, ``evidence_position``) without
    changing the score itself or this endpoint's read-only,
    non-ranking, non-diagnostic contract.

    Task 025 formalizes these fields into a stable scoring contract and
    validates every result against it before returning. Candidate
    order is preserved exactly as received — this endpoint never sorts
    by score, ranks, or compares hypotheses against one another.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    try:
        return hypothesis_scoring_service.score_session(db, session_id, candidates)
    except HypothesisScoreContractError as exc:
        # Task 025: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal hypothesis-scoring contract violation",
        ) from exc


@router.get(
    "/{session_id}/differential",
    response_model=list[DifferentialRankRead],
    status_code=status.HTTP_200_OK,
)
def get_differential_ranking(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Task 026: read-only differential ranking over Task 025 scores.

    Consumes ``HypothesisScoringService.score_session`` (Task 025)
    unchanged via ``DifferentialRankingService`` — it does not
    re-evaluate evidence, recompute contributions, inspect
    observations/entities, or generate candidates. Candidates are
    ordered by ``hypothesis_score`` descending, with competition
    ranking for ties (1, 1, 3 — never dense 1, 1, 2) and a documented
    deterministic secondary ordering (``hypothesis_name.casefold()``
    ascending, then ``str(hypothesis_id)`` ascending) that breaks ties
    for list position only, never for the shared rank. Candidates with
    no persisted evidence remain in the ranking, scored 0.0 like any
    other candidate.

    This endpoint answers "given the current deterministic hypothesis
    scores, what is their relative ordering?" — it never answers
    "which diagnosis is correct?" It performs no diagnosis selection,
    winner selection, decision-making, treatment recommendation,
    probability conversion, or confidence calibration, and it never
    writes to the database or persists a ranking table; ranking is a
    derived, read-only view over the current score state.

    Task 027 extends each entry with derived separation metadata
    (``is_tied``, ``tie_group_size``, ``score_gap_to_next_higher``,
    ``score_gap_to_next_lower``) describing how candidates are
    separated from one another by score — still purely structural,
    with no winner, probability, or decision logic added.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    try:
        return differential_ranking_service.rank_session(db, session_id, candidates)
    except (HypothesisScoreContractError, DifferentialRankingContractError) as exc:
        # Task 026: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal differential-ranking contract violation",
        ) from exc


@router.get(
    "/{session_id}/differential-summary",
    response_model=DifferentialRankingSummaryRead,
    status_code=status.HTTP_200_OK,
)
def get_differential_ranking_summary(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 028: read-only structural summary over the Task 027 ranking.

    Consumes ``DifferentialRankingService.rank_session`` (Tasks
    026/027) unchanged via ``DifferentialRankingSummaryService`` — it
    does not re-evaluate evidence, recompute scores, recompute ranks,
    or duplicate the ranking/tie-separation logic. It aggregates the
    already-ranked differential into a compact, session-level
    description of its shape: how many candidates, how many distinct
    scores, the score range, and how many/how large the tie groups
    are.

    This endpoint answers "what does the current differential ranking
    look like structurally?" — it never answers "which diagnosis is
    correct?" It performs no winner selection, decision-making,
    treatment recommendation, probability conversion, or confidence
    calibration, and it never writes to the database or persists a
    summary table; the summary is a derived, read-only view over the
    current ranked state. A session with no candidates still returns
    a fully defined summary rather than an error.

    Does not modify the existing ``GET /sessions/{session_id}/differential``
    behavior or any of its fields — this is an additional derived view.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    try:
        return differential_ranking_summary_service.summarize_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
    ) as exc:
        # Task 028: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal differential-ranking-summary contract violation",
        ) from exc


@router.get(
    "/{session_id}/differential-consistency",
    response_model=DifferentialRankingConsistencyRead,
    status_code=status.HTTP_200_OK,
)
def get_differential_ranking_consistency(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 029: read-only completeness/consistency contract.

    Consumes the Task 027 ranked differential
    (``DifferentialRankingService``) and the Task 028 structural
    summary (``DifferentialRankingSummaryService``) unchanged, via
    ``DifferentialRankingConsistencyService`` — it does not
    recalculate evidence, scores, ranks, or summary aggregates, and it
    introduces no second ranking algorithm. It independently
    re-derives each summary/separation value directly from the ranked
    entries and reports whether that matches what Tasks 027/028 already
    produced.

    This endpoint answers "do the ranking, separation metadata, and
    session summary agree with each other?" — it never answers "which
    diagnosis is correct?" It performs no winner selection, diagnosis
    selection, decision-making, treatment recommendation, probability
    conversion, or confidence calibration, and it never writes to the
    database or persists a consistency-result table; the result is a
    derived, read-only view over the current ranked and summarized
    state. A session with no candidates still returns a fully
    consistent result rather than an error, since two empty structures
    trivially agree.

    Does not modify the existing ``GET /sessions/{session_id}/differential``
    or ``GET /sessions/{session_id}/differential-summary`` behavior or
    any of their fields — this is an additional derived view.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    try:
        return differential_ranking_consistency_service.check_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
    ) as exc:
        # Task 029: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal differential-ranking-consistency contract violation",
        ) from exc


@router.get(
    "/{session_id}/differential-readiness",
    response_model=DifferentialDecisionReadinessRead,
    status_code=status.HTTP_200_OK,
)
def get_differential_decision_readiness(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 030: read-only structural decision-readiness contract.

    Consumes the Task 027 ranked differential, the Task 028 structural
    summary, and the Task 029 consistency verdict unchanged, via
    ``DifferentialDecisionReadinessService`` — it does not recompute a
    hypothesis score, introduce a second ranking engine, or reinterpret
    Task 029's verdict.

    This endpoint answers "is the current differential structurally
    complete and internally consistent enough for a future decision
    layer to consume?" — it never answers "what decision should be
    made?" It performs no winner selection, diagnosis selection,
    probability conversion, confidence calibration, recommendation, or
    treatment logic; it removes no candidates; and it never writes to
    the database or persists a readiness table.

    Ties and absent evidence are reported but never suppress
    ``ready``: an all-tied differential is still a structurally valid
    differential, and a candidate set may legitimately exist before
    evidence has been evaluated. An empty differential is valid but not
    ready — empty is not the same as structurally corrupt.

    Does not modify the behavior or fields of the existing
    ``/differential``, ``/differential-summary``, or
    ``/differential-consistency`` endpoints — this is an additional
    derived view.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    try:
        return differential_decision_readiness_service.evaluate_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
    ) as exc:
        # Task 030: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal differential-decision-readiness contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-context",
    response_model=DecisionContextRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_context(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 031: read-only decision-context contract.

    Packages the Task 027 ranked differential, the Task 028 structural
    summary, the Task 029 consistency result, and the Task 030
    readiness result into one deterministic object via
    ``DecisionContextService`` — it duplicates no scoring, ranking,
    summary, consistency, or readiness logic, and never reaches
    directly into evidence or observations.

    This is packaging only: it makes no decision, selects no
    hypothesis, identifies no winner, and calculates no probability or
    confidence. ``context_available`` means a complete, internally
    consistent decision-context package has been assembled — not that
    a decision exists or a diagnosis is known. It never writes to the
    database, persists nothing, and modifies no candidate or evidence.

    Does not modify the behavior or fields of the existing
    ``/differential``, ``/differential-summary``,
    ``/differential-consistency``, or ``/differential-readiness``
    endpoints — this is an additional derived view over the same
    underlying pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    try:
        return decision_context_service.build_for_session(db, session_id, candidates)
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
    ) as exc:
        # Task 031: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-context contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-candidate-evaluations",
    response_model=list[DecisionCandidateEvaluationRead],
    status_code=status.HTTP_200_OK,
)
def get_decision_candidate_evaluations(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Task 032: read-only deterministic decision-candidate evaluation contract.

    Consumes the Task 031 ``DecisionContext`` exclusively via
    ``DecisionCandidateEvaluationService`` — it does not reach directly
    into evidence, observations, scoring, or ranking services, and
    duplicates no logic already owned by Tasks 020-031. For every
    candidate in the context's differential, every declared decision
    criterion (support, contradiction, evidence coverage, consistency,
    separation, readiness) is evaluated deterministically against the
    context's already-validated fields — no LLM, no hidden reasoning,
    no probabilistic scoring.

    This answers "how does each candidate perform against the defined
    decision criteria?" — never "which candidate is correct?" There is
    no winner, selected candidate, decision, diagnosis, probability,
    confidence, or weighted/utility score anywhere in this response. It
    never writes to the database, persists nothing, and modifies no
    candidate, evidence, or upstream contract.

    Does not modify the behavior or fields of the existing
    ``/differential``, ``/differential-summary``,
    ``/differential-consistency``, ``/differential-readiness``, or
    ``/decision-context`` endpoints — this is an additional derived
    view over the same underlying pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 032's contract requires every candidate to receive an
    # evaluation, so every page of candidates must be retrieved — a
    # single offset=0/limit=100 call would silently drop candidates
    # beyond the first page for a session with more than 100.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_candidate_evaluation_service.evaluate_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
    ) as exc:
        # Task 032: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-candidate-evaluation contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-evaluation-consistency",
    response_model=DecisionEvaluationConsistencyRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_evaluation_consistency(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 033: read-only structural consistency/coverage over Task 032.

    Consumes only the output of ``DecisionCandidateEvaluationService``
    (Task 032) via ``DecisionEvaluationConsistencyService`` — it does
    not reach into evidence, evidence aggregation, scoring, ranking,
    ranking summary, ranking consistency, readiness, observations,
    entities, hypotheses, or database evidence records, and
    duplicates no logic already owned by Tasks 020-032.

    Answers "are the candidate evaluations complete, structurally
    consistent, and fully comparable across the current decision
    context?" — never "which candidate should be chosen?". There is
    no winner, selected candidate, decision, diagnosis, probability,
    confidence, or weighted/utility score anywhere in this response.
    Every structural fact is independently recalculated from the
    evaluations themselves rather than trusted from Task 032's own
    summary fields. Read-only throughout: nothing is persisted, and
    no input is mutated.

    Does not modify the behavior or fields of the existing
    ``/differential``, ``/differential-summary``,
    ``/differential-consistency``, ``/differential-readiness``,
    ``/decision-context``, or ``/decision-candidate-evaluations``
    endpoints — this is an additional derived view over the same
    underlying pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 033's contract requires every candidate's evaluation to be
    # checked for structural consistency, so every page of candidates
    # must be retrieved — a single offset=0/limit=100 call would
    # silently drop candidates beyond the first page for a session
    # with more than 100, matching Task 032's own pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_evaluation_consistency_service.check_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
    ) as exc:
        # Task 033: an internal contract violation, never medical or
        # client-input error — never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-evaluation-consistency contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-input-eligibility",
    response_model=DecisionInputEligibilityRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_input_eligibility(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 034: read-only decision-input eligibility contract.

    The final gate between decision preparation and the future
    decision engine. Combines the Task 030 readiness result (via
    Task 031), the Task 031 decision context, and the Task 033
    evaluation-consistency result (built over Task 032's candidate
    evaluations) into one deterministic eligibility verdict via
    ``DecisionInputEligibilityService`` -- it does not reach directly
    into evidence, observations, entities, hypothesis scores, ranking
    internals, or repositories, and duplicates no logic already owned
    by Tasks 020-033.

    Answers "is the current decision input structurally valid and
    sufficiently prepared to enter the future decision engine?" --
    never "which candidate should be chosen?". There is no winner,
    best candidate, diagnosis, recommendation, action, probability,
    confidence, utility, weighted score, expected outcome, or
    treatment anywhere in this response. It never writes to the
    database, persists nothing, and modifies no candidate, evidence,
    or upstream contract.

    Does not modify the behavior or fields of the existing
    ``/differential``, ``/differential-summary``,
    ``/differential-consistency``, ``/differential-readiness``,
    ``/decision-context``, ``/decision-candidate-evaluations``, or
    ``/decision-evaluation-consistency`` endpoints -- this is an
    additional derived view over the same underlying pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 034's contract requires the full candidate set (via the
    # Task 031 context it consumes), so every page of candidates must
    # be retrieved -- matching the Task 032/033 pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_input_eligibility_service.build_for_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
    ) as exc:
        # Task 034: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-input-eligibility contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-candidate-set",
    response_model=DecisionCandidateSetRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_candidate_set(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 035: read-only candidate-set handoff contract.

    The stable candidate-set package between Task 034's decision-input
    eligibility gate and the future decision engine. When Task 034
    reports the input eligible AND the Task 031 context is available
    and decision ready, every already-established candidate is
    forwarded in the exact differential order; otherwise the set is
    empty and ``available`` is ``False``. Consumes Task 031 and Task
    034 unchanged via ``DecisionCandidateSetService`` -- it does not
    reach into evidence, observations, entities, hypothesis scores,
    ranking internals, or repositories, and duplicates no logic
    already owned by Tasks 020-034.

    Answers "which already-established candidates is the future
    decision engine allowed to consider?" -- never "which candidate
    should be chosen?". There is no winner, best candidate, diagnosis,
    recommendation, action, probability, confidence, utility, weighted
    score, expected outcome, or treatment anywhere in this response.
    It never ranks, scores, breaks ties, applies a score threshold,
    filters, or removes a candidate. It never writes to the database,
    persists nothing, and modifies no candidate, evidence, or upstream
    contract.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 035's contract requires the full candidate set (via the
    # Task 031 context it consumes), so every page of candidates must
    # be retrieved -- matching the Task 032/033/034 pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_candidate_set_service.build_for_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
    ) as exc:
        # Task 035: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-candidate-set contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-candidate-assessments",
    response_model=DecisionCandidateAssessmentSetRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_candidate_assessments(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 036: read-only candidate-assessment packaging contract.

    The candidate-assessment package between Task 035's candidate-set
    handoff and the future decision engine. For every candidate in the
    Task 035 set, joins the candidate identity, rank, score, tie
    metadata, and score gaps (verbatim) with the corresponding Task
    032 evaluation's criteria results and counts (verbatim), under the
    structural guarantees reported by Task 033. Consumes Task 035,
    Task 032, and Task 033 unchanged via
    ``DecisionCandidateAssessmentService`` -- it does not reach into
    evidence, observations, entities, hypothesis scores, ranking
    internals, or repositories, and duplicates no logic already owned
    by Tasks 020-035.

    Answers "what do we know about each already-approved candidate
    under the established decision criteria?" -- never "which
    candidate should be chosen?". There is no winner, best candidate,
    diagnosis, recommendation, action, probability, confidence,
    utility, weighted score, expected outcome, or treatment anywhere
    in this response. It never ranks, scores, aggregates criteria
    into a new score, breaks ties, applies a score threshold, filters,
    or removes a candidate. It never writes to the database, persists
    nothing, and modifies no candidate, evidence, or upstream
    contract.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 036's contract requires the full candidate set (via the
    # Task 031 context it consumes), so every page of candidates must
    # be retrieved -- matching the Task 032/033/034/035 pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_candidate_assessment_service.build_for_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
        DecisionCandidateAssessmentContractError,
    ) as exc:
        # Task 036: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-candidate-assessment contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-input-bundle",
    response_model=DecisionInputBundleRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_input_bundle(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 037: read-only decision-input bundle contract.

    The final audited input package before the future decision layer.
    Packages the Task 035 candidate set and the Task 036 assessment set
    into one cross-validated structure, verifying that both refer to
    the same candidate sequence, in the same order, with matching
    identity and metadata. Consumes Task 035 and Task 036 unchanged via
    ``DecisionInputBundleService`` -- it does not reach into evidence,
    observations, entities, hypothesis scores, ranking internals, or
    repositories, does not walk Tasks 031-034 itself, and duplicates no
    logic already owned by Tasks 020-036.

    Answers "are the audited candidate set and the audited candidate
    assessments a single consistent package?" -- never "which candidate
    should be chosen?". There is no winner, best candidate, diagnosis,
    recommendation, action, probability, confidence, utility, weighted
    score, expected outcome, or treatment anywhere in this response. It
    never reranks, rescores, filters, deduplicates, reorders, or
    silently repairs either upstream structure. It never writes to the
    database, persists nothing, and modifies no upstream contract.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 037's contract requires the full candidate set, so every page
    # of candidates must be retrieved -- matching the Task
    # 032/033/034/035/036 pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_input_bundle_service.build_for_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
        DecisionCandidateAssessmentContractError,
        DecisionInputBundleContractError,
    ) as exc:
        # Task 037: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-input-bundle contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-policy",
    response_model=DecisionPolicyRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_policy(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 038: read-only decision policy contract.

    The explicit policy a future decision-execution layer is permitted
    to apply to the Task 037 decision-input bundle. This endpoint
    returns the policy contract only -- it does not execute the policy,
    select a candidate, rank or rerank candidates, break ties, or
    produce any decision, diagnosis, recommendation, action, or
    probability. The policy itself is session-independent: the same
    deterministic contract is returned for any session whose Task 037
    boundary is reachable, and reaching that boundary is verified by
    delegating to ``DecisionInputBundleService`` rather than walking
    Tasks 031-036 directly.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 038's boundary requires the full candidate set (via the
    # Task 037 bundle it delegates through), so every page of
    # candidates must be retrieved -- matching the established
    # pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_policy_service.build_for_session(db, session_id, candidates)
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
        DecisionCandidateAssessmentContractError,
        DecisionInputBundleContractError,
        DecisionPolicyContractError,
    ) as exc:
        # Task 038: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-policy contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-execution",
    response_model=DecisionExecutionRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_execution(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 039: read-only decision-policy execution contract.

    The first boundary at which a candidate may be selected. Consumes
    the Task 037 decision-input bundle and the Task 038 policy through
    their established service boundaries, evaluates eligibility from
    the existing Task 036 criterion results using required criteria
    only, and returns one of a fixed set of outcome identifiers. It
    introduces no new scoring, ranking, evidence interpretation, or
    domain-specific reasoning: eligibility is required-criteria-only,
    the highest eligible rank decides, and a tie at the highest
    eligible rank returns UNRESOLVED rather than applying any implicit
    tie-breaker. There is no probability, confidence, utility,
    recommendation, diagnosis, treatment, action, or expected-outcome
    field anywhere in this response.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 039's boundary requires the full candidate set (via the
    # Task 037 bundle it delegates through), so every page of
    # candidates must be retrieved -- matching the established
    # pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_execution_service.build_for_session(db, session_id, candidates)
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
        DecisionCandidateAssessmentContractError,
        DecisionInputBundleContractError,
        DecisionPolicyContractError,
        DecisionExecutionContractError,
    ) as exc:
        # Task 039: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-execution contract violation",
        ) from exc


@router.get(
    "/{session_id}/decision-execution-consistency",
    response_model=DecisionExecutionConsistencyRead,
    status_code=status.HTTP_200_OK,
)
def get_decision_execution_consistency(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 040: read-only consistency/audit of a Task 039 execution result.

    Independently re-derives the expected eligible candidate set and
    expected outcome from the Task 037 decision-input bundle and Task
    038 policy, then compares them field by field against the Task 039
    execution result. This is an audit contract only -- it does not
    select a candidate, rerank, rescore, or alter the execution result.
    It returns six independent consistency flags plus a deterministic
    ordered list of machine-readable consistency_issues. There is no
    winner, recommendation, diagnosis, treatment, action, probability,
    confidence, utility, or expected-outcome field anywhere in the
    response.

    Normal valid execution outcomes -- including INPUT_UNAVAILABLE and
    INPUT_INCONSISTENT -- are audited successfully; the audit's own
    ``available`` flag reflects whether the audit could run, not
    whether the execution was able to select a candidate.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 040's boundary requires the full candidate set (via the
    # Task 037 bundle it delegates through), so every page of
    # candidates must be retrieved -- matching the established
    # pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return decision_execution_consistency_service.build_for_session(
            db, session_id, candidates
        )
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
        DecisionCandidateAssessmentContractError,
        DecisionInputBundleContractError,
        DecisionPolicyContractError,
        DecisionExecutionContractError,
        DecisionExecutionConsistencyContractError,
    ) as exc:
        # Task 040: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal decision-execution-consistency contract violation",
        ) from exc


@router.get(
    "/{session_id}/reasoning-pipeline",
    response_model=ReasoningPipelineRead,
    status_code=status.HTTP_200_OK,
)
def get_reasoning_pipeline(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 041: read-only end-to-end reasoning pipeline composition.

    Composes the established decision-pipeline stages (Tasks 031-040)
    into one coherent, inspectable end-to-end run. Reuses only the
    already-approved service boundaries via
    ``ReasoningPipelineService`` -- it introduces no new reasoning, no
    re-selection, no policy override, and no mutation of any upstream
    result. ``final_execution`` and ``final_execution_consistency`` are
    the exact canonical outputs of Tasks 039 and 040.

    Valid downstream outcomes such as INPUT_UNAVAILABLE and
    INPUT_INCONSISTENT remain visible through ``final_execution`` and
    do not make the pipeline composition itself unavailable. There is
    no winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    anywhere in this response.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional composed view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Task 041's composition requires the full candidate set, so every
    # page of candidates must be retrieved -- matching the established
    # pagination fix.
    candidates: list[CandidateHypothesis] = []
    page_offset = 0
    page_size = 100
    while True:
        page = candidate_generation_service.list_by_session(
            db, session_id, offset=page_offset, limit=page_size
        )
        candidates.extend(page)
        if len(page) < page_size:
            break
        page_offset += page_size

    try:
        return reasoning_pipeline_service.build_for_session(db, session_id, candidates)
    except (
        HypothesisScoreContractError,
        DifferentialRankingContractError,
        DifferentialRankingSummaryContractError,
        DifferentialRankingConsistencyContractError,
        DifferentialDecisionReadinessContractError,
        DecisionContextContractError,
        DecisionCandidateEvaluationContractError,
        DecisionEvaluationConsistencyContractError,
        DecisionInputEligibilityContractError,
        DecisionCandidateSetContractError,
        DecisionCandidateAssessmentContractError,
        DecisionInputBundleContractError,
        DecisionPolicyContractError,
        DecisionExecutionContractError,
        DecisionExecutionConsistencyContractError,
        ReasoningPipelineContractError,
    ) as exc:
        # Task 041: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal reasoning-pipeline contract violation",
        ) from exc


@router.get(
    "/{session_id}/reasoning-run",
    response_model=ReasoningRunRead,
    status_code=status.HTTP_200_OK,
)
def get_reasoning_run(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 042: read-only full ROP reasoning-run composition.

    Bridges the session's own upstream state (observations, entities,
    missing information, template context, existing candidates) into
    the approved Task 041 reasoning pipeline, producing one coherent
    end-to-end ROP run representation. Read-only: candidate generation
    is never re-invoked from this endpoint, so a GET does not mutate
    session state. ``reasoning_pipeline`` is the exact canonical output
    of Task 041 -- not transformed or renamed. Valid downstream
    outcomes such as INPUT_UNAVAILABLE and INPUT_INCONSISTENT remain
    visible through ``reasoning_pipeline.final_execution`` and do not
    make the run composition itself unavailable.

    There is no winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    anywhere in this response.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional composed view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_run_service.build_for_session(db, session_id)
    except ReasoningRunContractError as exc:
        # Task 042: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal reasoning-run contract violation",
        ) from exc


@router.get(
    "/{session_id}/reasoning-run-consistency",
    response_model=ReasoningRunConsistencyRead,
    status_code=status.HTTP_200_OK,
)
def get_reasoning_run_consistency(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 043: read-only consistency/audit of a Task 042 reasoning run.

    Independently re-derives the expected run representation from the
    session's actual state, then compares it against the Task 042
    composition. Reports twelve consistency flags plus a deterministic
    ordered list of machine-readable consistency_issues. This is an
    audit contract only -- it does not select, rank, score, diagnose,
    recommend, or alter any upstream result. Valid but incomplete
    states (empty sessions, missing candidates, valid downstream
    outcomes such as INPUT_UNAVAILABLE) are audited as available with
    the appropriate issue list, never as exceptions.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional derived view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_run_consistency_service.build_for_session(db, session_id)
    except ReasoningRunConsistencyContractError as exc:
        # Task 043: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal reasoning-run-consistency contract violation",
        ) from exc


@router.post(
    "/{session_id}/reasoning-run/execute",
    response_model=ReasoningRunExecutionRead,
    status_code=status.HTTP_200_OK,
)
def execute_reasoning_run(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 044: write-side reasoning-run execution orchestrator.

    Runs the established deterministic reasoning workflow end-to-end
    by delegating to the existing services in the correct order:
    session verification, observation extraction, missing-information
    detection, template matching, candidate generation, evidence
    evaluation, Task 042 run composition, and Task 043 run
    consistency audit. This is the first write-side layer; it uses
    the existing persistence boundaries and never invents reasoning
    of its own.

    ``reasoning_run`` and ``reasoning_run_consistency`` are the exact
    canonical outputs of Tasks 042 and 043. A failed stage raises an
    internal contract error (500) and no further stages run; the
    exception is never converted into a fabricated successful result.

    The existing GET endpoints
    (``/sessions/{id}/reasoning-run`` and
    ``/sessions/{id}/reasoning-run-consistency``) remain read-only and
    are not affected by this endpoint.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_run_execution_service.execute_for_session(db, session_id)
    except ReasoningRunExecutionContractError as exc:
        # Task 044: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal reasoning-run-execution contract violation",
        ) from exc


@router.post(
    "/{session_id}/reasoning-run/execute-audited",
    response_model=ReasoningRunExecutionBundleRead,
    status_code=status.HTTP_200_OK,
)
def execute_reasoning_run_audited(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 046: execution + independent audit, in one bundle.

    Delegates execution to Task 044 and audits the exact returned
    execution result through Task 045, then assembles and validates
    one bundle. This is a composition contract only: it does not
    execute the reasoning workflow itself, does not audit itself, and
    does not add persistence. ``execution`` and ``execution_consistency``
    are the exact canonical outputs of their owners.

    Note that ``execution.execution_consistent`` (Task 044) and
    ``execution_consistency.execution_consistent`` (Task 045) have
    different meanings and are intentionally NOT required to be equal.
    Task 044's value is whether the underlying reasoning run was
    consistent; Task 045's value is whether the Task 044 execution
    contract itself was internally consistent. A valid FAILED
    execution, or a valid execution whose underlying reasoning run is
    legitimately inconsistent, is therefore still a valid bundle:
    ``bundle_consistent`` simply mirrors the Task 045 audit result.
    Only a genuine structural contract failure (invalid nested
    contract, mismatched session/source identity, or an unavailable
    audit) raises an internal error.

    Does not modify the behavior or fields of any existing endpoint --
    this is an additional composed view over the same underlying
    pipeline.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_run_execution_bundle_service.build_for_session(db, session_id)
    except ReasoningRunExecutionBundleContractError as exc:
        # Task 046: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal reasoning-run-execution-bundle contract violation",
        ) from exc


@router.post(
    "/{session_id}/reasoning-run/execute-fully-audited",
    response_model=ReasoningRunExecutionAuditPackageRead,
    status_code=status.HTTP_200_OK,
)
def execute_reasoning_run_fully_audited(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 049: expose the Task 048 fully audited execution package.

    Thin API boundary only. Delegates exclusively to Task 048's
    ``build_for_session`` and returns its result unchanged -- it does
    not invoke Tasks 044/045/046/047 directly, does not reconstruct
    the package, and does not alter any nested output.

    A valid FAILED Task 044 execution still produces a valid 200
    response: Task 048 faithfully packages the execution + audit and
    its own ``package_consistent`` reflects whether the Task 047 audit
    found the Task 046 bundle contract internally consistent.

    Does not modify the behavior or fields of any existing endpoint.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_run_execution_audit_package_service.build_for_session(
            db, session_id
        )
    except ReasoningRunExecutionAuditPackageContractError as exc:
        # Task 049: an internal contract violation, never medical or
        # client-input error -- never leak the raw exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Internal reasoning-run-execution-audit-package " "contract violation"
            ),
        ) from exc


@router.get(
    "/{session_id}/reasoning-handoff",
    response_model=ReasoningHandoffRead,
    status_code=status.HTTP_200_OK,
)
def get_reasoning_handoff(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 059: read-only validated reasoning handoff.

    Returns the Task 057 handoff for the requested session: the exact
    Task 055 canonical reasoning context, the exact Task 056 audit
    (including Task 058's ``audited_context_fingerprint``), and the
    Task 057 provenance-checked package that binds them.

    Delegates to ``ReasoningHandoffApiService``, which builds the
    Task 055 context exactly once and passes that exact object through
    Tasks 056 and 057. This endpoint does not itself build context,
    audit context, or enforce contract rules.

    Strictly read-only: no candidates are generated or regenerated, no
    observations or entities are written, no session state is mutated,
    no transaction is committed. Repeated GETs on an unchanged session
    return identical results.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_handoff_api_service.build_for_session(db, session_id)
    except (
        ReasoningContextContractError,
        ReasoningContextConsistencyContractError,
        ReasoningHandoffContractError,
    ) as exc:
        # Tasks 055/056/057: an internal contract violation, never
        # medical or client-input error -- never leak the raw
        # exception detail.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal reasoning-handoff contract violation",
        ) from exc


@router.get(
    "/{session_id}/reasoning-handoff/fully-audited",
    response_model=ReasoningHandoffApiAuditBundleRead,
    status_code=status.HTTP_200_OK,
)
def get_reasoning_handoff_fully_audited(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Task 065: fully audited reasoning handoff.

    Returns the Task 063 audit bundle for the requested session: the
    exact Task 061 audited API package, the exact Task 062 consistency
    audit of that package, the session identity, and the fixed Task 063
    bundle source. The bundle's ``bundle_consistent`` is derived
    deterministically from Task 062's ``package_consistent``.

    Delegates to ``ReasoningHandoffFullyAuditedApiService``, which calls
    the Task 059 API orchestration exactly once and derives Tasks 060,
    061, 062, and 063 from that exact response body. This endpoint does
    not itself build context, audit context or responses, package, or
    bundle, and makes no internal HTTP call.

    A valid result whose underlying handoff legitimately reports
    ``handoff_consistent = False`` still produces a valid 200 response:
    Task 060/061/062/063 faithfully represent it, so the bundle reports
    ``bundle_consistent = True``.

    Strictly read-only: no candidates are generated or regenerated, no
    observations or entities are written, no session state is mutated,
    no transaction is committed. Repeated GETs on an unchanged session
    return identical results.
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    try:
        return reasoning_handoff_fully_audited_api_service.build_for_session(
            db, session_id
        )
    except (
        ReasoningContextContractError,
        ReasoningContextConsistencyContractError,
        ReasoningHandoffContractError,
        ReasoningHandoffApiConsistencyContractError,
        ReasoningHandoffApiAuditPackageContractError,
        ReasoningHandoffApiAuditPackageConsistencyContractError,
        ReasoningHandoffApiAuditBundleContractError,
    ) as exc:
        # Tasks 055-063: an internal contract violation, never medical
        # or client-input error -- never leak the raw exception detail.
        # An unavailable or malformed upstream result is never silently
        # downgraded into a successful audited response.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=("Internal reasoning-handoff fully-audited contract violation"),
        ) from exc

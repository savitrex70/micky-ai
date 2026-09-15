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
    EntityService,
    EvidenceAggregationService,
    EvidenceEvaluationService,
    EvidenceService,
    HypothesisScoringService,
    HypothesisService,
    MissingInformationService,
    ObservationExtractionService,
    ObservationService,
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
    """
    if session_service.get(db, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    candidates = candidate_generation_service.list_by_session(
        db, session_id, offset=0, limit=100
    )

    return hypothesis_scoring_service.score_session(db, session_id, candidates)

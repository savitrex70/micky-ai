# Task 033 — wiring instructions

Two new files are included, already placed at their correct paths:

- src/rop/schemas/decision_evaluation_consistency.py
- src/rop/services/decision_evaluation_consistency.py

Three existing files need small additions. Do NOT overwrite them —
just add the lines below in the right place.

---

## 1. src/rop/schemas/__init__.py

Add an import line next to the existing DecisionCandidateEvaluationRead
import, e.g.:

    from rop.schemas.decision_evaluation_consistency import (
        DecisionEvaluationConsistencyRead,
    )

And add "DecisionEvaluationConsistencyRead" to whatever __all__ list
(or equivalent re-export) already includes DecisionCandidateEvaluationRead.

---

## 2. src/rop/services/__init__.py

Add an import line next to the existing DecisionCandidateEvaluationService
/ DecisionCandidateEvaluationContractError imports, e.g.:

    from rop.services.decision_evaluation_consistency import (
        DecisionEvaluationConsistencyContractError,
        DecisionEvaluationConsistencyService,
    )

And add both names to __all__ (or equivalent) alongside the Task 032 names.

---

## 3. src/rop/api/sessions.py

### a) Imports

In the `from rop.schemas import (...)` block, add:

    DecisionEvaluationConsistencyRead,

(keep alphabetical order with the existing entries, right after
DecisionContextRead or wherever it sorts).

In the `from rop.services import (...)` block, add:

    DecisionEvaluationConsistencyContractError,
    DecisionEvaluationConsistencyService,

### b) Service instantiation

Right after this existing line near the top of the file:

    decision_candidate_evaluation_service = DecisionCandidateEvaluationService(
        decision_context_service
    )

add:

    decision_evaluation_consistency_service = DecisionEvaluationConsistencyService(
        decision_candidate_evaluation_service
    )

### c) New endpoint

Add this at the very end of the file, after the
`get_decision_candidate_evaluations` endpoint:

    @router.get(
        "/{session_id}/decision-evaluation-consistency",
        response_model=DecisionEvaluationConsistencyRead,
        status_code=status.HTTP_200_OK,
    )
    def get_decision_evaluation_consistency(
        session_id: UUID,
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """Task 033: read-only structural consistency/coverage contract.

        Consumes only the Task 032 decision-candidate evaluations via
        ``DecisionEvaluationConsistencyService`` -- it does not reach
        into evidence, scoring, ranking, readiness, observations,
        entities, hypotheses, or database evidence records, and
        duplicates no logic already owned by Tasks 020-032.

        This answers "are the candidate evaluations complete,
        structurally consistent, and fully comparable across the
        current decision context?" -- never "which candidate should be
        chosen?" There is no winner, score, probability, confidence,
        or recommendation anywhere in this response. It never writes
        to the database, persists nothing, and modifies no candidate,
        evidence, or upstream contract.

        Does not modify the behavior or fields of the existing
        ``/decision-candidate-evaluations`` or ``/decision-context``
        endpoints -- this is an additional derived view over the same
        underlying pipeline.
        """
        if session_service.get(db, session_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
            )

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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal decision-evaluation-consistency contract violation",
            ) from exc

---

## Before running tests / pushing

I have NOT written `tests/test_decision_evaluation_consistency.py` yet --
I don't have your `conftest.py` / existing test fixtures (DB setup,
TestClient, however you build a session + candidates + evidence in a
test). Paste those and I'll write the test file to match, then you
can run the full suite and push in one shot like Task 032.

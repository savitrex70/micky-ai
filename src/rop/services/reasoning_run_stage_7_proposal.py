"""Task 158: Stage 7 provider response boundary service.

Validates one raw Stage 7 provider response -- handed over by the Task
157 dispatch -- into the approved public Task 057 proposal surface.
This service is the only reader of the raw ``provider_response`` the
dispatch result carries.

The pipeline order is the canonical Task 057 order, unchanged:

  1. provider metadata validation (Task 107),
  2. raw text type validation,
  3. strict JSON parsing,
  4. schema validation (parse-only Task 057 wrapper),
  5. candidate / evidence / missing-information reference validation
     (Task 105),
  6. public Task 057 proposal construction.

No heuristic repair, no regex correction, no retry loop, and no
model-output rewrite exist here. Failure statuses are the canonical
Task 057 outcome values verbatim. Raw provider text, the raw provider
response object, and any provider-specific surface never appear in the
returned projection: the projection carries the approved public Task
057 proposal only when the complete pipeline validated it.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from rop.schemas.llm_reasoning import (
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
    _RawLLMReasoningProposal,
)
from rop.schemas.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalRead,
)
from rop.services.llm_boundary_contract import (
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
)
from rop.services.llm_output_validation import validate_raw_proposal
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning import LLM_REASONING_TASK_057

REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158 = (
    "REASONING_RUN_STAGE_7_PROPOSAL_TASK_158"
)


class ReasoningRunStage7ProposalContractError(Exception):
    """Task 158: the proposal verdict cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ProposalService:
    """Deterministic validation of one Stage 7 provider response.

    Pure orchestration over the canonical Task 105 / 107 / 120 helpers.
    The service accepts no database session, performs no persistence,
    and never invokes any provider: validating an already-produced
    response must not contact a model.
    """

    def build(
        self,
        *,
        dispatch_result: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate the raw response carried by one dispatch result.

        Material gates run first: anything other than a ``DISPATCHED``
        result with a readable fingerprint and a matching canonical
        context is ``UNAVAILABLE`` -- except that the canonical Task
        057 model-failure outcomes observed at dispatch time pass
        through verbatim. Only a dispatched raw response is validated,
        strictly in the canonical Task 057 order; every failure maps to
        the canonical Task 057 outcome value, never to a new taxonomy.
        """
        result: dict[str, Any] = {
            "proposal_status": "UNAVAILABLE",
            "available": False,
            "session_id": "",
            "context_fingerprint": None,
            "provider": None,
            "model": None,
            "proposal": None,
            "proposal_source": REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158,
        }

        if not isinstance(dispatch_result, Mapping):
            return self._project(result)

        raw_session = dispatch_result.get("session_id")
        if isinstance(raw_session, str):
            result["session_id"] = raw_session

        if dispatch_result.get("dispatch_status") != "DISPATCHED":
            outcome = dispatch_result.get("outcome")
            if outcome in (
                OUTCOME_MODEL_UNAVAILABLE,
                OUTCOME_MODEL_OUTPUT_INVALID,
                OUTCOME_MODEL_OUTPUT_INCONSISTENT,
            ):
                result["proposal_status"] = outcome
            return self._project(result)

        provider_response = dispatch_result.get("provider_response")
        if provider_response is None:
            return self._project(result)

        fingerprint = dispatch_result.get("request_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            return self._project(result)

        if not isinstance(context, Mapping):
            return self._project(result)
        try:
            snapshot: dict[str, Any] = {
                key: copy.deepcopy(value) for key, value in dict(context).items()
            }
        except Exception:
            return self._project(result)

        session_id = snapshot.get("session_id")
        if not isinstance(session_id, UUID):
            return self._project(result)
        if str(session_id) != result["session_id"]:
            return self._project(result)
        if snapshot.get("available") is not True:
            return self._project(result)

        # Canonical Task 057 validation pipeline, order unchanged.

        metadata, metadata_issues = ProviderFailureBoundary.extract_provider_metadata(
            provider_response, fingerprint
        )
        if metadata_issues:
            result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INVALID
            return self._project(result)

        raw_text = metadata["text"]
        if not isinstance(raw_text, str):
            result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INVALID
            return self._project(result)

        try:
            raw_dict = json.loads(raw_text)
        except ValueError:
            result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INVALID
            return self._project(result)

        output_issues = validate_raw_proposal(raw_dict, snapshot)
        if output_issues:
            if any(
                issue.startswith("Top-level schema validation failed")
                for issue in output_issues
            ):
                result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INVALID
                return self._project(result)
            result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INCONSISTENT
            return self._project(result)

        try:
            raw = _RawLLMReasoningProposal.model_validate(raw_dict)
        except ValidationError:
            result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INVALID
            return self._project(result)

        # Public construction is itself a boundary: a value that passed
        # raw parsing but violates the strict public contract becomes
        # MODEL_OUTPUT_INVALID, never a raw Pydantic or TypeError escape.
        try:
            candidate_assessments = [
                ReasoningCandidateAssessmentRead(
                    candidate_id=a.candidate_id,
                    assessment=a.assessment,
                    supporting_evidence_ids=list(a.supporting_evidence_ids),
                    contradicting_evidence_ids=list(a.contradicting_evidence_ids),
                    unresolved_information_ids=list(a.unresolved_information_ids),
                    explanation=a.explanation,
                    uncertainty_flags=list(a.uncertainty_flags),
                )
                for a in raw.candidate_assessments
            ]
            result_model = LLMReasoningProposalRead(
                session_id=session_id,
                context_fingerprint=fingerprint,
                provider=metadata["provider"],
                model=metadata["model"],
                candidate_assessments=candidate_assessments,
                available=True,
                proposal_consistent=True,
                llm_reasoning_source=LLM_REASONING_TASK_057,
            )
        except Exception:
            result["proposal_status"] = OUTCOME_MODEL_OUTPUT_INVALID
            return self._project(result)

        result["proposal_status"] = "VALIDATED"
        result["available"] = True
        result["context_fingerprint"] = fingerprint
        result["provider"] = metadata["provider"]
        result["model"] = metadata["model"]
        result["proposal"] = result_model.model_dump(mode="json")
        return self._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = ReasoningRunStage7ProposalRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7ProposalContractError(
                "PROPOSAL_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

"""Task 057: LLM reasoning boundary service.

Deterministic boundary around an LLM reasoning call. The service:

  1. obtains the Task 055 canonical context exactly once,
  2. audits it with Task 056 exactly once,
  3. verifies the audit provenance and availability,
  4. computes a canonical fingerprint of the exact context the model
     will see,
  5. constructs a minimal request containing only the allowed fields,
  6. calls an injected provider,
  7. strictly parses and schema-validates the provider output,
  8. validates every candidate / evidence / missing-information
     reference against the canonical context,
  9. returns a structured result.

The model is never given decision authority. It cannot select, rank,
recommend, mutate state, call tools, or bypass deterministic
validation. There is no persistence and no HTTP endpoint here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.candidate_hypothesis import CandidateHypothesisRead
from rop.schemas.entity import EntityRead
from rop.schemas.llm_reasoning import (
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
    _RawLLMReasoningProposal,
)
from rop.schemas.missing_information import MissingInformationRead
from rop.schemas.observation import ObservationRead
from rop.schemas.template_match import TemplateMatchRead
from rop.services.llm_reasoning_provider import (
    LLMReasoningProvider,
    LLMReasoningProviderError,
    LLMReasoningRequest,
)
from rop.services.reasoning_context import (
    ReasoningContextContractError,
    ReasoningContextService,
)
from rop.services.reasoning_context_consistency import (
    ReasoningContextConsistencyService,
)
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
)

LLM_REASONING_TASK_057 = "LLM_REASONING_TASK_057"
"""Fixed structural-contract identifier for Task 057 results."""

# Context lists and the Read schemas that serialize each element for
# the model. Reused, not duplicated.
_ELEMENT_SERIALIZERS = (
    ("observations", ObservationRead),
    ("entities", EntityRead),
    ("missing_information", MissingInformationRead),
    ("template_context", TemplateMatchRead),
    ("candidate_state", CandidateHypothesisRead),
)

# Fields the model is allowed to receive. Nothing else is exposed.
_ALLOWED_PAYLOAD_FIELDS = (
    "session_id",
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
    "reasoning_pipeline",
)

_OUTCOME_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
_OUTCOME_INPUT_INCONSISTENT = "INPUT_INCONSISTENT"
_OUTCOME_MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
_OUTCOME_MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
_OUTCOME_MODEL_OUTPUT_INCONSISTENT = "MODEL_OUTPUT_INCONSISTENT"


class LLMReasoningContractError(Exception):
    """Task 057: an unrecoverable failure at the LLM reasoning boundary.

    Raised for INPUT_INCONSISTENT (the supplied Task 055 context
    exists but does not audit clean), MODEL_UNAVAILABLE (the provider
    could not produce a response), MODEL_OUTPUT_INVALID (the provider
    returned non-JSON or a schema-invalid shape), and
    MODEL_OUTPUT_INCONSISTENT (the provider returned a schema-valid
    proposal whose references do not exist in the supplied context).

    Never raised for INPUT_UNAVAILABLE -- that soft state is returned
    as a valid result with ``available=False``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class LLMReasoningService:
    """Task 057: deterministic LLM reasoning boundary.

    Pure orchestration. Every decision about what to send, what to
    accept, and what to reject is deterministic; only the model's
    candidate assessments come from outside the deterministic system.
    The service never mutates the supplied context, never touches the
    database, and never exposes raw model text.
    """

    def __init__(
        self,
        reasoning_context_service: ReasoningContextService | None = None,
        reasoning_context_consistency_service: (
            ReasoningContextConsistencyService | None
        ) = None,
        provider: LLMReasoningProvider | None = None,
    ) -> None:
        self.reasoning_context_service = (
            reasoning_context_service or ReasoningContextService()
        )
        self.reasoning_context_consistency_service = (
            reasoning_context_consistency_service
            or ReasoningContextConsistencyService()
        )
        self.provider = provider

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Obtain Task 055 context exactly once, then delegate to build."""
        try:
            context = self.reasoning_context_service.build_for_session(
                db, session_id
            )
        except ReasoningContextContractError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_UNAVAILABLE,
                "Task 055 context could not be produced: " + str(exc),
            ) from exc
        return self.build(context=context)

    def build(
        self,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the boundary on an already-built Task 055 context."""
        if not isinstance(context, Mapping):
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_UNAVAILABLE,
                "context is required and must be a mapping",
            )

        session_id = context.get("session_id")
        if not isinstance(session_id, UUID):
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_UNAVAILABLE,
                "context has no valid session_id",
            )

        # Soft unavailable: Task 055 itself declined to produce a
        # usable context. No model call, no exception -- a fully typed
        # result with available=False.
        if context.get("available") is not True:
            return self._soft_unavailable_result(context, session_id)

        # Task 056 audit of the exact supplied context.
        try:
            audit = self.reasoning_context_consistency_service.build(
                context=context
            )
        except Exception as exc:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "Task 056 audit could not be produced: " + str(exc),
            ) from exc

        if audit.get("available") is not True:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "Task 056 audit reports the context is unavailable",
            )
        if audit.get("context_consistent") is not True:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "Task 056 audit reports the context is not consistent",
            )
        if audit.get("audit_provenance_consistent") is not True:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "Task 056 audit reports inconsistent provenance",
            )

        # Serialize the exact context the model will see, and compute
        # the fingerprint of that serialization.
        serialized = self._serialize_context(context)
        fingerprint = self._fingerprint(serialized)

        request = LLMReasoningRequest(
            payload=serialized, context_fingerprint=fingerprint
        )

        provider = self.provider
        if provider is None:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_UNAVAILABLE,
                "no LLM reasoning provider was configured",
            )

        try:
            provider_response = provider.generate_reasoning(request)
        except LLMReasoningProviderError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_UNAVAILABLE, str(exc)
            ) from exc
        except Exception as exc:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_UNAVAILABLE,
                "provider raised unexpectedly: " + str(exc),
            ) from exc

        # Strict output parsing: no regex, no heuristic repair.
        try:
            raw = _RawLLMReasoningProposal.model_validate_json(
                provider_response.text
            )
        except ValidationError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INVALID,
                "provider output failed schema validation: " + str(exc),
            ) from exc
        except ValueError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INVALID,
                "provider output was not valid JSON: " + str(exc),
            ) from exc

        # Reference integrity against the canonical context.
        self._validate_references(raw.candidate_assessments, context)

        # Assemble the public result.
        candidate_assessments = [
            ReasoningCandidateAssessmentRead(
                candidate_id=a.candidate_id,
                assessment=a.assessment,
                supporting_evidence_ids=list(a.supporting_evidence_ids),
                contradicting_evidence_ids=list(
                    a.contradicting_evidence_ids
                ),
                unresolved_information_ids=list(
                    a.unresolved_information_ids
                ),
                explanation=a.explanation,
                uncertainty_flags=list(a.uncertainty_flags),
            )
            for a in raw.candidate_assessments
        ]

        result_model = LLMReasoningProposalRead(
            session_id=session_id,
            context_fingerprint=fingerprint,
            provider=provider_response.provider,
            model=provider_response.model,
            candidate_assessments=candidate_assessments,
            available=True,
            proposal_consistent=True,
            llm_reasoning_source=LLM_REASONING_TASK_057,
        )
        return result_model.model_dump(mode="json")

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _soft_unavailable_result(
        self,
        context: Mapping[str, Any],
        session_id: UUID,
    ) -> dict[str, Any]:
        try:
            serialized = self._serialize_context(context)
            fingerprint = self._fingerprint(serialized)
        except Exception:
            fingerprint = ""
        provider_name = ""
        model_name = ""
        if self.provider is not None:
            provider_name = getattr(self.provider, "provider_name", "")
            model_name = getattr(self.provider, "model_name", "")
        result_model = LLMReasoningProposalRead(
            session_id=session_id,
            context_fingerprint=fingerprint,
            provider=provider_name,
            model=model_name,
            candidate_assessments=[],
            available=False,
            proposal_consistent=False,
            llm_reasoning_source=LLM_REASONING_TASK_057,
        )
        return result_model.model_dump(mode="json")

    @staticmethod
    def _serialize_context(
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Project the context into a JSON-safe, model-safe payload.

        Only the seven allowed fields are emitted. Each list element is
        normalized through its own Read schema; anything else in the
        context (ORM internals, private attributes) is never exposed.
        """
        payload: dict[str, Any] = {
            "session_id": str(context["session_id"]),
            "observations": [],
            "entities": [],
            "missing_information": [],
            "template_context": [],
            "candidate_state": [],
            "reasoning_pipeline": dict(context["reasoning_pipeline"]),
        }
        for field, schema in _ELEMENT_SERIALIZERS:
            for item in context[field]:
                validated = schema.model_validate(item)
                payload[field].append(
                    validated.model_dump(mode="json")
                )
        return LLMReasoningService._to_json_safe(payload)

    @staticmethod
    def _to_json_safe(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(k): LLMReasoningService._to_json_safe(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [
                LLMReasoningService._to_json_safe(v) for v in value
            ]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _fingerprint(serialized: Mapping[str, Any]) -> str:
        canonical = ReasoningRunConsistencyService._canonicalize(
            serialized
        )
        payload = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_references(
        assessments: list[Any],
        context: Mapping[str, Any],
    ) -> None:
        candidate_ids = {c.id for c in context["candidate_state"]}
        observation_ids = {o.id for o in context["observations"]}
        entity_ids = {e.id for e in context["entities"]}
        evidence_ids = observation_ids | entity_ids
        missing_info_ids = {m.id for m in context["missing_information"]}

        seen_candidates: set[Any] = set()
        for a in assessments:
            if a.candidate_id not in candidate_ids:
                raise LLMReasoningContractError(
                    _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                    "candidate_id is not in the supplied context: "
                    + str(a.candidate_id),
                )
            if a.candidate_id in seen_candidates:
                raise LLMReasoningContractError(
                    _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                    "duplicate candidate_assessment for: "
                    + str(a.candidate_id),
                )
            seen_candidates.add(a.candidate_id)

            for eid in a.supporting_evidence_ids:
                if eid not in evidence_ids:
                    raise LLMReasoningContractError(
                        _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                        "supporting_evidence_id is not in the supplied "
                        "context: " + str(eid),
                    )
            for eid in a.contradicting_evidence_ids:
                if eid not in evidence_ids:
                    raise LLMReasoningContractError(
                        _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                        "contradicting_evidence_id is not in the "
                        "supplied context: " + str(eid),
                    )
            for mid in a.unresolved_information_ids:
                if mid not in missing_info_ids:
                    raise LLMReasoningContractError(
                        _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                        "unresolved_information_id is not in the "
                        "supplied context: " + str(mid),
                    )

        if seen_candidates != candidate_ids:
            missing = candidate_ids - seen_candidates
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                "proposal does not assess every supplied candidate; "
                "missing: " + ", ".join(str(x) for x in sorted(missing)),
            )

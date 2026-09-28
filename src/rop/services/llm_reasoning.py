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

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.llm_reasoning import (
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
    _RawLLMReasoningProposal,
)
from rop.services.llm_boundary_contract import (
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_INPUT_UNAVAILABLE,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
)
from rop.services.llm_output_validation import validate_raw_proposal
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning_provider import (
    LLMReasoningProvider,
    LLMReasoningProviderError,
    LLMReasoningRequest,
)
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
    to_json_safe,
    validate_payload,
)
from rop.services.reasoning_context import (
    ReasoningContextContractError,
    ReasoningContextService,
)
from rop.services.reasoning_context_consistency import (
    ReasoningContextConsistencyService,
)

LLM_REASONING_TASK_057 = "LLM_REASONING_TASK_057"
"""Fixed structural-contract identifier for Task 057 results."""

# Serialization constants and helpers live in Task 104's hardened
# boundary (rop.services.llm_request_serialization) and are reused
# here without duplication.

_OUTCOME_INPUT_UNAVAILABLE = OUTCOME_INPUT_UNAVAILABLE
_OUTCOME_INPUT_INCONSISTENT = OUTCOME_INPUT_INCONSISTENT
_OUTCOME_MODEL_UNAVAILABLE = OUTCOME_MODEL_UNAVAILABLE
_OUTCOME_MODEL_OUTPUT_INVALID = OUTCOME_MODEL_OUTPUT_INVALID
_OUTCOME_MODEL_OUTPUT_INCONSISTENT = OUTCOME_MODEL_OUTPUT_INCONSISTENT


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
            context = self.reasoning_context_service.build_for_session(db, session_id)
        except ReasoningContextContractError as exc:
            # Distinguish "the session/input does not exist" from
            # "the upstream state is malformed or inconsistent" so a
            # broken session state is not silently classified as
            # merely absent.
            if exc.invariant == "SESSION_NOT_FOUND":
                outcome = _OUTCOME_INPUT_UNAVAILABLE
            else:
                outcome = _OUTCOME_INPUT_INCONSISTENT
            raise LLMReasoningContractError(
                outcome,
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
            audit = self.reasoning_context_consistency_service.build(context=context)
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

        # Task 104 enforcement: the provider-bound payload must contain
        # exactly the allowed fields. serialize_context only emits those,
        # so a non-empty result here means the boundary was tampered
        # with -- fail before any provider invocation.
        unexpected_fields = validate_payload(serialized)
        if unexpected_fields:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "serialized payload violates the Task 104 allowed-field "
                "contract: " + ", ".join(sorted(unexpected_fields)),
            )

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
            # Task 107 is authoritative for ALL provider-call failures:
            # no second competing classification path exists.
            outcome = ProviderFailureBoundary.normalize_failure(exc)
            raise LLMReasoningContractError(outcome, str(exc)) from exc
        except Exception as exc:
            # Task 107 classifies unexpected provider failures; the
            # boundary never lets an arbitrary exception bypass the
            # contract outcomes.
            outcome = ProviderFailureBoundary.normalize_failure(exc)
            raise LLMReasoningContractError(
                outcome,
                "provider raised unexpectedly: " + str(exc),
            ) from exc

        # Task 107 provider-metadata gate: provider/model/text are read
        # once, defensively, and the validated values are the ones used
        # below. The untrusted response object is never accessed again
        # after this point, so a property that raises or changes value
        # on a second read cannot escape as a raw exception.
        metadata, metadata_issues = ProviderFailureBoundary.extract_provider_metadata(
            provider_response, fingerprint
        )
        if metadata_issues:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INVALID,
                "provider metadata failed validation: " + "; ".join(metadata_issues),
            )

        # Strict output parsing: no regex, no heuristic repair. The
        # validated text is guaranteed to be a string by Task 107; the
        # check is kept so a non-string can never reach json.loads.
        raw_text = metadata["text"]
        if not isinstance(raw_text, str):
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INVALID,
                "provider response text is not a string",
            )
        try:
            raw_dict = json.loads(raw_text)
        except ValueError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INVALID,
                "provider output was not valid JSON: " + str(exc),
            ) from exc

        # Task 105 is the authoritative output-validation boundary:
        # every reference, ordering, duplication, and content rule is
        # enforced through it. Schema-shape failures stay INVALID;
        # reference/content failures are INCONSISTENT.
        output_issues = validate_raw_proposal(raw_dict, context)
        if output_issues:
            if any(
                issue.startswith("Top-level schema validation failed")
                for issue in output_issues
            ):
                raise LLMReasoningContractError(
                    _OUTCOME_MODEL_OUTPUT_INVALID,
                    "provider output failed schema validation: "
                    + "; ".join(output_issues),
                )
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INCONSISTENT,
                "provider output failed reference validation: "
                + "; ".join(output_issues),
            )

        try:
            raw = _RawLLMReasoningProposal.model_validate(raw_dict)
        except ValidationError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_MODEL_OUTPUT_INVALID,
                "provider output failed schema validation: " + str(exc),
            ) from exc

        # Assemble the public result.
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
            # Defensive for the same reason as the response metadata: a
            # provider may expose these as properties that raise or
            # return a non-string, and neither may leak out of the
            # soft-unavailable path.
            raw_provider = ProviderFailureBoundary._safe_read(
                self.provider, "provider_name"
            )
            if isinstance(raw_provider, str) and raw_provider.strip():
                provider_name = raw_provider
            raw_model = ProviderFailureBoundary._safe_read(self.provider, "model_name")
            if isinstance(raw_model, str) and raw_model.strip():
                model_name = raw_model
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

        Delegates to Task 104's canonical boundary. Only the allowed
        fields are emitted; anything else in the context (ORM
        internals, private attributes) is never exposed.
        """
        try:
            return serialize_context(context)
        except TypeError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "unsupported value in context during serialization: " + str(exc),
            ) from exc

    @staticmethod
    def _to_json_safe(value: Any) -> Any:
        try:
            return to_json_safe(value)
        except TypeError as exc:
            raise LLMReasoningContractError(
                _OUTCOME_INPUT_INCONSISTENT,
                "unsupported value in context during serialization: " + str(exc),
            ) from exc

    @staticmethod
    def _fingerprint(serialized: Mapping[str, Any]) -> str:
        return compute_fingerprint(serialized)

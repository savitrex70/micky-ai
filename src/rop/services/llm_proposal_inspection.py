"""Task 109: read-only inspection boundary for the validated LLM proposal.

Pure, deterministic helpers over an already-validated Task 057 LLM
reasoning proposal. No database access, no HTTP, no provider calls,
no mutation of the supplied mapping.

The single entry point, ``LLMProposalInspectionService.build``, takes
a Task 057 proposal mapping (``LLMReasoningProposalRead`` in
``mode="json"`` form), reuses Task 106 ``normalize_proposal`` plus
``NormalizedLLMReasoningProposalRead`` validation, then returns a
fresh inspection dict with exactly the documented keys.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from rop.schemas.llm_proposal_normalization import (
    NormalizedLLMReasoningProposalRead,
)
from rop.services.llm_proposal_normalization import (
    LLMProposalNormalizationContractError,
    compute_normalized_fingerprint,
    normalize_proposal,
)

LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109 = "LLM_PROPOSAL_INSPECTION_TASK_109"
"""Fixed structural-contract identifier for Task 109 inspection output."""

_EXPECTED_LLM_REASONING_SOURCE = "LLM_REASONING_TASK_057"
"""Task 057 proposals must carry this provenance marker."""

_FORBIDDEN_RAW_TEXT_KEYS = ("text", "raw_text", "prompt")
"""Keys that must never appear; the proposal carries no provider text."""

_EXPECTED_INSPECTION_KEYS = frozenset(
    {
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "available",
        "proposal_consistent",
        "candidate_assessments",
        "evidence_references",
        "unresolved_information_references",
        "uncertainty_flags",
        "inspection_source",
        "proposal_fingerprint",
    }
)

__all__ = [
    "LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109",
    "LLMProposalInspectionContractError",
    "LLMProposalInspectionService",
]


class LLMProposalInspectionContractError(Exception):
    """Task 109: structural violation at the proposal inspection boundary."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        self.detail = detail
        super().__init__(f"[{invariant}] {detail}")


class LLMProposalInspectionService:
    """Task 109: read-only inspection over a validated Task 057 proposal."""

    @staticmethod
    def build(
        *,
        proposal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inspect a validated Task 057 proposal without mutating it."""
        if proposal is None or not isinstance(proposal, Mapping):
            raise LLMProposalInspectionContractError(
                "INPUT_UNAVAILABLE",
                "proposal is required and must be a mapping",
            )

        LLMProposalInspectionService._reject_raw_text_keys(proposal)

        snapshot = copy.deepcopy(proposal)

        provided_source = snapshot.get("inspection_source")
        if provided_source is not None and (
            provided_source != LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109
        ):
            raise LLMProposalInspectionContractError(
                "INVALID_SOURCE",
                "inspection_source does not match Task 109: " + str(provided_source),
            )

        provided_fingerprint = snapshot.get("proposal_fingerprint")

        # Strip Task 109's own envelope fields before delegating: Task 106
        # validates the exact Task 057 field set, and these two keys are
        # 109-level passthrough (already captured above), not 057 content.
        snapshot.pop("proposal_fingerprint", None)
        snapshot.pop("inspection_source", None)

        try:
            normalized = normalize_proposal(snapshot)
        except LLMProposalNormalizationContractError as exc:
            raise LLMProposalInspectionContractError(
                "INPUT_INCONSISTENT",
                "proposal failed normalization: " + str(exc),
            ) from exc

        try:
            validated = NormalizedLLMReasoningProposalRead.model_validate(normalized)
        except ValidationError as exc:
            raise LLMProposalInspectionContractError(
                "INPUT_INCONSISTENT",
                "proposal failed structural validation: " + str(exc),
            ) from exc

        session_id = normalized.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise LLMProposalInspectionContractError(
                "INPUT_INCONSISTENT",
                "proposal has no valid session_id",
            )
        try:
            UUID(session_id)
        except ValueError as exc:
            raise LLMProposalInspectionContractError(
                "INPUT_INCONSISTENT",
                "proposal session_id is not a valid UUID: " + str(session_id),
            ) from exc

        if validated.llm_reasoning_source != _EXPECTED_LLM_REASONING_SOURCE:
            raise LLMProposalInspectionContractError(
                "INVALID_SOURCE",
                "llm_reasoning_source does not match Task 057: "
                + str(validated.llm_reasoning_source),
            )

        if validated.available is True and len(validated.candidate_assessments) == 0:
            raise LLMProposalInspectionContractError(
                "PROPOSAL_INCONSISTENT",
                "proposal is available but has no candidate assessments",
            )

        proposal_fingerprint = compute_normalized_fingerprint(normalized)

        if provided_fingerprint is not None and (
            provided_fingerprint != proposal_fingerprint
        ):
            raise LLMProposalInspectionContractError(
                "FINGERPRINT_MISMATCH",
                "proposal_fingerprint does not match the recomputed value",
            )

        candidate_assessments = copy.deepcopy(normalized["candidate_assessments"])

        evidence_ids: set[str] = set()
        unresolved_ids: set[str] = set()
        flags: set[str] = set()
        for assessment in validated.candidate_assessments:
            evidence_ids.update(assessment.supporting_evidence_ids)
            evidence_ids.update(assessment.contradicting_evidence_ids)
            unresolved_ids.update(assessment.unresolved_information_ids)
            flags.update(assessment.uncertainty_flags)

        inspection: dict[str, Any] = {
            "session_id": normalized["session_id"],
            "context_fingerprint": normalized["context_fingerprint"],
            "provider": normalized["provider"],
            "model": normalized["model"],
            "available": normalized["available"],
            "proposal_consistent": normalized["proposal_consistent"],
            "candidate_assessments": candidate_assessments,
            "evidence_references": sorted(evidence_ids),
            "unresolved_information_references": sorted(unresolved_ids),
            "uncertainty_flags": sorted(flags),
            "inspection_source": LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109,
            "proposal_fingerprint": proposal_fingerprint,
        }

        if set(inspection.keys()) != set(_EXPECTED_INSPECTION_KEYS):
            raise LLMProposalInspectionContractError(
                "INPUT_INCONSISTENT",
                "inspection output keys do not match the Task 109 contract",
            )
        for forbidden in _FORBIDDEN_RAW_TEXT_KEYS:
            if forbidden in inspection:
                raise LLMProposalInspectionContractError(
                    "INPUT_INCONSISTENT",
                    "inspection output leaked a raw text key: " + forbidden,
                )
        return inspection

    @staticmethod
    def _reject_raw_text_keys(proposal: Mapping[str, Any]) -> None:
        for forbidden in _FORBIDDEN_RAW_TEXT_KEYS:
            if forbidden in proposal:
                raise LLMProposalInspectionContractError(
                    "INPUT_INCONSISTENT",
                    "proposal leaked a raw text key: " + forbidden,
                )
        assessments = proposal.get("candidate_assessments")
        if isinstance(assessments, list):
            for entry in assessments:
                if isinstance(entry, Mapping):
                    for forbidden in _FORBIDDEN_RAW_TEXT_KEYS:
                        if forbidden in entry:
                            raise LLMProposalInspectionContractError(
                                "INPUT_INCONSISTENT",
                                "assessment leaked a raw text key: " + forbidden,
                            )

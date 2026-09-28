"""Task 105: Pure validation functions for LLM reasoning model output.

This module provides deterministic, side-effect-free validation of raw LLM
reasoning proposals against the canonical Task 055 context. All functions
are pure: no DB, no HTTP, no provider calls, no mutation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.schemas.llm_output_validation import (
    LLM_OUTPUT_VALIDATION_SOURCE_TASK_105,
)
from rop.schemas.llm_reasoning import _RawLLMReasoningProposal
from rop.services.llm_boundary_contract import VALID_ASSESSMENTS

__all__ = ["LLM_OUTPUT_VALIDATION_SOURCE_TASK_105", "validate_raw_proposal"]


def validate_raw_proposal(
    raw: Mapping[str, Any],
    context: Mapping[str, Any],
) -> list[str]:
    """Validate a raw LLM reasoning proposal against the canonical context.

    Args:
        raw: The parsed model output as a mapping (typically from JSON).
        context: The canonical Task 055 context mapping, containing at least
            "candidate_state", "observations", "entities", and
            "missing_information" lists with objects that have an ``id``
            attribute/key of type UUID.

    Returns:
        A list of human-readable issue strings. Empty list means the
        proposal is clean and consistent with the context.
    """
    issues: list[str] = []

    # 1. Validate top-level structure using the parse-only schema.
    #    This enforces ConfigDict(extra="forbid") -- no extra keys allowed.
    try:
        proposal = _RawLLMReasoningProposal.model_validate(raw)
    except Exception as exc:
        issues.append(f"Top-level schema validation failed: {exc}")
        return issues

    assessments = proposal.candidate_assessments

    # 2. Build reference sets from context.
    candidate_ids = {c.id for c in context.get("candidate_state", [])}
    observation_ids = {o.id for o in context.get("observations", [])}
    entity_ids = {e.id for e in context.get("entities", [])}
    evidence_ids = observation_ids | entity_ids
    missing_info_ids = {m.id for m in context.get("missing_information", [])}

    # 3. Validate each assessment.
    seen_candidates: set[UUID] = set()
    for idx, a in enumerate(assessments):
        prefix = f"Assessment[{idx}]"

        # candidate_id must be in context candidate_state
        if a.candidate_id not in candidate_ids:
            issues.append(
                f"{prefix}: candidate_id {a.candidate_id} not found "
                "in context candidate_state"
            )

        # No duplicate candidate_id
        if a.candidate_id in seen_candidates:
            issues.append(f"{prefix}: duplicate candidate_id {a.candidate_id}")
        seen_candidates.add(a.candidate_id)

        # assessment must be a valid enum value (already enforced by schema,
        # but we re-verify for completeness)
        if a.assessment not in VALID_ASSESSMENTS:
            issues.append(
                f"{prefix}: invalid assessment value '{a.assessment}' "
                f"(expected one of SUPPORTS, WEAKENS, UNCLEAR)"
            )

        # supporting_evidence_ids must reference known evidence
        for eid in a.supporting_evidence_ids:
            if eid not in evidence_ids:
                issues.append(
                    f"{prefix}: supporting_evidence_id {eid} not found in "
                    f"context observations or entities"
                )

        # contradicting_evidence_ids must reference known evidence
        for eid in a.contradicting_evidence_ids:
            if eid not in evidence_ids:
                issues.append(
                    f"{prefix}: contradicting_evidence_id {eid} not found in "
                    f"context observations or entities"
                )

        # unresolved_information_ids must reference known missing_information
        for mid in a.unresolved_information_ids:
            if mid not in missing_info_ids:
                issues.append(
                    f"{prefix}: unresolved_information_id {mid} not found in "
                    f"context missing_information"
                )

        # explanation must be non-empty string
        if not isinstance(a.explanation, str) or not a.explanation.strip():
            issues.append(f"{prefix}: explanation must be a non-empty string")

        # uncertainty_flags must be a list of strings (schema enforces list,
        # but we verify element types)
        if not isinstance(a.uncertainty_flags, list):
            issues.append(f"{prefix}: uncertainty_flags must be a list")
        else:
            for flag in a.uncertainty_flags:
                if not isinstance(flag, str):
                    issues.append(
                        f"{prefix}: uncertainty_flags must contain only strings, "
                        f"got {type(flag).__name__}"
                    )
                    break

    # 4. Validate candidate assessment order matches context candidate_state order.
    expected_order = [c.id for c in context.get("candidate_state", [])]
    actual_order = [a.candidate_id for a in assessments]
    if actual_order != expected_order:
        issues.append(
            "candidate_assessments order does not match context candidate_state order: "
            f"expected {[str(x) for x in expected_order]}, "
            f"got {[str(x) for x in actual_order]}"
        )

    # 5. Validate no missing assessments (every candidate must have one).
    if len(assessments) != len(expected_order):
        issues.append(
            f"candidate_assessments count ({len(assessments)}) does not match "
            f"candidate_state count ({len(expected_order)})"
        )

    return issues

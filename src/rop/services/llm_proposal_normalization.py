"""Task 106: deterministic LLM proposal normalization boundary.

Pure functions only: no DB, no HTTP, no provider calls, no mutation,
deterministic ordering. Normalizes a Task 057 LLM reasoning proposal
into a canonical form suitable for hashing and comparison.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106 = "LLM_PROPOSAL_NORMALIZATION_TASK_106"
"""Fixed structural-contract identifier for Task 106 normalization."""


def normalize_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical normalized representation of a Task 057 proposal.

    Does NOT add/remove/change semantics:
    - session_id normalized to string (UUID -> str)
    - context_fingerprint as-is (already string)
    - provider, model as-is (strings)
    - available, proposal_consistent as-is (bools)
    - llm_reasoning_source as-is
    - candidate_assessments: list normalized preserving EXACT order from input
      (which should match context order). Each assessment:
      - candidate_id -> string
      - assessment as-is (enum string)
      - supporting_evidence_ids -> list[str] (UUIDs -> str, preserve order)
      - contradicting_evidence_ids -> list[str] (preserve order)
      - unresolved_information_ids -> list[str] (preserve order)
      - explanation as-is (string)
      - uncertainty_flags -> list[str] sorted alphabetically for determinism
        (only field where order is NOT semantically meaningful per Task 057)

    Args:
        proposal: A Task 057 LLMReasoningProposalRead dict (mode="json").

    Returns:
        A canonical normalized dict with all values JSON-safe.
    """
    normalized: dict[str, Any] = {}

    # session_id -> string
    session_id = proposal.get("session_id")
    normalized["session_id"] = str(session_id) if session_id is not None else None

    # context_fingerprint as-is
    normalized["context_fingerprint"] = proposal.get("context_fingerprint")

    # provider, model as-is
    normalized["provider"] = proposal.get("provider")
    normalized["model"] = proposal.get("model")

    # available, proposal_consistent as-is
    normalized["available"] = proposal.get("available")
    normalized["proposal_consistent"] = proposal.get("proposal_consistent")

    # llm_reasoning_source as-is
    normalized["llm_reasoning_source"] = proposal.get("llm_reasoning_source")

    # candidate_assessments: preserve EXACT order, normalize each
    raw_assessments = proposal.get("candidate_assessments", [])
    normalized_assessments = []
    for assessment in raw_assessments:
        norm_assessment: dict[str, Any] = {}

        # candidate_id -> string
        candidate_id = assessment.get("candidate_id")
        norm_assessment["candidate_id"] = (
            str(candidate_id) if candidate_id is not None else None
        )

        # assessment as-is
        norm_assessment["assessment"] = assessment.get("assessment")

        # supporting_evidence_ids -> list[str] (preserve order)
        norm_assessment["supporting_evidence_ids"] = [
            str(eid) for eid in assessment.get("supporting_evidence_ids", [])
        ]

        # contradicting_evidence_ids -> list[str] (preserve order)
        norm_assessment["contradicting_evidence_ids"] = [
            str(eid) for eid in assessment.get("contradicting_evidence_ids", [])
        ]

        # unresolved_information_ids -> list[str] (preserve order)
        norm_assessment["unresolved_information_ids"] = [
            str(eid) for eid in assessment.get("unresolved_information_ids", [])
        ]

        # explanation as-is
        norm_assessment["explanation"] = assessment.get("explanation")

        # uncertainty_flags -> list[str] sorted alphabetically
        uncertainty_flags = assessment.get("uncertainty_flags", [])
        norm_assessment["uncertainty_flags"] = sorted(str(f) for f in uncertainty_flags)

        normalized_assessments.append(norm_assessment)

    normalized["candidate_assessments"] = normalized_assessments

    return normalized


def compute_normalized_fingerprint(normalized: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 fingerprint over canonical JSON.

    - sort_keys=True for dicts except candidate_assessments list which preserves order
    - separators=(',', ':')
    - default=str

    Args:
        normalized: Output of normalize_proposal.

    Returns:
        Hex digest string (64 lowercase hex chars).
    """

    # Custom serialization that preserves list order for candidate_assessments
    def to_canonical(value: Any) -> Any:
        if isinstance(value, Mapping):
            # For candidate_assessments list, we must not sort keys of its dict elements
            # but we do sort keys of the top-level dict and other nested dicts
            return {
                str(k): to_canonical(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [to_canonical(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        # Fallback for any unexpected type (should not happen for normalized output)
        return str(value)

    # Apply canonicalization to everything except we need special handling
    # for candidate_assessments list to preserve element order (already preserved)
    # but still sort keys within each assessment dict
    canonical = to_canonical(normalized)

    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_normalized(normalized: Mapping[str, Any]) -> list[str]:
    """Structural validation of normalized form.

    Args:
        normalized: Output of normalize_proposal.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []

    # Required top-level fields
    required_fields = (
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "candidate_assessments",
        "available",
        "proposal_consistent",
        "llm_reasoning_source",
    )
    for field in required_fields:
        if field not in normalized:
            errors.append(f"missing required field: {field}")

    if errors:
        return errors

    # Type checks
    if normalized["session_id"] is not None and not isinstance(
        normalized["session_id"], str
    ):
        errors.append("session_id must be string or null")

    if not isinstance(normalized["context_fingerprint"], str):
        errors.append("context_fingerprint must be string")

    if not isinstance(normalized["provider"], str):
        errors.append("provider must be string")

    if not isinstance(normalized["model"], str):
        errors.append("model must be string")

    if not isinstance(normalized["available"], bool):
        errors.append("available must be bool")

    if not isinstance(normalized["proposal_consistent"], bool):
        errors.append("proposal_consistent must be bool")

    if not isinstance(normalized["llm_reasoning_source"], str):
        errors.append("llm_reasoning_source must be string")

    if not isinstance(normalized["candidate_assessments"], list):
        errors.append("candidate_assessments must be list")
        return errors

    # Validate each assessment
    for i, assessment in enumerate(normalized["candidate_assessments"]):
        if not isinstance(assessment, Mapping):
            errors.append(f"candidate_assessments[{i}] must be a mapping")
            continue

        if "candidate_id" not in assessment:
            errors.append(f"candidate_assessments[{i}] missing candidate_id")
        elif assessment["candidate_id"] is not None and not isinstance(
            assessment["candidate_id"], str
        ):
            errors.append(
                f"candidate_assessments[{i}].candidate_id must be string or null"
            )

        if "assessment" not in assessment:
            errors.append(f"candidate_assessments[{i}] missing assessment")
        elif assessment["assessment"] not in ("SUPPORTS", "WEAKENS", "UNCLEAR"):
            errors.append(
                f"candidate_assessments[{i}].assessment must be "
                "SUPPORTS/WEAKENS/UNCLEAR"
            )

        for list_field in (
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "unresolved_information_ids",
        ):
            if list_field not in assessment:
                errors.append(f"candidate_assessments[{i}] missing {list_field}")
            elif not isinstance(assessment[list_field], list):
                errors.append(f"candidate_assessments[{i}].{list_field} must be list")
            else:
                for j, eid in enumerate(assessment[list_field]):
                    if not isinstance(eid, str):
                        errors.append(
                            f"candidate_assessments[{i}].{list_field}[{j}] "
                            "must be string"
                        )

        if "explanation" not in assessment:
            errors.append(f"candidate_assessments[{i}] missing explanation")
        elif not isinstance(assessment["explanation"], str):
            errors.append(f"candidate_assessments[{i}].explanation must be string")

        if "uncertainty_flags" not in assessment:
            errors.append(f"candidate_assessments[{i}] missing uncertainty_flags")
        elif not isinstance(assessment["uncertainty_flags"], list):
            errors.append(f"candidate_assessments[{i}].uncertainty_flags must be list")
        else:
            # Check that uncertainty_flags is sorted alphabetically
            flags = assessment["uncertainty_flags"]
            if flags != sorted(flags):
                errors.append(
                    f"candidate_assessments[{i}].uncertainty_flags "
                    "must be sorted alphabetically"
                )
            for j, flag in enumerate(flags):
                if not isinstance(flag, str):
                    errors.append(
                        f"candidate_assessments[{i}].uncertainty_flags[{j}] "
                        "must be string"
                    )

    return errors

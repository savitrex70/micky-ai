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
from uuid import UUID

LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106 = "LLM_PROPOSAL_NORMALIZATION_TASK_106"
"""Fixed structural-contract identifier for Task 106 normalization."""

# Exact Task 057 field set. No more, no less.
_REQUIRED_TOP_FIELDS = (
    "session_id",
    "context_fingerprint",
    "provider",
    "model",
    "candidate_assessments",
    "available",
    "proposal_consistent",
    "llm_reasoning_source",
)

_REQUIRED_ASSESSMENT_FIELDS = (
    "candidate_id",
    "assessment",
    "supporting_evidence_ids",
    "contradicting_evidence_ids",
    "unresolved_information_ids",
    "explanation",
    "uncertainty_flags",
)

_VALID_ASSESSMENTS = ("SUPPORTS", "WEAKENS", "UNCLEAR")


class LLMProposalNormalizationContractError(Exception):
    """Task 106: the proposal cannot be normalized.

    Raised when the input is not a mapping, misses required fields,
    carries unexpected fields, or holds a malformed nested assessment.
    Normalization never invents missing values and never silently
    discards unexpected ones.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


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
            Must hold exactly the Task 057 field set with well-formed
            nested assessments.

    Returns:
        A canonical normalized dict with all values JSON-safe.

    Raises:
        LLMProposalNormalizationContractError: If the input is not a
            mapping, misses required fields, carries unexpected fields,
            or holds a malformed nested assessment.
    """
    if not isinstance(proposal, Mapping):
        raise LLMProposalNormalizationContractError(
            "INPUT_UNAVAILABLE",
            "proposal is required and must be a mapping",
        )
    missing = [f for f in _REQUIRED_TOP_FIELDS if f not in proposal]
    if missing:
        raise LLMProposalNormalizationContractError(
            "MISSING_FIELD",
            "proposal is missing required fields: " + ", ".join(missing),
        )
    unexpected = [k for k in proposal.keys() if k not in _REQUIRED_TOP_FIELDS]
    if unexpected:
        raise LLMProposalNormalizationContractError(
            "UNEXPECTED_FIELD",
            "proposal carries unexpected top-level fields: "
            + ", ".join(str(k) for k in unexpected),
        )

    def _require_uuid(value: Any, where: str) -> str:
        text = value if isinstance(value, str) else None
        if text is None:
            try:
                text = str(value)
            except Exception:
                text = ""
        try:
            UUID(text)
        except (ValueError, AttributeError, TypeError):
            raise LLMProposalNormalizationContractError(
                "INVALID_ID",
                f"{where} is not a valid UUID: {value!r}",
            ) from None
        return text

    session_id = proposal["session_id"]
    if not isinstance(session_id, (str, UUID)):
        raise LLMProposalNormalizationContractError(
            "INVALID_ID", f"session_id is not a valid UUID: {session_id!r}"
        )
    for field in ("context_fingerprint", "provider", "model", "llm_reasoning_source"):
        if not isinstance(proposal[field], str):
            raise LLMProposalNormalizationContractError(
                "INVALID_TYPE", f"{field} must be a string"
            )
    for field in ("available", "proposal_consistent"):
        if not isinstance(proposal[field], bool):
            raise LLMProposalNormalizationContractError(
                "INVALID_TYPE", f"{field} must be a bool"
            )

    raw_assessments = proposal["candidate_assessments"]
    if not isinstance(raw_assessments, list):
        raise LLMProposalNormalizationContractError(
            "INVALID_TYPE", "candidate_assessments must be a list"
        )

    normalized: dict[str, Any] = {}

    # session_id -> string
    normalized["session_id"] = _require_uuid(session_id, "session_id")

    # context_fingerprint as-is
    normalized["context_fingerprint"] = proposal["context_fingerprint"]

    # provider, model as-is
    normalized["provider"] = proposal["provider"]
    normalized["model"] = proposal["model"]

    # available, proposal_consistent as-is
    normalized["available"] = proposal["available"]
    normalized["proposal_consistent"] = proposal["proposal_consistent"]

    # llm_reasoning_source as-is
    normalized["llm_reasoning_source"] = proposal["llm_reasoning_source"]

    # candidate_assessments: preserve EXACT order, normalize each.
    # Every assessment must be complete and well-formed; nothing is
    # invented and nothing unexpected is discarded.
    raw_assessments = proposal["candidate_assessments"]
    normalized_assessments = []
    for index, assessment in enumerate(raw_assessments):
        where = f"candidate_assessments[{index}]"
        if not isinstance(assessment, Mapping):
            raise LLMProposalNormalizationContractError(
                "MALFORMED_ASSESSMENT", f"{where} must be a mapping"
            )
        missing_nested = [f for f in _REQUIRED_ASSESSMENT_FIELDS if f not in assessment]
        if missing_nested:
            raise LLMProposalNormalizationContractError(
                "MISSING_FIELD",
                f"{where} is missing required fields: " + ", ".join(missing_nested),
            )
        unexpected_nested = [
            k for k in assessment.keys() if k not in _REQUIRED_ASSESSMENT_FIELDS
        ]
        if unexpected_nested:
            raise LLMProposalNormalizationContractError(
                "UNEXPECTED_FIELD",
                f"{where} carries unexpected fields: "
                + ", ".join(str(k) for k in unexpected_nested),
            )
        norm_assessment: dict[str, Any] = {}

        # candidate_id -> string (must be a valid UUID)
        norm_assessment["candidate_id"] = _require_uuid(
            assessment["candidate_id"], f"{where}.candidate_id"
        )

        # assessment as-is (must be a valid enum value)
        if assessment["assessment"] not in _VALID_ASSESSMENTS:
            raise LLMProposalNormalizationContractError(
                "INVALID_ASSESSMENT",
                f"{where}.assessment must be one of " + ", ".join(_VALID_ASSESSMENTS),
            )
        norm_assessment["assessment"] = assessment["assessment"]

        # evidence id lists -> list[str] (preserve order, UUID-validated)
        for list_field in (
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "unresolved_information_ids",
        ):
            raw_ids = assessment[list_field]
            if not isinstance(raw_ids, list):
                raise LLMProposalNormalizationContractError(
                    "INVALID_TYPE", f"{where}.{list_field} must be a list"
                )
            norm_assessment[list_field] = [
                _require_uuid(eid, f"{where}.{list_field}") for eid in raw_ids
            ]

        # explanation as-is (must be a non-empty string)
        explanation = assessment["explanation"]
        if not isinstance(explanation, str) or not explanation.strip():
            raise LLMProposalNormalizationContractError(
                "INVALID_EXPLANATION", f"{where}.explanation must be non-empty"
            )
        norm_assessment["explanation"] = explanation

        # uncertainty_flags -> list[str] sorted alphabetically
        uncertainty_flags = assessment["uncertainty_flags"]
        if not isinstance(uncertainty_flags, list) or any(
            not isinstance(f, str) for f in uncertainty_flags
        ):
            raise LLMProposalNormalizationContractError(
                "INVALID_TYPE",
                f"{where}.uncertainty_flags must be a list of strings",
            )
        norm_assessment["uncertainty_flags"] = sorted(uncertainty_flags)

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

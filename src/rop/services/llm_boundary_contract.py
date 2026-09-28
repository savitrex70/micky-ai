"""Task 113: canonical LLM boundary contract registry.

One authoritative source for the LLM boundary's structural constants.
Tasks 057 and 103-112 import these definitions instead of maintaining
competing literal copies, so a typo or drift fails loudly at import or
test time rather than silently forking the contract.

Semantics are unchanged: every value below matches the previously
approved literals exactly. Only the ownership moves here.
"""

from __future__ import annotations

__all__ = [
    "OUTCOME_INPUT_UNAVAILABLE",
    "OUTCOME_INPUT_INCONSISTENT",
    "OUTCOME_MODEL_UNAVAILABLE",
    "OUTCOME_MODEL_OUTPUT_INVALID",
    "OUTCOME_MODEL_OUTPUT_INCONSISTENT",
    "ALLOWED_BOUNDARY_OUTCOMES",
    "PROPOSAL_TOP_FIELDS",
    "ASSESSMENT_FIELDS",
    "RAW_PROPOSAL_TOP_FIELDS",
    "PAYLOAD_FIELDS",
    "PROVIDER_RESPONSE_REQUIRED_FIELDS",
    "PROVIDER_RESPONSE_KNOWN_FIELDS",
    "VALID_ASSESSMENTS",
]

# -----------------------------------------------------------------
# Allowed boundary outcomes (Task 057 taxonomy; Task 107 normalizer
# returns the 4 model/input outcomes, never INPUT_UNAVAILABLE).
# -----------------------------------------------------------------

OUTCOME_INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
OUTCOME_INPUT_INCONSISTENT = "INPUT_INCONSISTENT"
OUTCOME_MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
OUTCOME_MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
OUTCOME_MODEL_OUTPUT_INCONSISTENT = "MODEL_OUTPUT_INCONSISTENT"

ALLOWED_BOUNDARY_OUTCOMES = (
    OUTCOME_INPUT_UNAVAILABLE,
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_MODEL_UNAVAILABLE,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
)

# -----------------------------------------------------------------
# Task 057 public proposal fields, fixed deterministic order.
# -----------------------------------------------------------------

PROPOSAL_TOP_FIELDS = (
    "session_id",
    "context_fingerprint",
    "provider",
    "model",
    "candidate_assessments",
    "available",
    "proposal_consistent",
    "llm_reasoning_source",
)

# -----------------------------------------------------------------
# Candidate-assessment fields, fixed deterministic order.
# -----------------------------------------------------------------

ASSESSMENT_FIELDS = (
    "candidate_id",
    "assessment",
    "supporting_evidence_ids",
    "contradicting_evidence_ids",
    "unresolved_information_ids",
    "explanation",
    "uncertainty_flags",
)

# -----------------------------------------------------------------
# Raw provider-output allowed structure: exactly one top-level key.
# -----------------------------------------------------------------

RAW_PROPOSAL_TOP_FIELDS = ("candidate_assessments",)

# -----------------------------------------------------------------
# Task 104 provider payload fields, fixed deterministic order.
# -----------------------------------------------------------------

PAYLOAD_FIELDS = (
    "session_id",
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
    "reasoning_pipeline",
)

# -----------------------------------------------------------------
# Provider response fields. The declared response carries exactly the
# three required fields; the isolation boundary additionally
# understands the optional ``context_fingerprint`` metadata echoed by
# some providers, so the known surface is four.
# -----------------------------------------------------------------

PROVIDER_RESPONSE_REQUIRED_FIELDS = (
    "provider",
    "model",
    "text",
)

PROVIDER_RESPONSE_KNOWN_FIELDS = (
    "provider",
    "model",
    "text",
    "context_fingerprint",
)

# -----------------------------------------------------------------
# Valid assessment values, fixed deterministic order.
# -----------------------------------------------------------------

VALID_ASSESSMENTS = (
    "SUPPORTS",
    "WEAKENS",
    "UNCLEAR",
)

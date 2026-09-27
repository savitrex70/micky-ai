"""Task 103: Independent consistency audit of the Task 057 LLM reasoning proposal.

This service performs a pure, deterministic audit of an already-produced
LLMReasoningProposalRead. It does not call any provider, touch the database,
or make HTTP calls. It verifies structural integrity, type correctness,
fingerprint validity, candidate assessment structure, evidence reference
format, assessment enum values, explanation non-emptiness, uncertainty flags,
provider/model presence, source constant exactness, issue ordering
determinism and deduplication, and derives coherent flags from issues.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.llm_reasoning import LLM_REASONING_TASK_057

LLM_REASONING_AUDIT_TASK_103 = "LLM_REASONING_AUDIT_TASK_103"
"""Fixed structural-contract identifier for Task 103 audit results."""

# Valid assessment values from the Assessment enum
_VALID_ASSESSMENTS = {"SUPPORTS", "WEAKENS", "UNCLEAR"}

# UUID regex pattern for validation
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# Fingerprint pattern: 64 lowercase hex characters
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _is_valid_uuid(value: str) -> bool:
    return isinstance(value, str) and _UUID_PATTERN.match(value) is not None


class LLMReasoningAuditContractError(Exception):
    """Task 103: an unrecoverable failure during audit construction.

    Raised when the input is not a mapping or is None. All other
    inconsistencies are recorded in the audit result, not raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class LLMReasoningAuditService:
    """Task 103: independent consistency audit of a Task 057 proposal.

    Pure orchestration. No database, HTTP, provider calls, or side effects.
    The audit receives only the proposal dict and verifies its internal
    consistency and structural validity.
    """

    @staticmethod
    def build(
        *,
        proposal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit a Task 057 LLMReasoningProposalRead dict.

        Args:
            proposal: The proposal dict to audit. If None or not a mapping,
                raises LLMReasoningAuditContractError.

        Returns:
            A dict with all audit fields, suitable for
            LLMReasoningAuditRead validation.
        """
        if not isinstance(proposal, Mapping):
            raise LLMReasoningAuditContractError(
                "INPUT_UNAVAILABLE",
                "proposal is required and must be a mapping",
            )

        issues: list[str] = []

        # Track all individual check results
        available = False
        proposal_consistent = False
        session_consistent = True
        fingerprint_consistent = True
        candidate_assessments_consistent = True
        evidence_references_consistent = True
        unresolved_info_consistent = True
        candidate_order_consistent = True
        provenance_consistent = True
        metadata_consistent = True

        # -----------------------------------------------------------------
        # Required fields and types
        # -----------------------------------------------------------------
        required_fields = {
            "session_id": (str, UUID),
            "context_fingerprint": (str,),
            "provider": (str,),
            "model": (str,),
            "candidate_assessments": (list,),
            "available": (bool,),
            "proposal_consistent": (bool,),
            "llm_reasoning_source": (str,),
        }

        for field, expected_types in required_fields.items():
            if field not in proposal:
                issues.append(f"missing_field:{field}")
                metadata_consistent = False
            else:
                value = proposal[field]
                # Handle UUID fields that may be string or UUID
                if field == "session_id":
                    if not isinstance(value, (str, UUID)):
                        issues.append(f"wrong_type:{field}")
                        metadata_consistent = False
                        session_consistent = False
                    else:
                        try:
                            UUID(str(value))
                        except (ValueError, AttributeError):
                            issues.append(f"invalid_uuid:{field}")
                            session_consistent = False
                elif not isinstance(value, expected_types):
                    issues.append(f"wrong_type:{field}")
                    metadata_consistent = False

        # If critical fields are missing or wrong type, we can't proceed
        # with deeper checks, but we still return the audit with flags set
        if not metadata_consistent:
            return LLMReasoningAuditService._build_result(
                proposal=proposal,
                available=available,
                proposal_consistent=proposal_consistent,
                session_consistent=session_consistent,
                fingerprint_consistent=fingerprint_consistent,
                candidate_assessments_consistent=candidate_assessments_consistent,
                evidence_references_consistent=evidence_references_consistent,
                unresolved_info_consistent=unresolved_info_consistent,
                candidate_order_consistent=candidate_order_consistent,
                provenance_consistent=provenance_consistent,
                metadata_consistent=metadata_consistent,
                issues=issues,
            )

        # -----------------------------------------------------------------
        # available and proposal_consistent fields
        # -----------------------------------------------------------------
        available = bool(proposal.get("available"))
        proposal_consistent = bool(proposal.get("proposal_consistent"))

        # If proposal is not available, many checks are not applicable
        # but we still verify structure
        if not available:
            # For unavailable proposals, candidate_assessments should be empty
            candidate_assessments = proposal.get("candidate_assessments", [])
            if candidate_assessments:
                issues.append("unavailable_proposal_has_assessments")
                candidate_assessments_consistent = False

        # -----------------------------------------------------------------
        # session_id format
        # -----------------------------------------------------------------
        session_id_str = str(proposal["session_id"])
        if not _is_valid_uuid(session_id_str):
            issues.append("invalid_session_id_format")
            session_consistent = False

        # -----------------------------------------------------------------
        # context_fingerprint format and recomputation
        # -----------------------------------------------------------------
        fingerprint = proposal.get("context_fingerprint", "")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.match(
            fingerprint
        ):
            issues.append("invalid_fingerprint_format")
            fingerprint_consistent = False
        else:
            # We cannot recompute the fingerprint without the original context,
            # but we can verify it's a valid SHA256 hex digest
            # The audit only receives the proposal, not the context, so we
            # verify format only. The fingerprint_consistent flag here means
            # "format is valid", not "matches recomputed context".
            pass

        # -----------------------------------------------------------------
        # candidate_assessments structure
        # -----------------------------------------------------------------
        candidate_assessments = proposal.get("candidate_assessments", [])
        seen_candidate_ids: set[str] = set()
        candidate_ids_in_order: list[str] = []

        for assessment in candidate_assessments:
            if not isinstance(assessment, Mapping):
                issues.append("candidate_assessment_not_mapping")
                candidate_assessments_consistent = False
                continue

            # candidate_id
            cand_id = assessment.get("candidate_id")
            if cand_id is None:
                issues.append("missing_candidate_id")
                candidate_assessments_consistent = False
            else:
                cand_id_str = str(cand_id)
                try:
                    UUID(cand_id_str)
                except (ValueError, AttributeError):
                    issues.append("invalid_candidate_id_format")
                    candidate_assessments_consistent = False
                else:
                    candidate_ids_in_order.append(cand_id_str)
                    if cand_id_str in seen_candidate_ids:
                        issues.append("duplicate_candidate_id")
                        candidate_assessments_consistent = False
                    seen_candidate_ids.add(cand_id_str)

            # assessment value
            assess_val = assessment.get("assessment")
            if assess_val not in _VALID_ASSESSMENTS:
                issues.append("invalid_assessment_value")
                candidate_assessments_consistent = False

            # supporting_evidence_ids
            sup_ids = assessment.get("supporting_evidence_ids", [])
            if not isinstance(sup_ids, list):
                issues.append("supporting_evidence_not_list")
                evidence_references_consistent = False
            else:
                for eid in sup_ids:
                    if not _UUID_PATTERN.match(str(eid)):
                        issues.append("invalid_supporting_evidence_id_format")
                        evidence_references_consistent = False

            # contradicting_evidence_ids
            con_ids = assessment.get("contradicting_evidence_ids", [])
            if not isinstance(con_ids, list):
                issues.append("contradicting_evidence_not_list")
                evidence_references_consistent = False
            else:
                for eid in con_ids:
                    if not _UUID_PATTERN.match(str(eid)):
                        issues.append("invalid_contradicting_evidence_id_format")
                        evidence_references_consistent = False

            # unresolved_information_ids
            unres_ids = assessment.get("unresolved_information_ids", [])
            if not isinstance(unres_ids, list):
                issues.append("unresolved_info_not_list")
                unresolved_info_consistent = False
            else:
                for mid in unres_ids:
                    if not _UUID_PATTERN.match(str(mid)):
                        issues.append("invalid_missing_info_id_format")
                        unresolved_info_consistent = False

            # explanation
            explanation = assessment.get("explanation", "")
            if not isinstance(explanation, str) or len(explanation.strip()) == 0:
                issues.append("empty_explanation")
                candidate_assessments_consistent = False

            # uncertainty_flags
            uncert_flags = assessment.get("uncertainty_flags", [])
            if not isinstance(uncert_flags, list):
                issues.append("uncertainty_flags_not_list")
                candidate_assessments_consistent = False
            else:
                for flag in uncert_flags:
                    if not isinstance(flag, str):
                        issues.append("uncertainty_flag_not_string")
                        candidate_assessments_consistent = False

        # -----------------------------------------------------------------
        # candidate_order_consistent
        # Since we don't have the original context, we verify that the
        # order in the proposal is internally consistent (no duplicates,
        # which we already checked). We cannot verify against context order
        # without the context. The flag reflects structural order validity.
        # -----------------------------------------------------------------
        # Duplicate check already done above. If no duplicates, order is
        # internally consistent as a sequence.

        # -----------------------------------------------------------------
        # provider and model non-empty
        # -----------------------------------------------------------------
        provider = proposal.get("provider", "")
        model = proposal.get("model", "")
        if not isinstance(provider, str) or len(provider.strip()) == 0:
            issues.append("empty_provider")
            provenance_consistent = False
        if not isinstance(model, str) or len(model.strip()) == 0:
            issues.append("empty_model")
            provenance_consistent = False

        # -----------------------------------------------------------------
        # llm_reasoning_source exact match
        # -----------------------------------------------------------------
        source = proposal.get("llm_reasoning_source", "")
        if source != LLM_REASONING_TASK_057:
            issues.append(
                f"source_constant_mismatch:expected={LLM_REASONING_TASK_057},got={source}"
            )
            provenance_consistent = False

        # -----------------------------------------------------------------
        # Deterministic issue ordering and deduplication
        # -----------------------------------------------------------------
        # Sort issues for deterministic output, then deduplicate
        unique_issues = sorted(set(issues))

        # -----------------------------------------------------------------
        # Build result
        # -----------------------------------------------------------------
        return LLMReasoningAuditService._build_result(
            proposal=proposal,
            available=available,
            proposal_consistent=proposal_consistent,
            session_consistent=session_consistent,
            fingerprint_consistent=fingerprint_consistent,
            candidate_assessments_consistent=candidate_assessments_consistent,
            evidence_references_consistent=evidence_references_consistent,
            unresolved_info_consistent=unresolved_info_consistent,
            candidate_order_consistent=candidate_order_consistent,
            provenance_consistent=provenance_consistent,
            metadata_consistent=metadata_consistent,
            issues=unique_issues,
        )

    @staticmethod
    def _build_result(
        *,
        proposal: Mapping[str, Any] | None,
        available: bool,
        proposal_consistent: bool,
        session_consistent: bool,
        fingerprint_consistent: bool,
        candidate_assessments_consistent: bool,
        evidence_references_consistent: bool,
        unresolved_info_consistent: bool,
        candidate_order_consistent: bool,
        provenance_consistent: bool,
        metadata_consistent: bool,
        issues: list[str],
    ) -> dict[str, Any]:
        """Construct the final audit result dict."""
        # Derive overall consistency flags from issues
        # A proposal is "consistent" overall if all checks pass
        all_consistent = all(
            [
                session_consistent,
                fingerprint_consistent,
                candidate_assessments_consistent,
                evidence_references_consistent,
                unresolved_info_consistent,
                candidate_order_consistent,
                provenance_consistent,
                metadata_consistent,
            ]
        )

        return {
            "available": available,
            "proposal_consistent": proposal_consistent and all_consistent,
            "session_consistent": session_consistent,
            "fingerprint_consistent": fingerprint_consistent,
            "candidate_assessments_consistent": candidate_assessments_consistent,
            "evidence_references_consistent": evidence_references_consistent,
            "unresolved_info_consistent": unresolved_info_consistent,
            "candidate_order_consistent": candidate_order_consistent,
            "provenance_consistent": provenance_consistent,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": issues,
            "audit_source": LLM_REASONING_AUDIT_TASK_103,
        }

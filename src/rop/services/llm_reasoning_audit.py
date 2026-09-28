"""Task 103: Independent consistency audit of the Task 057 LLM reasoning proposal.

This service performs a pure, deterministic audit of an already-produced
LLMReasoningProposalRead AGAINST the exact canonical Task 055 context that
produced it. It does not call any provider, touch the database, or make
HTTP calls.

Provenance is verified, not assumed: the context fingerprint is
recomputed from the supplied context with the canonical Task 104
serializer/fingerprint definition (never duplicated here), session
identity is matched exactly, and every candidate/evidence/
missing-information reference is checked for membership in the
canonical context with exact ordering. A well-formed fingerprint that
does not match the recomputed value is reported, never trusted.

A canonical Task 055 context is REQUIRED. Without it the audit cannot
verify provenance, so the call is rejected instead of returning a
misleading success.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from rop.schemas.llm_reasoning_audit import LLMReasoningAuditRead
from rop.services.llm_boundary_contract import (
    ASSESSMENT_FIELDS,
    PROPOSAL_TOP_FIELDS,
    VALID_ASSESSMENTS,
)
from rop.services.llm_reasoning import LLM_REASONING_TASK_057
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
)
from rop.services.reasoning_context import REASONING_CONTEXT_SOURCE_TASK_055

LLM_REASONING_AUDIT_TASK_103 = "LLM_REASONING_AUDIT_TASK_103"
"""Fixed structural-contract identifier for Task 103 audit results."""

# Valid assessment values. Canonical Task 113 tuple; the set preserves
# the audit's membership-check semantics.
_VALID_ASSESSMENTS = set(VALID_ASSESSMENTS)

# Canonical Task 113 field sets; the audit consumes them directly so a
# drifted literal cannot silently fork the contract.
_REQUIRED_TOP_FIELDS = PROPOSAL_TOP_FIELDS
_REQUIRED_NESTED_FIELDS = ASSESSMENT_FIELDS

# UUID regex pattern for validation
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# Fingerprint pattern: 64 lowercase hex characters
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Fixed deterministic issue order. Issues carrying a ":suffix" payload
# sort under their group entry.
_ISSUE_ORDER = (
    "missing_field",
    "wrong_type",
    "invalid_uuid",
    "invalid_session_id_format",
    "unexpected_field",
    "session_mismatch",
    "availability_mismatch",
    "context_source_mismatch",
    "context_inconsistent",
    "invalid_fingerprint_format",
    "fingerprint_compute_failed",
    "fingerprint_mismatch",
    "candidate_assessment_not_mapping",
    "unexpected_assessment_field",
    "missing_assessment_field",
    "missing_candidate_id",
    "invalid_candidate_id_format",
    "duplicate_candidate_id",
    "unknown_candidate_id",
    "missing_candidate_assessment",
    "extra_candidate_assessment",
    "candidate_order_mismatch",
    "invalid_assessment_value",
    "supporting_evidence_not_list",
    "invalid_supporting_evidence_id_format",
    "unknown_supporting_evidence_id",
    "contradicting_evidence_not_list",
    "invalid_contradicting_evidence_id_format",
    "unknown_contradicting_evidence_id",
    "unresolved_info_not_list",
    "invalid_missing_info_id_format",
    "unknown_missing_info_id",
    "empty_explanation",
    "uncertainty_flags_not_list",
    "uncertainty_flag_not_string",
    "empty_provider",
    "empty_model",
    "source_constant_mismatch",
    "unavailable_proposal_has_assessments",
)


def _is_valid_uuid(value: str) -> bool:
    return isinstance(value, str) and _UUID_PATTERN.match(value) is not None


def _issue_order_key(issue: str) -> tuple[int, str]:
    for index, group in enumerate(_ISSUE_ORDER):
        if issue == group or issue.startswith(group + ":"):
            return (index, issue)
    return (len(_ISSUE_ORDER), issue)


class LLMReasoningAuditContractError(Exception):
    """Task 103: an unrecoverable failure during audit construction.

    Raised when the proposal or the canonical context is not a mapping
    (including None). All other inconsistencies are recorded in the
    audit result, not raised.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class LLMReasoningAuditService:
    """Task 103: independent consistency audit of a Task 057 proposal.

    Pure orchestration. No database, HTTP, provider calls, or side effects.
    The audit verifies the proposal against the exact canonical Task 055
    context supplied alongside it.
    """

    @staticmethod
    def build(
        *,
        proposal: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit a Task 057 LLMReasoningProposalRead dict against its context.

        Args:
            proposal: The proposal dict to audit. If None or not a mapping,
                raises LLMReasoningAuditContractError.
            context: The exact canonical Task 055 context that produced the
                proposal. Required: provenance (session, fingerprint,
                membership, order) cannot be verified without it, so a
                missing or non-mapping context raises instead of
                returning a misleading success.

        Returns:
            A dict with all audit fields, suitable for
            LLMReasoningAuditRead validation.
        """
        if not isinstance(proposal, Mapping):
            raise LLMReasoningAuditContractError(
                "INPUT_UNAVAILABLE",
                "proposal is required and must be a mapping",
            )
        if not isinstance(context, Mapping):
            raise LLMReasoningAuditContractError(
                "CONTEXT_REQUIRED",
                "canonical Task 055 context is required and must be a mapping",
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

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
        # Required fields and types. Names come from the canonical
        # Task 113 registry; only the per-field type expectations are
        # local to the audit.
        # -----------------------------------------------------------------
        _FIELD_TYPES: dict[str, tuple[type, ...]] = {
            "session_id": (str, UUID),
            "context_fingerprint": (str,),
            "provider": (str,),
            "model": (str,),
            "candidate_assessments": (list,),
            "available": (bool,),
            "proposal_consistent": (bool,),
            "llm_reasoning_source": (str,),
        }
        assert set(_FIELD_TYPES) == set(_REQUIRED_TOP_FIELDS)
        required_fields = {field: _FIELD_TYPES[field] for field in _REQUIRED_TOP_FIELDS}

        for field, expected_types in required_fields.items():
            if field not in proposal:
                _add(f"missing_field:{field}")
                metadata_consistent = False
            else:
                value = proposal[field]
                # Handle UUID fields that may be string or UUID
                if field == "session_id":
                    if not isinstance(value, (str, UUID)):
                        _add(f"wrong_type:{field}")
                        metadata_consistent = False
                        session_consistent = False
                    else:
                        try:
                            UUID(str(value))
                        except (ValueError, AttributeError):
                            _add(f"invalid_uuid:{field}")
                            session_consistent = False
                elif not isinstance(value, expected_types):
                    _add(f"wrong_type:{field}")
                    metadata_consistent = False

        # Exact top-level field set: the Task 057 proposal contract.
        # Unexpected fields are never silently accepted.
        for name in sorted(str(k) for k in proposal.keys()):
            if name not in required_fields:
                _add(f"unexpected_field:{name}")
                metadata_consistent = False

        # If critical fields are missing or wrong type, we can't proceed
        # with deeper checks, but we still return the audit with flags set
        if not metadata_consistent:
            ordered_early = sorted(set(issues), key=_issue_order_key)
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
                issues=ordered_early,
            )

        # -----------------------------------------------------------------
        # available and proposal_consistent fields
        # -----------------------------------------------------------------
        available = bool(proposal.get("available"))
        proposal_consistent = bool(proposal.get("proposal_consistent"))

        # -----------------------------------------------------------------
        # Canonical context identity (ground truth for every check below)
        # -----------------------------------------------------------------
        context_session_raw = context.get("session_id")
        if context_session_raw is None or not _is_valid_uuid(str(context_session_raw)):
            raise LLMReasoningAuditContractError(
                "CONTEXT_INVALID",
                "canonical context has no valid session_id",
            )
        context_session_id = str(context_session_raw)

        # -----------------------------------------------------------------
        # Canonical context provenance and availability binding. A
        # proposal cannot claim usable LLM reasoning unless the exact
        # canonical context agrees it is available, carries the fixed
        # Task 055 source, and is internally consistent.
        # -----------------------------------------------------------------
        if context.get("context_source") != REASONING_CONTEXT_SOURCE_TASK_055:
            _add("context_source_mismatch")
            provenance_consistent = False
            proposal_consistent = False
        if context.get("context_consistent") is not True:
            _add("context_inconsistent")
            proposal_consistent = False
        context_available = context.get("available")
        if available != context_available:
            _add("availability_mismatch")
            proposal_consistent = False

        # -----------------------------------------------------------------
        # session identity: exact match against the canonical context
        # -----------------------------------------------------------------
        proposal_session_id = str(proposal["session_id"])
        if not _is_valid_uuid(proposal_session_id):
            _add("invalid_session_id_format")
            session_consistent = False
        elif proposal_session_id != context_session_id:
            _add("session_mismatch")
            session_consistent = False

        # -----------------------------------------------------------------
        # context_fingerprint: format, then independent recomputation
        # from the exact canonical context via Task 104. A well-formed
        # fingerprint that does not match is reported, never trusted.
        # -----------------------------------------------------------------
        fingerprint = proposal.get("context_fingerprint", "")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.match(
            fingerprint
        ):
            _add("invalid_fingerprint_format")
            fingerprint_consistent = False
        else:
            try:
                serialized = serialize_context(context)
                expected_fingerprint = compute_fingerprint(serialized)
            except Exception:
                _add("fingerprint_compute_failed")
                fingerprint_consistent = False
            else:
                if fingerprint != expected_fingerprint:
                    _add("fingerprint_mismatch")
                    fingerprint_consistent = False

        # -----------------------------------------------------------------
        # Canonical reference sets from the exact context
        # -----------------------------------------------------------------
        try:
            context_candidate_ids = [str(c.id) for c in context["candidate_state"]]
            context_observation_ids = {str(o.id) for o in context["observations"]}
            context_entity_ids = {str(e.id) for e in context["entities"]}
            context_missing_ids = {str(m.id) for m in context["missing_information"]}
        except Exception:
            raise LLMReasoningAuditContractError(
                "CONTEXT_INVALID",
                "canonical context is missing required reference collections",
            ) from None
        context_evidence_ids = context_observation_ids | context_entity_ids

        # If proposal is not available, assessments must be absent; the
        # membership/order checks below are vacuous and therefore skipped
        # rather than reported as spurious issues.
        candidate_assessments = proposal.get("candidate_assessments", [])
        if not available:
            if candidate_assessments:
                _add("unavailable_proposal_has_assessments")
                candidate_assessments_consistent = False
        else:
            if not isinstance(candidate_assessments, list):
                _add("wrong_type:candidate_assessments")
                metadata_consistent = False
                candidate_assessments_consistent = False
                candidate_assessments = []
            else:
                seen_candidate_ids: set[str] = set()
                actual_ids_in_order: list[str] = []

                for assessment in candidate_assessments:
                    if not isinstance(assessment, Mapping):
                        _add("candidate_assessment_not_mapping")
                        candidate_assessments_consistent = False
                        continue

                    # Exact nested field set: no invented, discarded, or
                    # smuggled assessment fields. Canonical Task 113 set.
                    for name in sorted(str(k) for k in assessment.keys()):
                        if name not in _REQUIRED_NESTED_FIELDS:
                            _add(f"unexpected_assessment_field:{name}")
                            candidate_assessments_consistent = False

                    # candidate_id: format, membership, duplicates
                    cand_id = assessment.get("candidate_id")
                    if cand_id is None:
                        _add("missing_candidate_id")
                        candidate_assessments_consistent = False
                    else:
                        cand_id_str = str(cand_id)
                        if not _is_valid_uuid(cand_id_str):
                            _add("invalid_candidate_id_format")
                            candidate_assessments_consistent = False
                        else:
                            actual_ids_in_order.append(cand_id_str)
                            if cand_id_str in seen_candidate_ids:
                                _add("duplicate_candidate_id")
                                candidate_assessments_consistent = False
                            seen_candidate_ids.add(cand_id_str)
                            if cand_id_str not in set(context_candidate_ids):
                                _add("unknown_candidate_id")
                                candidate_assessments_consistent = False

                    # assessment value
                    assess_val = assessment.get("assessment")
                    if assess_val not in _VALID_ASSESSMENTS:
                        _add("invalid_assessment_value")
                        candidate_assessments_consistent = False

                    # supporting_evidence_ids: presence, format, membership.
                    # A missing list must fail explicitly: the audit is
                    # independent from Pydantic defaults and never
                    # substitutes an empty list for an absent field. The
                    # remaining checks still run on safe defaults so one
                    # gap never hides another defect.
                    if "supporting_evidence_ids" not in assessment:
                        _add("missing_assessment_field:supporting_evidence_ids")
                        candidate_assessments_consistent = False
                        evidence_references_consistent = False
                    sup_ids = assessment.get("supporting_evidence_ids", [])
                    if not isinstance(sup_ids, list):
                        _add("supporting_evidence_not_list")
                        evidence_references_consistent = False
                    else:
                        for eid in sup_ids:
                            if not _is_valid_uuid(str(eid)):
                                _add("invalid_supporting_evidence_id_format")
                                evidence_references_consistent = False
                            elif str(eid) not in context_evidence_ids:
                                _add("unknown_supporting_evidence_id")
                                evidence_references_consistent = False

                    # contradicting_evidence_ids: presence, format, membership
                    if "contradicting_evidence_ids" not in assessment:
                        _add("missing_assessment_field:contradicting_evidence_ids")
                        candidate_assessments_consistent = False
                        evidence_references_consistent = False
                    con_ids = assessment.get("contradicting_evidence_ids", [])
                    if not isinstance(con_ids, list):
                        _add("contradicting_evidence_not_list")
                        evidence_references_consistent = False
                    else:
                        for eid in con_ids:
                            if not _is_valid_uuid(str(eid)):
                                _add("invalid_contradicting_evidence_id_format")
                                evidence_references_consistent = False
                            elif str(eid) not in context_evidence_ids:
                                _add("unknown_contradicting_evidence_id")
                                evidence_references_consistent = False

                    # unresolved_information_ids: presence, format, membership
                    if "unresolved_information_ids" not in assessment:
                        _add("missing_assessment_field:unresolved_information_ids")
                        candidate_assessments_consistent = False
                        unresolved_info_consistent = False
                    unres_ids = assessment.get("unresolved_information_ids", [])
                    if not isinstance(unres_ids, list):
                        _add("unresolved_info_not_list")
                        unresolved_info_consistent = False
                    else:
                        for mid in unres_ids:
                            if not _is_valid_uuid(str(mid)):
                                _add("invalid_missing_info_id_format")
                                unresolved_info_consistent = False
                            elif str(mid) not in context_missing_ids:
                                _add("unknown_missing_info_id")
                                unresolved_info_consistent = False

                    # explanation: presence, then non-empty string
                    if "explanation" not in assessment:
                        _add("missing_assessment_field:explanation")
                        candidate_assessments_consistent = False
                    else:
                        explanation = assessment["explanation"]
                        if (
                            not isinstance(explanation, str)
                            or len(explanation.strip()) == 0
                        ):
                            _add("empty_explanation")
                            candidate_assessments_consistent = False

                    # uncertainty_flags: presence, then list of strings
                    if "uncertainty_flags" not in assessment:
                        _add("missing_assessment_field:uncertainty_flags")
                        candidate_assessments_consistent = False
                    else:
                        uncert_flags = assessment["uncertainty_flags"]
                        if not isinstance(uncert_flags, list):
                            _add("uncertainty_flags_not_list")
                            candidate_assessments_consistent = False
                        else:
                            for flag in uncert_flags:
                                if not isinstance(flag, str):
                                    _add("uncertainty_flag_not_string")
                                    candidate_assessments_consistent = False

                # Coverage: every canonical candidate assessed exactly once.
                actual_id_set = set(actual_ids_in_order)
                expected_id_set = set(context_candidate_ids)
                if expected_id_set - actual_id_set:
                    _add("missing_candidate_assessment")
                    candidate_assessments_consistent = False
                    candidate_order_consistent = False
                if actual_id_set - expected_id_set:
                    _add("extra_candidate_assessment")
                    candidate_assessments_consistent = False
                    candidate_order_consistent = False

                # Order: exact canonical candidate order. Checked only
                # when coverage matches, so a missing/extra candidate is
                # not double-reported as a reordering.
                if actual_id_set == expected_id_set:
                    if actual_ids_in_order != context_candidate_ids:
                        _add("candidate_order_mismatch")
                        candidate_order_consistent = False

        # -----------------------------------------------------------------
        # provider and model non-empty
        # -----------------------------------------------------------------
        provider = proposal.get("provider", "")
        model = proposal.get("model", "")
        if not isinstance(provider, str) or len(provider.strip()) == 0:
            _add("empty_provider")
            provenance_consistent = False
        if not isinstance(model, str) or len(model.strip()) == 0:
            _add("empty_model")
            provenance_consistent = False

        # -----------------------------------------------------------------
        # llm_reasoning_source exact match
        # -----------------------------------------------------------------
        source = proposal.get("llm_reasoning_source", "")
        if source != LLM_REASONING_TASK_057:
            _add(
                f"source_constant_mismatch:expected={LLM_REASONING_TASK_057},got={source}"
            )
            provenance_consistent = False

        # -----------------------------------------------------------------
        # Deterministic fixed-order, deduplicated issues
        # -----------------------------------------------------------------
        ordered_issues = sorted(set(issues), key=_issue_order_key)

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
            issues=ordered_issues,
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
        """Construct the final audit result dict.

        Task 117: the result is validated before it leaves the boundary.
        Every issue must belong to the defined Task 103 vocabulary and
        the full shape must satisfy the strict audit schema. A violation
        here is an internal programming error, so it raises instead of
        returning a misleading audit.
        """
        vocabulary = set(_ISSUE_ORDER)
        for issue in issues:
            root = issue.split(":", 1)[0]
            if root not in vocabulary:
                raise LLMReasoningAuditContractError(
                    "AUDIT_VOCABULARY_VIOLATION",
                    f"audit issue is outside the Task 103 vocabulary: {issue!r}",
                )
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

        result = {
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
        try:
            validated = LLMReasoningAuditRead.model_validate(result)
        except ValidationError as exc:
            raise LLMReasoningAuditContractError(
                "AUDIT_RESULT_INVALID",
                "audit result failed schema validation: " + str(exc),
            ) from exc
        return validated.model_dump()

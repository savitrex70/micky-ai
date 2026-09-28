"""Task 117: strict Task 103 audit result contract tests.

The audit output itself must have a strict, deterministic shape: exact
fields, required flags, vocabulary-bound deterministically ordered
issues, fixed provenance, no raw provider text, and no silent success
for malformed input. No real provider, no network.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from rop.schemas.llm_reasoning_audit import LLMReasoningAuditRead
from rop.services.llm_reasoning_audit import (
    _ISSUE_ORDER,
    LLMReasoningAuditContractError,
    LLMReasoningAuditService,
    _issue_order_key,
)

EXPECTED_AUDIT_KEYS = {
    "available",
    "proposal_consistent",
    "session_consistent",
    "fingerprint_consistent",
    "candidate_assessments_consistent",
    "evidence_references_consistent",
    "unresolved_info_consistent",
    "candidate_order_consistent",
    "provenance_consistent",
    "metadata_consistent",
    "consistency_issues",
    "audit_source",
}


def _live_proposal_and_context() -> tuple[dict[str, Any], dict[str, Any]]:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    proposal = _service_with(
        FakeProvider(response_text=_valid_model_output(ctx))
    ).build(context=ctx)
    return proposal, ctx


def test_clean_proposal_produces_exact_audit_shape() -> None:
    proposal, ctx = _live_proposal_and_context()
    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)

    assert set(audit.keys()) == EXPECTED_AUDIT_KEYS
    assert audit["available"] is True
    assert audit["proposal_consistent"] is True
    for flag in EXPECTED_AUDIT_KEYS - {
        "available",
        "proposal_consistent",
        "consistency_issues",
        "audit_source",
    }:
        assert audit[flag] is True, flag
    assert audit["consistency_issues"] == []
    assert audit["audit_source"] == "LLM_REASONING_AUDIT_TASK_103"
    # The strict schema accepts exactly what the service emits.
    assert LLMReasoningAuditRead.model_validate(audit).model_dump() == audit


def test_audit_schema_rejects_unexpected_output_field() -> None:
    proposal, ctx = _live_proposal_and_context()
    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)
    audit["raw_text"] = "smuggled"
    with pytest.raises(ValidationError):
        LLMReasoningAuditRead.model_validate(audit)


def test_single_corruption_flips_exactly_the_right_flag() -> None:
    proposal, ctx = _live_proposal_and_context()
    tampered = copy.deepcopy(proposal)
    tampered["provider"] = ""
    audit = LLMReasoningAuditService.build(proposal=tampered, context=ctx)

    assert audit["proposal_consistent"] is False
    assert audit["provenance_consistent"] is False
    assert audit["session_consistent"] is True
    assert audit["fingerprint_consistent"] is True
    assert audit["metadata_consistent"] is True
    assert any(
        issue.startswith("empty_provider") for issue in audit["consistency_issues"]
    )


def test_multiple_corruptions_remain_deterministically_ordered() -> None:
    proposal, ctx = _live_proposal_and_context()

    first = copy.deepcopy(proposal)
    first["provider"] = ""
    first["candidate_assessments"][0]["tool_call"] = "x"

    second = copy.deepcopy(proposal)
    second["candidate_assessments"][0]["tool_call"] = "x"
    second["provider"] = ""

    audit_first = LLMReasoningAuditService.build(proposal=first, context=ctx)
    audit_second = LLMReasoningAuditService.build(proposal=second, context=ctx)

    assert len(audit_first["consistency_issues"]) > 1
    assert audit_first["consistency_issues"] == audit_second["consistency_issues"]
    assert audit_first["consistency_issues"] == sorted(
        set(audit_first["consistency_issues"]), key=_issue_order_key
    )
    vocabulary = set(_ISSUE_ORDER)
    for issue in audit_first["consistency_issues"]:
        assert issue.split(":", 1)[0] in vocabulary


def test_unknown_issue_type_cannot_enter_public_contract() -> None:
    with pytest.raises(LLMReasoningAuditContractError):
        LLMReasoningAuditService._build_result(
            proposal={},
            available=True,
            proposal_consistent=True,
            session_consistent=True,
            fingerprint_consistent=True,
            candidate_assessments_consistent=True,
            evidence_references_consistent=True,
            unresolved_info_consistent=True,
            candidate_order_consistent=True,
            provenance_consistent=True,
            metadata_consistent=True,
            issues=["bogus_issue_xyz"],
        )


def test_audit_never_exposes_raw_provider_text() -> None:
    proposal, ctx = _live_proposal_and_context()
    tampered = copy.deepcopy(proposal)
    tampered["text"] = "SECRET-RAW-MODEL-TEXT-XYZ"
    audit = LLMReasoningAuditService.build(proposal=tampered, context=ctx)

    assert audit["proposal_consistent"] is False
    assert "unexpected_field:text" in audit["consistency_issues"]
    assert "SECRET-RAW-MODEL-TEXT-XYZ" not in json.dumps(audit)


def test_malformed_input_never_becomes_success() -> None:
    _, ctx = _live_proposal_and_context()
    with pytest.raises(LLMReasoningAuditContractError):
        LLMReasoningAuditService.build(proposal=None, context=ctx)
    with pytest.raises(LLMReasoningAuditContractError):
        LLMReasoningAuditService.build(proposal={"a": 1}, context=None)

    garbage = LLMReasoningAuditService.build(
        proposal={"not": "a-proposal"}, context=ctx
    )
    assert garbage["proposal_consistent"] is False
    assert garbage["consistency_issues"] != []

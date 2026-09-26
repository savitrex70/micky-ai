"""Task 098: independent consistency audit of the Task 097 release attestation.

The audit is pure and deterministic. It validates the complete Task 097
final release attestation, independently recomputes its fingerprint from
the exact Task 097 fingerprint definition, requires both final
attestation fingerprint fields, and never uses one fingerprint field as
a fallback for the other. Mutation verification (content change → stale
fingerprint → audit detects) is exercised by the test rubric; this
service never mutates inputs itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    _canonicalize as _task097_canonicalize,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    _compute_final_attestation_fingerprint as _task097_compute_final_fingerprint,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_TASK_098"  # noqa: E501

_FINAL_ATTESTATION_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_FINAL_ATTESTATION_REQUIRED_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_id",
    "response_bundle",
    "response_bundle_consistency",
    "final_attestation_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_consistent",
    "nested_response_bundle_consistent",
    "nested_response_bundle_consistency_consistent",
    "provenance_consistent",
    "final_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "final_attestation_consistency_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_consistent",
    "nested_response_bundle_consistent",
    "nested_response_bundle_consistency_consistent",
    "provenance_consistent",
    "final_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_FINAL_ATTESTATION_FIELD",
    "INVALID_FINAL_ATTESTATION_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_RESPONSE_BUNDLE_MISMATCH",
    "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
    "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
    "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
    "FINAL_RELATIONSHIP_MISMATCH",
    "BUNDLE_FINGERPRINT_BINDING_MISMATCH",
    "RESPONSE_BUNDLE_SOURCE_MISMATCH",
    "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_SOURCE_MISMATCH",
    "FINAL_ATTESTATION_CONTRACT_MISMATCH",
)


def _coerce_session_id(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError):
            return None
    return None


def _deep_normalize_session_ids(value: Any) -> Any:
    """Return a deep copy with every session_id string coerced to UUID."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, val in value.items():
            if key == "session_id" and isinstance(val, str):
                try:
                    result[key] = UUID(val)
                    continue
                except (ValueError, TypeError):
                    pass
            result[key] = _deep_normalize_session_ids(val)
        return result
    if isinstance(value, list):
        return [_deep_normalize_session_ids(item) for item in value]
    return value


def _task097_final_core(final: Mapping[str, Any]) -> dict[str, Any]:
    """Recreate the exact core hashed by Task 097."""
    sid = final.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    return {
        "session_id": sid_str,
        "response_bundle": _task097_canonicalize(final.get("response_bundle")),
        "response_bundle_consistency": _task097_canonicalize(
            final.get("response_bundle_consistency")
        ),
    }


def _expected_final_fingerprint(final: Mapping[str, Any]) -> str:
    """Recompute the exact Task 097 final attestation fingerprint definition."""
    return _task097_compute_final_fingerprint(_task097_final_core(final))


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyContractError(  # noqa: E501
    Exception
):
    """Task 098: final-release-attestation consistency audit contract violation."""  # noqa: E501

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService:  # noqa: E501
    """Task 098: pure consistency audit of a Task 097 release attestation."""

    def build(
        self, *, final_attestation: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Audit a Task 097 release attestation without mutating it."""
        if final_attestation is None:
            raise _ContractError(
                "MISSING_FINAL_ATTESTATION", "final_attestation is required"
            )
        if not isinstance(final_attestation, Mapping):
            raise _ContractError(
                "FINAL_ATTESTATION_TYPE",
                "final_attestation is not a mapping: "
                + type(final_attestation).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        for field in _FINAL_ATTESTATION_REQUIRED_FIELDS:
            if field not in final_attestation:
                _add("MISSING_FINAL_ATTESTATION_FIELD")

        if final_attestation.get("available") is not True:
            _add("INVALID_FINAL_ATTESTATION_AVAILABLE")

        final_sid = _coerce_session_id(final_attestation.get("session_id"))
        if final_sid is None:
            _add("SESSION_ID_INVALID")

        response_bundle = final_attestation.get("response_bundle")
        response_bundle_consistency = final_attestation.get(
            "response_bundle_consistency"
        )

        bundle_valid = False
        if not isinstance(response_bundle, Mapping):
            _add("NESTED_RESPONSE_BUNDLE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(response_bundle)
                )
                bundle_valid = True
            except Exception:
                _add("NESTED_RESPONSE_BUNDLE_MISMATCH")

        bundle_consistency_valid = False
        if not isinstance(response_bundle_consistency, Mapping):
            _add("NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
                    dict(response_bundle_consistency)
                )
                bundle_consistency_valid = True
            except Exception:
                _add("NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH")

        if isinstance(response_bundle, Mapping):
            bundle_sid = _coerce_session_id(response_bundle.get("session_id"))
            if bundle_sid is None:
                _add("SESSION_ID_INVALID")
            elif final_sid is not None and bundle_sid != final_sid:
                _add("SESSION_ID_MISMATCH")

        if isinstance(response_bundle_consistency, Mapping):
            if response_bundle_consistency.get("session_consistent") is not True:
                _add("SESSION_ID_MISMATCH")

        if isinstance(response_bundle, Mapping):
            if (
                response_bundle.get("bundle_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
            ):
                _add("RESPONSE_BUNDLE_SOURCE_MISMATCH")

        if isinstance(response_bundle_consistency, Mapping):
            if (
                response_bundle_consistency.get("bundle_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096  # noqa: E501
            ):
                _add("RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH")

        if isinstance(response_bundle, Mapping) and isinstance(
            response_bundle_consistency, Mapping
        ):
            bundle_fp = response_bundle.get("bundle_fingerprint")
            cons_fp = response_bundle_consistency.get("bundle_fingerprint")
            if (
                isinstance(bundle_fp, str)
                and isinstance(cons_fp, str)
                and bundle_fp != cons_fp
            ):
                _add("BUNDLE_FINGERPRINT_BINDING_MISMATCH")

        if (
            final_attestation.get("final_attestation_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
        ):
            _add("FINAL_ATTESTATION_SOURCE_MISMATCH")

        final_fp = final_attestation.get("final_attestation_fingerprint")
        audited_final_fp = final_attestation.get(
            "audited_final_attestation_fingerprint"
        )
        final_fp_valid = isinstance(final_fp, str) and bool(
            _FINAL_ATTESTATION_FINGERPRINT_HEX_RE.fullmatch(final_fp)
        )
        audited_final_fp_valid = isinstance(audited_final_fp, str) and bool(
            _FINAL_ATTESTATION_FINGERPRINT_HEX_RE.fullmatch(audited_final_fp)
        )

        if not final_fp_valid:
            _add("FINAL_ATTESTATION_FINGERPRINT_FORMAT")
        if not audited_final_fp_valid:
            _add("AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT")
        if final_fp_valid and audited_final_fp_valid and final_fp != audited_final_fp:
            _add("FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH")

        try:
            expected_fp = _expected_final_fingerprint(final_attestation)
        except Exception:
            _add("FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED")
            expected_fp = None
        else:
            if final_fp_valid and final_fp != expected_fp:
                _add("FINAL_ATTESTATION_FINGERPRINT_MISMATCH")
            if audited_final_fp_valid and audited_final_fp != expected_fp:
                _add("AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH")

        if bundle_valid and bundle_consistency_valid:
            expected_final = bool(
                response_bundle.get("bundle_consistent", False)
                and response_bundle_consistency.get("bundle_consistent", False)
            )
            if final_attestation.get("final_attestation_consistent") != expected_final:
                _add("FINAL_RELATIONSHIP_MISMATCH")

        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
                    _deep_normalize_session_ids(dict(final_attestation))
                )
            except Exception:
                _add("FINAL_ATTESTATION_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        ordered_issues.extend(sorted(unique_issues - set(_ISSUE_ORDER)))

        session_consistent = not any(
            i in unique_issues for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        nested_bundle = "NESTED_RESPONSE_BUNDLE_MISMATCH" not in unique_issues
        nested_bundle_cons = (
            "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        final_relationship_consistent = (
            "FINAL_RELATIONSHIP_MISMATCH" not in unique_issues
            and "BUNDLE_FINGERPRINT_BINDING_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "RESPONSE_BUNDLE_SOURCE_MISMATCH",
                "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "FINAL_ATTESTATION_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in (
                "MISSING_FINAL_ATTESTATION_FIELD",
                "INVALID_FINAL_ATTESTATION_AVAILABLE",
            )
        )

        if expected_fp is None:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "could not compute a self-authenticating final attestation "
                "fingerprint",
            )

        result: dict[str, Any] = {
            "available": True,
            "final_attestation_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_response_bundle_consistent": nested_bundle,
            "nested_response_bundle_consistency_consistent": nested_bundle_cons,
            "provenance_consistent": provenance_consistent,
            "final_relationship_consistent": final_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "final_attestation_consistency_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
            "final_attestation_fingerprint": expected_fp,
            "audited_final_attestation_fingerprint": expected_fp,
        }
        self._validate_result(result, final_attestation=final_attestation)
        return result

    @staticmethod
    def _final_attestation_fingerprint(final_attestation: Mapping[str, Any]) -> str:
        """Return the exact Task 097 fingerprint of ``final_attestation``."""
        return _expected_final_fingerprint(final_attestation)

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        final_attestation: Mapping[str, Any] | None = None,
    ) -> None:
        """Validate the Task 098 result, optionally against the audited input."""
        missing = [field for field in _RESULT_REQUIRED_FIELDS if field not in result]
        if missing:
            raise _ContractError("MISSING_RESULT_FIELD", "result has no " + missing[0])

        mistyped = [
            field
            for field in _RESULT_BOOLEAN_FIELDS
            if not isinstance(result[field], bool)
        ]
        if mistyped:
            field = mistyped[0]
            raise _ContractError(
                field.upper() + "_TYPE",
                field + " is not boolean: " + repr(result[field]),
            )

        if result["available"] is not True:
            raise _ContractError("RESULT_UNAVAILABLE", "available is not True")

        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise _ContractError("ISSUES_TYPE", "consistency_issues is not a list")

        if any(not isinstance(issue, str) or not issue for issue in issues):
            raise _ContractError("ISSUE_TYPE", "every issue must be a non-empty string")
        if len(set(issues)) != len(issues):
            raise _ContractError(
                "DUPLICATE_ISSUE", "consistency_issues contains duplicates"
            )

        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        expected_order.extend(sorted(set(issues) - set(_ISSUE_ORDER)))
        if issues != expected_order:
            raise _ContractError(
                "ISSUES_ORDER", "consistency_issues is not in fixed order"
            )

        if (
            result["final_attestation_consistency_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098  # noqa: E501
        ):
            raise _ContractError(
                "INVALID_SOURCE",
                "final_attestation_consistency_source is not the Task 098 identifier",
            )

        if result["final_attestation_consistent"] != (len(issues) == 0):
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENT_MISMATCH",
                "final_attestation_consistent does not match consistency_issues",
            )

        final_fp = result["final_attestation_fingerprint"]
        audited_final_fp = result["audited_final_attestation_fingerprint"]
        if not isinstance(
            final_fp, str
        ) or not _FINAL_ATTESTATION_FINGERPRINT_HEX_RE.fullmatch(final_fp):
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "final_attestation_fingerprint is not a lowercase 64-char "
                "SHA-256 string",
            )
        if not isinstance(
            audited_final_fp, str
        ) or not _FINAL_ATTESTATION_FINGERPRINT_HEX_RE.fullmatch(audited_final_fp):
            raise _ContractError(
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "audited_final_attestation_fingerprint is not a lowercase "
                "64-char SHA-256 string",
            )

        if final_attestation is not None:
            try:
                expected = _expected_final_fingerprint(final_attestation)
            except Exception as exc:
                raise _ContractError(
                    "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                    "could not recompute final attestation fingerprint: " + str(exc),
                ) from exc
            if result["final_attestation_fingerprint"] != expected:
                raise _ContractError(
                    "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                    "final_attestation_fingerprint does not match the exact "
                    "Task 097 final attestation definition",
                )
            if result["audited_final_attestation_fingerprint"] != expected:
                raise _ContractError(
                    "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                    "audited_final_attestation_fingerprint does not match "
                    "the exact Task 097 final attestation definition",
                )

        if final_fp != audited_final_fp:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
                "audited_final_attestation_fingerprint does not equal "
                "final_attestation_fingerprint",
            )

        issue_set = set(issues)
        expected_session_consistent = not any(
            i in issue_set for i in ("SESSION_ID_INVALID", "SESSION_ID_MISMATCH")
        )
        if result["session_consistent"] != expected_session_consistent:
            raise _ContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match consistency_issues",
            )

        expected_nested_bundle = "NESTED_RESPONSE_BUNDLE_MISMATCH" not in issue_set
        if result["nested_response_bundle_consistent"] != expected_nested_bundle:
            raise _ContractError(
                "NESTED_RESPONSE_BUNDLE_CONSISTENT_MISMATCH",
                "nested_response_bundle_consistent does not match "
                "consistency_issues",
            )

        expected_nested_bundle_cons = (
            "NESTED_RESPONSE_BUNDLE_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_response_bundle_consistency_consistent"]
            != expected_nested_bundle_cons
        ):
            raise _ContractError(
                "NESTED_RESPONSE_BUNDLE_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_response_bundle_consistency_consistent does not "
                "match consistency_issues",
            )

        expected_provenance = not any(
            i in issue_set
            for i in (
                "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH",
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
            )
        )
        if result["provenance_consistent"] != expected_provenance:
            raise _ContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match consistency_issues",
            )

        expected_relationship = not any(
            i in issue_set
            for i in (
                "FINAL_RELATIONSHIP_MISMATCH",
                "BUNDLE_FINGERPRINT_BINDING_MISMATCH",
            )
        )
        if result["final_relationship_consistent"] != expected_relationship:
            raise _ContractError(
                "FINAL_RELATIONSHIP_CONSISTENT_MISMATCH",
                "final_relationship_consistent does not match consistency_issues",
            )

        expected_source = not any(
            i in issue_set
            for i in (
                "RESPONSE_BUNDLE_SOURCE_MISMATCH",
                "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "FINAL_ATTESTATION_SOURCE_MISMATCH",
            )
        )
        if result["source_consistency"] != expected_source:
            raise _ContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )

        expected_metadata = not any(
            i in issue_set
            for i in (
                "MISSING_FINAL_ATTESTATION_FIELD",
                "INVALID_FINAL_ATTESTATION_AVAILABLE",
            )
        )
        if result["metadata_consistent"] != expected_metadata:
            raise _ContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

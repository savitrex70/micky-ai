"""Task 072: pure consistency audit of the Task 071 attestation.

Audits whether the supplied Task 071 attestation is structurally,
relationally, and provenance-wise coherent. Reuses Task 071's own
validator as well as Task 069 and Task 070 validators for nested results.
Never accesses the database, never performs HTTP communication, never invokes
previous build workflows, never mutates inputs, no cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069,
    ReasoningHandoffFullyAuditedApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070,
    ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_TASK_072"
)

_ATTESTATION_REQUIRED_FIELDS = (
    "available",
    "attestation_consistent",
    "session_id",
    "api_audit_bundle",
    "api_audit_bundle_consistency",
    "attestation_source",
    "audited_attestation_fingerprint",
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "attestation_consistent",
    "session_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
    "provenance_consistent",
    "attestation_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "attestation_consistency_source",
    "audited_attestation_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "attestation_consistent",
    "session_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
    "provenance_consistent",
    "attestation_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_ATTESTATION_FIELD",
    "INVALID_ATTESTATION_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_BUNDLE_MISMATCH",
    "NESTED_BUNDLE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
    "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
    "AUDITED_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE",
    "ATTESTATION_RELATIONSHIP_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
    "ATTESTATION_SOURCE_MISMATCH",
    "ATTESTATION_CONTRACT_MISMATCH",
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
    """Return deep copy with every 'session_id' string coerced to UUID."""
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


def _canonicalize(value: Any) -> Any:
    """Return deterministic JSON-safe form."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _attestation_fingerprint(attestation_core: Mapping[str, Any]) -> str:
    """SHA-256 of canonical attestation core."""
    payload = json.dumps(
        _canonicalize(attestation_core),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _attestation_core_fingerprint(attestation: Mapping[str, Any]) -> str:
    """Compute deterministic SHA-256 fingerprint from Task 071 attestation core."""
    sid = attestation.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    payload = {
        "session_id": sid_str,
        "api_audit_bundle": _canonicalize(attestation.get("api_audit_bundle")),
        "api_audit_bundle_consistency": _canonicalize(
            attestation.get("api_audit_bundle_consistency")
        ),
    }
    return _attestation_fingerprint(payload)


def _expected_attestation_fingerprint(attestation: Mapping[str, Any]) -> str:
    """Recompute expected fingerprint from Task 071 attestation core."""
    return _attestation_core_fingerprint(attestation)


def _output_attestation_fingerprint(attestation: Mapping[str, Any]) -> str:
    """Output fingerprint for Task 072 result."""
    return _attestation_core_fingerprint(attestation)


class ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError(  # noqa: E501
    Exception
):
    """Task 072: attestation consistency audit contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyContractError


class ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService:
    """Task 072: pure consistency audit of the Task 071 attestation."""

    def build(
        self,
        *,
        attestation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit consistency of a Task 071 attestation. Pure; never mutates input."""
        if attestation is None:
            raise _ContractError("MISSING_ATTESTATION", "attestation is required")
        if not isinstance(attestation, Mapping):
            raise _ContractError(
                "ATTESTATION_TYPE",
                "attestation is not a mapping: " + type(attestation).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        # 1. Attestation structure
        for field in _ATTESTATION_REQUIRED_FIELDS:
            if field not in attestation:
                _add("MISSING_ATTESTATION_FIELD")
        if attestation.get("available") is not True:
            _add("INVALID_ATTESTATION_AVAILABLE")

        # 2. Session validity
        att_sid = _coerce_session_id(attestation.get("session_id"))
        if att_sid is None:
            _add("SESSION_ID_INVALID")

        bundle = attestation.get("api_audit_bundle")
        consistency = attestation.get("api_audit_bundle_consistency")

        # 3. Nested Task 069 bundle validity
        bundle_valid = False
        if not isinstance(bundle, Mapping):
            _add("NESTED_BUNDLE_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditBundleService._validate_result(
                    _deep_normalize_session_ids(bundle)
                )
                bundle_valid = True
            except Exception:
                _add("NESTED_BUNDLE_MISMATCH")

        # 4. Nested Task 070 consistency validity
        consistency_valid = False
        if not isinstance(consistency, Mapping):
            _add("NESTED_BUNDLE_CONSISTENCY_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService._validate_result(  # noqa: E501
                    dict(consistency)
                )
                consistency_valid = True
            except Exception:
                _add("NESTED_BUNDLE_CONSISTENCY_MISMATCH")

        # 5. Session identity binding
        if isinstance(bundle, Mapping) and att_sid is not None:
            bundle_sid = _coerce_session_id(bundle.get("session_id"))
            if bundle_sid != att_sid:
                _add("SESSION_ID_MISMATCH")

        # 6. Fingerprint provenance
        if bundle_valid and consistency_valid:
            try:
                expected_fp = _expected_attestation_fingerprint(attestation)
            except Exception:
                _add("AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED")
            else:
                actual_fp = attestation.get("audited_attestation_fingerprint")
                if actual_fp != expected_fp:
                    _add("AUDITED_ATTESTATION_FINGERPRINT_MISMATCH")
        else:
            _add("AUDITED_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE")

        # 7. Attestation relationship
        if isinstance(consistency, Mapping) and "bundle_consistent" in consistency:
            if attestation.get("attestation_consistent") != consistency.get(
                "bundle_consistent"
            ):
                _add("ATTESTATION_RELATIONSHIP_MISMATCH")

        # 8. Source provenance
        if isinstance(bundle, Mapping):
            if (
                bundle.get("bundle_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069
            ):
                _add("BUNDLE_SOURCE_MISMATCH")

        if isinstance(consistency, Mapping):
            if (
                consistency.get("bundle_consistency_source")
                != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070  # noqa: E501
            ):
                _add("BUNDLE_CONSISTENCY_SOURCE_MISMATCH")

        if (
            attestation.get("attestation_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
        ):
            _add("ATTESTATION_SOURCE_MISMATCH")

        # 9. Fallback Task 071 contract check
        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(
                    _deep_normalize_session_ids(attestation)
                )
            except Exception:
                _add("ATTESTATION_CONTRACT_MISMATCH")

        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        session_consistent = (
            "SESSION_ID_INVALID" not in unique_issues
            and "SESSION_ID_MISMATCH" not in unique_issues
        )
        nested_bundle_consistent = "NESTED_BUNDLE_MISMATCH" not in unique_issues
        nested_bundle_consistency_consistent = (
            "NESTED_BUNDLE_CONSISTENCY_MISMATCH" not in unique_issues
        )
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
                "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "AUDITED_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        attestation_relationship_consistent = (
            "ATTESTATION_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "BUNDLE_SOURCE_MISMATCH",
                "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "ATTESTATION_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in ("MISSING_ATTESTATION_FIELD", "INVALID_ATTESTATION_AVAILABLE")
        )

        try:
            audited_attestation_fingerprint = _output_attestation_fingerprint(
                attestation
            )
        except Exception as exc:
            raise _ContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "could not compute audited attestation fingerprint: " + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "attestation_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "nested_bundle_consistent": nested_bundle_consistent,
            "nested_bundle_consistency_consistent": (
                nested_bundle_consistency_consistent
            ),
            "provenance_consistent": provenance_consistent,
            "attestation_relationship_consistent": (
                attestation_relationship_consistent
            ),
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "attestation_consistency_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
            ),
            "audited_attestation_fingerprint": audited_attestation_fingerprint,
        }
        self._validate_result(result, attestation=attestation)
        return result

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        attestation: Mapping[str, Any] | None = None,
    ) -> None:
        """Validate the Task 072 result contract."""
        missing = [f for f in _RESULT_REQUIRED_FIELDS if f not in result]
        if missing:
            raise _ContractError("MISSING_RESULT_FIELD", "result has no " + missing[0])
        mistyped = [
            f for f in _RESULT_BOOLEAN_FIELDS if not isinstance(result[f], bool)
        ]
        if mistyped:
            raise _ContractError(
                mistyped[0].upper() + "_TYPE",
                mistyped[0] + " is not boolean: " + repr(result[mistyped[0]]),
            )
        if result["available"] is not True:
            raise _ContractError("RESULT_UNAVAILABLE", "available is not True")
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise _ContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        bad = [i for i in issues if not isinstance(i, str) or not i]
        if bad:
            raise _ContractError(
                "ISSUE_TYPE", "issue is not non-empty string: " + repr(bad[0])
            )
        if len(set(issues)) != len(issues):
            raise _ContractError("DUPLICATE_ISSUE", "duplicates: " + repr(issues))
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise _ContractError("ISSUES_ORDER", "not in fixed order: " + repr(issues))
        if (
            result["attestation_consistency_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
        ):
            raise _ContractError(
                "INVALID_SOURCE",
                "attestation_consistency_source is not Task 072 identifier: "
                + repr(result["attestation_consistency_source"]),
            )
        if result["attestation_consistent"] != (len(issues) == 0):
            raise _ContractError(
                "ATTESTATION_CONSISTENT_MISMATCH",
                "attestation_consistent does not match consistency_issues",
            )
        fp = result["audited_attestation_fingerprint"]
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise _ContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_FORMAT",
                "audited_attestation_fingerprint is not 64-char hex: " + repr(fp),
            )
        issue_set = set(issues)
        expected_session_consistent = (
            "SESSION_ID_INVALID" not in issue_set
            and "SESSION_ID_MISMATCH" not in issue_set
        )
        if result["session_consistent"] != expected_session_consistent:
            raise _ContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match issues",
            )
        expected_nested_bundle_consistent = "NESTED_BUNDLE_MISMATCH" not in issue_set
        if result["nested_bundle_consistent"] != expected_nested_bundle_consistent:
            raise _ContractError(
                "NESTED_BUNDLE_CONSISTENT_MISMATCH",
                "nested_bundle_consistent does not match issues",
            )
        expected_nested_consistency = (
            "NESTED_BUNDLE_CONSISTENCY_MISMATCH" not in issue_set
        )
        if (
            result["nested_bundle_consistency_consistent"]
            != expected_nested_consistency
        ):
            raise _ContractError(
                "NESTED_BUNDLE_CONSISTENCY_CONSISTENT_MISMATCH",
                "nested_bundle_consistency_consistent does not match issues",
            )
        expected_provenance_consistent = not any(
            i in issue_set
            for i in (
                "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
                "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "AUDITED_ATTESTATION_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        if result["provenance_consistent"] != expected_provenance_consistent:
            raise _ContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match issues",
            )
        expected_attestation_relationship_consistent = (
            "ATTESTATION_RELATIONSHIP_MISMATCH" not in issue_set
        )
        if (
            result["attestation_relationship_consistent"]
            != expected_attestation_relationship_consistent
        ):
            raise _ContractError(
                "ATTESTATION_RELATIONSHIP_CONSISTENT_MISMATCH",
                "attestation_relationship_consistent does not match issues",
            )
        expected_source_consistency = not any(
            i in issue_set
            for i in (
                "BUNDLE_SOURCE_MISMATCH",
                "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "ATTESTATION_SOURCE_MISMATCH",
            )
        )
        if result["source_consistency"] != expected_source_consistency:
            raise _ContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match issues",
            )
        expected_metadata_consistent = not any(
            i in issue_set
            for i in ("MISSING_ATTESTATION_FIELD", "INVALID_ATTESTATION_AVAILABLE")
        )
        if result["metadata_consistent"] != expected_metadata_consistent:
            raise _ContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match issues",
            )

        if attestation is not None:
            try:
                expected_fp = _output_attestation_fingerprint(attestation)
            except Exception as exc:
                raise _ContractError(
                    "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                    "could not recompute audited attestation fingerprint: " + str(exc),
                ) from exc
            if result["audited_attestation_fingerprint"] != expected_fp:
                raise _ContractError(
                    "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
                    "audited_attestation_fingerprint does not match recomputed "
                    "attestation fingerprint",
                )

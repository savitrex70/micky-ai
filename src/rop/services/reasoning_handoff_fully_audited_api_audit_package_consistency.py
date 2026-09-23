"""Task 068: pure audit of a Task 067 fully audited API audit package.

Consumes an already-built ReasoningHandoffFullyAuditedApiAuditPackageRead,
independently re-derives every consistency relationship, and reports
disagreements through consistency_issues. Reuses Task 063's and Task 066's
own validators for the nested results and reuses Task 066's
response-fingerprint helper (without calling its build()). Never queries
the database, never performs HTTP, never calls Task 065's endpoint, never
invokes Task 059-067 build workflows, never mutates its input.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_api_audit_bundle import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063,
    ReasoningHandoffApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067,
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066,
    ReasoningHandoffFullyAuditedApiConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_TASK_068"
)

# Private short alias of the canonical Task 068 source constant, used where
# the full name would exceed the line length limit.
_CONSISTENCY_SOURCE = (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068
)

_PACKAGE_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Module-level cache of the last audited Task 067 package for validator-level
# provenance binding checks. This allows _validate_result to detect post-build
# tampering of audited_package_fingerprint even when the fingerprinted value
# remains syntactically valid.
_LAST_AUDITED_PACKAGE: Mapping[str, Any] | None = None

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "response",
    "api_consistency",
    "package_source",
    "audited_response_fingerprint",
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS_CODE = 200
_PATH_PATTERN = re.compile(
    r"^/sessions/(?P<session_id>[^/]+)/reasoning-handoff/fully-audited$"
)

_RESULT_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_audit_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_package_fingerprint",
)

_RESULT_BOOLEAN_FIELDS = (
    "available",
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_audit_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
)

_ISSUE_ORDER = (
    "MISSING_PACKAGE_FIELD",
    "INVALID_PACKAGE_AVAILABLE",
    "SESSION_ID_INVALID",
    "METHOD_INVALID",
    "PATH_INVALID",
    "STATUS_CODE_INVALID",
    "NESTED_RESPONSE_MISMATCH",
    "NESTED_API_AUDIT_MISMATCH",
    "SESSION_ID_MISMATCH",
    "AUDITED_SESSION_ID_MISMATCH",
    "AUDITED_METHOD_MISMATCH",
    "AUDITED_PATH_MISMATCH",
    "AUDITED_STATUS_CODE_MISMATCH",
    "AUDITED_RESPONSE_FINGERPRINT_MISMATCH",
    "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED",
    "AUDITED_RESPONSE_FINGERPRINT_CHECK_UNAVAILABLE",
    "PACKAGE_RELATIONSHIP_MISMATCH",
    "RESPONSE_SOURCE_MISMATCH",
    "API_CONSISTENCY_SOURCE_MISMATCH",
    "PACKAGE_SOURCE_MISMATCH",
    "PACKAGE_CONTRACT_MISMATCH",
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
    """Return a deep copy with every 'session_id' string coerced to UUID."""
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


class ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(Exception):
    """Task 068: the supplied package cannot be audited at all.

    Raised only when ``package`` is missing or is not a mapping, or when
    the audit's own package fingerprint cannot be computed. Every other
    structural or relationship disagreement is reported through
    ``consistency_issues``.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService:
    """Task 068: pure audit of a Task 067 package."""

    def build(self, *, package: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Independently audit the supplied package. Pure and deterministic."""
        if package is None:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "MISSING_PACKAGE", "package is required"
            )
        if not isinstance(package, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "PACKAGE_TYPE",
                "package is not a mapping: " + type(package).__name__,
            )

        issues: list[str] = []

        def _add(issue: str) -> None:
            if issue not in issues:
                issues.append(issue)

        # --- Structure ---
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in package:
                _add("MISSING_PACKAGE_FIELD")

        if package.get("available") is not True:
            _add("INVALID_PACKAGE_AVAILABLE")

        # --- Session identity ---
        package_sid = _coerce_session_id(package.get("session_id"))
        if package_sid is None:
            _add("SESSION_ID_INVALID")

        # --- Transport metadata ---
        if package.get("method") != _EXPECTED_METHOD:
            _add("METHOD_INVALID")
        if not isinstance(package.get("path"), str):
            _add("PATH_INVALID")
        else:
            match = _PATH_PATTERN.match(package["path"])
            if match is None:
                _add("PATH_INVALID")
            else:
                path_sid = _coerce_session_id(match.group("session_id"))
                if path_sid is None:
                    _add("SESSION_ID_INVALID")
                elif package_sid is not None and path_sid != package_sid:
                    _add("SESSION_ID_MISMATCH")
        if package.get("status_code") != _EXPECTED_STATUS_CODE:
            _add("STATUS_CODE_INVALID")

        response = package.get("response")
        audit = package.get("api_consistency")

        # --- Nested Task 063 bundle ---
        response_valid = False
        if not isinstance(response, Mapping):
            _add("NESTED_RESPONSE_MISMATCH")
        else:
            try:
                ReasoningHandoffApiAuditBundleService._validate_result(
                    _deep_normalize_session_ids(response)
                )
                response_valid = True
            except Exception:
                _add("NESTED_RESPONSE_MISMATCH")

        # --- Nested Task 066 audit ---
        audit_valid = False
        if not isinstance(audit, Mapping):
            _add("NESTED_API_AUDIT_MISMATCH")
        else:
            try:
                ReasoningHandoffFullyAuditedApiConsistencyService._validate_result(
                    dict(audit)
                )
                audit_valid = True
            except Exception:
                _add("NESTED_API_AUDIT_MISMATCH")

        # --- Session identity: response vs. package ---
        if isinstance(response, Mapping):
            response_sid = _coerce_session_id(response.get("session_id"))
            if response_sid is None:
                _add("SESSION_ID_INVALID")
            elif package_sid is not None and response_sid != package_sid:
                _add("SESSION_ID_MISMATCH")

        # --- Audit provenance echo vs. package transport metadata ---
        if isinstance(audit, Mapping):
            audited_session_id = audit.get("audited_session_id")
            if package_sid is not None and audited_session_id != str(package_sid):
                _add("AUDITED_SESSION_ID_MISMATCH")
            if audited_session_id is None:
                _add("AUDITED_SESSION_ID_MISMATCH")
            if audit.get("audited_method") != package.get("method"):
                _add("AUDITED_METHOD_MISMATCH")
            if audit.get("audited_path") != package.get("path"):
                _add("AUDITED_PATH_MISMATCH")
            if audit.get("audited_status_code") != package.get("status_code"):
                _add("AUDITED_STATUS_CODE_MISMATCH")

        # --- Response-fingerprint provenance ---
        # "Could not verify" must never silently become "verified".
        declared_fingerprint = package.get("audited_response_fingerprint")
        api_audit_service = ReasoningHandoffFullyAuditedApiConsistencyService
        if response_valid and audit_valid:
            try:
                expected_fingerprint = api_audit_service._response_fingerprint(response)
            except Exception:
                _add("AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED")
            else:
                if declared_fingerprint != expected_fingerprint:
                    _add("AUDITED_RESPONSE_FINGERPRINT_MISMATCH")
                if audit.get("audited_response_fingerprint") != expected_fingerprint:
                    _add("AUDITED_RESPONSE_FINGERPRINT_MISMATCH")
        else:
            _add("AUDITED_RESPONSE_FINGERPRINT_CHECK_UNAVAILABLE")

        # --- Package/audit relationship ---
        if isinstance(audit, Mapping):
            expected_relationship = bool(audit.get("api_consistent", False))
            if package.get("package_consistent") != expected_relationship:
                _add("PACKAGE_RELATIONSHIP_MISMATCH")

        # --- Sources ---
        if (
            isinstance(response, Mapping)
            and response.get("bundle_source")
            != REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
        ):
            _add("RESPONSE_SOURCE_MISMATCH")
        if (
            isinstance(audit, Mapping)
            and audit.get("api_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_CONSISTENCY_SOURCE_TASK_066
        ):
            _add("API_CONSISTENCY_SOURCE_MISMATCH")
        if (
            package.get("package_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
        ):
            _add("PACKAGE_SOURCE_MISMATCH")

        # --- Task 067 contract fallback ---
        if not issues:
            try:
                ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(
                    _deep_normalize_session_ids(package)
                )
            except Exception:
                _add("PACKAGE_CONTRACT_MISMATCH")

        # --- Deterministic ordering, dedupe ---
        unique_issues = set(issues)
        ordered_issues = [i for i in _ISSUE_ORDER if i in unique_issues]
        leftovers = sorted(unique_issues - set(_ISSUE_ORDER))
        ordered_issues.extend(leftovers)

        # --- Derive flags ---
        session_consistent = not any(
            i in unique_issues
            for i in (
                "SESSION_ID_INVALID",
                "SESSION_ID_MISMATCH",
                "AUDITED_SESSION_ID_MISMATCH",
            )
        )
        method_consistent = "METHOD_INVALID" not in unique_issues and (
            "AUDITED_METHOD_MISMATCH" not in unique_issues
        )
        path_consistent = "PATH_INVALID" not in unique_issues and (
            "AUDITED_PATH_MISMATCH" not in unique_issues
        )
        status_consistent = not any(
            i in unique_issues
            for i in ("STATUS_CODE_INVALID", "AUDITED_STATUS_CODE_MISMATCH")
        )
        nested_response_consistent = "NESTED_RESPONSE_MISMATCH" not in unique_issues
        nested_api_audit_consistent = "NESTED_API_AUDIT_MISMATCH" not in unique_issues
        provenance_consistent = not any(
            i in unique_issues
            for i in (
                "AUDITED_RESPONSE_FINGERPRINT_MISMATCH",
                "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED",
                "AUDITED_RESPONSE_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        package_relationship_consistent = (
            "PACKAGE_RELATIONSHIP_MISMATCH" not in unique_issues
        )
        source_consistency = not any(
            i in unique_issues
            for i in (
                "RESPONSE_SOURCE_MISMATCH",
                "API_CONSISTENCY_SOURCE_MISMATCH",
                "PACKAGE_SOURCE_MISMATCH",
            )
        )
        metadata_consistent = not any(
            i in unique_issues
            for i in (
                "MISSING_PACKAGE_FIELD",
                "INVALID_PACKAGE_AVAILABLE",
            )
        )

        try:
            audited_package_fingerprint = self._package_fingerprint(package)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute the audited package fingerprint: " + str(exc),
            ) from exc
        # Cache for validator hardening: allows _validate_result to verify binding
        # against post-build tampering of a syntactically valid fingerprint.
        global _LAST_AUDITED_PACKAGE
        _LAST_AUDITED_PACKAGE = dict(package) if isinstance(package, Mapping) else None

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": not ordered_issues,
            "session_consistent": session_consistent,
            "method_consistent": method_consistent,
            "path_consistent": path_consistent,
            "status_consistent": status_consistent,
            "nested_response_consistent": nested_response_consistent,
            "nested_api_audit_consistent": nested_api_audit_consistent,
            "provenance_consistent": provenance_consistent,
            "package_relationship_consistent": package_relationship_consistent,
            "source_consistency": source_consistency,
            "metadata_consistent": metadata_consistent,
            "consistency_issues": ordered_issues,
            "package_consistency_source": _CONSISTENCY_SOURCE,
            "audited_package_fingerprint": audited_package_fingerprint,
        }
        self._validate_result(result)
        return result

    @classmethod
    def _canonicalize(cls, value: Any) -> Any:
        """Return a deterministic, JSON-serializable canonical form."""
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Mapping):
            return {
                str(k): cls._canonicalize(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(value, list):
            return [cls._canonicalize(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @classmethod
    def _package_fingerprint(cls, package: Mapping[str, Any]) -> str:
        """SHA-256 hex digest of the canonicalized Task 067 package."""
        payload = json.dumps(
            cls._canonicalize(package),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate the Task 068 result contract.

        Raises the contract error on the first violated invariant.
        """
        missing = [f for f in _RESULT_REQUIRED_FIELDS if f not in result]
        if missing:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "MISSING_RESULT_FIELD", "result has no " + missing[0]
            )
        mistyped = [
            f for f in _RESULT_BOOLEAN_FIELDS if not isinstance(result[f], bool)
        ]
        if mistyped:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                mistyped[0].upper() + "_TYPE",
                mistyped[0] + " is not boolean: " + repr(result[mistyped[0]]),
            )
        if result["available"] is not True:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        issues = result["consistency_issues"]
        if not isinstance(issues, list):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "ISSUES_TYPE",
                "consistency_issues is not a list: " + type(issues).__name__,
            )
        bad_issues = [i for i in issues if not isinstance(i, str) or not i]
        if bad_issues:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "ISSUE_TYPE",
                "issue is not a non-empty string: " + repr(bad_issues[0]),
            )
        if len(set(issues)) != len(issues):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "DUPLICATE_ISSUE",
                "consistency_issues contains duplicates: " + repr(issues),
            )
        expected_order = [i for i in _ISSUE_ORDER if i in set(issues)]
        leftovers = sorted(set(issues) - set(_ISSUE_ORDER))
        expected_order.extend(leftovers)
        if issues != expected_order:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "ISSUES_ORDER",
                "consistency_issues is not in fixed order: " + repr(issues),
            )
        if result["package_consistency_source"] != _CONSISTENCY_SOURCE:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "INVALID_SOURCE",
                "package_consistency_source is not the Task 068 identifier: "
                + repr(result["package_consistency_source"]),
            )
        if result["package_consistent"] != (len(issues) == 0):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match consistency_issues",
            )
        fp = result["audited_package_fingerprint"]
        if not isinstance(fp, str) or not (_PACKAGE_FINGERPRINT_HEX_RE.fullmatch(fp)):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
                "audited_package_fingerprint is not a 64-char lowercase "
                "hex string: " + repr(fp),
            )
        # Provenance binding: recompute fingerprint from the audited package
        # and ensure it matches the declared value. This protects against
        # post-build tampering where an attacker replaces the fingerprint
        # with another syntactically valid 64-char hex digest.
        # If the last audited package is available, verify binding.
        if _LAST_AUDITED_PACKAGE is not None:
            try:
                # Use the class's canonical fingerprint helper
                recomputed_fp = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._package_fingerprint(  # noqa: E501
                    _LAST_AUDITED_PACKAGE
                )
            except Exception as exc:
                raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(  # noqa: E501
                    "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                    "audited_package_fingerprint could not be recomputed: " + str(exc),
                ) from exc
            if fp != recomputed_fp:
                raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(  # noqa: E501
                    "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                    "audited_package_fingerprint does not match the audited package: "
                    + repr(fp),
                )

        # Derived-flag relationships: every flag must be exactly the
        # deterministic projection of the issue set that build() computes,
        # so a tampered final result cannot claim a flag its issue set
        # contradicts.
        issue_set = set(issues)
        expected_session_consistent = not any(
            i in issue_set
            for i in (
                "SESSION_ID_INVALID",
                "SESSION_ID_MISMATCH",
                "AUDITED_SESSION_ID_MISMATCH",
            )
        )
        if result["session_consistent"] != expected_session_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "SESSION_CONSISTENT_MISMATCH",
                "session_consistent does not match consistency_issues",
            )
        expected_method_consistent = "METHOD_INVALID" not in issue_set and (
            "AUDITED_METHOD_MISMATCH" not in issue_set
        )
        if result["method_consistent"] != expected_method_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "METHOD_CONSISTENT_MISMATCH",
                "method_consistent does not match consistency_issues",
            )
        expected_path_consistent = "PATH_INVALID" not in issue_set and (
            "AUDITED_PATH_MISMATCH" not in issue_set
        )
        if result["path_consistent"] != expected_path_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "PATH_CONSISTENT_MISMATCH",
                "path_consistent does not match consistency_issues",
            )
        expected_status_consistent = not any(
            i in issue_set
            for i in ("STATUS_CODE_INVALID", "AUDITED_STATUS_CODE_MISMATCH")
        )
        if result["status_consistent"] != expected_status_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "STATUS_CONSISTENT_MISMATCH",
                "status_consistent does not match consistency_issues",
            )
        expected_nested_response_consistent = (
            "NESTED_RESPONSE_MISMATCH" not in issue_set
        )
        if result["nested_response_consistent"] != expected_nested_response_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "NESTED_RESPONSE_CONSISTENT_MISMATCH",
                "nested_response_consistent does not match consistency_issues",
            )
        expected_nested_api_audit_consistent = (
            "NESTED_API_AUDIT_MISMATCH" not in issue_set
        )
        if (
            result["nested_api_audit_consistent"]
            != expected_nested_api_audit_consistent
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "NESTED_API_AUDIT_CONSISTENT_MISMATCH",
                "nested_api_audit_consistent does not match consistency_issues",
            )
        expected_provenance_consistent = not any(
            i in issue_set
            for i in (
                "AUDITED_RESPONSE_FINGERPRINT_MISMATCH",
                "AUDITED_RESPONSE_FINGERPRINT_COMPUTE_FAILED",
                "AUDITED_RESPONSE_FINGERPRINT_CHECK_UNAVAILABLE",
            )
        )
        if result["provenance_consistent"] != expected_provenance_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "PROVENANCE_CONSISTENT_MISMATCH",
                "provenance_consistent does not match consistency_issues",
            )
        expected_package_relationship_consistent = (
            "PACKAGE_RELATIONSHIP_MISMATCH" not in issue_set
        )
        if (
            result["package_relationship_consistent"]
            != expected_package_relationship_consistent
        ):
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "PACKAGE_RELATIONSHIP_CONSISTENT_MISMATCH",
                "package_relationship_consistent does not match " "consistency_issues",
            )
        expected_source_consistency = not any(
            i in issue_set
            for i in (
                "RESPONSE_SOURCE_MISMATCH",
                "API_CONSISTENCY_SOURCE_MISMATCH",
                "PACKAGE_SOURCE_MISMATCH",
            )
        )
        if result["source_consistency"] != expected_source_consistency:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "SOURCE_CONSISTENT_MISMATCH",
                "source_consistency does not match consistency_issues",
            )
        expected_metadata_consistent = not any(
            i in issue_set
            for i in (
                "MISSING_PACKAGE_FIELD",
                "INVALID_PACKAGE_AVAILABLE",
            )
        )
        if result["metadata_consistent"] != expected_metadata_consistent:
            raise ReasoningHandoffFullyAuditedApiAuditPackageConsistencyContractError(
                "METADATA_CONSISTENT_MISMATCH",
                "metadata_consistent does not match consistency_issues",
            )

"""Task 069: compose a Task 067 package with its Task 068 audit.

Composition only. Reuses Task 067's and Task 068's own validators for the
nested results. Never queries the database, never performs HTTP, never
invokes Task 065's endpoint or any Task 059-068 build workflow, never
mutates its inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067,
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068,
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_TASK_069"
)

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
    "audited_bundle_fingerprint",
)

_BUNDLE_BOOLEAN_FIELDS = ("available", "bundle_consistent")


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


def _canonicalize(value: Any) -> Any:
    """Return a deterministic JSON-safe form."""
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


def _bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
    """SHA-256 of canonical JSON form of the bundle."""
    payload = json.dumps(
        _canonicalize(bundle),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReasoningHandoffFullyAuditedApiAuditBundleContractError(Exception):
    """Task 069: the bundle could not be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffFullyAuditedApiAuditBundleService:
    """Task 069: compose a Task 067 package with its Task 068 audit."""

    def build(
        self,
        *,
        session_id: Any = None,
        api_audit_package: Mapping[str, Any] | None = None,
        api_audit_package_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the bundle. Pure; never mutates inputs."""
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(api_audit_package, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "api_audit_package is required and must be a mapping",
            )
        if not isinstance(api_audit_package_consistency, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "api_audit_package_consistency is required and must be a mapping",
            )

        # Session identity - package must match supplied session
        package_sid = _coerce_session_id(api_audit_package.get("session_id"))
        if package_sid != sid:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_package.session_id does not match supplied session_id",
            )

        # Sources - hoisted above nested validators for precise invariant
        package_source = api_audit_package.get("package_source")
        if (
            package_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "PACKAGE_SOURCE_MISMATCH",
                "api_audit_package.package_source is not Task 067 identifier: "
                + repr(package_source),
            )
        consistency_source = api_audit_package_consistency.get(
            "package_consistency_source"
        )
        _expected_consistency_source = REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068  # noqa: E501
        if consistency_source != _expected_consistency_source:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "CONSISTENCY_SOURCE_MISMATCH",
                (
                    "api_audit_package_consistency.package_consistency_source "
                    "is not Task 068 identifier: " + repr(consistency_source)
                ),
            )

        # Nested Task 067 contract
        try:
            ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(
                _deep_normalize_session_ids(api_audit_package)
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "Task 067 package failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 068 contract
        try:
            ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
                dict(api_audit_package_consistency)
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "Task 068 audit failed its own validator: " + str(exc),
            ) from exc

        # Package fingerprint provenance - Task 068 must bind to exact package
        # Recompute using Task 068's helper
        try:
            expected_fingerprint = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._package_fingerprint(  # noqa: E501
                api_audit_package
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute Task 067 package fingerprint: " + str(exc),
            ) from exc

        actual_fingerprint = api_audit_package_consistency.get(
            "audited_package_fingerprint"
        )
        if actual_fingerprint != expected_fingerprint:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "api_audit_package_consistency.audited_package_fingerprint does not match package",  # noqa: E501
            )

        # If fingerprint recomputation impossible due to invalid nested,
        # would have been caught above. But if either nested was
        # invalid, we already raised. So provenance is available here.

        # Bundle relationship - bundle_consistent mirrors Task 068 package_consistent
        expected_bundle_consistent = bool(
            api_audit_package_consistency.get("package_consistent", False)
        )

        # Compute audited_bundle_fingerprint deterministically
        # Fingerprint is of the bundle's core contents (session + nested artifacts)
        # Use canonical JSON of the supplied package and consistency
        bundle_for_fp = {
            "session_id": str(sid),
            "api_audit_package": _canonicalize(api_audit_package),
            "api_audit_package_consistency": _canonicalize(
                api_audit_package_consistency
            ),
        }
        try:
            audited_bundle_fingerprint = _bundle_fingerprint(bundle_for_fp)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute audited bundle fingerprint: " + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": expected_bundle_consistent,
            "session_id": sid,
            "api_audit_package": api_audit_package,
            "api_audit_package_consistency": api_audit_package_consistency,
            "bundle_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069,  # noqa: E501
            "audited_bundle_fingerprint": audited_bundle_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                    "MISSING_BUNDLE_FIELD", "result has no " + field
                )
        for field in _BUNDLE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        if not isinstance(result["api_audit_package"], Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH", "api_audit_package is not a mapping"
            )
        if not isinstance(result["api_audit_package_consistency"], Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "api_audit_package_consistency is not a mapping",
            )
        if (
            result["bundle_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "BUNDLE_SOURCE_MISMATCH",
                "bundle_source is not Task 069 identifier: "
                + repr(result["bundle_source"]),
            )
        fp = result["audited_bundle_fingerprint"]
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "audited_bundle_fingerprint is not 64-char hex: " + repr(fp),
            )
        # Nested validators
        try:
            ReasoningHandoffFullyAuditedApiAuditPackageService._validate_result(
                _deep_normalize_session_ids(result["api_audit_package"])
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_MISMATCH",
                "nested Task 067 package failed: " + str(exc),
            ) from exc
        try:
            ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._validate_result(
                dict(result["api_audit_package_consistency"])
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH",
                "nested Task 068 audit failed: " + str(exc),
            ) from exc
        # Session identity
        package_sid = _coerce_session_id(result["api_audit_package"].get("session_id"))
        if package_sid != result["session_id"]:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_package.session_id != bundle session_id",
            )
        # Sources
        package = result["api_audit_package"]
        audit = result["api_audit_package_consistency"]
        if (
            package.get("package_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_SOURCE_TASK_067
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "PACKAGE_SOURCE_MISMATCH", "package_source mismatch"
            )
        if (
            audit.get("package_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_068  # noqa: E501
        ):
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "CONSISTENCY_SOURCE_MISMATCH", "consistency source mismatch"
            )
        # Fingerprint provenance
        try:
            expected = ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService._package_fingerprint(  # noqa: E501
                package
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute package fingerprint: " + str(exc),
            ) from exc
        if audit.get("audited_package_fingerprint") != expected:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "audited_package_fingerprint mismatch",
            )
        # Bundle relationship
        expected_cons = bool(audit.get("package_consistent", False))
        if result["bundle_consistent"] != expected_cons:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match audit package_consistent",
            )
        # Fingerprint recomputation for bundle itself
        bundle_for_fp = {
            "session_id": str(result["session_id"]),
            "api_audit_package": _canonicalize(result["api_audit_package"]),
            "api_audit_package_consistency": _canonicalize(
                result["api_audit_package_consistency"]
            ),
        }
        try:
            recomputed = _bundle_fingerprint(bundle_for_fp)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute audited bundle fingerprint: " + str(exc),
            ) from exc
        if result["audited_bundle_fingerprint"] != recomputed:
            raise ReasoningHandoffFullyAuditedApiAuditBundleContractError(
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "audited_bundle_fingerprint does not match bundle contents",
            )

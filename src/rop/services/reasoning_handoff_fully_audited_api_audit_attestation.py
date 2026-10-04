"""Task 071: final attestation over Task 069 bundle and Task 070 audit.

Pure composition boundary. Reuses Task 069 and Task 070 validators and
deterministic fingerprint helpers. Never queries database, never
performs HTTP, never invokes Task 065 endpoint or Task 059-070
workflows, never mutates inputs, no cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_bundle import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069,
    ReasoningHandoffFullyAuditedApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle_consistency import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070,
    ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_TASK_071"
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

_ATTESTATION_BOOLEAN_FIELDS = ("available", "attestation_consistent")


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


def _bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
    """Task070-style bundle fingerprint: SHA-256 of canonical bundle."""
    payload = json.dumps(
        _canonicalize(bundle),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _attestation_fingerprint(attestation_core: Mapping[str, Any]) -> str:
    """SHA-256 of canonical attestation core."""
    payload = json.dumps(
        _canonicalize(attestation_core),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReasoningHandoffFullyAuditedApiAuditAttestationContractError(Exception):
    """Task 071: attestation could not be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningHandoffFullyAuditedApiAuditAttestationService:
    """Task 071: final attestation over Task 069 bundle and Task 070 audit."""

    def build(
        self,
        *,
        session_id: Any = None,
        api_audit_bundle: Mapping[str, Any] | None = None,
        api_audit_bundle_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble and validate the attestation. Pure; never mutates inputs."""
        sid = _coerce_session_id(session_id)
        if sid is None:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(session_id).__name__,
            )
        if not isinstance(api_audit_bundle, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_MISMATCH",
                "api_audit_bundle is required and must be a mapping",
            )
        if not isinstance(api_audit_bundle_consistency, Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_CONSISTENCY_MISMATCH",
                "api_audit_bundle_consistency is required and must be a mapping",
            )

        # Session identity - bundle must match supplied session
        bundle_sid = _coerce_session_id(api_audit_bundle.get("session_id"))
        if bundle_sid != sid:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_bundle.session_id does not match supplied session_id",
            )

        # Sources - hoisted for precise invariant
        bundle_source = api_audit_bundle.get("bundle_source")
        if (
            bundle_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069
        ):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_SOURCE_MISMATCH",
                "api_audit_bundle.bundle_source is not Task 069 identifier: "
                + repr(bundle_source),
            )
        consistency_source = api_audit_bundle_consistency.get(
            "bundle_consistency_source"
        )
        if (
            consistency_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070  # noqa: E501
        ):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "api_audit_bundle_consistency.bundle_consistency_source is not Task 070 identifier: "  # noqa: E501
                + repr(consistency_source),
            )

        # Nested Task 069 contract
        try:
            ReasoningHandoffFullyAuditedApiAuditBundleService._validate_result(
                _deep_normalize_session_ids(api_audit_bundle)
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_MISMATCH",
                "Task 069 bundle failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 070 contract
        try:
            ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService._validate_result(
                dict(api_audit_bundle_consistency)
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_CONSISTENCY_MISMATCH",
                "Task 070 consistency failed its own validator: " + str(exc),
            ) from exc

        # Task 070 -> Task 069 fingerprint binding
        try:
            expected_bundle_fp = _bundle_fingerprint(api_audit_bundle)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not compute Task 069 bundle fingerprint: " + str(exc),
            ) from exc

        actual_bundle_fp = api_audit_bundle_consistency.get(
            "audited_bundle_fingerprint"
        )
        if actual_bundle_fp != expected_bundle_fp:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "api_audit_bundle_consistency.audited_bundle_fingerprint does not match bundle",  # noqa: E501
            )

        # Attestation relationship - mirrors Task 070 bundle_consistent
        expected_attestation_consistent = bool(
            api_audit_bundle_consistency.get("bundle_consistent", False)
        )

        # Compute audited_attestation_fingerprint deterministically
        attestation_core = {
            "session_id": str(sid),
            "api_audit_bundle": _canonicalize(api_audit_bundle),
            "api_audit_bundle_consistency": _canonicalize(api_audit_bundle_consistency),
        }
        try:
            audited_attestation_fingerprint = _attestation_fingerprint(attestation_core)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "could not compute audited attestation fingerprint: " + str(exc),
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "attestation_consistent": expected_attestation_consistent,
            "session_id": sid,
            "api_audit_bundle": api_audit_bundle,
            "api_audit_bundle_consistency": api_audit_bundle_consistency,
            "attestation_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,  # noqa: E501
            "audited_attestation_fingerprint": audited_attestation_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _ATTESTATION_REQUIRED_FIELDS:
            if field not in result:
                raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                    "MISSING_ATTESTATION_FIELD", "result has no " + field
                )
        for field in _ATTESTATION_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "RESULT_UNAVAILABLE", "available is not True"
            )
        if not isinstance(result["session_id"], UUID):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        if not isinstance(result["api_audit_bundle"], Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_MISMATCH", "api_audit_bundle is not a mapping"
            )
        if not isinstance(result["api_audit_bundle_consistency"], Mapping):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_CONSISTENCY_MISMATCH",
                "api_audit_bundle_consistency is not a mapping",
            )
        if (
            result["attestation_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071  # noqa: E501
        ):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "ATTESTATION_SOURCE_MISMATCH",
                "attestation_source is not Task 071 identifier: "
                + repr(result["attestation_source"]),
            )
        fp = result["audited_attestation_fingerprint"]
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_FORMAT",
                "audited_attestation_fingerprint is not 64-char hex: " + repr(fp),
            )
        # Nested validators
        try:
            ReasoningHandoffFullyAuditedApiAuditBundleService._validate_result(
                _deep_normalize_session_ids(result["api_audit_bundle"])
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_MISMATCH",
                "nested Task 069 bundle failed: " + str(exc),
            ) from exc
        try:
            ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService._validate_result(
                dict(result["api_audit_bundle_consistency"])
            )
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_CONSISTENCY_MISMATCH",
                "nested Task 070 audit failed: " + str(exc),
            ) from exc
        # Session identity
        bundle_sid = _coerce_session_id(result["api_audit_bundle"].get("session_id"))
        if bundle_sid != result["session_id"]:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "SESSION_ID_MISMATCH",
                "api_audit_bundle.session_id != attestation session_id",
            )
        # Sources
        bundle = result["api_audit_bundle"]
        consistency = result["api_audit_bundle_consistency"]
        if (
            bundle.get("bundle_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_SOURCE_TASK_069
        ):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_SOURCE_MISMATCH", "bundle_source mismatch"
            )
        if (
            consistency.get("bundle_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_070  # noqa: E501
        ):
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "bundle_consistency_source mismatch",
            )
        # Fingerprint binding Task070 -> Task069
        try:
            expected_bundle_fp = _bundle_fingerprint(bundle)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute bundle fingerprint: " + str(exc),
            ) from exc
        if consistency.get("audited_bundle_fingerprint") != expected_bundle_fp:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "audited_bundle_fingerprint mismatch",
            )
        # Attestation relationship
        expected_cons = bool(consistency.get("bundle_consistent", False))
        if result["attestation_consistent"] != expected_cons:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "ATTESTATION_CONSISTENCY_MISMATCH",
                "attestation_consistent does not match consistency bundle_consistent",  # noqa: E501
            )
        # Fingerprint recomputation for attestation itself
        attestation_core = {
            "session_id": str(result["session_id"]),
            "api_audit_bundle": _canonicalize(result["api_audit_bundle"]),
            "api_audit_bundle_consistency": _canonicalize(
                result["api_audit_bundle_consistency"]
            ),
        }
        try:
            recomputed = _attestation_fingerprint(attestation_core)
        except Exception as exc:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute audited attestation fingerprint: " + str(exc),
            ) from exc
        if result["audited_attestation_fingerprint"] != recomputed:
            raise ReasoningHandoffFullyAuditedApiAuditAttestationContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
                "audited_attestation_fingerprint does not match attestation contents",  # noqa: E501
            )

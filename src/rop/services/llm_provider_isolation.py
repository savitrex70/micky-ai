"""Task 107: Provider isolation and failure boundary hardening.

Pure boundary-hardening helpers with no DB, HTTP, or network access.
All methods are stateless and pure.
"""

from __future__ import annotations

from typing import Any

from rop.schemas.llm_provider_isolation import (
    LLM_PROVIDER_ISOLATION_SOURCE_TASK_107,
)
from rop.services.llm_boundary_contract import (
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
    PROVIDER_RESPONSE_KNOWN_FIELDS,
)
from rop.services.llm_reasoning_provider import LLMReasoningProviderResponse

__all__ = ["LLM_PROVIDER_ISOLATION_SOURCE_TASK_107", "ProviderFailureBoundary"]


class ProviderFailureBoundary:
    """Stateless, pure boundary-hardening helpers for LLM provider isolation.

    No DB, HTTP, real network, mutation, or real provider instantiation.
    """

    # -----------------------------------------------------------------
    # Failure normalization
    # -----------------------------------------------------------------

    @staticmethod
    def describe_failure(exc: Exception) -> str:
        """Render an exception as text without ever leaking exceptions.

        A hostile exception may raise from ``__str__`` itself; fall back
        to the bare type name so the boundary always has a message.
        """
        try:
            text = str(exc)
        except Exception:
            text = ""
        label = type(exc).__name__ or "Exception"
        return f"{label}: {text}" if text else label

    @staticmethod
    def normalize_failure(exc: Exception) -> str:
        """Map any provider exception to one of 4 hard outcomes.

        Outcomes:
        - MODEL_UNAVAILABLE: network/timeout/config failures
        - MODEL_OUTPUT_INVALID: schema/JSON parsing failures
        - MODEL_OUTPUT_INCONSISTENT: reference/validation failures
        - INPUT_INCONSISTENT: bad context/input failures

        Precedence is message-subject first: transport/config signals,
        then input-pipeline signals, then reference signals, then
        parse signals, then exception-type fallbacks, then a safe
        MODEL_UNAVAILABLE default. Keyword checks precede type checks
        so a specific message is never shadowed by a generic type.
        """
        # MODEL_UNAVAILABLE: network, timeout, config, connection errors.
        # Task 120: the exception message itself is untrusted (a hostile
        # __str__ must not escape the boundary), so it is rendered
        # defensively.
        exc_type = type(exc).__name__
        try:
            exc_msg = str(exc).lower()
        except Exception:
            exc_msg = ""

        # Network/timeout/connection errors
        if any(
            keyword in exc_msg
            for keyword in (
                "connection",
                "timeout",
                "timed out",
                "network",
                "unreachable",
                "refused",
                "reset",
                "dns",
                "socket",
                "ssl",
                "tls",
            )
        ):
            return OUTCOME_MODEL_UNAVAILABLE

        # Config/missing provider errors
        if any(
            keyword in exc_msg
            for keyword in (
                "config",
                "configuration",
                "not configured",
                "missing provider",
                "no provider",
                "provider not found",
                "model not found",
                "model not configured",
                "api key",
                "credentials",
                "authentication",
                "unauthorized",
            )
        ):
            return OUTCOME_MODEL_UNAVAILABLE

        # Provider-specific error types that indicate unavailability
        if exc_type in (
            "LLMReasoningProviderError",
            "ConnectionError",
            "TimeoutError",
            "OSError",
            "IOError",
            "PermissionError",
        ):
            return OUTCOME_MODEL_UNAVAILABLE

        # INPUT_INCONSISTENT: the input pipeline (context, audit,
        # fingerprint, serialization) is at fault. Checked before
        # reference signals: "audit"/"provenance" must win over a
        # generic "inconsistent", and "context fingerprint" must win
        # over reference messages that merely mention the context.
        if any(
            keyword in exc_msg
            for keyword in (
                "audit",
                "provenance",
                "fingerprint",
                "serializ",
                "canonical",
                "payload",
                "input",
                "bad context",
                "invalid context",
                "inconsistent context",
            )
        ):
            return OUTCOME_INPUT_INCONSISTENT

        # MODEL_OUTPUT_INCONSISTENT: reference failures (validated downstream)
        if any(
            keyword in exc_msg
            for keyword in (
                "reference",
                "not found",
                "unknown candidate",
                "unknown evidence",
                "unknown missing",
                "duplicate candidate",
                "duplicate",
                "order mismatch",
                "inconsistent",
            )
        ):
            return OUTCOME_MODEL_OUTPUT_INCONSISTENT

        # MODEL_OUTPUT_INVALID: JSON/schema parsing errors
        if any(
            keyword in exc_msg
            for keyword in (
                "json",
                "schema",
                "validation",
                "parse",
                "deserializ",
                "malformed",
                "invalid json",
                "not valid json",
                "json decode",
                "expecting value",
                "extra data",
            )
        ):
            return OUTCOME_MODEL_OUTPUT_INVALID

        # Exception-type fallbacks (message carried no subject signal)
        if exc_type in ("ValidationError", "ValueError", "TypeError", "KeyError"):
            return OUTCOME_MODEL_OUTPUT_INVALID

        # Default to MODEL_UNAVAILABLE for unknown provider exceptions
        return OUTCOME_MODEL_UNAVAILABLE

    # -----------------------------------------------------------------
    # Provider metadata validation
    # -----------------------------------------------------------------

    @staticmethod
    def _safe_read(response: Any, name: str) -> Any:
        """Read one response attribute without ever leaking exceptions.

        A hostile provider object may expose metadata as properties that
        raise on access. The default in getattr() only suppresses
        AttributeError, so any other exception is caught here and
        reported as a missing value by the caller.
        """
        try:
            return getattr(response, name, None)
        except Exception:
            return None

    @staticmethod
    def extract_provider_metadata(
        response: LLMReasoningProviderResponse, expected_fingerprint: str
    ) -> tuple[dict[str, Any], list[str]]:
        """Read and validate provider metadata in one defensive pass.

        Returns ``(metadata, issues)``. Each response attribute is read
        exactly once through :meth:`_safe_read`, so the caller consumes
        the returned values instead of touching the untrusted response
        again. That removes the second-access hazard entirely: a
        property that raises, changes type, or returns a different value
        on re-read cannot be reached after validation.

        A non-empty ``issues`` list means the metadata is untrustworthy
        and the returned values must not be used.

        Checks:
        - provider and model are non-empty strings
        - text is a string (non-string text cannot reach json parsing)
        - context_fingerprint matches expected (if provided)
        - no extra fields in response beyond provider, model, text
        """
        issues: list[str] = []
        _read = ProviderFailureBoundary._safe_read

        # Check provider non-empty (missing/unreadable attribute counts
        # as empty)
        provider_name = _read(response, "provider")
        if not isinstance(provider_name, str) or not provider_name.strip():
            issues.append("provider field is empty or not a string")

        # Check model non-empty (missing/unreadable attribute counts
        # as empty)
        model_name = _read(response, "model")
        if not isinstance(model_name, str) or not model_name.strip():
            issues.append("model field is empty or not a string")

        # Check text is a string (missing/unreadable/non-string text
        # cannot proceed to JSON parsing)
        text_value = _read(response, "text")
        if not isinstance(text_value, str):
            issues.append("response text is not a string")

        # Check fingerprint match if expected provided
        actual_fp = _read(response, "context_fingerprint")
        if expected_fingerprint and actual_fp:
            if actual_fp != expected_fingerprint:
                issues.append(
                    "context_fingerprint mismatch: expected "
                    f"{expected_fingerprint}, got {actual_fp}"
                )

        # Check for extra fields. The known response surface is the
        # canonical Task 113 set: provider, model, text, plus the
        # optional context_fingerprint metadata the fingerprint check
        # above already understands. Anything else -- whether declared
        # on a dataclass or attached as a plain attribute -- is
        # untrusted provider surface.
        allowed_fields = set(PROVIDER_RESPONSE_KNOWN_FIELDS)
        extra: set[str] = set()
        if hasattr(response, "__dataclass_fields__"):
            try:
                extra |= set(response.__dataclass_fields__.keys()) - allowed_fields
            except Exception:
                pass
        try:
            extra |= set(vars(response).keys()) - allowed_fields
        except Exception:
            pass
        try:
            base_attrs = set(dir(LLMReasoningProviderResponse))
            for attr in dir(type(response)):
                if attr.startswith("_") or attr in allowed_fields or attr in base_attrs:
                    continue
                try:
                    if not callable(getattr(type(response), attr, None)):
                        extra.add(attr)
                except Exception:
                    pass
        except Exception:
            pass
        if extra:
            issues.append(f"response contains extra fields: {sorted(extra)}")

        return (
            {"provider": provider_name, "model": model_name, "text": text_value},
            issues,
        )

    @staticmethod
    def validate_provider_metadata(
        response: LLMReasoningProviderResponse, expected_fingerprint: str
    ) -> list[str]:
        """Validate provider response metadata and return the issue list.

        Thin wrapper over :meth:`extract_provider_metadata` for callers
        that need the verdict only. Callers that also need the validated
        provider/model/text values must use ``extract_provider_metadata``
        so the untrusted response is never read a second time.
        """
        _metadata, issues = ProviderFailureBoundary.extract_provider_metadata(
            response, expected_fingerprint
        )
        return issues

    # -----------------------------------------------------------------
    # Text sanitization (pass-through, no modification)
    # -----------------------------------------------------------------

    @staticmethod
    def sanitize_provider_text(text: str) -> str:
        """Return provider text as-is.

        Raw model text is never modified; just returned for downstream validation.
        """
        return text

    # -----------------------------------------------------------------
    # Provider mutation safety check (inspection-only)
    # -----------------------------------------------------------------

    @staticmethod
    def check_provider_cannot_mutate_rop(provider: Any) -> list[str]:
        """Inspect provider for suspicious attributes that could mutate ROP state.

        Returns list of issues found (empty if clean).
        Pure inspection, no instantiation, no method calls.
        """
        issues: list[str] = []

        # Suspicious attribute names that indicate DB/session access
        suspicious_attrs = {
            "db_session",
            "session",
            "engine",
            "execute",
            "commit",
            "close",
            "flush",
            "rollback",
            "connection",
            "cursor",
            "transaction",
            "db",
            "database",
            "orm",
            "query",
            "add",
            "delete",
            "merge",
            "refresh",
            "expire",
            "scalar",
            "scalars",
            "first",
            "all",
            "one",
            "one_or_none",
            "get",
            "filter",
            "filter_by",
        }

        # Check provider instance attributes
        for attr in dir(provider):
            if attr.startswith("_"):
                continue
            if attr.lower() in suspicious_attrs:
                issues.append(f"provider has suspicious attribute: {attr}")

        # Check provider class attributes
        for attr in dir(type(provider)):
            if attr.startswith("_"):
                continue
            if attr.lower() in suspicious_attrs:
                issues.append(f"provider class has suspicious attribute: {attr}")

        # Check for callable attributes that look like DB operations
        for attr in dir(provider):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(provider, attr)
                if callable(val) and attr.lower() in suspicious_attrs:
                    issues.append(f"provider has suspicious callable: {attr}")
            except Exception:
                # Ignore attributes that raise on access
                pass

        return issues

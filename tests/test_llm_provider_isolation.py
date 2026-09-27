"""Tests for Task 107: Provider isolation and failure boundary hardening.

All tests use fake provider classes. No real network, DB, or provider instantiation.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning_provider import LLMReasoningProviderResponse

# ---------------------------------------------------------------------------
# Fake provider classes for testing
# ---------------------------------------------------------------------------


class FakeCleanProvider:
    """Clean provider with no suspicious attributes."""

    provider_name = "fake-clean"
    model_name = "fake-model"

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text='{"candidate_assessments": []}',
        )


class FakeSuspiciousProvider:
    """Provider with suspicious DB-like attributes."""

    provider_name = "fake-suspicious"
    model_name = "fake-model"
    db_session = None
    engine = None

    def execute(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text='{"candidate_assessments": []}',
        )


class FakeProviderWithExtraFields(LLMReasoningProviderResponse):
    """Provider response with extra fields (simulated via subclass)."""

    extra_field: str = "should_not_be_here"


# ---------------------------------------------------------------------------
# normalize_failure tests
# ---------------------------------------------------------------------------


def test_normalize_network_error_to_model_unavailable() -> None:
    exc = ConnectionError("connection refused")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


def test_normalize_timeout_error_to_model_unavailable() -> None:
    exc = TimeoutError("request timed out")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


def test_normalize_dns_error_to_model_unavailable() -> None:
    exc = OSError("dns lookup failed")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


def test_normalize_config_missing_to_model_unavailable() -> None:
    exc = RuntimeError("provider not configured")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


def test_normalize_missing_model_to_model_unavailable() -> None:
    exc = ValueError("model not found")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


def test_normalize_auth_error_to_model_unavailable() -> None:
    exc = PermissionError("authentication failed: invalid api key")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


def test_normalize_invalid_json_to_model_output_invalid() -> None:
    exc = json.JSONDecodeError("Expecting value", "", 0)
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INVALID"


def test_normalize_validation_error_to_model_output_invalid() -> None:
    exc = ValidationError.from_exception_data("test", [])
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INVALID"


def test_normalize_schema_mismatch_to_model_output_invalid() -> None:
    exc = ValueError("schema validation failed: missing required field")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INVALID"


def test_normalize_type_error_to_model_output_invalid() -> None:
    exc = TypeError("expected dict, got list")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INVALID"


def test_normalize_key_error_to_model_output_invalid() -> None:
    exc = KeyError("missing key: candidate_assessments")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INVALID"


def test_normalize_bad_refs_to_model_output_inconsistent() -> None:
    exc = ValueError("unknown candidate_id reference not found in context")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INCONSISTENT"


def test_normalize_duplicate_candidate_to_model_output_inconsistent() -> None:
    exc = RuntimeError("duplicate candidate_assessment for candidate-x")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INCONSISTENT"


def test_normalize_order_mismatch_to_model_output_inconsistent() -> None:
    exc = ValueError("candidate_assessments order mismatch")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_OUTPUT_INCONSISTENT"


def test_normalize_bad_context_to_input_inconsistent() -> None:
    exc = ValueError("context fingerprint mismatch")
    assert ProviderFailureBoundary.normalize_failure(exc) == "INPUT_INCONSISTENT"


def test_normalize_bad_fingerprint_to_input_inconsistent() -> None:
    exc = RuntimeError("audit provenance inconsistent")
    assert ProviderFailureBoundary.normalize_failure(exc) == "INPUT_INCONSISTENT"


def test_normalize_unknown_exception_defaults_to_model_unavailable() -> None:
    exc = RuntimeError("some completely unknown error")
    assert ProviderFailureBoundary.normalize_failure(exc) == "MODEL_UNAVAILABLE"


# ---------------------------------------------------------------------------
# validate_provider_metadata tests
# ---------------------------------------------------------------------------


def test_validate_metadata_clean_response() -> None:
    response = LLMReasoningProviderResponse(
        provider="ollama", model="llama3", text="{}"
    )
    issues = ProviderFailureBoundary.validate_provider_metadata(response, "")
    assert issues == []


def test_validate_metadata_empty_provider_rejected() -> None:
    response = LLMReasoningProviderResponse(provider="", model="llama3", text="{}")
    issues = ProviderFailureBoundary.validate_provider_metadata(response, "")
    assert any("provider field is empty" in i for i in issues)


def test_validate_metadata_whitespace_provider_rejected() -> None:
    response = LLMReasoningProviderResponse(provider="   ", model="llama3", text="{}")
    issues = ProviderFailureBoundary.validate_provider_metadata(response, "")
    assert any("provider field is empty" in i for i in issues)


def test_validate_metadata_empty_model_rejected() -> None:
    response = LLMReasoningProviderResponse(provider="ollama", model="", text="{}")
    issues = ProviderFailureBoundary.validate_provider_metadata(response, "")
    assert any("model field is empty" in i for i in issues)


def test_validate_metadata_fingerprint_match_passes() -> None:
    fp = "a" * 64
    # A provider may attach the fingerprint as plain metadata; the
    # frozen dataclass cannot grow attributes, so simulate with a stub
    # carrying the same surface.
    response = SimpleNamespace(
        provider="ollama", model="llama3", text="{}", context_fingerprint=fp
    )
    issues = ProviderFailureBoundary.validate_provider_metadata(response, fp)
    assert issues == []


def test_validate_metadata_fingerprint_mismatch_flagged() -> None:
    response = SimpleNamespace(
        provider="ollama",
        model="llama3",
        text="{}",
        context_fingerprint="b" * 64,
    )
    issues = ProviderFailureBoundary.validate_provider_metadata(response, "a" * 64)
    assert any("context_fingerprint mismatch" in i for i in issues)


def test_validate_metadata_extra_fields_flagged() -> None:
    # Create a response with extra field via subclass
    response = FakeProviderWithExtraFields(provider="ollama", model="llama3", text="{}")
    issues = ProviderFailureBoundary.validate_provider_metadata(response, "")
    assert any("extra fields" in i for i in issues)


# ---------------------------------------------------------------------------
# sanitize_provider_text tests
# ---------------------------------------------------------------------------


def test_sanitize_returns_text_unchanged() -> None:
    text = (
        '{"candidate_assessments": [{"candidate_id": "1", "assessment": "SUPPORTED"}]}'
    )
    result = ProviderFailureBoundary.sanitize_provider_text(text)
    assert result == text


def test_sanitize_empty_string() -> None:
    assert ProviderFailureBoundary.sanitize_provider_text("") == ""


def test_sanitize_special_chars_unchanged() -> None:
    text = 'Model says: "hello\\nworld" & <tag>'
    assert ProviderFailureBoundary.sanitize_provider_text(text) == text


# ---------------------------------------------------------------------------
# check_provider_cannot_mutate_rop tests
# ---------------------------------------------------------------------------


def test_check_clean_provider_no_issues() -> None:
    provider = FakeCleanProvider()
    issues = ProviderFailureBoundary.check_provider_cannot_mutate_rop(provider)
    assert issues == []


def test_check_suspicious_provider_flagged() -> None:
    provider = FakeSuspiciousProvider()
    issues = ProviderFailureBoundary.check_provider_cannot_mutate_rop(provider)
    assert len(issues) > 0
    assert any("db_session" in i for i in issues)
    assert any("engine" in i for i in issues)
    assert any("execute" in i for i in issues)
    assert any("commit" in i for i in issues)
    assert any("close" in i for i in issues)


def test_check_provider_with_callable_db_methods_flagged() -> None:
    class ProviderWithCallable:
        provider_name = "test"
        model_name = "test"

        def query(self) -> list:
            return []

        def filter(self) -> Any:
            return self

    provider = ProviderWithCallable()
    issues = ProviderFailureBoundary.check_provider_cannot_mutate_rop(provider)
    assert any("query" in i for i in issues)
    assert any("filter" in i for i in issues)


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


def test_deterministic_same_fake_output_same_result() -> None:
    """Same fake output always produces same normalized failure."""
    exc1 = ConnectionError("connection refused")
    exc2 = ConnectionError("connection refused")

    result1 = ProviderFailureBoundary.normalize_failure(exc1)
    result2 = ProviderFailureBoundary.normalize_failure(exc2)

    assert result1 == result2 == "MODEL_UNAVAILABLE"


def test_deterministic_metadata_validation() -> None:
    """Same metadata validation input produces same output."""
    response = LLMReasoningProviderResponse(
        provider="ollama", model="llama3", text="{}"
    )
    fp = "a" * 64

    result1 = ProviderFailureBoundary.validate_provider_metadata(response, fp)
    result2 = ProviderFailureBoundary.validate_provider_metadata(response, fp)

    assert result1 == result2


# ---------------------------------------------------------------------------
# Provider unavailable raises MODEL_UNAVAILABLE not generic exception
# ---------------------------------------------------------------------------


def test_provider_unavailable_raises_model_unavailable_not_generic() -> None:
    """Verify that provider unavailability maps to MODEL_UNAVAILABLE."""
    from rop.services.llm_reasoning_provider import LLMReasoningProviderError

    exc = LLMReasoningProviderError("no connection")
    result = ProviderFailureBoundary.normalize_failure(exc)

    assert result == "MODEL_UNAVAILABLE"
    assert result != "INPUT_UNAVAILABLE"
    assert result != "INPUT_INCONSISTENT"
    assert result != "MODEL_OUTPUT_INVALID"
    assert result != "MODEL_OUTPUT_INCONSISTENT"


# ---------------------------------------------------------------------------
# Syntax check via ast.parse
# ---------------------------------------------------------------------------


def test_source_files_parse_cleanly() -> None:
    """Verify all created source files are syntactically valid."""
    import ast
    from pathlib import Path

    files = [
        Path(__file__).parent.parent
        / "src"
        / "rop"
        / "services"
        / "llm_provider_isolation.py",
        Path(__file__).parent.parent
        / "src"
        / "rop"
        / "schemas"
        / "llm_provider_isolation.py",
    ]

    for f in files:
        source = f.read_text(encoding="utf-8")
        # This will raise SyntaxError if invalid
        ast.parse(source)

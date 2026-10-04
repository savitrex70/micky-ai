"""Tests for Task 080 bundle consistency audit (pure).

Task 080 performs a pure, deterministic, independent consistency audit
of the Task 079 response bundle without executing Task 079, making HTTP
calls, accessing the database, or invoking external models/providers.
"""

from __future__ import annotations

import copy
import inspect
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_080,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyService,  # noqa: E501
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


RESULT_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "nested_response_package_consistent",
    "nested_response_package_consistency_consistent",
    "provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)

BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "response_package",
    "response_package_consistency",
    "bundle_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)

ISSUE_ORDER = (
    "MISSING_BUNDLE_FIELD",
    "INVALID_BUNDLE_AVAILABLE",
    "SESSION_ID_INVALID",
    "NESTED_RESPONSE_PACKAGE_MISMATCH",
    "NESTED_RESPONSE_PACKAGE_CONSISTENCY_MISMATCH",
    "SESSION_ID_MISMATCH",
    "BUNDLE_FINGERPRINT_FORMAT",
    "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
    "BUNDLE_FINGERPRINT_MISMATCH",
    "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
    "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
    "BUNDLE_RELATIONSHIP_MISMATCH",
    "PACKAGE_FINGERPRINT_BINDING_MISMATCH",
    "RESPONSE_PACKAGE_SOURCE_MISMATCH",
    "RESPONSE_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
    "BUNDLE_SOURCE_MISMATCH",
    "BUNDLE_CONTRACT_MISMATCH",
)


def _svc() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService()  # noqa: E501
    )


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-080-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full(user_input: str) -> str:
    sid = _create_session(user_input)
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    return sid


def _valid_bundle() -> dict[str, Any]:
    sid_str = _seed_full("Task 080 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        response_075 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    consistency_076 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService().build(  # noqa: E501
        response=response_075
    )
    package_077 = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        attestation_response=response_075,
        attestation_response_consistency=consistency_076,
    )
    package_consistency_078 = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=package_077
    )
    return ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=package_077,
        response_package_consistency=package_consistency_078,
    )


def _check(bundle: dict[str, Any]) -> dict[str, Any]:
    return _svc().build(bundle=bundle)


# --- Valid bundle -----------------------------------------------------------
def test_valid_reports_all_true_for_honest_bundle() -> None:
    result = _check(_valid_bundle())
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["bundle_consistent"] is True
    assert result["session_consistent"] is True
    assert result["nested_response_package_consistent"] is True
    assert result["nested_response_package_consistency_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["bundle_relationship_consistent"] is True
    assert result["source_consistency"] is True
    assert result["metadata_consistent"] is True
    assert result["consistency_issues"] == []
    assert (
        result["bundle_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_080  # noqa: E501
    )


def test_result_shape_and_fingerprint_types() -> None:
    result = _check(_valid_bundle())
    assert set(result) == set(RESULT_FIELDS)
    for field in ("bundle_fingerprint", "audited_bundle_fingerprint"):
        value = result[field]
        assert isinstance(value, str)
        assert len(value) == 64
        assert all(c in "0123456789abcdef" for c in value)
    assert result["bundle_fingerprint"] == result["audited_bundle_fingerprint"]


def test_result_schema_roundtrip() -> None:
    result = _check(_valid_bundle())
    model = ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead.model_validate(  # noqa: E501
        result
    )
    assert model.bundle_consistent is True
    assert model.consistency_issues == []


def test_fingerprint_matches_task079_definition() -> None:
    bundle = _valid_bundle()
    result = _check(bundle)
    expected = mod._expected_bundle_fingerprint(bundle)
    assert result["bundle_fingerprint"] == expected
    assert result["audited_bundle_fingerprint"] == expected
    assert result["bundle_fingerprint"] == bundle["bundle_fingerprint"]


# --- Contract boundary ------------------------------------------------------
def test_missing_bundle_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError  # noqa: E501
    ) as ei:
        _svc().build(bundle=None)
    assert ei.value.invariant == "MISSING_BUNDLE"


def test_non_mapping_bundle_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError  # noqa: E501
    ) as ei:
        _svc().build(bundle="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "BUNDLE_TYPE"


@pytest.mark.parametrize("field", BUNDLE_REQUIRED_FIELDS)
def test_every_required_field_missing_is_reported(field: str) -> None:
    bundle = _valid_bundle()
    del bundle[field]
    result = _check(bundle)
    assert "MISSING_BUNDLE_FIELD" in result["consistency_issues"]
    assert result["bundle_consistent"] is False
    assert result["metadata_consistent"] is False


def test_duplicate_missing_fields_collapse_to_one_issue() -> None:
    bundle = _valid_bundle()
    del bundle["available"]
    del bundle["bundle_source"]
    result = _check(bundle)
    assert result["consistency_issues"].count("MISSING_BUNDLE_FIELD") == 1


def test_invalid_bundle_available_reports_issue() -> None:
    bundle = _valid_bundle()
    bundle["available"] = "yes"  # type: ignore[assignment]
    result = _check(bundle)
    assert "INVALID_BUNDLE_AVAILABLE" in result["consistency_issues"]
    assert result["available"] is True
    assert result["metadata_consistent"] is False
    assert result["bundle_consistent"] is False


# --- Nested package tampering ------------------------------------------------
def test_nested_response_package_mismatch_reports_issue() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle["response_package"])
    broken["available"] = False
    bundle["response_package"] = broken
    result = _check(bundle)
    assert "NESTED_RESPONSE_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_package_consistent"] is False
    assert result["bundle_consistent"] is False


def test_nested_response_package_non_mapping_reports_issue() -> None:
    bundle = _valid_bundle()
    bundle["response_package"] = "broken"  # type: ignore[assignment]
    result = _check(bundle)
    assert "NESTED_RESPONSE_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_response_package_consistent"] is False


def test_nested_response_package_consistency_mismatch() -> None:
    bundle = _valid_bundle()
    broken = copy.deepcopy(bundle["response_package_consistency"])
    broken["available"] = False
    bundle["response_package_consistency"] = broken
    result = _check(bundle)
    assert (
        "NESTED_RESPONSE_PACKAGE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )
    assert result["nested_response_package_consistency_consistent"] is False
    assert result["bundle_consistent"] is False


def test_nested_response_package_consistency_non_mapping() -> None:
    bundle = _valid_bundle()
    bundle["response_package_consistency"] = []  # type: ignore[assignment]
    result = _check(bundle)
    assert (
        "NESTED_RESPONSE_PACKAGE_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )
    assert result["bundle_consistent"] is False


# --- Session tampering -------------------------------------------------------
def test_session_id_invalid_reports_issue() -> None:
    bundle = _valid_bundle()
    bundle["session_id"] = "not-a-uuid"
    result = _check(bundle)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["bundle_consistent"] is False


def test_session_id_mismatch_nested_package() -> None:
    bundle = _valid_bundle()
    bundle["response_package"] = copy.deepcopy(bundle["response_package"])
    bundle["response_package"]["session_id"] = uuid4()
    result = _check(bundle)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["bundle_consistent"] is False


def test_session_consistent_false_flags_session_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["response_package_consistency"] = copy.deepcopy(
        bundle["response_package_consistency"]
    )
    bundle["response_package_consistency"]["session_consistent"] = False
    result = _check(bundle)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


# --- Source tampering ---------------------------------------------------------
def test_response_package_source_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["response_package"] = copy.deepcopy(bundle["response_package"])
    bundle["response_package"]["package_source"] = "WRONG"
    result = _check(bundle)
    assert "RESPONSE_PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["bundle_consistent"] is False


def test_response_package_consistency_source_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["response_package_consistency"] = copy.deepcopy(
        bundle["response_package_consistency"]
    )
    bundle["response_package_consistency"]["package_consistency_source"] = "WRONG"
    result = _check(bundle)
    assert (
        "RESPONSE_PACKAGE_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    )
    assert result["source_consistency"] is False


def test_bundle_source_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["bundle_source"] = "WRONG"
    result = _check(bundle)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False
    assert result["bundle_consistent"] is False


def test_package_fingerprint_binding_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["response_package_consistency"] = copy.deepcopy(
        bundle["response_package_consistency"]
    )
    bundle["response_package_consistency"]["package_fingerprint"] = "0" * 64
    result = _check(bundle)
    assert "PACKAGE_FINGERPRINT_BINDING_MISMATCH" in result["consistency_issues"]
    assert result["bundle_relationship_consistent"] is False
    assert result["bundle_consistent"] is False


# --- Fingerprint tampering (each field independently) --------------------------
def test_bundle_fingerprint_format_reports_issue() -> None:
    bundle = _valid_bundle()
    bundle["bundle_fingerprint"] = "not-hex"
    result = _check(bundle)
    assert "BUNDLE_FINGERPRINT_FORMAT" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["bundle_consistent"] is False


def test_audited_bundle_fingerprint_format_reports_issue() -> None:
    bundle = _valid_bundle()
    bundle["audited_bundle_fingerprint"] = "not-hex"
    result = _check(bundle)
    assert "AUDITED_BUNDLE_FINGERPRINT_FORMAT" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_bundle_fingerprint_tampering_flags_mismatch_and_pair() -> None:
    bundle = _valid_bundle()
    bundle["bundle_fingerprint"] = "0" * 64
    result = _check(bundle)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False
    assert result["bundle_consistent"] is False


def test_audited_bundle_fingerprint_tampering_flags_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["audited_bundle_fingerprint"] = "f" * 64
    result = _check(bundle)
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in result["consistency_issues"]
    assert result["provenance_consistent"] is False


def test_both_fingerprints_wrong_but_equal_flag_both_mismatches() -> None:
    bundle = _valid_bundle()
    wrong = "1" * 64
    assert wrong != bundle["bundle_fingerprint"]
    bundle["bundle_fingerprint"] = wrong
    bundle["audited_bundle_fingerprint"] = wrong
    result = _check(bundle)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    # Equal to each other, so no pair mismatch; still inconsistent overall.
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" not in result["consistency_issues"]
    assert result["bundle_consistent"] is False


def test_uppercase_fingerprint_rejected_as_format() -> None:
    bundle = _valid_bundle()
    bundle["bundle_fingerprint"] = bundle["bundle_fingerprint"].upper()
    result = _check(bundle)
    assert "BUNDLE_FINGERPRINT_FORMAT" in result["consistency_issues"]


# --- Derived-flag tampering ----------------------------------------------------
def test_bundle_consistent_flip_flags_relationship_mismatch() -> None:
    bundle = _valid_bundle()
    bundle["bundle_consistent"] = not bundle["bundle_consistent"]
    result = _check(bundle)
    assert "BUNDLE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["bundle_relationship_consistent"] is False
    assert result["bundle_consistent"] is False


def test_coherent_bundle_vs_defect_free_underlying() -> None:
    # The audit verdict tracks coherence, not underlying health: an
    # honest bundle audits clean, while flipping only the derived
    # bundle_consistent flag is flagged as incoherent even though the
    # nested underlying values are untouched and defect-free.
    bundle = _valid_bundle()
    honest = _check(bundle)
    assert honest["bundle_consistent"] is True
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = False
    flagged = _check(tampered)
    assert flagged["bundle_consistent"] is False
    assert "BUNDLE_RELATIONSHIP_MISMATCH" in flagged["consistency_issues"]
    assert tampered["response_package"]["package_consistent"] is True


def test_validate_result_rejects_derived_flag_mismatch() -> None:
    bundle = _valid_bundle()
    result = _check(bundle)
    for field in (
        "session_consistent",
        "nested_response_package_consistent",
        "nested_response_package_consistency_consistent",
        "provenance_consistent",
        "bundle_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        tampered = copy.deepcopy(result)
        tampered[field] = not tampered[field]
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError  # noqa: E501
        ):
            mod.ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
                tampered, bundle=bundle
            )


def test_validate_result_rejects_pair_mismatch() -> None:
    bundle = _valid_bundle()
    result = _check(bundle)
    tampered = copy.deepcopy(result)
    tampered["audited_bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError  # noqa: E501
    ) as ei:
        mod.ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
            tampered, bundle=bundle
        )
    assert ei.value.invariant in (
        "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
        "BUNDLE_FINGERPRINT_PAIR_MISMATCH",
    )


# --- Ordering / duplicates / determinism / immutability -------------------------
def test_issue_order_and_dedupe() -> None:
    bundle = _valid_bundle()
    bundle["session_id"] = "not-a-uuid"
    bundle["bundle_source"] = "WRONG"
    bundle["bundle_fingerprint"] = "not-hex"
    result = _check(bundle)
    issues = result["consistency_issues"]
    assert len(issues) == len(set(issues))
    assert issues == [i for i in ISSUE_ORDER if i in set(issues)]


def test_validate_result_rejects_duplicates_and_bad_order() -> None:
    bundle = _valid_bundle()
    result = _check(bundle)
    duped = copy.deepcopy(result)
    duped["consistency_issues"] = ["SESSION_ID_MISMATCH", "SESSION_ID_MISMATCH"]
    duped["bundle_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError  # noqa: E501
    ) as ei:
        mod.ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
            duped, bundle=bundle
        )
    assert ei.value.invariant == "DUPLICATE_ISSUE"


def test_deterministic() -> None:
    bundle = _valid_bundle()
    assert _check(bundle) == _check(bundle)


def test_global_cache_regression() -> None:
    b1 = _valid_bundle()
    r1_before = _check(b1)
    b2 = _valid_bundle()
    _ = _check(b2)
    assert _check(b1) == r1_before


def test_input_immutability() -> None:
    bundle = _valid_bundle()
    before = copy.deepcopy(bundle)
    _check(bundle)
    assert bundle == before


def test_no_hidden_state_tokens() -> None:
    src = inspect.getsource(mod)
    assert "_LAST" not in src
    assert "global" not in src


# --- Purity ---------------------------------------------------------------------
def test_no_database_imports() -> None:
    src = inspect.getsource(mod)
    for token in ("SessionLocal", "create_engine", "get_db", "sqlalchemy"):
        assert token not in src


def test_no_http_imports() -> None:
    src = inspect.getsource(mod)
    for token in ("TestClient", "httpx", "requests", "urllib"):
        assert token not in src


def test_no_llm_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("ollama", "openai", "gemini", "anthropic", "model_name", "api_key"):
        assert token not in src
    assert "provider" not in src.split() and "rag" not in src.split()


def test_no_fingerprint_fallback() -> None:
    # Both fingerprint fields are required independently; neither may
    # serve as an ``or`` fallback for the other.
    src = inspect.getsource(mod)
    assert 'bundle.get("bundle_fingerprint") or' not in src
    assert 'bundle.get("audited_bundle_fingerprint") or' not in src
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in src
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in src
    assert "BUNDLE_FINGERPRINT_MISMATCH" in src


def test_source_identifiers_present() -> None:
    src = inspect.getsource(mod)
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_079"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_077"  # noqa: E501
        in src
    )
    assert (
        "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_078"  # noqa: E501
        in src
    )


# --- Mutation verification of recomputation logic --------------------------------
def test_broken_recompute_is_flagged_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutate the recompute helper: a correct suite must flag the
    # resulting mismatch instead of reporting a clean bundle.
    bundle = _valid_bundle()
    monkeypatch.setattr(mod, "_expected_bundle_fingerprint", lambda _b: "0" * 64)
    result = _check(bundle)
    assert result["bundle_consistent"] is False
    assert "BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]
    assert "AUDITED_BUNDLE_FINGERPRINT_MISMATCH" in result["consistency_issues"]


def test_broken_task079_fingerprint_helper_is_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _valid_bundle()
    monkeypatch.setattr(
        mod, "_task079_compute_bundle_fingerprint", lambda _core: "f" * 64
    )
    result = _check(bundle)
    assert result["bundle_consistent"] is False
    assert result["provenance_consistent"] is False


def test_fingerprint_compute_failure_raises_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _valid_bundle()

    def _boom(_bundle: Any) -> str:
        raise RuntimeError("forced")

    monkeypatch.setattr(mod, "_expected_bundle_fingerprint", _boom)
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyContractError  # noqa: E501
    ) as ei:
        _check(bundle)
    assert ei.value.invariant == "BUNDLE_FINGERPRINT_COMPUTE_FAILED"


def test_bundle_contract_mismatch_when_unfixable() -> None:
    bundle = _valid_bundle()
    bundle["response_package"] = copy.deepcopy(bundle["response_package"])
    bundle["response_package"]["package_source"] = "WRONG"
    bundle["response_package"]["available"] = False
    result = _check(bundle)
    assert "NESTED_RESPONSE_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["bundle_consistent"] is False


def test_available_flag_is_true_even_for_flagged_bundle() -> None:
    bundle = _valid_bundle()
    bundle["bundle_source"] = "WRONG"
    result = _check(bundle)
    assert result["available"] is True
    assert result["bundle_consistent"] is False

"""Tests for Task 095: fully audited final attestation response bundle.

Task 095 binds the Task 093 response package with the Task 094
independent consistency audit of that exact package into a single
deterministic, self-authenticating bundle. Pure composition boundary:
no database writes, no HTTP calls, no external models, never mutates
inputs. A legitimate underlying defect is preserved unchanged rather
than converted into a false success.
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService,  # noqa: E501
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


BUNDLE_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "response_package",
    "response_package_consistency",
    "bundle_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService
):  # noqa: E501
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService()
    )  # noqa: E501


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-095-test"},
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


def _seed_chain() -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Build the real Task 093 package + Task 094 audit via services."""
    sid_str = _seed_full("Task 095 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        package = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build_for_session(  # noqa: E501
            db, sid
        )
    consistency = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=package
    )
    return sid_str, package, consistency


def _seed_and_build() -> tuple[str, dict[str, Any]]:
    sid_str, package, consistency = _seed_chain()
    bundle = _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=consistency,
    )
    return sid_str, bundle


def _defect_consistency(
    package: dict[str, Any], consistency: dict[str, Any]
) -> dict[str, Any]:
    """Derive a genuinely defect-reporting Task 094 result from a real one.

    Starts from the real seeded Task 094 audit and reports a single
    non-session issue with all derived flags set per the Task 094
    contract, then proves validity with the real Task 094 validator.
    """
    defect = copy.deepcopy(consistency)
    defect["consistency_issues"] = ["PACKAGE_RELATIONSHIP_MISMATCH"]
    defect["package_consistent"] = False
    if "session_consistent" in defect:
        defect["session_consistent"] = True
    for key in list(defect.keys()):
        if key in (
            "available",
            "package_consistent",
            "session_consistent",
            "consistency_issues",
            "package_consistency_source",
            "package_fingerprint",
            "audited_package_fingerprint",
        ):
            continue
        if isinstance(defect[key], bool):
            if key == "package_relationship_consistent":
                defect[key] = False
            else:
                defect[key] = True
    try:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService._validate_result(  # noqa: E501
            defect, package=package
        )
    except TypeError:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService._validate_result(  # noqa: E501
            defect
        )
    return defect


# --- Valid bundle -----------------------------------------------------------
def test_valid_bundle_shape_and_flags() -> None:
    _, bundle = _seed_and_build()
    assert set(bundle) == set(BUNDLE_FIELDS)
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is True
    assert isinstance(bundle["session_id"], UUID)
    assert (
        bundle["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
    )


def test_nested_package_preserved() -> None:
    _, bundle = _seed_and_build()
    package = bundle["response_package"]
    assert (
        package["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093  # noqa: E501
    )
    assert package["package_consistent"] is True


def test_nested_consistency_preserved() -> None:
    _, bundle = _seed_and_build()
    consistency = bundle["response_package_consistency"]
    assert (
        consistency["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094  # noqa: E501
    )
    assert consistency["package_consistent"] is True
    assert consistency["session_consistent"] is True


def test_session_binding() -> None:
    sid_str, bundle = _seed_and_build()
    assert bundle["session_id"] == UUID(sid_str)
    assert bundle["response_package"]["session_id"] == UUID(sid_str)


def test_fingerprint_binding() -> None:
    _, bundle = _seed_and_build()
    assert len(bundle["bundle_fingerprint"]) == 64
    assert bundle["audited_bundle_fingerprint"] == bundle["bundle_fingerprint"]


def test_result_schema_roundtrip() -> None:
    _, bundle = _seed_and_build()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead.model_validate(  # noqa: E501
        bundle
    )
    assert model.available is True
    assert model.bundle_consistent is True


def test_valid_bundle_via_build_for_session() -> None:
    sid_str = _seed_full("Task 095 session-build capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        bundle = _service().build_for_session(db, sid)
    assert set(bundle) == set(BUNDLE_FIELDS)
    assert bundle["available"] is True
    assert bundle["session_id"] == sid


# --- Legitimate underlying defect remains truthfully represented -------------
def test_legitimate_underlying_defect_preserved() -> None:
    """A defect-reporting upstream audit still yields an available bundle."""
    sid_str, package, consistency = _seed_chain()
    defect = _defect_consistency(package, consistency)
    assert defect["package_consistent"] is False
    bundle = _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=defect,
    )
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is False
    assert bundle["response_package_consistency"]["package_consistent"] is False
    assert bundle["response_package_consistency"]["consistency_issues"] == [
        "PACKAGE_RELATIONSHIP_MISMATCH"
    ]


def test_does_not_convert_defect_to_success() -> None:
    sid_str, package, consistency = _seed_chain()
    defect = _defect_consistency(package, consistency)
    bundle = _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=defect,
    )
    assert bundle["bundle_consistent"] is False


def test_upgrading_a_defect_to_success_is_rejected() -> None:
    sid_str, package, consistency = _seed_chain()
    defect = _defect_consistency(package, consistency)
    bundle = _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=defect,
    )
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = True
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_CONSISTENT_MISMATCH"


# --- Missing / malformed nested data ----------------------------------------
def test_missing_nested_package_raises() -> None:
    _, _, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            response_package=None,
            response_package_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_PACKAGE_MISMATCH"


def test_missing_nested_consistency_raises() -> None:
    _, package, _ = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            response_package=package,
            response_package_consistency=None,
        )
    assert ei.value.invariant == "RESPONSE_PACKAGE_CONSISTENCY_MISMATCH"


def test_non_mapping_nested_package_raises() -> None:
    _, _, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            response_package="not-a-mapping",  # type: ignore[arg-type]
            response_package_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_PACKAGE_MISMATCH"


def test_non_mapping_nested_consistency_raises() -> None:
    _, package, _ = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            response_package=package,
            response_package_consistency="not-a-mapping",  # type: ignore[arg-type]  # noqa: E501
        )
    assert ei.value.invariant == "RESPONSE_PACKAGE_CONSISTENCY_MISMATCH"


def test_malformed_nested_package_raises() -> None:
    _, _, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ):
        _service().build(
            response_package={"available": False},
            response_package_consistency=consistency,
        )


def test_malformed_nested_consistency_raises() -> None:
    _, package, _ = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            response_package=package,
            response_package_consistency={},
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


# --- Session / source / fingerprint binding ---------------------------------
def test_session_mismatch_raises() -> None:
    _, package, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=uuid4(),
            response_package=package,
            response_package_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_nested_session_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(package)
    tampered["session_id"] = uuid4()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            response_package=tampered,
            response_package_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_inconsistent_consistency_session_flag_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(consistency)
    tampered["session_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            response_package=package,
            response_package_consistency=tampered,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_package_source_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            response_package=tampered,
            response_package_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_PACKAGE_SOURCE_MISMATCH"


def test_consistency_source_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(consistency)
    tampered["package_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            response_package=package,
            response_package_consistency=tampered,
        )
    assert ei.value.invariant == "RESPONSE_PACKAGE_CONSISTENCY_SOURCE_MISMATCH"


def test_fingerprint_binding_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(consistency)
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            response_package=package,
            response_package_consistency=tampered,
        )
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_BINDING_MISMATCH"


# --- Derived flag tampering --------------------------------------------------
def test_bundle_consistent_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_CONSISTENT_MISMATCH"


def test_bundle_fingerprint_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["audited_bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "AUDITED_BUNDLE_FINGERPRINT_MISMATCH"


def test_bundle_source_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_SOURCE_MISMATCH"


# --- Deterministic flags (no bundle issues list) -----------------------------
def test_bundle_has_no_issues_list() -> None:
    _, bundle = _seed_and_build()
    assert "consistency_issues" not in bundle


def test_bundle_consistent_derived_from_upstream() -> None:
    _, bundle = _seed_and_build()
    expected = bool(
        bundle["response_package"].get("package_consistent", False)
        and bundle["response_package_consistency"].get("package_consistent", False)
    )
    assert bundle["bundle_consistent"] == expected


def test_deterministic_direct_build() -> None:
    sid_str, package, consistency = _seed_chain()
    first = _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=consistency,
    )
    second = _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=consistency,
    )
    assert first == second


def test_deterministic_build_for_session() -> None:
    sid_str = _seed_full("Task 095 session-build capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        first = _service().build_for_session(db, sid)
    with TestingSessionLocal() as db:
        second = _service().build_for_session(db, sid)
    assert first == second


# --- Immutability / no external side effects ---------------------------------
def test_inputs_not_mutated() -> None:
    sid_str, package, consistency = _seed_chain()
    before_package = copy.deepcopy(package)
    before_consistency = copy.deepcopy(consistency)
    _service().build(
        session_id=UUID(sid_str),
        response_package=package,
        response_package_consistency=consistency,
    )
    assert package == before_package
    assert consistency == before_consistency


def test_read_only_no_new_sessions_created() -> None:
    sid_str = _seed_full("Task 095 read-only capture")
    before = client.get("/sessions", params={"limit": 100}).json()
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        _service().build_for_session(db, sid)
    with TestingSessionLocal() as db:
        _service().build_for_session(db, sid)
    after = client.get("/sessions", params={"limit": 100}).json()
    assert len(before) == len(after)


def test_no_http_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("TestClient", "httpx", "requests", "urllib", "client.get"):
        assert forbidden not in src


def test_no_database_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("SessionLocal", "create_engine"):
        assert forbidden not in src


def test_no_llm_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("ollama", "openai", "gemini", "anthropic", "model_name", "api_key"):
        assert token not in src

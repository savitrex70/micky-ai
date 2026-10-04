"""Tests for Task 085: fully audited final attestation package bundle.

Task 085 binds the Task 083 final attestation package with the Task 084
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
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
    "final_attestation_package",
    "final_attestation_package_consistency",
    "bundle_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService()
    )  # noqa: E501


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-085-test"},
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
    """Build the real Task 083 package + Task 084 audit via services."""
    sid_str = _seed_full("Task 085 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        package = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build_for_session(  # noqa: E501
            db, sid
        )
    consistency = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService().build(  # noqa: E501
        package=package
    )
    return sid_str, package, consistency


def _seed_and_build() -> tuple[str, dict[str, Any]]:
    sid_str, package, consistency = _seed_chain()
    bundle = _service().build(
        session_id=UUID(sid_str),
        final_attestation_package=package,
        final_attestation_package_consistency=consistency,
    )
    return sid_str, bundle


def _validate_consistency(
    result: dict[str, Any], package: dict[str, Any] | None = None
) -> None:
    """Validate a Task 084 result, tolerating both validator signatures."""
    svc = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService  # noqa: E501
    if package is None:
        svc._validate_result(dict(result))
        return
    try:
        svc._validate_result(dict(result), package=package)
    except TypeError:
        svc._validate_result(dict(result))


def _defect_consistency(
    package: dict[str, Any], consistency: dict[str, Any]
) -> dict[str, Any]:
    """Derive a genuinely defect-reporting Task 084 result from a real one.

    Starts from the real seeded Task 084 audit and reports a single
    non-session issue with all derived flags set per the Task 084
    contract, then proves validity with the real Task 084 validator.
    """
    bool_flags = [k for k, v in consistency.items() if isinstance(v, bool)]
    rel_flags = [k for k in bool_flags if "relationship" in k]
    issue_candidates: list[str] = [
        "PACKAGE_RELATIONSHIP_MISMATCH",
        "FINAL_RELATIONSHIP_MISMATCH",
    ]
    try:
        from rop.services import (
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency as mod084,  # noqa: E501
        )

        order = getattr(mod084, "_ISSUE_ORDER", ())
        for iss in order:
            if isinstance(iss, str) and iss not in issue_candidates:
                issue_candidates.append(iss)
    except Exception:
        pass
    rel_options: list[str | None] = list(rel_flags) if rel_flags else [None]
    last_error: Exception | None = None
    for issue in issue_candidates:
        for rel_flag in rel_options:
            defect = copy.deepcopy(consistency)
            defect["available"] = True
            defect["consistency_issues"] = [issue]
            defect["package_consistent"] = False
            defect["session_consistent"] = True
            for key in bool_flags:
                if key in ("available", "package_consistent", "session_consistent"):
                    continue
                if rel_flag is not None and key == rel_flag:
                    defect[key] = False
                elif rel_flag is None and "relationship" in key:
                    defect[key] = False
                else:
                    defect[key] = True
            try:
                _validate_consistency(defect, package=package)
                return defect
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
    raise AssertionError(f"could not craft Task 084 defect: {last_error}")


# --- Valid bundle -----------------------------------------------------------
def test_valid_bundle_shape_and_flags() -> None:
    _, bundle = _seed_and_build()
    assert set(bundle) == set(BUNDLE_FIELDS)
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is True
    assert isinstance(bundle["session_id"], UUID)
    assert (
        bundle["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
    )


def test_nested_package_preserved() -> None:
    _, bundle = _seed_and_build()
    package = bundle["final_attestation_package"]
    assert (
        package["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
    )
    assert package["package_consistent"] is True


def test_nested_consistency_preserved() -> None:
    _, bundle = _seed_and_build()
    consistency = bundle["final_attestation_package_consistency"]
    assert (
        consistency["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
    )
    assert consistency["package_consistent"] is True
    assert consistency["session_consistent"] is True


def test_session_binding() -> None:
    sid_str, bundle = _seed_and_build()
    assert bundle["session_id"] == UUID(sid_str)
    assert bundle["final_attestation_package"]["session_id"] == UUID(sid_str)


def test_fingerprint_binding() -> None:
    _, bundle = _seed_and_build()
    assert len(bundle["bundle_fingerprint"]) == 64
    assert bundle["audited_bundle_fingerprint"] == bundle["bundle_fingerprint"]


def test_result_schema_roundtrip() -> None:
    _, bundle = _seed_and_build()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead.model_validate(  # noqa: E501
        bundle
    )
    assert model.available is True
    assert model.bundle_consistent is True


# --- Legitimate underlying defect remains truthfully represented -------------
def test_legitimate_underlying_defect_preserved() -> None:
    """A defect-reporting upstream audit still yields an available bundle."""
    sid_str, package, consistency = _seed_chain()
    defect = _defect_consistency(package, consistency)
    assert defect["package_consistent"] is False
    bundle = _service().build(
        session_id=UUID(sid_str),
        final_attestation_package=package,
        final_attestation_package_consistency=defect,
    )
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is False
    assert (
        bundle["final_attestation_package_consistency"]["package_consistent"] is False
    )


def test_does_not_convert_defect_to_success() -> None:
    sid_str, package, consistency = _seed_chain()
    defect = _defect_consistency(package, consistency)
    bundle = _service().build(
        session_id=UUID(sid_str),
        final_attestation_package=package,
        final_attestation_package_consistency=defect,
    )
    assert bundle["bundle_consistent"] is False


def test_upgrading_a_defect_to_success_is_rejected() -> None:
    sid_str, package, consistency = _seed_chain()
    defect = _defect_consistency(package, consistency)
    bundle = _service().build(
        session_id=UUID(sid_str),
        final_attestation_package=package,
        final_attestation_package_consistency=defect,
    )
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = True
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_CONSISTENT_MISMATCH"


# --- Missing / malformed nested data ----------------------------------------
def test_missing_nested_package_raises() -> None:
    _, _, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            final_attestation_package=None,
            final_attestation_package_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_PACKAGE_MISMATCH"


def test_missing_nested_consistency_raises() -> None:
    _, package, _ = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            final_attestation_package=package,
            final_attestation_package_consistency=None,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH"


def test_non_mapping_nested_package_raises() -> None:
    _, _, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            final_attestation_package="not-a-mapping",  # type: ignore[arg-type]
            final_attestation_package_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_PACKAGE_MISMATCH"


def test_non_mapping_nested_consistency_raises() -> None:
    _, package, _ = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            final_attestation_package=package,
            final_attestation_package_consistency="not-a-mapping",  # type: ignore[arg-type]  # noqa: E501
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH"


def test_malformed_nested_package_raises() -> None:
    _, _, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ):
        _service().build(
            final_attestation_package={"available": False},
            final_attestation_package_consistency=consistency,
        )


def test_malformed_nested_consistency_raises() -> None:
    _, package, _ = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            final_attestation_package=package,
            final_attestation_package_consistency={},
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


# --- Session / source / fingerprint binding ---------------------------------
def test_session_mismatch_raises() -> None:
    _, package, consistency = _seed_chain()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=uuid4(),
            final_attestation_package=package,
            final_attestation_package_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_nested_session_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(package)
    tampered["session_id"] = uuid4()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            final_attestation_package=tampered,
            final_attestation_package_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_inconsistent_consistency_session_flag_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(consistency)
    tampered["session_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            final_attestation_package=package,
            final_attestation_package_consistency=tampered,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_package_source_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            final_attestation_package=tampered,
            final_attestation_package_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_PACKAGE_SOURCE_MISMATCH"


def test_consistency_source_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(consistency)
    tampered["package_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            final_attestation_package=package,
            final_attestation_package_consistency=tampered,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_MISMATCH"


def test_fingerprint_binding_mismatch_raises() -> None:
    sid_str, package, consistency = _seed_chain()
    tampered = copy.deepcopy(consistency)
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=UUID(sid_str),
            final_attestation_package=package,
            final_attestation_package_consistency=tampered,
        )
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_BINDING_MISMATCH"


# --- Derived flag tampering --------------------------------------------------
def test_bundle_consistent_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_CONSISTENT_MISMATCH"


def test_bundle_fingerprint_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "BUNDLE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["audited_bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "AUDITED_BUNDLE_FINGERPRINT_MISMATCH"


def test_bundle_source_tampering_rejected() -> None:
    _, bundle = _seed_and_build()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
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
        bundle["final_attestation_package"].get("package_consistent", False)
        and bundle["final_attestation_package_consistency"].get(
            "package_consistent", False
        )
    )
    assert bundle["bundle_consistent"] == expected


def test_deterministic_direct_build() -> None:
    sid_str, package, consistency = _seed_chain()
    first = _service().build(
        session_id=UUID(sid_str),
        final_attestation_package=package,
        final_attestation_package_consistency=consistency,
    )
    second = _service().build(
        session_id=UUID(sid_str),
        final_attestation_package=package,
        final_attestation_package_consistency=consistency,
    )
    assert first == second


def test_deterministic_build_for_session() -> None:
    sid_str = _seed_full("Task 085 session-build capture")
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
        final_attestation_package=package,
        final_attestation_package_consistency=consistency,
    )
    assert package == before_package
    assert consistency == before_consistency


def test_read_only_no_new_sessions_created() -> None:
    sid_str = _seed_full("Task 085 read-only capture")
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

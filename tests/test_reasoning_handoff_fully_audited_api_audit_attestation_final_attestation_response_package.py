"""Tests for Task 093 fully audited final-attestation response package.

Task 093 binds the canonical Task 087 final-attestation API response to
the Task 088 consistency audit into a deterministic package. Pure
composition boundary; never accesses the database, never performs HTTP
calls, never calls external models, never mutates inputs.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    _expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService,  # noqa: E501
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
    """Re-assert this module's db override before every test.

    ``app.dependency_overrides`` is a single shared dict keyed by the
    ``get_db`` dependency; importing sibling test modules during
    collection can leave a different module's override active. Session
    identity must be preserved between ``client.post``/``client.get``
    calls (mediated by the app) and direct ``build_for_session`` calls
    (mediated by this module's own engine), so both must point at the
    same underlying database.
    """
    app.dependency_overrides[get_db] = override_get_db
    yield


PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "response",
    "response_consistency",
    "package_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService
):  # noqa: E501
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService()
    )  # noqa: E501


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-093-test"},
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


def _build_response_087(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_consistency_088(response: dict[str, Any]) -> dict[str, Any]:
    return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=response
    )


def _valid_triple() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full("Task 093 capture")
    sid = UUID(sid_str)
    response = _build_response_087(sid)
    consistency = _build_consistency_088(response)
    return sid, response, consistency


def _valid_package() -> tuple[UUID, dict[str, Any], dict[str, Any], dict[str, Any]]:
    sid, response, consistency = _valid_triple()
    pkg = _service().build(
        session_id=sid,
        response=response,
        response_consistency=consistency,
    )
    return sid, response, consistency, pkg


# --- Valid package ----------------------------------------------------------
def test_valid_package_shape_direct() -> None:
    sid, _response, _consistency, pkg = _valid_package()
    assert set(pkg) == set(PACKAGE_FIELDS)
    assert pkg["available"] is True
    assert pkg["package_consistent"] is True
    assert pkg["session_id"] == sid
    assert (
        pkg["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093  # noqa: E501
    )
    assert pkg["audited_package_fingerprint"] == pkg["package_fingerprint"]


def test_valid_package_schema_roundtrip() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead.model_validate(  # noqa: E501
        pkg
    )
    assert model.available is True
    assert model.package_consistent is True
    assert model.package_fingerprint == pkg["package_fingerprint"]
    assert model.audited_package_fingerprint == pkg["package_fingerprint"]


def test_build_for_session_matches_build() -> None:
    sid_str = _seed_full("Task 093 build-for-session")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        via_session = _service().build_for_session(db, sid)
    response = _build_response_087(sid)
    consistency = _build_consistency_088(response)
    via_build = _service().build(
        session_id=sid,
        response=response,
        response_consistency=consistency,
    )
    assert via_session == via_build


def test_build_for_session_delegates_exactly_once() -> None:
    sid_str = _seed_full("Task 093 delegation")
    sid = UUID(sid_str)
    calls_087: list[Any] = []
    calls_088: list[Any] = []

    real_087 = (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService()
    )  # noqa: E501
    real_088 = (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService()
    )  # noqa: E501

    class _Counting087:
        def build_for_session(self, db: Session, session_id: UUID) -> dict[str, Any]:
            calls_087.append(session_id)
            return real_087.build_for_session(db, session_id)

    class _Counting088:
        def build(self, *, response: Any = None) -> dict[str, Any]:
            calls_088.append(response)
            return real_088.build(response=response)

    svc = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService(  # noqa: E501
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_service=_Counting087(),  # type: ignore[arg-type]  # noqa: E501
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency_service=_Counting088(),  # type: ignore[arg-type]  # noqa: E501
    )
    with TestingSessionLocal() as db:
        svc.build_for_session(db, sid)
    assert len(calls_087) == 1
    assert len(calls_088) == 1


def test_nested_sources_preserved() -> None:
    _sid, response, consistency, pkg = _valid_package()
    assert (
        pkg["response"]["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
    )
    assert (
        pkg["response_consistency"]["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
    )
    assert response["response_source"] == pkg["response"]["response_source"]
    assert (
        consistency["response_consistency_source"]
        == pkg["response_consistency"]["response_consistency_source"]
    )


# --- Missing fields ---------------------------------------------------------
@pytest.mark.parametrize("field", PACKAGE_FIELDS)
def test_missing_package_field_rejected(field: str) -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    del tampered[field]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "MISSING_PACKAGE_FIELD"
    with pytest.raises(ValidationError):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead.model_validate(  # noqa: E501
            tampered
        )


def test_missing_response_rejected() -> None:
    sid, _response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=None,
            response_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_MISMATCH"


def test_missing_response_consistency_rejected() -> None:
    sid, response, _consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=response,
            response_consistency=None,
        )
    assert ei.value.invariant == "RESPONSE_CONSISTENCY_MISMATCH"


def test_non_mapping_inputs_rejected() -> None:
    sid, response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response="not-a-mapping",  # type: ignore[arg-type]
            response_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_MISMATCH"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=response,
            response_consistency="not-a-mapping",  # type: ignore[arg-type]  # noqa: E501
        )
    assert ei.value.invariant == "RESPONSE_CONSISTENCY_MISMATCH"


# --- Session binding --------------------------------------------------------
def test_session_mismatch_rejected() -> None:
    _sid, response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=uuid4(),
            response=response,
            response_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_session_consistent_false_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["session_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=response,
            response_consistency=broken,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_implicit_session_id_derived_from_response() -> None:
    _sid, response, consistency = _valid_triple()
    pkg = _service().build(
        response=response,
        response_consistency=consistency,
    )
    assert pkg["session_id"] == response["session_id"]


def test_invalid_session_id_rejected() -> None:
    _sid, response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id="not-a-uuid",
            response=response,
            response_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


# --- Source binding ---------------------------------------------------------
def test_response_source_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(response)
    broken["response_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=broken,
            response_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_SOURCE_MISMATCH"


def test_consistency_source_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["response_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=response,
            response_consistency=broken,
        )
    assert ei.value.invariant == ("RESPONSE_CONSISTENCY_SOURCE_MISMATCH")


def test_package_source_mismatch_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


# --- Nested contract failures -----------------------------------------------
def test_nested_response_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(response)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=broken,
            response_consistency=consistency,
        )
    assert ei.value.invariant == "RESPONSE_MISMATCH"


def test_nested_consistency_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            response=response,
            response_consistency=broken,
        )
    assert ei.value.invariant == "RESPONSE_CONSISTENCY_MISMATCH"


def test_nested_response_tamper_detected_by_validator() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["response"]["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ):
        _service()._validate_result(tampered)


def test_nested_consistency_tamper_detected_by_validator() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["response_consistency"]["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "RESPONSE_CONSISTENCY_MISMATCH"


# --- Fingerprints -----------------------------------------------------------
def test_fingerprint_format_failure_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    for bad in ("AB" * 32, "0" * 63, "0" * 65, "", None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "PACKAGE_FINGERPRINT_FORMAT"


def test_audited_fingerprint_format_failure_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    for bad in ("AB" * 32, "0" * 63, "0" * 65, "", None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["audited_package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_fingerprint_tampering_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_tampering_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["audited_package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_binds_to_package_fingerprint() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    assert pkg["audited_package_fingerprint"] == pkg["package_fingerprint"]
    assert len(pkg["package_fingerprint"]) == 64
    assert len(pkg["audited_package_fingerprint"]) == 64


def test_package_consistent_tamper_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_MISMATCH"


def test_exact_fingerprint_recomputation() -> None:
    sid, response, consistency, pkg = _valid_package()
    core = {
        "session_id": str(sid),
        "response": mod._canonicalize(response),
        "response_consistency": mod._canonicalize(consistency),
    }
    expected = mod._compute_package_fingerprint(core)
    assert pkg["package_fingerprint"] == expected
    assert pkg["package_fingerprint"] == mod._expected_package_fingerprint(pkg)
    manual = hashlib.sha256(
        json.dumps(
            mod._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert pkg["package_fingerprint"] == manual


# --- Legitimate defect preservation (AND-derivation) ------------------------
def test_legitimate_defect_false_response_true_audit_packages_false() -> None:
    """A coherent Task 087 False + Task 088 True must package to False.

    Builds the defect coherently via real services: tampers the nested
    Task 084 fingerprints to create a package-binding mismatch (which the
    Task 085 validator does not police), rebuilds the Task 086 audit via
    its real service (False, with the binding issue), constructs the
    coherent Task 087 False envelope, rebuilds the Task 088 audit via its
    real service (True, envelope coherent), then packages. The package
    must report ``package_consistent is False`` (AND-derivation) without
    raising, preserving the legitimate defect.
    """
    sid_str = _seed_full("Task 093 legitimate defect")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        valid_087 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    bundle_085 = copy.deepcopy(valid_087["final_attestation_bundle"])
    nested_cons = bundle_085["final_attestation_package_consistency"]
    nested_cons["package_fingerprint"] = "0" * 64
    nested_cons["audited_package_fingerprint"] = "0" * 64
    recomputed_bundle_fp = _expected_bundle_fingerprint(bundle_085)
    bundle_085["bundle_fingerprint"] = recomputed_bundle_fp
    bundle_085["audited_bundle_fingerprint"] = recomputed_bundle_fp

    tampered_086 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
        bundle=bundle_085
    )
    assert tampered_086["bundle_consistent"] is False
    assert "PACKAGE_FINGERPRINT_BINDING_MISMATCH" in tampered_086["consistency_issues"]

    tampered_087 = {
        "available": True,
        "response_consistent": False,
        "session_id": sid,
        "final_attestation_bundle": bundle_085,
        "final_attestation_bundle_consistency": tampered_086,
        "response_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    }
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
        tampered_087
    )

    tampered_088 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered_087
    )
    assert tampered_088["response_consistent"] is True
    assert tampered_088["session_consistent"] is True

    pkg = _service().build(
        session_id=sid,
        response=tampered_087,
        response_consistency=tampered_088,
    )
    assert pkg["package_consistent"] is False
    assert pkg["package_consistent"] == bool(
        tampered_087["response_consistent"] and tampered_088["response_consistent"]
    )
    _service()._validate_result(pkg)


# --- Determinism / purity ---------------------------------------------------
def test_deterministic_output() -> None:
    sid, response, consistency = _valid_triple()
    p1 = _service().build(
        session_id=sid,
        response=response,
        response_consistency=consistency,
    )
    p2 = _service().build(
        session_id=sid,
        response=response,
        response_consistency=consistency,
    )
    assert p1 == p2
    assert p1["package_fingerprint"] == p2["package_fingerprint"]


def test_input_immutability() -> None:
    sid, response, consistency = _valid_triple()
    before_response = copy.deepcopy(response)
    before_consistency = copy.deepcopy(consistency)
    _service().build(
        session_id=sid,
        response=response,
        response_consistency=consistency,
    )
    assert response == before_response
    assert consistency == before_consistency


def test_build_does_not_mutate_inputs_deep() -> None:
    sid, response, consistency = _valid_triple()
    response_snapshot = copy.deepcopy(response)
    consistency_snapshot = copy.deepcopy(consistency)
    pkg = _service().build(
        session_id=sid,
        response=response,
        response_consistency=consistency,
    )
    assert response == response_snapshot
    assert consistency == consistency_snapshot
    assert pkg["response"] == response_snapshot
    assert pkg["response_consistency"] == consistency_snapshot


# --- No external dependencies -----------------------------------------------
def test_build_has_no_external_dependencies() -> None:
    src = inspect.getsource(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService.build  # noqa: E501
    )
    for forbidden in (
        "TestClient",
        "httpx",
        "requests",
        "urllib",
        "urlopen",
        "socket",
        "client.get",
        "SessionLocal",
        "create_engine",
        "get_db",
        "sqlalchemy",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "provider",
        "model_name",
        "api_key",
    ):
        assert forbidden not in src, f"Forbidden symbol {forbidden!r} in build"


def test_production_service_purity() -> None:
    src_file = inspect.getfile(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService  # noqa: E501
    )
    with open(src_file, encoding="utf-8") as f:
        src = f.read()
    for sym in (
        "TestClient",
        "httpx",
        "requests",
        "urllib",
        "urlopen",
        "socket",
        "FastAPI",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "provider",
        "model_name",
        "api_key",
        "RAG",
    ):
        assert sym not in src, f"Forbidden symbol {sym!r} in production service"


def test_no_module_mutable_state() -> None:
    for name in dir(mod):
        assert not name.startswith("_LAST"), f"Found mutable state: {name}"
    for name, val in inspect.getmembers(mod):
        if name.startswith("__"):
            continue
        if isinstance(val, (dict, list, set)):
            assert name not in ("cache", "state", "store", "registry")

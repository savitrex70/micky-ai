"""Tests for Task 077 fully audited attestation response package.

Task 077 binds the canonical Task 075 attestation API response to the
Task 076 consistency audit into a deterministic package. Pure composition
boundary; never accesses the database, never performs HTTP calls, never
calls external models, never mutates inputs.
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_response_package as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_077,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService,
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
    "attestation_response",
    "attestation_response_consistency",
    "package_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)


def _service() -> ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService:
    return ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-077-test"},
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


def _build_response_075(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationResponseService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_consistency_076(response: dict[str, Any]) -> dict[str, Any]:
    return ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService().build(  # noqa: E501
        response=response
    )


def _valid_triple() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full("Task 077 capture")
    sid = UUID(sid_str)
    response = _build_response_075(sid)
    consistency = _build_consistency_076(response)
    return sid, response, consistency


def _valid_package() -> tuple[UUID, dict[str, Any], dict[str, Any], dict[str, Any]]:
    sid, response, consistency = _valid_triple()
    pkg = _service().build(
        session_id=sid,
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    return sid, response, consistency, pkg


def _endpoint(sid: str) -> str:
    return (
        f"/sessions/{sid}/reasoning-handoff/fully-audited/"
        "attestation/response-package"
    )


# --- Valid package ----------------------------------------------------------
def test_valid_package_shape_direct() -> None:
    sid, _response, _consistency, pkg = _valid_package()
    assert set(pkg) == set(PACKAGE_FIELDS)
    assert pkg["available"] is True
    assert pkg["package_consistent"] is True
    assert pkg["session_id"] == sid
    assert (
        pkg["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_077  # noqa: E501
    )
    assert pkg["audited_package_fingerprint"] == pkg["package_fingerprint"]


def test_valid_package_schema_roundtrip() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead.model_validate(  # noqa: E501
        pkg
    )
    assert model.available is True
    assert model.package_consistent is True
    assert model.package_fingerprint == pkg["package_fingerprint"]
    assert model.audited_package_fingerprint == pkg["package_fingerprint"]


def test_build_for_session_matches_build() -> None:
    sid_str = _seed_full("Task 077 build-for-session")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        via_session = _service().build_for_session(db, sid)
    response = _build_response_075(sid)
    consistency = _build_consistency_076(response)
    via_build = _service().build(
        session_id=sid,
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    assert via_session == via_build


def test_nested_sources_preserved() -> None:
    _sid, response, consistency, pkg = _valid_package()
    assert (
        pkg["attestation_response"]["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
    )
    assert (
        pkg["attestation_response_consistency"]["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076  # noqa: E501
    )
    assert response["response_source"] == pkg["attestation_response"]["response_source"]
    assert (
        consistency["response_consistency_source"]
        == pkg["attestation_response_consistency"]["response_consistency_source"]
    )


# --- HTTP endpoint ----------------------------------------------------------
def test_valid_package_via_endpoint() -> None:
    sid_str = _seed_full("Task 077 endpoint capture")
    r = client.get(_endpoint(sid_str))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(PACKAGE_FIELDS)
    assert body["available"] is True
    assert body["session_id"] == sid_str
    assert (
        body["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_077  # noqa: E501
    )


def test_endpoint_matches_direct_build() -> None:
    sid_str = _seed_full("Task 077 endpoint parity")
    r = client.get(_endpoint(sid_str))
    assert r.status_code == 200
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        direct = _service().build_for_session(db, sid)
    body = r.json()
    assert body["package_fingerprint"] == direct["package_fingerprint"]
    assert body["audited_package_fingerprint"] == direct["audited_package_fingerprint"]
    assert body["package_consistent"] == direct["package_consistent"]


def test_missing_session_returns_404() -> None:
    r = client.get(_endpoint(str(uuid4())))
    assert r.status_code == 404


# --- Missing fields ---------------------------------------------------------
@pytest.mark.parametrize("field", PACKAGE_FIELDS)
def test_missing_package_field_rejected(field: str) -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    del tampered[field]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "MISSING_PACKAGE_FIELD"
    with pytest.raises(ValidationError):
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead.model_validate(  # noqa: E501
            tampered
        )


def test_missing_attestation_response_rejected() -> None:
    sid, _response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=None,
            attestation_response_consistency=consistency,
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_MISMATCH"


def test_missing_attestation_response_consistency_rejected() -> None:
    sid, response, _consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=response,
            attestation_response_consistency=None,
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_CONSISTENCY_MISMATCH"


def test_non_mapping_inputs_rejected() -> None:
    sid, response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response="not-a-mapping",  # type: ignore[arg-type]
            attestation_response_consistency=consistency,
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_MISMATCH"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=response,
            attestation_response_consistency="not-a-mapping",  # type: ignore[arg-type]  # noqa: E501
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_CONSISTENCY_MISMATCH"


# --- Session binding --------------------------------------------------------
def test_session_mismatch_rejected() -> None:
    _sid, response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=uuid4(),
            attestation_response=response,
            attestation_response_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_session_consistent_false_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["session_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=response,
            attestation_response_consistency=broken,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_implicit_session_id_derived_from_response() -> None:
    _sid, response, consistency = _valid_triple()
    pkg = _service().build(
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    assert pkg["session_id"] == response["session_id"]


def test_invalid_session_id_rejected() -> None:
    _sid, response, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id="not-a-uuid",
            attestation_response=response,
            attestation_response_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


# --- Source binding ---------------------------------------------------------
def test_attestation_response_source_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(response)
    broken["response_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=broken,
            attestation_response_consistency=consistency,
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_SOURCE_MISMATCH"


def test_consistency_source_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["response_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=response,
            attestation_response_consistency=broken,
        )
    assert ei.value.invariant == ("ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_MISMATCH")


def test_package_source_mismatch_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


# --- Nested contract failures -----------------------------------------------
def test_nested_response_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(response)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=broken,
            attestation_response_consistency=consistency,
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_MISMATCH"


def test_nested_consistency_mismatch_rejected() -> None:
    sid, response, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            attestation_response=response,
            attestation_response_consistency=broken,
        )
    assert ei.value.invariant == "ATTESTATION_RESPONSE_CONSISTENCY_MISMATCH"


def test_nested_response_tamper_detected_by_validator() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["attestation_response"]["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ):
        _service()._validate_result(tampered)


def test_nested_consistency_tamper_detected_by_validator() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["attestation_response_consistency"]["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "ATTESTATION_RESPONSE_CONSISTENCY_MISMATCH"


# --- Fingerprints -----------------------------------------------------------
def test_fingerprint_format_failure_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    for bad in ("AB" * 32, "0" * 63, "0" * 65, "", None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "PACKAGE_FINGERPRINT_FORMAT"


def test_audited_fingerprint_format_failure_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    for bad in ("AB" * 32, "0" * 63, "0" * 65, "", None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["audited_package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_fingerprint_tampering_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_tampering_rejected() -> None:
    _sid, _response, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["audited_package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
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
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageContractError
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_MISMATCH"


def test_exact_fingerprint_recomputation() -> None:
    sid, response, consistency, pkg = _valid_package()
    core = {
        "session_id": str(sid),
        "attestation_response": mod._canonicalize(response),
        "attestation_response_consistency": mod._canonicalize(consistency),
    }
    expected = mod._compute_package_fingerprint(core)
    assert pkg["package_fingerprint"] == expected
    manual = hashlib.sha256(
        json.dumps(
            mod._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert pkg["package_fingerprint"] == manual


# --- Determinism / purity ---------------------------------------------------
def test_deterministic_output() -> None:
    sid, response, consistency = _valid_triple()
    p1 = _service().build(
        session_id=sid,
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    p2 = _service().build(
        session_id=sid,
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    assert p1 == p2
    assert p1["package_fingerprint"] == p2["package_fingerprint"]


def test_deterministic_repeated_get() -> None:
    sid_str = _seed_full("Task 077 deterministic capture")
    r1 = client.get(_endpoint(sid_str))
    r2 = client.get(_endpoint(sid_str))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_input_immutability() -> None:
    sid, response, consistency = _valid_triple()
    before_response = copy.deepcopy(response)
    before_consistency = copy.deepcopy(consistency)
    _service().build(
        session_id=sid,
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    assert response == before_response
    assert consistency == before_consistency


def test_build_does_not_mutate_inputs_deep() -> None:
    sid, response, consistency = _valid_triple()
    response_snapshot = copy.deepcopy(response)
    consistency_snapshot = copy.deepcopy(consistency)
    pkg = _service().build(
        session_id=sid,
        attestation_response=response,
        attestation_response_consistency=consistency,
    )
    assert response == response_snapshot
    assert consistency == consistency_snapshot
    assert pkg["attestation_response"] == response_snapshot
    assert pkg["attestation_response_consistency"] == consistency_snapshot


# --- No external dependencies -----------------------------------------------
def test_build_has_no_external_dependencies() -> None:
    src = inspect.getsource(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService.build
    )
    for forbidden in (
        "TestClient",
        "httpx",
        "requests",
        "urllib",
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
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService
    )
    with open(src_file, encoding="utf-8") as f:
        src = f.read()
    for sym in (
        "TestClient",
        "httpx",
        "requests",
        "urllib",
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

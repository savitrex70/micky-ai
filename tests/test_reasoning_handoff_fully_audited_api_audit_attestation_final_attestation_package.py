"""Tests for Task 083 final attestation package.

Task 083 binds the canonical Task 081 final attestation to the Task 082
consistency audit into a deterministic package. Pure composition
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
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead,
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,  # noqa: E501
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
    identity must be preserved between ``client.post`` calls (mediated
    by the app) and direct ``build_for_session`` calls (mediated by this
    module's own engine), so both must point at the same database.
    """
    app.dependency_overrides[get_db] = override_get_db
    yield


PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "final_attestation",
    "final_attestation_consistency",
    "package_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService
):  # noqa: E501
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService()
    )  # noqa: E501


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-083-test"},
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


def _build_final_081(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_consistency_082(
    final_attestation: dict[str, Any],
) -> dict[str, Any]:
    return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService().build(  # noqa: E501
        final_attestation=final_attestation
    )


def _valid_triple() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full("Task 083 capture")
    sid = UUID(sid_str)
    final = _build_final_081(sid)
    consistency = _build_consistency_082(final)
    return sid, final, consistency


def _valid_package() -> tuple[UUID, dict[str, Any], dict[str, Any], dict[str, Any]]:
    sid, final, consistency = _valid_triple()
    pkg = _service().build(
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    return sid, final, consistency, pkg


# --- Valid package ----------------------------------------------------------
def test_valid_package_shape_direct() -> None:
    sid, _final, _consistency, pkg = _valid_package()
    assert set(pkg) == set(PACKAGE_FIELDS)
    assert pkg["available"] is True
    assert pkg["package_consistent"] is True
    assert pkg["session_id"] == sid
    assert (
        pkg["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
    )
    assert pkg["audited_package_fingerprint"] == pkg["package_fingerprint"]


def test_valid_package_schema_roundtrip() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead.model_validate(  # noqa: E501
        pkg
    )
    assert model.available is True
    assert model.package_consistent is True
    assert model.package_fingerprint == pkg["package_fingerprint"]
    assert model.audited_package_fingerprint == pkg["package_fingerprint"]


def test_build_for_session_matches_build() -> None:
    sid_str = _seed_full("Task 083 build-for-session")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        via_session = _service().build_for_session(db, sid)
    final = _build_final_081(sid)
    consistency = _build_consistency_082(final)
    via_build = _service().build(
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    assert via_session == via_build


def test_nested_sources_preserved() -> None:
    _sid, final, consistency, pkg = _valid_package()
    assert (
        pkg["final_attestation"]["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081  # noqa: E501
    )
    assert (
        pkg["final_attestation_consistency"][
            "final_attestation_consistency_source"
        ]  # noqa: E501
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
    )
    assert (
        final["final_attestation_source"]
        == pkg["final_attestation"]["final_attestation_source"]
    )
    assert (
        consistency["final_attestation_consistency_source"]
        == pkg["final_attestation_consistency"]["final_attestation_consistency_source"]
    )


def test_package_consistent_derived_from_consistency() -> None:
    _sid, _final, consistency, pkg = _valid_package()
    assert pkg["package_consistent"] == bool(
        consistency.get("final_attestation_consistent", False)
    )
    assert pkg["package_consistent"] is True


def test_build_for_session_calls_081_exactly_once() -> None:
    sid_str = _seed_full("Task 083 exactly-once")
    sid = UUID(sid_str)
    svc = _service()
    calls: list[UUID] = []
    inner = (
        svc.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_service
    )  # noqa: E501
    orig = inner.build_for_session

    def _counting(db: Session, session_id: UUID) -> dict[str, Any]:
        calls.append(session_id)
        return orig(db, session_id)

    inner.build_for_session = _counting  # type: ignore[method-assign]
    try:
        with TestingSessionLocal() as db:
            svc.build_for_session(db, sid)
    finally:
        inner.build_for_session = orig  # type: ignore[method-assign]
    assert calls == [sid]


# --- Missing fields ---------------------------------------------------------
@pytest.mark.parametrize("field", PACKAGE_FIELDS)
def test_missing_package_field_rejected(field: str) -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    del tampered[field]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "MISSING_PACKAGE_FIELD"
    with pytest.raises(ValidationError):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead.model_validate(  # noqa: E501
            tampered
        )


def test_missing_final_attestation_rejected() -> None:
    sid, _final, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=None,
            final_attestation_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_MISMATCH"


def test_missing_final_attestation_consistency_rejected() -> None:
    sid, final, _consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=None,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_MISMATCH"


def test_non_mapping_inputs_rejected() -> None:
    sid, final, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation="not-a-mapping",  # type: ignore[arg-type]
            final_attestation_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_MISMATCH"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency="not-a-mapping",  # type: ignore[arg-type]  # noqa: E501
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_MISMATCH"


# --- Session binding --------------------------------------------------------
def test_session_mismatch_rejected() -> None:
    _sid, final, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=uuid4(),
            final_attestation=final,
            final_attestation_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_session_consistent_false_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["session_consistent"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=broken,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_implicit_session_id_derived_from_final() -> None:
    _sid, final, consistency = _valid_triple()
    pkg = _service().build(
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    assert pkg["session_id"] == final["session_id"]


def test_invalid_session_id_rejected() -> None:
    _sid, final, consistency = _valid_triple()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id="not-a-uuid",
            final_attestation=final,
            final_attestation_consistency=consistency,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


# --- Source binding ---------------------------------------------------------
def test_final_attestation_source_mismatch_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(final)
    broken["final_attestation_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=broken,
            final_attestation_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_SOURCE_MISMATCH"


def test_consistency_source_mismatch_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["final_attestation_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=broken,
        )
    assert (
        ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH"
    )  # noqa: E501


def test_package_source_mismatch_rejected() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


# --- Nested contract failures -----------------------------------------------
def test_nested_final_mismatch_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(final)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=broken,
            final_attestation_consistency=consistency,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_MISMATCH"


def test_nested_consistency_mismatch_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=broken,
        )
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_MISMATCH"


def test_nested_final_tamper_detected_by_validator() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["final_attestation"]["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ):
        _service()._validate_result(tampered)


def test_nested_consistency_tamper_detected_by_validator() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["final_attestation_consistency"]["available"] = False
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_MISMATCH"


# --- Task 081 fingerprint binding (no or-fallback) ---------------------------
def test_consistency_fingerprint_binding_mismatch_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["final_attestation_fingerprint"] = "0" * 64
    assert (
        broken["final_attestation_fingerprint"]
        != final["final_attestation_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=broken,
        )
    # The tampered nested Task 082 audit fails its own canonical validator
    # first (it recomputes the binding itself); the package layer reports
    # the nested failure rather than masking it.
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_MISMATCH"


def test_consistency_audited_fingerprint_binding_mismatch_rejected() -> None:
    sid, final, consistency = _valid_triple()
    broken = copy.deepcopy(consistency)
    broken["audited_final_attestation_fingerprint"] = "1" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=broken,
        )
    # Same layered detection as above: the nested Task 082 validator
    # rejects its own tampered fingerprint binding first.
    assert ei.value.invariant == "FINAL_ATTESTATION_CONSISTENCY_MISMATCH"


def test_binding_requires_both_fields_no_fallback() -> None:
    sid, final, consistency = _valid_triple()
    only_first = copy.deepcopy(consistency)
    del only_first["audited_final_attestation_fingerprint"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ):
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=only_first,
        )
    only_second = copy.deepcopy(consistency)
    del only_second["final_attestation_fingerprint"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ):
        _service().build(
            session_id=sid,
            final_attestation=final,
            final_attestation_consistency=only_second,
        )


# --- Fingerprints -----------------------------------------------------------
def test_fingerprint_format_failure_rejected() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    for bad in ("AB" * 32, "0" * 63, "0" * 65, "", None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "PACKAGE_FINGERPRINT_FORMAT"


def test_audited_fingerprint_format_failure_rejected() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    for bad in ("AB" * 32, "0" * 63, "0" * 65, "", None, 123):
        tampered = copy.deepcopy(pkg)
        tampered["audited_package_fingerprint"] = bad
        with pytest.raises(
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
        ) as ei:
            _service()._validate_result(tampered)
        assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_fingerprint_tampering_rejected() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_tampering_rejected() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["audited_package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"


def test_audited_fingerprint_binds_to_package_fingerprint() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    assert pkg["audited_package_fingerprint"] == pkg["package_fingerprint"]
    assert len(pkg["package_fingerprint"]) == 64
    assert len(pkg["audited_package_fingerprint"]) == 64


def test_package_consistent_tamper_rejected() -> None:
    _sid, _final, _consistency, pkg = _valid_package()
    tampered = copy.deepcopy(pkg)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ) as ei:
        _service()._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_MISMATCH"


def test_exact_fingerprint_recomputation() -> None:
    sid, final, consistency, pkg = _valid_package()
    core = {
        "session_id": str(sid),
        "final_attestation": mod._canonicalize(final),
        "final_attestation_consistency": mod._canonicalize(consistency),
    }
    expected = mod._compute_package_fingerprint(core)
    assert pkg["package_fingerprint"] == expected
    assert mod._expected_package_fingerprint(pkg) == expected
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
    sid, final, consistency = _valid_triple()
    p1 = _service().build(
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    p2 = _service().build(
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    assert p1 == p2
    assert p1["package_fingerprint"] == p2["package_fingerprint"]


def test_input_immutability() -> None:
    sid, final, consistency = _valid_triple()
    before_final = copy.deepcopy(final)
    before_consistency = copy.deepcopy(consistency)
    _service().build(
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    assert final == before_final
    assert consistency == before_consistency


def test_build_does_not_mutate_inputs_deep() -> None:
    sid, final, consistency = _valid_triple()
    final_snapshot = copy.deepcopy(final)
    consistency_snapshot = copy.deepcopy(consistency)
    pkg = _service().build(
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    assert final == final_snapshot
    assert consistency == consistency_snapshot
    assert pkg["final_attestation"] == final_snapshot
    assert pkg["final_attestation_consistency"] == consistency_snapshot


# --- No external dependencies -----------------------------------------------
def test_build_has_no_external_dependencies() -> None:
    src = inspect.getsource(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService.build  # noqa: E501
    )
    lowered = src.lower()
    for forbidden in (
        "testclient",
        "httpx",
        "requests",
        "urllib",
        "urlopen",
        "socket",
        "client.get",
        "sessionlocal",
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
        assert (
            forbidden not in lowered
        ), f"Forbidden symbol {forbidden!r} in build"  # noqa: E501


def test_production_service_purity() -> None:
    src_file = inspect.getfile(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService  # noqa: E501
    )
    with open(src_file, encoding="utf-8") as f:
        src = f.read()
    lowered = src.lower()
    for sym in (
        "testclient",
        "httpx",
        "requests",
        "urlopen",
        "socket",
        "fastapi",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "provider",
        "model_name",
        "api_key",
        "rag",
    ):
        assert (
            sym not in lowered
        ), f"Forbidden symbol {sym!r} in production service"  # noqa: E501
    assert "get_db" not in src, "Forbidden symbol 'get_db' in production service"


def test_no_module_mutable_state() -> None:
    for name in dir(mod):
        assert not name.startswith("_LAST"), f"Found mutable state: {name}"
    for name, val in inspect.getmembers(mod):
        if name.startswith("__"):
            continue
        if isinstance(val, (dict, list, set)):
            assert name not in ("cache", "state", "store", "registry")

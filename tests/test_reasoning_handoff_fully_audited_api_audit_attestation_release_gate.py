"""Tests for Task 092 release gate over Tasks 083-091 chain.

Final verification gate for the complete 083-091 chain. Review-oriented
regression tests only; no speculative functionality. Seeded via TestClient
sqlite-memory sessions and using only real services.
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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.models.reasoning_session import ReasoningSession
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle as mod085,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency as mod086,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package as mod083,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency as mod084,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response as mod087,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency as mod088,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
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


FIELDS_075 = (
    "available",
    "response_consistent",
    "session_id",
    "attestation_package",
    "attestation_package_consistency",
    "response_source",
)

FIELDS_081 = (
    "available",
    "final_attestation_consistent",
    "session_id",
    "response_bundle",
    "response_bundle_consistency",
    "final_attestation_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

PATH_075 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation"
PATH_077 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "response-package"
)
PATH_079 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "audit-bundle"
PATH_081 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/final"
PATH_087 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "final-response"
)

FORBIDDEN_TOKENS = (
    "httpx",
    "requests",
    "get_db",
    "TestClient",
    "openai",
    "gemini",
    "anthropic",
    "ollama",
    "api_key",
    "urlopen",
    "socket",
)

SIX_MODULES = (mod083, mod084, mod085, mod086, mod087, mod088)


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-092-test"},
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


def _build_083(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_085(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_087(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_088(response: dict[str, Any]) -> dict[str, Any]:
    return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=response
    )


def _seed_and_build_087() -> tuple[str, dict[str, Any]]:
    sid_str = _seed_full("Task 092 capture")
    return sid_str, _build_087(UUID(sid_str))


def _session_count() -> int:
    with TestingSessionLocal() as db:
        return int(db.query(ReasoningSession).count())


def _alt_hex(value: str) -> str:
    assert isinstance(value, str) and len(value) == 64
    return "0" * 64 if value != "0" * 64 else "f" * 64


# --- (1) additive / backward-compatible ---------------------------------------


def test_075_endpoint_exact_shape() -> None:
    sid_str = _seed_full("Task 092 compat 075")
    r = client.get(PATH_075.format(sid=sid_str))
    assert r.status_code == 200
    assert set(r.json()) == set(FIELDS_075)


def test_081_endpoint_exact_shape() -> None:
    sid_str = _seed_full("Task 092 compat 081")
    r = client.get(PATH_081.format(sid=sid_str))
    assert r.status_code == 200
    assert set(r.json()) == set(FIELDS_081)


# --- (2) purity ----------------------------------------------------------------


def test_purity_no_forbidden_tokens_all_six() -> None:
    for mod in SIX_MODULES:
        src = inspect.getsource(mod).lower()
        for token in FORBIDDEN_TOKENS:
            assert token.lower() not in src, (mod.__name__, token)


def test_purity_no_db_writes_full_chain() -> None:
    sid_str = _seed_full("Task 092 purity")
    sid = UUID(sid_str)
    before = _session_count()
    with TestingSessionLocal() as db:
        pkg = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build_for_session(  # noqa: E501
            db, sid
        )
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService().build(  # noqa: E501
            package=pkg
        )
        bundle = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build_for_session(  # noqa: E501
            db, sid
        )
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
            bundle=bundle
        )
        response = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
        _build_088(response)
    after = _session_count()
    assert before == after


# --- (3) read-only API ----------------------------------------------------------


def test_readonly_repeated_gets_identical() -> None:
    sid_str = _seed_full("Task 092 readonly")
    for path in (PATH_075, PATH_077, PATH_079, PATH_081, PATH_087):
        first = client.get(path.format(sid=sid_str))
        second = client.get(path.format(sid=sid_str))
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()


def test_readonly_repeated_get_075() -> None:
    sid_str = _seed_full("Task 092 readonly 075")
    first = client.get(PATH_075.format(sid=sid_str))
    second = client.get(PATH_075.format(sid=sid_str))
    assert first.json() == second.json()


def test_readonly_repeated_get_077() -> None:
    sid_str = _seed_full("Task 092 readonly 077")
    first = client.get(PATH_077.format(sid=sid_str))
    second = client.get(PATH_077.format(sid=sid_str))
    assert first.status_code == 200
    assert first.json() == second.json()


def test_readonly_repeated_get_079() -> None:
    sid_str = _seed_full("Task 092 readonly 079")
    first = client.get(PATH_079.format(sid=sid_str))
    second = client.get(PATH_079.format(sid=sid_str))
    assert first.status_code == 200
    assert first.json() == second.json()


def test_readonly_repeated_get_081() -> None:
    sid_str = _seed_full("Task 092 readonly 081")
    first = client.get(PATH_081.format(sid=sid_str))
    second = client.get(PATH_081.format(sid=sid_str))
    assert first.status_code == 200
    assert first.json() == second.json()


def test_readonly_repeated_get_087() -> None:
    sid_str = _seed_full("Task 092 readonly 087")
    first = client.get(PATH_087.format(sid=sid_str))
    second = client.get(PATH_087.format(sid=sid_str))
    assert first.status_code == 200
    assert first.json() == second.json()


# --- (4) self-authenticating ----------------------------------------------------


def test_self_auth_083_package_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_087()
    pkg = _build_083(UUID(sid_str))
    tampered = copy.deepcopy(pkg)
    tampered["package_fingerprint"] = _alt_hex(pkg["package_fingerprint"])
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_083_audited_package_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_087()
    pkg = _build_083(UUID(sid_str))
    tampered = copy.deepcopy(pkg)
    tampered["audited_package_fingerprint"] = _alt_hex(
        pkg["audited_package_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_085_bundle_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_087()
    bundle = _build_085(UUID(sid_str))
    tampered = copy.deepcopy(bundle)
    tampered["bundle_fingerprint"] = _alt_hex(bundle["bundle_fingerprint"])
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_085_audited_bundle_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_087()
    bundle = _build_085(UUID(sid_str))
    tampered = copy.deepcopy(bundle)
    tampered["audited_bundle_fingerprint"] = _alt_hex(
        bundle["audited_bundle_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_087_bundle_fingerprint_binding_tamper() -> None:
    _, response = _seed_and_build_087()
    tampered = copy.deepcopy(response)
    nested = copy.deepcopy(response["final_attestation_bundle_consistency"])
    nested["bundle_fingerprint"] = _alt_hex(nested["bundle_fingerprint"])
    tampered["final_attestation_bundle_consistency"] = nested
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_087_audited_bundle_fingerprint_binding_tamper() -> None:
    _, response = _seed_and_build_087()
    tampered = copy.deepcopy(response)
    nested = copy.deepcopy(response["final_attestation_bundle_consistency"])
    nested["audited_bundle_fingerprint"] = _alt_hex(
        nested["audited_bundle_fingerprint"]
    )
    tampered["final_attestation_bundle_consistency"] = nested
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_087_envelope_bundle_tamper() -> None:
    _, response = _seed_and_build_087()
    tampered = copy.deepcopy(response)
    bundle = copy.deepcopy(response["final_attestation_bundle"])
    bundle["bundle_fingerprint"] = _alt_hex(bundle["bundle_fingerprint"])
    tampered["final_attestation_bundle"] = bundle
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


# --- (5) recomputability --------------------------------------------------------


def test_recompute_083_fingerprint() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    pkg = _build_083(sid)
    core = {
        "session_id": str(sid),
        "final_attestation": mod083._canonicalize(pkg["final_attestation"]),
        "final_attestation_consistency": mod083._canonicalize(
            pkg["final_attestation_consistency"]
        ),
    }
    expected = mod083._compute_package_fingerprint(core)
    assert pkg["package_fingerprint"] == expected
    assert pkg["audited_package_fingerprint"] == expected
    assert mod083._expected_package_fingerprint(pkg) == expected
    manual = hashlib.sha256(
        json.dumps(
            mod083._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert pkg["package_fingerprint"] == manual


def test_recompute_085_fingerprint() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    bundle = _build_085(sid)
    core = {
        "session_id": str(sid),
        "final_attestation_package": mod085._canonicalize(
            bundle["final_attestation_package"]
        ),
        "final_attestation_package_consistency": mod085._canonicalize(
            bundle["final_attestation_package_consistency"]
        ),
    }
    expected = mod085._compute_bundle_fingerprint(core)
    assert bundle["bundle_fingerprint"] == expected
    assert bundle["audited_bundle_fingerprint"] == expected
    assert mod085._expected_bundle_fingerprint(bundle) == expected
    manual = hashlib.sha256(
        json.dumps(
            mod085._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert bundle["bundle_fingerprint"] == manual


# --- (6) False-states preserved --------------------------------------------------


def test_false_states_healthy_088_true_empty() -> None:
    _, response = _seed_and_build_087()
    result = _build_088(response)
    assert result["available"] is True
    assert result["response_consistent"] is True
    assert result["consistency_issues"] == []
    assert (
        result["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
    )


def test_false_states_coherent_defect_preserves_false() -> None:
    _, response = _seed_and_build_087()
    defective_bundle = copy.deepcopy(response["final_attestation_bundle"])
    defective_consistency = copy.deepcopy(
        response["final_attestation_bundle_consistency"]
    )
    defective_bundle["bundle_consistent"] = False
    defective_consistency["bundle_consistent"] = False
    defective = copy.deepcopy(response)
    defective["response_consistent"] = False
    refreshed = mod085._expected_bundle_fingerprint(defective_bundle)
    defective_consistency["bundle_fingerprint"] = refreshed
    defective_consistency["audited_bundle_fingerprint"] = refreshed
    defective["final_attestation_bundle"] = defective_bundle
    defective["final_attestation_bundle_consistency"] = defective_consistency
    assert defective["response_consistent"] is False
    assert defective["final_attestation_bundle"]["bundle_consistent"] is False
    result = _build_088(defective)
    assert "RESPONSE_RELATIONSHIP_MISMATCH" not in result["consistency_issues"]


# --- (7) determinism + immutability ----------------------------------------------


def test_determinism_double_build_083() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    first = _build_083(sid)
    second = _build_083(sid)
    assert first == second


def test_determinism_double_build_085() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    first = _build_085(sid)
    second = _build_085(sid)
    assert first == second


def test_determinism_double_build_087() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    first = _build_087(sid)
    second = _build_087(sid)
    assert first == second


def test_determinism_double_build_088() -> None:
    _, response = _seed_and_build_087()
    first = _build_088(response)
    second = _build_088(response)
    assert first == second


def test_immutability_083_inputs_unchanged() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    pkg = _build_083(sid)
    final = copy.deepcopy(pkg["final_attestation"])
    consistency = copy.deepcopy(pkg["final_attestation_consistency"])
    final_before = copy.deepcopy(final)
    consistency_before = copy.deepcopy(consistency)
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build(  # noqa: E501
        session_id=sid,
        final_attestation=final,
        final_attestation_consistency=consistency,
    )
    assert final == final_before
    assert consistency == consistency_before


def test_immutability_085_inputs_unchanged() -> None:
    sid_str, _ = _seed_and_build_087()
    sid = UUID(sid_str)
    bundle = _build_085(sid)
    package = copy.deepcopy(bundle["final_attestation_package"])
    consistency = copy.deepcopy(bundle["final_attestation_package_consistency"])
    package_before = copy.deepcopy(package)
    consistency_before = copy.deepcopy(consistency)
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build(  # noqa: E501
        session_id=sid,
        final_attestation_package=package,
        final_attestation_package_consistency=consistency,
    )
    assert package == package_before
    assert consistency == consistency_before


def test_immutability_087_088_inputs_unchanged() -> None:
    _, response = _seed_and_build_087()
    before = copy.deepcopy(response)
    _build_088(response)
    assert response == before


# --- (8) no or-fallback ----------------------------------------------------------


def test_no_or_fallback_all_six() -> None:
    patterns = (
        'get("package_fingerprint") or',
        'get("audited_package_fingerprint") or',
        'get("bundle_fingerprint") or',
        'get("audited_bundle_fingerprint") or',
        'get("final_attestation_fingerprint") or',
        'get("audited_final_attestation_fingerprint") or',
        '["package_fingerprint"] or',
        '["audited_package_fingerprint"] or',
        '["bundle_fingerprint"] or',
        '["audited_bundle_fingerprint"] or',
    )
    for mod in SIX_MODULES:
        src = inspect.getsource(mod)
        for pattern in patterns:
            assert pattern not in src, (mod.__name__, pattern)


def test_no_or_fallback_pair_markers_present() -> None:
    assert "PACKAGE_FINGERPRINT_PAIR_MISMATCH" in inspect.getsource(mod084)
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in inspect.getsource(mod086)
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in inspect.getsource(mod088)
    assert "PACKAGE_FINGERPRINT_MISMATCH" in inspect.getsource(mod083)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in inspect.getsource(mod085)


def test_source_constants_present() -> None:
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
        in inspect.getsource(mod083)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
        in inspect.getsource(mod084)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
        in inspect.getsource(mod085)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086  # noqa: E501
        in inspect.getsource(mod086)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
        in inspect.getsource(mod087)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
        in inspect.getsource(mod088)
    )


# --- (9) error boundaries --------------------------------------------------------


def test_087_unknown_session_404() -> None:
    r = client.get(PATH_087.format(sid=str(uuid4())))
    assert r.status_code == 404


def test_087_downstream_contract_500_and_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid_str = _seed_full("Task 092 boundary")
    ok = client.get(PATH_087.format(sid=sid_str))
    assert ok.status_code == 200

    def _boom(_self: object, db: Session, session_id: UUID) -> dict[str, Any]:
        raise ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleContractError(  # noqa: E501
            "SIMULATED", "forced Task 085 downstream failure"
        )

    monkeypatch.setattr(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,
        "build_for_session",
        _boom,
    )
    failed = client.get(PATH_087.format(sid=sid_str))
    assert failed.status_code == 500
    monkeypatch.undo()
    restored = client.get(PATH_087.format(sid=sid_str))
    assert restored.status_code == 200
    assert restored.json() == ok.json()

"""Tests for Task 102 release gate over Tasks 093-101 chain.

Final verification gate for the complete 093-101 chain. Review-oriented
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
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle as mod095,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency as mod096,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package as mod093,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency as mod094,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation as mod097,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency as mod098,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response as mod099,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_consistency as mod100,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService,  # noqa: E501
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

FIELDS_087 = (
    "available",
    "response_consistent",
    "session_id",
    "final_attestation_bundle",
    "final_attestation_bundle_consistency",
    "response_source",
)

FIELDS_099 = (
    "available",
    "response_consistent",
    "session_id",
    "final_release_attestation",
    "final_release_attestation_consistency",
    "response_source",
)

PATH_075 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation"
PATH_081 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/final"
PATH_087 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "final-response"
)
PATH_099 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/"
    "final-release-response"
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

EIGHT_MODULES = (
    mod093,
    mod094,
    mod095,
    mod096,
    mod097,
    mod098,
    mod099,
    mod100,
)


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-102-test"},
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


def _build_093(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_095(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_097(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_099(session_id: UUID) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService().build_for_session(  # noqa: E501
            db, session_id
        )


def _build_100(response: dict[str, Any]) -> dict[str, Any]:
    return ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=response
    )


def _seed_and_build_099() -> tuple[str, dict[str, Any]]:
    sid_str = _seed_full("Task 102 capture")
    return sid_str, _build_099(UUID(sid_str))


def _session_count() -> int:
    with TestingSessionLocal() as db:
        return int(db.query(ReasoningSession).count())


def _alt_hex(value: str) -> str:
    assert isinstance(value, str) and len(value) == 64
    return "0" * 64 if value != "0" * 64 else "f" * 64


# --- (1) additive / backward-compatible ---------------------------------------


def test_075_endpoint_exact_shape() -> None:
    sid_str = _seed_full("Task 102 compat 075")
    r = client.get(PATH_075.format(sid=sid_str))
    assert r.status_code == 200
    assert set(r.json()) == set(FIELDS_075)


def test_081_endpoint_exact_shape() -> None:
    sid_str = _seed_full("Task 102 compat 081")
    r = client.get(PATH_081.format(sid=sid_str))
    assert r.status_code == 200
    assert set(r.json()) == set(FIELDS_081)


def test_087_endpoint_exact_shape() -> None:
    sid_str = _seed_full("Task 102 compat 087")
    r = client.get(PATH_087.format(sid=sid_str))
    assert r.status_code == 200
    assert set(r.json()) == set(FIELDS_087)


def test_099_endpoint_exact_shape() -> None:
    sid_str = _seed_full("Task 102 compat 099")
    r = client.get(PATH_099.format(sid=sid_str))
    assert r.status_code == 200
    assert set(r.json()) == set(FIELDS_099)


# --- (2) purity ----------------------------------------------------------------


def test_purity_no_forbidden_tokens_all_eight() -> None:
    for mod in EIGHT_MODULES:
        src = inspect.getsource(mod).lower()
        for token in FORBIDDEN_TOKENS:
            assert token.lower() not in src, (mod.__name__, token)


def test_purity_no_db_writes_full_chain() -> None:
    sid_str = _seed_full("Task 102 purity")
    sid = UUID(sid_str)
    before = _session_count()
    with TestingSessionLocal() as db:
        pkg = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build_for_session(  # noqa: E501
            db, sid
        )
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
            package=pkg
        )
        bundle = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService().build_for_session(  # noqa: E501
            db, sid
        )
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService().build(  # noqa: E501
            bundle=bundle
        )
        attestation = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService().build_for_session(  # noqa: E501
            db, sid
        )
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService().build(  # noqa: E501
            final_attestation=attestation
        )
        response = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
        _build_100(response)
    after = _session_count()
    assert before == after


# --- (3) read-only API ----------------------------------------------------------


def test_readonly_repeated_gets_099_identical() -> None:
    sid_str = _seed_full("Task 102 readonly 099")
    first = client.get(PATH_099.format(sid=sid_str))
    second = client.get(PATH_099.format(sid=sid_str))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_readonly_repeated_get_075_spotcheck() -> None:
    sid_str = _seed_full("Task 102 readonly 075")
    first = client.get(PATH_075.format(sid=sid_str))
    second = client.get(PATH_075.format(sid=sid_str))
    assert first.status_code == 200
    assert first.json() == second.json()


def test_readonly_repeated_get_087_spotcheck() -> None:
    sid_str = _seed_full("Task 102 readonly 087")
    first = client.get(PATH_087.format(sid=sid_str))
    second = client.get(PATH_087.format(sid=sid_str))
    assert first.status_code == 200
    assert first.json() == second.json()


# --- (4) self-authenticating ----------------------------------------------------


def test_self_auth_093_package_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_099()
    pkg = _build_093(UUID(sid_str))
    tampered = copy.deepcopy(pkg)
    tampered["package_fingerprint"] = _alt_hex(pkg["package_fingerprint"])
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_093_audited_package_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_099()
    pkg = _build_093(UUID(sid_str))
    tampered = copy.deepcopy(pkg)
    tampered["audited_package_fingerprint"] = _alt_hex(
        pkg["audited_package_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_095_bundle_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_099()
    bundle = _build_095(UUID(sid_str))
    tampered = copy.deepcopy(bundle)
    tampered["bundle_fingerprint"] = _alt_hex(bundle["bundle_fingerprint"])
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_095_audited_bundle_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_099()
    bundle = _build_095(UUID(sid_str))
    tampered = copy.deepcopy(bundle)
    tampered["audited_bundle_fingerprint"] = _alt_hex(
        bundle["audited_bundle_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_097_final_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_099()
    attestation = _build_097(UUID(sid_str))
    tampered = copy.deepcopy(attestation)
    tampered["final_attestation_fingerprint"] = _alt_hex(
        attestation["final_attestation_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_097_audited_final_fingerprint_tamper() -> None:
    sid_str, _ = _seed_and_build_099()
    attestation = _build_097(UUID(sid_str))
    tampered = copy.deepcopy(attestation)
    tampered["audited_final_attestation_fingerprint"] = _alt_hex(
        attestation["audited_final_attestation_fingerprint"]
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_099_binding_fingerprint_tamper() -> None:
    _, response = _seed_and_build_099()
    tampered = copy.deepcopy(response)
    nested = copy.deepcopy(response["final_release_attestation_consistency"])
    nested["final_attestation_fingerprint"] = _alt_hex(
        nested["final_attestation_fingerprint"]
    )
    tampered["final_release_attestation_consistency"] = nested
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


def test_self_auth_099_binding_audited_fingerprint_tamper() -> None:
    _, response = _seed_and_build_099()
    tampered = copy.deepcopy(response)
    nested = copy.deepcopy(response["final_release_attestation_consistency"])
    nested["audited_final_attestation_fingerprint"] = _alt_hex(
        nested["audited_final_attestation_fingerprint"]
    )
    tampered["final_release_attestation_consistency"] = nested
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


# --- (5) recomputability --------------------------------------------------------


def test_recompute_093_fingerprint() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    pkg = _build_093(sid)
    core = {
        "session_id": str(sid),
        "response": mod093._canonicalize(pkg["response"]),
        "response_consistency": mod093._canonicalize(pkg["response_consistency"]),
    }
    expected = mod093._compute_package_fingerprint(core)
    assert pkg["package_fingerprint"] == expected
    assert pkg["audited_package_fingerprint"] == expected
    assert mod093._expected_package_fingerprint(pkg) == expected
    manual = hashlib.sha256(
        json.dumps(
            mod093._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert pkg["package_fingerprint"] == manual


def test_recompute_095_fingerprint() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    bundle = _build_095(sid)
    core = {
        "session_id": str(sid),
        "response_package": mod095._canonicalize(bundle["response_package"]),
        "response_package_consistency": mod095._canonicalize(
            bundle["response_package_consistency"]
        ),
    }
    expected = mod095._compute_bundle_fingerprint(core)
    assert bundle["bundle_fingerprint"] == expected
    assert bundle["audited_bundle_fingerprint"] == expected
    assert mod095._expected_bundle_fingerprint(bundle) == expected
    manual = hashlib.sha256(
        json.dumps(
            mod095._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert bundle["bundle_fingerprint"] == manual


def test_recompute_097_fingerprint() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    attestation = _build_097(sid)
    core = {
        "session_id": str(sid),
        "response_bundle": mod097._canonicalize(attestation["response_bundle"]),
        "response_bundle_consistency": mod097._canonicalize(
            attestation["response_bundle_consistency"]
        ),
    }
    expected = mod097._compute_final_attestation_fingerprint(core)
    assert attestation["final_attestation_fingerprint"] == expected
    assert attestation["audited_final_attestation_fingerprint"] == expected
    assert mod097._expected_final_fingerprint(attestation) == expected
    manual = hashlib.sha256(
        json.dumps(
            mod097._canonicalize(core),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert attestation["final_attestation_fingerprint"] == manual


# --- (6) False-states preserved --------------------------------------------------


def test_false_states_healthy_100_true_empty() -> None:
    _, response = _seed_and_build_099()
    result = _build_100(response)
    assert result["available"] is True
    assert result["response_consistent"] is True
    assert result["consistency_issues"] == []
    assert (
        result["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100  # noqa: E501
    )


def test_false_states_coherent_defect_preserves_false() -> None:
    _, response = _seed_and_build_099()
    defective_attestation = copy.deepcopy(response["final_release_attestation"])
    defective_consistency = copy.deepcopy(
        response["final_release_attestation_consistency"]
    )
    defective_attestation["final_attestation_consistent"] = False
    defective_consistency["final_attestation_consistent"] = False
    defective = copy.deepcopy(response)
    defective["response_consistent"] = False
    refreshed = mod097._expected_final_fingerprint(defective_attestation)
    defective_consistency["final_attestation_fingerprint"] = refreshed
    defective_consistency["audited_final_attestation_fingerprint"] = refreshed
    defective["final_release_attestation"] = defective_attestation
    defective["final_release_attestation_consistency"] = defective_consistency
    assert defective["response_consistent"] is False
    assert (
        defective["final_release_attestation_consistency"][
            "final_attestation_consistent"
        ]
        is False
    )
    result = _build_100(defective)
    assert result["available"] is True
    assert "RESPONSE_RELATIONSHIP_MISMATCH" not in result["consistency_issues"]


# --- (7) determinism + immutability ----------------------------------------------


def test_determinism_double_build_093() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    first = _build_093(sid)
    second = _build_093(sid)
    assert first == second


def test_determinism_double_build_095() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    first = _build_095(sid)
    second = _build_095(sid)
    assert first == second


def test_determinism_double_build_097() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    first = _build_097(sid)
    second = _build_097(sid)
    assert first == second


def test_determinism_double_build_099() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    first = _build_099(sid)
    second = _build_099(sid)
    assert first == second


def test_determinism_double_build_100() -> None:
    _, response = _seed_and_build_099()
    first = _build_100(response)
    second = _build_100(response)
    assert first == second


def test_immutability_093_inputs_unchanged() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    pkg = _build_093(sid)
    nested_response = copy.deepcopy(pkg["response"])
    nested_consistency = copy.deepcopy(pkg["response_consistency"])
    nested_response_before = copy.deepcopy(nested_response)
    nested_consistency_before = copy.deepcopy(nested_consistency)
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        response=nested_response,
        response_consistency=nested_consistency,
    )
    assert nested_response == nested_response_before
    assert nested_consistency == nested_consistency_before


def test_immutability_095_inputs_unchanged() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    bundle = _build_095(sid)
    package = copy.deepcopy(bundle["response_package"])
    consistency = copy.deepcopy(bundle["response_package_consistency"])
    package_before = copy.deepcopy(package)
    consistency_before = copy.deepcopy(consistency)
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=package,
        response_package_consistency=consistency,
    )
    assert package == package_before
    assert consistency == consistency_before


def test_immutability_097_inputs_unchanged() -> None:
    sid_str, _ = _seed_and_build_099()
    sid = UUID(sid_str)
    attestation = _build_097(sid)
    bundle = copy.deepcopy(attestation["response_bundle"])
    consistency = copy.deepcopy(attestation["response_bundle_consistency"])
    bundle_before = copy.deepcopy(bundle)
    consistency_before = copy.deepcopy(consistency)
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=bundle,
        response_bundle_consistency=consistency,
    )
    assert bundle == bundle_before
    assert consistency == consistency_before


def test_immutability_099_returns_fresh_objects() -> None:
    sid_str = _seed_full("Task 102 immutability 099")
    sid = UUID(sid_str)
    first = _build_099(sid)
    snapshot = copy.deepcopy(first)
    first["final_release_attestation"]["final_attestation_consistent"] = False
    first["response_consistent"] = False
    second = _build_099(sid)
    assert second == snapshot


def test_immutability_100_input_unchanged() -> None:
    _, response = _seed_and_build_099()
    before = copy.deepcopy(response)
    _build_100(response)
    assert response == before


# --- (8) no or-fallback ----------------------------------------------------------


def test_no_or_fallback_all_eight() -> None:
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
        '["final_attestation_fingerprint"] or',
        '["audited_final_attestation_fingerprint"] or',
    )
    for mod in EIGHT_MODULES:
        src = inspect.getsource(mod)
        for pattern in patterns:
            assert pattern not in src, (mod.__name__, pattern)


def test_no_or_fallback_pair_markers_present() -> None:
    assert "PACKAGE_FINGERPRINT_PAIR_MISMATCH" in inspect.getsource(mod094)
    assert "BUNDLE_FINGERPRINT_PAIR_MISMATCH" in inspect.getsource(mod096)
    assert "FINAL_ATTESTATION_FINGERPRINT_PAIR_MISMATCH" in inspect.getsource(mod098)
    assert "PACKAGE_FINGERPRINT_MISMATCH" in inspect.getsource(mod093)
    assert "BUNDLE_FINGERPRINT_MISMATCH" in inspect.getsource(mod095)
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in inspect.getsource(mod097)
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in inspect.getsource(mod099)
    assert "RESPONSE_RELATIONSHIP_MISMATCH" in inspect.getsource(mod100)


def test_source_constants_present() -> None:
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093  # noqa: E501
        in inspect.getsource(mod093)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094  # noqa: E501
        in inspect.getsource(mod094)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
        in inspect.getsource(mod095)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096  # noqa: E501
        in inspect.getsource(mod096)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
        in inspect.getsource(mod097)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098  # noqa: E501
        in inspect.getsource(mod098)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
        in inspect.getsource(mod099)
    )
    assert (
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100  # noqa: E501
        in inspect.getsource(mod100)
    )


# --- (9) error boundaries --------------------------------------------------------


def test_099_unknown_session_404() -> None:
    r = client.get(PATH_099.format(sid=str(uuid4())))
    assert r.status_code == 404


def test_099_downstream_contract_500_and_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid_str = _seed_full("Task 102 boundary")
    ok = client.get(PATH_099.format(sid=sid_str))
    assert ok.status_code == 200

    def _boom(_self: object, db: Session, session_id: UUID) -> dict[str, Any]:
        raise ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError(  # noqa: E501
            "SIMULATED", "forced Task 097 downstream failure"
        )

    monkeypatch.setattr(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,
        "build_for_session",
        _boom,
    )
    failed = client.get(PATH_099.format(sid=sid_str))
    assert failed.status_code == 500
    monkeypatch.undo()
    restored = client.get(PATH_099.format(sid=sid_str))
    assert restored.status_code == 200
    assert restored.json() == ok.json()


# --- (10) exports / imports complete ---------------------------------------------


def test_exports_services_root() -> None:
    import rop.services as services_root

    expected = {
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService  # noqa: E501
        ),
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyContractError": (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyContractError  # noqa: E501
        ),
    }
    for name, obj in expected.items():
        assert getattr(services_root, name, None) is obj, name


def test_exports_schemas_root() -> None:
    import rop.schemas as schemas_root

    expected = (
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseRead",  # noqa: E501
        "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyRead",  # noqa: E501
    )
    for name in expected:
        assert getattr(schemas_root, name, None) is not None, name


def test_source_constants_from_modules() -> None:
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099,  # noqa: E501
        str,
    )
    assert isinstance(
        REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100,  # noqa: E501
        str,
    )

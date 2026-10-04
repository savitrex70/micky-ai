"""Tests for Task 099: expose the Task 097/098 final release attestation via API.

Task 099 composes the existing canonical Task 097 release attestation
service with the Task 098 independent consistency audit into a
session-level, read-only API boundary without rebuilding their logic,
without an internal HTTP call, and without database writes.
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
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response as mod,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService,  # noqa: E501
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


FINAL_RELEASE_RESPONSE_PATH = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/final-release-response"  # noqa: E501

RESPONSE_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_release_attestation",
    "final_release_attestation_consistency",
    "response_source",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService  # noqa: E501
):
    return (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService()  # noqa: E501
    )


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-099-test"},
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


def _db_session() -> Session:
    return TestingSessionLocal()


def _build_response_direct(session_id: UUID) -> dict[str, Any]:
    with _db_session() as db:
        return _service().build_for_session(db, session_id)


def _seed_and_build() -> tuple[str, dict[str, Any]]:
    sid_str = _seed_full("Task 099 capture")
    response = _build_response_direct(UUID(sid_str))
    return sid_str, response


# --- Valid response / shape ---
def test_valid_response_via_endpoint() -> None:
    sid_str = _seed_full("Task 099 endpoint capture")
    r = client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(RESPONSE_FIELDS)
    assert body["available"] is True
    assert body["session_id"] == sid_str


def test_valid_response_direct_matches_endpoint() -> None:
    sid_str = _seed_full("Task 099 direct capture")
    direct = _build_response_direct(UUID(sid_str))
    r = client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    assert r.status_code == 200
    body = r.json()
    assert body["response_source"] == direct["response_source"]
    assert body["session_id"] == str(direct["session_id"])
    assert (
        body["final_release_attestation"]["final_attestation_fingerprint"]
        == direct["final_release_attestation"]["final_attestation_fingerprint"]
    )


def test_exact_response_shape_direct() -> None:
    _, response = _seed_and_build()
    assert set(response) == set(RESPONSE_FIELDS)


def test_response_source_fixed() -> None:
    _, response = _seed_and_build()
    assert (
        response["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
    )


def test_available_true() -> None:
    _, response = _seed_and_build()
    assert response["available"] is True


# --- Missing session -> 404 ---
def test_missing_session_returns_404() -> None:
    r = client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=uuid4()))
    assert r.status_code == 404


# --- Session binding ---
def test_session_binding_top_level() -> None:
    sid_str, response = _seed_and_build()
    assert response["session_id"] == UUID(sid_str)


def test_session_binding_nested_attestation() -> None:
    sid_str, response = _seed_and_build()
    assert response["final_release_attestation"]["session_id"] == UUID(sid_str)


def test_session_binding_nested_bundle() -> None:
    sid_str, response = _seed_and_build()
    bundle = response["final_release_attestation"]["response_bundle"]
    assert bundle["session_id"] == UUID(sid_str)


def test_session_binding_consistency_reports_consistent() -> None:
    _, response = _seed_and_build()
    assert (
        response["final_release_attestation_consistency"]["session_consistent"] is True
    )


# --- Nested Task 097/098 values preserved ---
def test_nested_task_097_attestation_preserved() -> None:
    _, response = _seed_and_build()
    attestation = response["final_release_attestation"]
    assert (
        attestation["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
    )
    assert "response_bundle" in attestation
    assert "response_bundle_consistency" in attestation
    assert "final_attestation_fingerprint" in attestation
    assert "audited_final_attestation_fingerprint" in attestation


def test_nested_task_098_consistency_preserved() -> None:
    _, response = _seed_and_build()
    attestation_consistency = response["final_release_attestation_consistency"]
    assert (
        attestation_consistency["final_attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098  # noqa: E501
    )
    assert "consistency_issues" in attestation_consistency


def test_fingerprint_binding_between_nested_layers() -> None:
    _, response = _seed_and_build()
    attestation = response["final_release_attestation"]
    attestation_consistency = response["final_release_attestation_consistency"]
    assert (
        attestation_consistency["final_attestation_fingerprint"]
        == attestation["final_attestation_fingerprint"]
    )
    assert (
        attestation_consistency["audited_final_attestation_fingerprint"]
        == attestation["final_attestation_fingerprint"]
    )


# --- Deterministic repeated GET ---
def test_deterministic_repeated_get() -> None:
    sid_str = _seed_full("Task 099 deterministic capture")
    r1 = client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    r2 = client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_deterministic_direct_build() -> None:
    sid_str, response_1 = _seed_and_build()
    response_2 = _build_response_direct(UUID(sid_str))
    assert response_1 == response_2


# --- No internal HTTP call ---
def test_no_http_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "TestClient",
        "httpx",
        "requests",
        "urllib",
        "urlopen",
        "client.get",
    ):
        assert forbidden not in src


def test_no_database_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("SessionLocal", "create_engine"):
        assert forbidden not in src


# --- No unrelated workflow duplication ---
def test_no_rebuilt_contract_logic() -> None:
    """Task 099 must delegate, never reimplement Task 097/098 validators."""
    src = inspect.getsource(mod)
    assert "consistency_issues.append" not in src
    assert "hashlib" not in src
    assert "_ISSUE_ORDER" not in src


def test_no_llm_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("ollama", "openai", "gemini", "anthropic", "model_name", "api_key"):
        assert token not in src


def test_delegates_to_release_attestation_orchestrator() -> None:
    """Task 099 must build Task 097 exactly once via its own orchestrator."""
    src = inspect.getsource(mod)
    assert "build_for_session" in src
    assert "FinalReleaseAttestationService" in src
    assert "FinalReleaseAttestationConsistencyService" in src


# --- Read-only behavior ---
def test_read_only_no_new_sessions_created() -> None:
    sid_str = _seed_full("Task 099 read-only capture")
    before = client.get("/sessions", params={"limit": 100}).json()
    client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    after = client.get("/sessions", params={"limit": 100}).json()
    assert len(before) == len(after)


def test_input_immutability() -> None:
    sid_str, response = _seed_and_build()
    before = copy.deepcopy(response)
    _build_response_direct(UUID(sid_str))
    assert response == before


# --- Contract error boundary ---
def test_contract_error_boundary_invalid_attestation() -> None:
    tampered = {
        "available": True,
        "response_consistent": True,
        "session_id": uuid4(),
        "final_release_attestation": {"available": False},
        "final_release_attestation_consistency": {},
        "response_source": (
            REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
        ),
    }
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


def test_wrong_response_source_rejected() -> None:
    _, response = _seed_and_build()
    tampered = dict(response)
    tampered["response_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "RESPONSE_SOURCE_MISMATCH"


def test_response_consistent_mismatch_rejected() -> None:
    _, response = _seed_and_build()
    tampered = dict(response)
    tampered["response_consistent"] = not tampered["response_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )
    assert ei.value.invariant == "RESPONSE_CONSISTENT_MISMATCH"


def test_fingerprint_tampering_rejected() -> None:
    _, response = _seed_and_build()
    tampered = copy.deepcopy(response)
    tampered["final_release_attestation_consistency"][
        "final_attestation_fingerprint"
    ] = (  # noqa: E501
        "0" * 64
    )
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


def test_session_mismatch_rejected() -> None:
    _, response = _seed_and_build()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = uuid4()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )


def test_endpoint_maps_contract_error_to_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Task 099 contract failure must surface as 500, never 200."""
    import rop.api.sessions as sessions_api

    sid_str = _seed_full("Task 099 contract capture")

    def _boom(db: Session, session_id: UUID) -> dict[str, Any]:
        raise ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError(  # noqa: E501
            "SIMULATED", "simulated Task 099 contract failure"
        )

    monkeypatch.setattr(
        sessions_api.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_service,  # noqa: E501
        "build_for_session",
        _boom,
    )
    r = client.get(FINAL_RELEASE_RESPONSE_PATH.format(sid=sid_str))
    assert r.status_code == 500


# --- Legitimate underlying defect remains truthfully represented ---
def _seed_and_break_final_release_attestation_response() -> dict[str, Any]:
    """Force a real, legitimately-inconsistent Task 098 audit."""
    sid_str, response = _seed_and_build()
    broken = copy.deepcopy(response)
    broken["final_release_attestation_consistency"]["consistency_issues"] = [
        "SOURCE_MISMATCH_SIMULATED"
    ]
    broken["final_release_attestation_consistency"][
        "final_attestation_consistent"
    ] = False
    broken["response_consistent"] = False
    return broken


def test_legitimate_defect_preserved_not_masked() -> None:
    """A defect-reporting nested audit must not be silently upgraded."""
    _, response = _seed_and_build()
    # response_consistent must mirror Task 098's
    # final_attestation_consistent exactly, never independently claim
    # consistency.
    assert (
        response["response_consistent"]
        == response["final_release_attestation_consistency"][
            "final_attestation_consistent"
        ]
    )


def test_does_not_convert_defect_to_success() -> None:
    broken = _seed_and_break_final_release_attestation_response()
    assert (
        broken["final_release_attestation_consistency"]["final_attestation_consistent"]
        is False
    )
    assert broken["response_consistent"] is False


def test_upgrading_a_defect_to_success_is_rejected() -> None:
    """A tampered final_attestation_consistent that contradicts its own issue
    list (i.e. an attempt to silently upgrade a legitimate defect into a
    success) must be rejected by the Task 098 validator Task 099 reuses.
    """
    _, response = _seed_and_build()
    tampered = copy.deepcopy(response)
    tampered_consistency = tampered["final_release_attestation_consistency"]
    tampered_consistency["consistency_issues"] = ["FINAL_ATTESTATION_SOURCE_MISMATCH"]
    tampered_consistency["final_attestation_consistent"] = True
    tampered["response_consistent"] = True
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
            tampered
        )

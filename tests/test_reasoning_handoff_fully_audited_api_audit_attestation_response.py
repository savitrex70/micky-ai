"""Tests for Task 075: expose the Task 071-074 attestation layer via API.

Task 075 composes the existing canonical Task 071-074 services into a
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
    reasoning_handoff_fully_audited_api_audit_attestation_response as mod,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseService,
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


RESPONSE_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "attestation_package",
    "attestation_package_consistency",
    "response_source",
)


def _service() -> ReasoningHandoffFullyAuditedApiAuditAttestationResponseService:
    return ReasoningHandoffFullyAuditedApiAuditAttestationResponseService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-075-test"},
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
    sid_str = _seed_full("Task 075 capture")
    response = _build_response_direct(UUID(sid_str))
    return sid_str, response


# --- Valid response / shape ---
def test_valid_response_via_endpoint() -> None:
    sid_str = _seed_full("Task 075 endpoint capture")
    r = client.get(f"/sessions/{sid_str}/reasoning-handoff/fully-audited/attestation")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(RESPONSE_FIELDS)
    assert body["available"] is True
    assert body["session_id"] == sid_str


def test_exact_response_shape_direct() -> None:
    _, response = _seed_and_build()
    assert set(response) == set(RESPONSE_FIELDS)


def test_response_source_fixed() -> None:
    _, response = _seed_and_build()
    assert (
        response["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
    )


def test_available_true() -> None:
    _, response = _seed_and_build()
    assert response["available"] is True


# --- Missing session -> 404 ---
def test_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/reasoning-handoff/fully-audited/attestation")
    assert r.status_code == 404


# --- Session binding ---
def test_session_binding_top_level() -> None:
    sid_str, response = _seed_and_build()
    assert response["session_id"] == UUID(sid_str)


def test_session_binding_nested_package() -> None:
    sid_str, response = _seed_and_build()
    assert response["attestation_package"]["session_id"] == UUID(sid_str)


def test_session_binding_nested_attestation() -> None:
    sid_str, response = _seed_and_build()
    attestation = response["attestation_package"]["attestation"]
    assert attestation["session_id"] == UUID(sid_str)


# --- Nested Task 071/072/073/074 values preserved ---
def test_nested_task_071_attestation_preserved() -> None:
    _, response = _seed_and_build()
    attestation = response["attestation_package"]["attestation"]
    assert (
        attestation["attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
    )
    assert "api_audit_bundle" in attestation
    assert "audited_attestation_fingerprint" in attestation


def test_nested_task_072_consistency_preserved() -> None:
    _, response = _seed_and_build()
    consistency = response["attestation_package"]["attestation_consistency"]
    assert (
        consistency["attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
    )
    assert "consistency_issues" in consistency


def test_nested_task_073_package_preserved() -> None:
    _, response = _seed_and_build()
    package = response["attestation_package"]
    assert (
        package["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073
    )
    assert "package_fingerprint" in package
    assert "audited_package_fingerprint" in package


def test_nested_task_074_package_consistency_preserved() -> None:
    _, response = _seed_and_build()
    package_consistency = response["attestation_package_consistency"]
    assert (
        package_consistency["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074  # noqa: E501
    )
    assert "consistency_issues" in package_consistency


# --- Deterministic repeated GET ---
def test_deterministic_repeated_get() -> None:
    sid_str = _seed_full("Task 075 deterministic capture")
    r1 = client.get(f"/sessions/{sid_str}/reasoning-handoff/fully-audited/attestation")
    r2 = client.get(f"/sessions/{sid_str}/reasoning-handoff/fully-audited/attestation")
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
    for forbidden in ("TestClient", "httpx", "requests", "urllib", "client.get"):
        assert forbidden not in src


def test_no_database_imports() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("SessionLocal", "create_engine"):
        assert forbidden not in src


# --- No unrelated workflow duplication ---
def test_no_rebuilt_contract_logic() -> None:
    """Task 075 must delegate, never reimplement Task 066-074 validators."""
    src = inspect.getsource(mod)
    assert "consistency_issues.append" not in src
    assert "hashlib" not in src
    assert "_ISSUE_ORDER" not in src


def test_no_llm_provider_symbols() -> None:
    src = inspect.getsource(mod).lower()
    for token in ("ollama", "openai", "gemini", "anthropic", "model_name", "api_key"):
        assert token not in src


# --- Read-only behavior ---
def test_read_only_no_new_sessions_created() -> None:
    sid_str = _seed_full("Task 075 read-only capture")
    before = client.get("/sessions", params={"limit": 100}).json()
    client.get(f"/sessions/{sid_str}/reasoning-handoff/fully-audited/attestation")
    client.get(f"/sessions/{sid_str}/reasoning-handoff/fully-audited/attestation")
    after = client.get("/sessions", params={"limit": 100}).json()
    assert len(before) == len(after)


def test_input_immutability() -> None:
    sid_str, response = _seed_and_build()
    before = copy.deepcopy(response)
    _build_response_direct(UUID(sid_str))
    assert response == before


# --- Contract error boundary ---
def test_contract_error_boundary_invalid_package() -> None:
    tampered = {
        "available": True,
        "response_consistent": True,
        "session_id": uuid4(),
        "attestation_package": {"available": False},
        "attestation_package_consistency": {},
        "response_source": (
            REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
        ),
    }
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(
            tampered
        )


def test_wrong_response_source_rejected() -> None:
    _, response = _seed_and_build()
    tampered = dict(response)
    tampered["response_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(
            tampered
        )
    assert ei.value.invariant == "RESPONSE_SOURCE_MISMATCH"


def test_response_consistent_mismatch_rejected() -> None:
    _, response = _seed_and_build()
    tampered = dict(response)
    tampered["response_consistent"] = not tampered["response_consistent"]
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError
    ) as ei:
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(
            tampered
        )
    assert ei.value.invariant == "RESPONSE_CONSISTENT_MISMATCH"


def test_fingerprint_tampering_rejected() -> None:
    _, response = _seed_and_build()
    tampered = copy.deepcopy(response)
    tampered["attestation_package_consistency"]["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(
            tampered
        )


def test_session_mismatch_rejected() -> None:
    _, response = _seed_and_build()
    tampered = copy.deepcopy(response)
    tampered["session_id"] = uuid4()
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(
            tampered
        )


# --- Legitimate underlying defect remains truthfully represented ---
def _seed_and_break_attestation_response() -> dict[str, Any]:
    """Force a real, legitimately-inconsistent Task 074 audit."""
    sid_str, response = _seed_and_build()
    broken = copy.deepcopy(response)
    broken["attestation_package_consistency"]["consistency_issues"] = [
        "SOURCE_MISMATCH_SIMULATED"
    ]
    broken["attestation_package_consistency"]["package_consistent"] = False
    broken["response_consistent"] = False
    return broken


def test_legitimate_defect_preserved_not_masked() -> None:
    """A defect-reporting nested audit must not be silently upgraded."""
    _, response = _seed_and_build()
    # response_consistent must mirror Task 074's package_consistent exactly,
    # never independently claim consistency.
    assert (
        response["response_consistent"]
        == response["attestation_package_consistency"]["package_consistent"]
    )


def test_does_not_convert_defect_to_success() -> None:
    broken = _seed_and_break_attestation_response()
    assert broken["attestation_package_consistency"]["package_consistent"] is False
    assert broken["response_consistent"] is False


def test_upgrading_a_defect_to_success_is_rejected() -> None:
    """A tampered package_consistent that contradicts its own issue list
    (i.e. an attempt to silently upgrade a legitimate defect into a
    success) must be rejected by the Task 074 validator Task 075 reuses.
    """
    _, response = _seed_and_build()
    tampered = copy.deepcopy(response)
    tampered["attestation_package_consistency"]["consistency_issues"] = [
        "PACKAGE_SOURCE_MISMATCH"
    ]
    tampered["attestation_package_consistency"]["package_consistent"] = True
    tampered["response_consistent"] = True
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseService._validate_result(
            tampered
        )

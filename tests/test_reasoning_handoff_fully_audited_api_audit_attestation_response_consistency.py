"""Tests for Task 076 attestation-response consistency audit.

Task 076 performs a pure, deterministic, independent consistency audit of
the Task 075 attestation API response without executing Task 075, making
HTTP calls, accessing the database, or invoking external models/providers.
"""

from __future__ import annotations

import copy
from collections.abc import Generator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyContractError,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService,
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
    "response_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "nested_package_consistent",
    "nested_package_consistency_consistent",
    "provenance_consistent",
    "response_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "response_consistency_source",
)


def _service() -> (
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService
):  # noqa: E501
    return ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-076-test"},
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


def _valid_response() -> tuple[UUID, dict[str, Any]]:
    sid_str = _seed_full("Task 076 capture")
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        response = ReasoningHandoffFullyAuditedApiAuditAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    return sid, response


def _valid_result() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid, response = _valid_response()
    return sid, response, _service().build(response=response)


# --- Valid response ---------------------------------------------------------
def test_valid_shape_and_flags() -> None:
    _sid, _response, result = _valid_result()
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["response_consistent"] is True
    assert result["consistency_issues"] == []
    assert result["session_consistent"] is True
    assert result["nested_attestation_consistent"] is True
    assert result["nested_attestation_consistency_consistent"] is True
    assert result["nested_package_consistent"] is True
    assert result["nested_package_consistency_consistent"] is True
    assert result["provenance_consistent"] is True
    assert result["response_relationship_consistent"] is True
    assert result["source_consistency"] is True
    assert result["metadata_consistent"] is True
    assert (
        result["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076  # noqa: E501
    )


def test_result_schema_roundtrip() -> None:
    _sid, _response, result = _valid_result()
    model = ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead.model_validate(  # noqa: E501
        result
    )
    assert model.response_consistent is True
    assert model.consistency_issues == []


def test_missing_response_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyContractError
    ) as ei:
        _service().build(response=None)
    assert ei.value.invariant == "MISSING_RESPONSE"


def test_non_mapping_response_raises() -> None:
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyContractError
    ) as ei:
        _service().build(response="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "RESPONSE_TYPE"


# --- Every required field missing -------------------------------------------
@pytest.mark.parametrize(
    "field",
    (
        "available",
        "response_consistent",
        "session_id",
        "attestation_package",
        "attestation_package_consistency",
        "response_source",
    ),
)
def test_every_required_field_missing_is_reported(field: str) -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    del tampered[field]
    result = _service().build(response=tampered)
    assert "MISSING_RESPONSE_FIELD" in result["consistency_issues"]
    assert result["response_consistent"] is False
    assert result["metadata_consistent"] is False


def test_duplicate_missing_fields_collapse_to_one_issue() -> None:
    _sid, response, _result = _valid_result()
    tampered = copy.deepcopy(response)
    del tampered["available"]
    del tampered["response_source"]
    result = _service().build(response=tampered)
    assert result["consistency_issues"].count("MISSING_RESPONSE_FIELD") == 1

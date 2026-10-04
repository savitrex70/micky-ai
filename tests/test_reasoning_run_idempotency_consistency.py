"""Task 135: idempotency API consistency audit tests.

Proves the POST HTTP boundary end-to-end -- real Task 134 envelopes
audited through ``POST /sessions/{id}/reasoning-run/idempotency-consistency``
-- plus each corruption class, strict request validation, and zero
database writes. No model, no network beyond the test app.
"""

from __future__ import annotations

import copy
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
from rop.schemas.reasoning_run_idempotency_consistency import (
    ReasoningRunIdempotencyConsistencyRead,
)
from rop.services.reasoning_run_idempotency_consistency import (
    REASONING_RUN_IDEMPOTENCY_CONSISTENCY_SOURCE_TASK_135,
    ReasoningRunIdempotencyConsistencyContractError,
    ReasoningRunIdempotencyConsistencyService,
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

AUDIT_URL = "/sessions/{sid}/reasoning-run/idempotency-consistency"


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str = "Patient reports chest pain") -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "idempotency-audit-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(session_id: str, text: str) -> None:
    o = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": text,
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert o.status_code == 201


def _executed_envelope(session_id: str) -> dict[str, Any]:
    r = client.post(f"/sessions/{session_id}/reasoning-run/execute-idempotent")
    assert r.status_code == 200
    return r.json()


def _reused_envelope(session_id: str, known: str) -> dict[str, Any]:
    r = client.post(
        f"/sessions/{session_id}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    )
    assert r.status_code == 200
    return r.json()


def _stale_envelope(session_id: str, known: str) -> dict[str, Any]:
    _add_observation(session_id, "Patient reports new dizziness")
    return _reused_envelope(session_id, known)


def _counts() -> dict[str, int]:
    from sqlalchemy import text as sql_text

    from rop.database import Base as _Base

    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in _Base.metadata.sorted_tables
        }


# ---------------------------------------------------------------------------
# Valid envelopes through the real HTTP boundary (POST)
# ---------------------------------------------------------------------------


def test_http_valid_executed_new() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    assert envelope["disposition"] == "EXECUTED_NEW"

    before = _counts()
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    after = _counts()
    assert after == before

    audit = r.json()
    assert audit["audit_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["disposition"] == "EXECUTED_NEW"
    assert audit["session_id"] == sid
    assert audit["available"] is True
    assert (
        audit["audit_source"] == REASONING_RUN_IDEMPOTENCY_CONSISTENCY_SOURCE_TASK_135
    )
    assert ReasoningRunIdempotencyConsistencyRead.model_validate(audit)


def test_http_valid_reused_identical() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    envelope = _reused_envelope(sid, known)
    assert envelope["disposition"] == "REUSED_IDENTICAL"

    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["disposition"] == "REUSED_IDENTICAL"


def test_http_valid_stale_changed() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    envelope = _stale_envelope(sid, known)
    assert envelope["disposition"] == "STALE_CHANGED"

    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["disposition"] == "STALE_CHANGED"
    assert audit["available"] is True
    assert ReasoningRunIdempotencyConsistencyRead.model_validate(audit)


# ---------------------------------------------------------------------------
# Corruption cases through the real HTTP boundary: parseable envelopes
# audit to HTTP 200 with audit_consistent=False
# ---------------------------------------------------------------------------


def test_http_invalid_disposition_reports_issue() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["disposition"] = "EXECUTED_SOMETIMES"
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "INVALID_DISPOSITION" in audit["consistency_issues"]


def test_http_stale_result_present_reports_issue() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    envelope = _stale_envelope(sid, known)
    assert envelope["disposition"] == "STALE_CHANGED"
    envelope["result"] = dict(
        _executed_envelope(sid)["result"]
    )  # parseable stale contradiction
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "STALE_RESULT_PRESENT" in audit["consistency_issues"]


def test_http_reused_fingerprint_mismatch_reports_issue() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    envelope = _reused_envelope(sid, known)
    assert envelope["disposition"] == "REUSED_IDENTICAL"
    envelope["result"] = dict(envelope["result"])
    envelope["result"]["input_fingerprint"] = "b" * 64
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "REUSED_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


def test_http_executed_fingerprint_mismatch_reports_issue() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["result"] = dict(envelope["result"])
    envelope["result"]["input_fingerprint"] = "c" * 64
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "EXECUTED_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


def test_http_session_mismatch_reports_issue() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    other = _create_session()
    envelope["session_id"] = other
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "SESSION_ID_MISMATCH" in audit["consistency_issues"]


def test_http_semantically_inconsistent_nested_result_reports_issue() -> None:
    """A shape-valid nested result with a bogus outcome parses through
    the strict schema, reaches the audit, and is reported as
    inconsistent -- never repaired or silently accepted."""
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["result"] = dict(envelope["result"])
    envelope["result"]["outcome"] = "BOGUS_OUTCOME"
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "NESTED_RESULT_INCONSISTENT" in audit["consistency_issues"]


def test_http_missing_result_for_executed_new_reports_issue() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["result"] = None
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    assert audit["audit_consistent"] is False
    assert "MISSING_RESULT" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Structurally invalid requests are rejected by the strict request
# schema (HTTP 422), never reaching the audit service
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "patch",
    (
        {"current_input_fingerprint": "short"},
        {"current_input_fingerprint": "A" * 64},
        {"current_input_fingerprint": "z" * 64},
        {"known_input_fingerprint": "short"},
        {"known_input_fingerprint": "B" * 64},
    ),
)
def test_http_malformed_fingerprints_rejected_422(patch: dict[str, Any]) -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope.update(patch)
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 422


def test_http_missing_required_fields_rejected_422() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    for field in ("disposition", "session_id", "current_input_fingerprint", "result"):
        broken = {k: v for k, v in envelope.items() if k != field}
        r = client.post(AUDIT_URL.format(sid=sid), json=broken)
        assert r.status_code == 422, field


def test_http_unknown_field_rejected_422() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["smuggled"] = {"payload": True}
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 422


def test_http_missing_body_rejected_422() -> None:
    sid = _create_session()
    r = client.post(AUDIT_URL.format(sid=sid))
    assert r.status_code == 422


def test_http_malformed_nested_result_structure_rejected_422() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["result"] = {"outcome": "BOGUS", "session_id": sid}
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Session lifecycle errors
# ---------------------------------------------------------------------------


def test_http_missing_session_404() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    r = client.post(AUDIT_URL.format(sid=uuid4()), json=envelope)
    assert r.status_code == 404


def test_http_missing_session_does_not_leak_raw_error_detail() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    r = client.post(AUDIT_URL.format(sid=uuid4()), json=envelope)
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# Service-level behaviors retained from the original Task 135 audit
# ---------------------------------------------------------------------------


def test_service_missing_envelope_raises() -> None:
    with pytest.raises(ReasoningRunIdempotencyConsistencyContractError):
        ReasoningRunIdempotencyConsistencyService().build(
            envelope=None, session_id=uuid4()
        )
    with pytest.raises(ReasoningRunIdempotencyConsistencyContractError):
        ReasoningRunIdempotencyConsistencyService().build(
            envelope=["not", "a", "mapping"], session_id=uuid4()
        )


def test_audit_result_rejects_extra_fields() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    audit = r.json()
    audit["smuggled"] = True
    with pytest.raises(ValidationError):
        ReasoningRunIdempotencyConsistencyRead.model_validate(audit)


def test_audit_performs_zero_database_writes() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = copy.deepcopy(_executed_envelope(sid))
    before = _counts()
    r = client.post(AUDIT_URL.format(sid=sid), json=envelope)
    assert r.status_code == 200
    r2 = client.post(AUDIT_URL.format(sid=sid), json=copy.deepcopy(envelope))
    assert r2.status_code == 200
    assert _counts() == before


def test_audit_does_not_mutate_supplied_envelope() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = copy.deepcopy(_executed_envelope(sid))
    frozen = copy.deepcopy(envelope)
    ReasoningRunIdempotencyConsistencyService().build(
        envelope=envelope, session_id=UUID(sid)
    )
    assert envelope == frozen

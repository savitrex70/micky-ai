"""Task 135: idempotency API consistency audit tests.

Proves the audit accepts faithful envelopes, rejects each corruption
class, and never touches the database. No model, no network beyond the
test app for fixtures.
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


def _audit(envelope: Any, session_id: str) -> dict[str, Any]:
    return ReasoningRunIdempotencyConsistencyService().build(
        envelope=envelope, session_id=UUID(session_id)
    )


def test_valid_executed_new() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    audit = _audit(_executed_envelope(sid), sid)
    assert audit["audit_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["disposition"] == "EXECUTED_NEW"
    assert audit["session_id"] == sid
    assert (
        audit["audit_source"] == REASONING_RUN_IDEMPOTENCY_CONSISTENCY_SOURCE_TASK_135
    )
    assert ReasoningRunIdempotencyConsistencyRead.model_validate(audit)


def test_valid_reused_identical() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    )
    assert r.json()["disposition"] == "REUSED_IDENTICAL"
    audit = _audit(r.json(), sid)
    assert audit["audit_consistent"] is True


def test_valid_stale_changed() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    _add_observation(sid, "Patient reports new dizziness")
    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    )
    assert r.json()["disposition"] == "STALE_CHANGED"
    audit = _audit(r.json(), sid)
    assert audit["audit_consistent"] is True


def test_wrong_disposition_rejected() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["disposition"] = "EXECUTED_SOMETIMES"
    audit = _audit(envelope, sid)
    assert audit["audit_consistent"] is False
    assert "INVALID_DISPOSITION" in audit["consistency_issues"]


def test_stale_result_present_rejected() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    _add_observation(sid, "Patient reports new dizziness")
    envelope = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    ).json()
    assert envelope["disposition"] == "STALE_CHANGED"
    envelope["result"] = {"fabricated": True}
    audit = _audit(envelope, sid)
    assert audit["audit_consistent"] is False
    assert "STALE_RESULT_PRESENT" in audit["consistency_issues"]


def test_reused_fingerprint_mismatch_rejected() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    known = _executed_envelope(sid)["result"]["input_fingerprint"]
    envelope = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    ).json()
    assert envelope["disposition"] == "REUSED_IDENTICAL"
    envelope["result"] = dict(envelope["result"])
    envelope["result"]["input_fingerprint"] = "b" * 64
    audit = _audit(envelope, sid)
    assert audit["audit_consistent"] is False
    assert "REUSED_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


def test_executed_fingerprint_mismatch_rejected() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["result"] = dict(envelope["result"])
    envelope["result"]["input_fingerprint"] = "c" * 64
    audit = _audit(envelope, sid)
    assert audit["audit_consistent"] is False
    assert "EXECUTED_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


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
def test_malformed_fingerprints_rejected(patch: dict[str, Any]) -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope.update(patch)
    audit = _audit(envelope, sid)
    assert audit["audit_consistent"] is False
    assert any(
        issue.endswith("_FINGERPRINT") or "FINGERPRINT" in issue
        for issue in audit["consistency_issues"]
    )


def test_session_mismatch_rejected() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    audit = ReasoningRunIdempotencyConsistencyService().build(
        envelope=envelope, session_id=uuid4()
    )
    assert audit["audit_consistent"] is False
    assert "SESSION_ID_MISMATCH" in audit["consistency_issues"]


def test_malformed_nested_result_rejected() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = _executed_envelope(sid)
    envelope["result"] = {"outcome": "BOGUS", "session_id": sid}
    audit = _audit(envelope, sid)
    assert audit["audit_consistent"] is False
    assert (
        "NESTED_RESULT_MALFORMED" in audit["consistency_issues"]
        or "NESTED_RESULT_INCONSISTENT" in audit["consistency_issues"]
    )


def test_missing_envelope_raises() -> None:
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
    audit = _audit(_executed_envelope(sid), sid)
    audit["smuggled"] = True
    with pytest.raises(ValidationError):
        ReasoningRunIdempotencyConsistencyRead.model_validate(audit)


def test_audit_performs_zero_database_writes() -> None:
    import inspect

    from rop.services import reasoning_run_idempotency_consistency as audit_mod

    source = inspect.getsource(audit_mod)
    assert "Session" not in source
    assert "get_db" not in source
    assert "db.commit" not in source
    assert "db.add" not in source

    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    envelope = copy.deepcopy(_executed_envelope(sid))
    with TestingSessionLocal() as db:
        from sqlalchemy import text as sql_text

        from rop.database import Base as _Base

        before = {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in _Base.metadata.sorted_tables
        }
    _audit(envelope, sid)
    with TestingSessionLocal() as db:
        after = {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in _Base.metadata.sorted_tables
        }
    assert after == before

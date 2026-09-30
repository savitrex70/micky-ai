"""Task 134: deterministic reasoning-run idempotency API tests.

Proves the thin HTTP boundary over Task 127: new execution, exact
reuse, stale on changed input, no-receipt execution, malformed
fingerprints, missing sessions, and internal-error mapping. No model,
no network beyond the test app.
"""

from __future__ import annotations

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
from rop.services.candidate_generation import CandidateGenerationService

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
            "metadata": {"source": "idempotency-api-test"},
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


def _candidate_ids(session_id: str) -> list[str]:
    with TestingSessionLocal() as db:
        return sorted(
            str(c.id)
            for c in CandidateGenerationService().list_by_session(db, UUID(session_id))
        )


def _seeded_session(user_input: str = "Patient reports steady chest pain") -> str:
    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    return sid


def test_a_new_execution_without_body() -> None:
    sid = _seeded_session()
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-idempotent")
    assert r.status_code == 200
    body = r.json()
    assert body["disposition"] == "EXECUTED_NEW"
    assert body["result"] is not None
    assert body["result"]["outcome"] == "COMPLETED"
    fingerprint = body["result"]["input_fingerprint"]
    assert len(fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint)


def test_a_new_execution_with_explicit_null() -> None:
    sid = _seeded_session("Patient reports explicit null chest pain")
    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": None},
    )
    assert r.status_code == 200
    assert r.json()["disposition"] == "EXECUTED_NEW"


def test_b_exact_idempotent_reuse() -> None:
    from rop.repositories.reasoning_run_receipt import (
        ReasoningRunReceiptRepository,
    )

    sid = _seeded_session()
    first = client.post(f"/sessions/{sid}/reasoning-run/execute-idempotent").json()
    assert first["disposition"] == "EXECUTED_NEW"
    known = first["result"]["input_fingerprint"]
    ids_before = _candidate_ids(sid)

    second = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["disposition"] == "REUSED_IDENTICAL"
    assert body["result"] is not None
    assert body["result"]["input_fingerprint"] == known
    # No additional receipt and no derived-state churn.
    with TestingSessionLocal() as db:
        assert ReasoningRunReceiptRepository().count_by_session(db, UUID(sid)) == 1
    assert _candidate_ids(sid) == ids_before


def test_c_changed_input_becomes_stale() -> None:
    sid = _seeded_session()
    known = client.post(f"/sessions/{sid}/reasoning-run/execute-idempotent").json()[
        "result"
    ]["input_fingerprint"]
    _add_observation(sid, "Patient reports new dizziness")

    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": known},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["disposition"] == "STALE_CHANGED"
    assert body["result"] is None
    assert body["known_input_fingerprint"] == known
    assert body["current_input_fingerprint"] != known


def test_d_matching_fingerprint_without_receipt_executes() -> None:
    from rop.services.reasoning_run_fingerprint import (
        compute_snapshot_fingerprint,
    )
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    sid = _seeded_session("Patient reports unobserved chest pain")
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        observed = compute_snapshot_fingerprint(
            ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
        )
    finally:
        gen.close()
    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": observed},
    )
    assert r.status_code == 200
    assert r.json()["disposition"] == "EXECUTED_NEW"
    assert r.json()["disposition"] != "REUSED_IDENTICAL"


@pytest.mark.parametrize(
    "bad",
    (
        "short",
        "G" * 64,
        "z" * 64,
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "not hex at all !!!!",
    ),
)
def test_e_malformed_fingerprint_rejected(bad: str) -> None:
    sid = _seeded_session()
    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": bad},
    )
    assert r.status_code == 422


def test_e_extra_field_rejected() -> None:
    sid = _seeded_session()
    r = client.post(
        f"/sessions/{sid}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": None, "smuggled": True},
    )
    assert r.status_code == 422


def test_f_missing_session_returns_404() -> None:
    r = client.post(f"/sessions/{uuid4()}/reasoning-run/execute-idempotent")
    assert r.status_code == 404
    r = client.post(
        f"/sessions/{uuid4()}/reasoning-run/execute-idempotent",
        json={"known_input_fingerprint": "a" * 64},
    )
    assert r.status_code == 404


def test_g_internal_contract_error_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rop.api.sessions as sessions_api
    from rop.services.reasoning_run_idempotency import (
        ReasoningRunIdempotencyContractError,
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise ReasoningRunIdempotencyContractError(
            "INPUT_SNAPSHOT_FAILED", "secret-internal-detail"
        )

    monkeypatch.setattr(
        sessions_api.reasoning_run_idempotency_service,
        "execute_idempotent",
        _boom,
    )
    sid = _seeded_session()
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-idempotent")
    assert r.status_code == 500
    assert r.json()["detail"] == (
        "Internal reasoning-run-idempotency contract violation"
    )
    assert "secret-internal-detail" not in r.text

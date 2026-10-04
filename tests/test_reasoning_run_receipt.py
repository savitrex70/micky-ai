"""Task 137: deterministic reasoning-run receipt inspection contract tests.

Proves the read-only single-identity receipt inspection boundary:
exact ``(session_id, input_fingerprint)`` lookup, strict schema shape,
explicit found/not-found results, malformed fingerprint rejection, and
zero side effects. No model, no network, no execution, no writes.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_receipt import (
    ReasoningRunReceiptInspectionRead,
    ReasoningRunReceiptRead,
)
from rop.services.reasoning_run_receipt import (
    REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137,
    ReasoningRunReceiptService,
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

RECEIPT_URL = "/sessions/{sid}/reasoning-run/receipt"


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
            "metadata": {"source": "receipt-inspection-test"},
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


def _executed_fingerprint(session_id: str) -> str:
    """Complete one idempotent execution; return its canonical fingerprint."""
    r = client.post(f"/sessions/{session_id}/reasoning-run/execute-idempotent")
    assert r.status_code == 200
    envelope = r.json()
    assert envelope["disposition"] == "EXECUTED_NEW"
    return envelope["result"]["input_fingerprint"]


def _counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in Base.metadata.sorted_tables
        }


# ---------------------------------------------------------------------------
# 1-4: valid matching completed receipt
# ---------------------------------------------------------------------------


def test_matching_completed_receipt_returned() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["available"] is True
    assert body["receipt"] is not None
    assert body["receipt_source"] == REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137


def test_returned_session_id_matches_requested() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    )
    body = r.json()
    assert body["receipt"]["session_id"] == sid
    assert body["requested_session_id"] == sid
    assert UUID(body["receipt"]["session_id"])


def test_returned_fingerprint_matches_requested() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    )
    body = r.json()
    assert body["receipt"]["input_fingerprint"] == fingerprint
    assert body["requested_input_fingerprint"] == fingerprint
    assert len(body["receipt"]["input_fingerprint"]) == 64


def test_persisted_receipt_metadata_consistent() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    )
    receipt = r.json()["receipt"]
    assert set(receipt) == {
        "id",
        "session_id",
        "input_fingerprint",
        "exogenous_snapshot",
        "outcome",
        "created_at",
    }
    assert receipt["outcome"] == "COMPLETED"
    assert isinstance(receipt["exogenous_snapshot"], dict)
    UUID(receipt["id"])
    # created_at parses as an ISO-8601 timestamp.
    from datetime import datetime

    datetime.fromisoformat(receipt["created_at"])


# ---------------------------------------------------------------------------
# 5-8: not-found and no-substitution semantics
# ---------------------------------------------------------------------------


def test_nonexistent_identity_returns_explicit_not_found() -> None:
    sid = _create_session()
    fingerprint = "a" * 64
    r = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["receipt"] is None
    assert body["requested_session_id"] == sid
    assert body["requested_input_fingerprint"] == fingerprint
    assert body["receipt_source"] == REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137


@pytest.mark.parametrize(
    "bad",
    ("short", "A" * 64, "z" * 64, "g" * 63 + "h", "b" * 65),
)
def test_malformed_fingerprint_rejected_422(bad: str) -> None:
    sid = _create_session()
    r = client.get(RECEIPT_URL.format(sid=sid), params={"input_fingerprint": bad})
    assert r.status_code == 422


def test_missing_fingerprint_param_rejected_422() -> None:
    sid = _create_session()
    r = client.get(RECEIPT_URL.format(sid=sid))
    assert r.status_code == 422


def test_different_fingerprint_not_substituted() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    executed = _executed_fingerprint(sid)

    # The exact identity resolves; an unrelated valid fingerprint for
    # the same session does not substitute for it.
    r_exact = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": executed}
    )
    assert r_exact.json()["found"] is True

    other = ("f" if executed[0] != "f" else "e") * 64
    r_other = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": other}
    )
    assert r_other.status_code == 200
    body = r_other.json()
    assert body["found"] is False
    assert body["receipt"] is None


def test_different_session_not_substituted() -> None:
    sid_a = _create_session()
    _add_observation(sid_a, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid_a)

    sid_b = _create_session()
    r = client.get(
        RECEIPT_URL.format(sid=sid_b), params={"input_fingerprint": fingerprint}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["receipt"] is None
    assert body["requested_session_id"] == sid_b


def test_missing_session_404() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)
    r = client.get(
        RECEIPT_URL.format(sid=uuid4()), params={"input_fingerprint": fingerprint}
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# 9-12: read-only guarantees
# ---------------------------------------------------------------------------


def test_inspection_is_read_only() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    before = _counts()
    for _ in range(3):
        r = client.get(
            RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
        )
        assert r.status_code == 200
        assert r.json()["found"] is True
    assert _counts() == before


def test_inspection_does_not_create_receipt() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        before_count = ReasoningRunReceiptRepository().count_by_session(db, UUID(sid))
    assert before_count == 0

    # Inspecting a nonexistent identity must not fabricate a receipt.
    r = client.get(RECEIPT_URL.format(sid=sid), params={"input_fingerprint": "a" * 64})
    assert r.json()["found"] is False
    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        assert ReasoningRunReceiptRepository().count_by_session(db, UUID(sid)) == 0


def test_inspection_does_not_alter_receipt_count() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        before = ReasoningRunReceiptRepository().count_by_session(db, UUID(sid))
    assert before == 1
    for _ in range(2):
        client.get(
            RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
        )
    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        assert ReasoningRunReceiptRepository().count_by_session(db, UUID(sid)) == before


def test_inspection_does_not_execute_reasoning_workflow() -> None:
    """No write-side stage effects appear from inspecting a receipt.

    A fresh observation would trigger OBSERVATION_EXTRACTION during a
    real execution; after inspection the derived state is untouched.
    """
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    with TestingSessionLocal() as db:
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.missing_information import MissingInformationService

        candidates_before = len(
            CandidateGenerationService().list_by_session(db, UUID(sid))
        )
        missing_before = len(MissingInformationService().list_by_session(db, UUID(sid)))

    client.get(RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint})

    with TestingSessionLocal() as db:
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.missing_information import MissingInformationService

        assert (
            len(CandidateGenerationService().list_by_session(db, UUID(sid)))
            == candidates_before
        )
        assert (
            len(MissingInformationService().list_by_session(db, UUID(sid)))
            == missing_before
        )


def test_service_source_has_no_database_or_execution_imports() -> None:
    """The inspection service module stays pure: no executor import."""
    from rop.services import reasoning_run_receipt as receipt_mod

    source = inspect.getsource(receipt_mod)
    assert "ReasoningRunExecutionService" not in source
    assert "execute_for_session" not in source
    assert "db.commit" not in source
    assert "db.add" not in source


# ---------------------------------------------------------------------------
# 13: non-completed receipt state is not presented as completed
# ---------------------------------------------------------------------------


def test_non_completed_receipt_not_reported_as_completed() -> None:
    """A receipt row with a non-COMPLETED outcome is invisible to the
    canonical completed-receipt lookup -- not falsely reported."""
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    # Insert a second receipt row for the same identity with a
    # non-completed outcome directly (the production path only ever
    # writes COMPLETED receipts).
    with TestingSessionLocal() as db:
        from rop.models.reasoning_run_receipt import ReasoningRunReceipt

        db.add(
            ReasoningRunReceipt(
                session_id=UUID(sid),
                input_fingerprint=("b" * 64),
                exogenous_snapshot={"projection": "legacy"},
                outcome="PENDING",
            )
        )
        db.commit()

    r_pending = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": "b" * 64}
    )
    assert r_pending.status_code == 200
    body = r_pending.json()
    assert body["found"] is False
    assert body["receipt"] is None


# ---------------------------------------------------------------------------
# 14-15: determinism and exact schema shape
# ---------------------------------------------------------------------------


def test_repeated_inspection_is_deterministic() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    first = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    ).json()
    for _ in range(3):
        again = client.get(
            RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
        ).json()
        assert again == first


def test_api_response_shape_matches_schema_contract() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    body = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
    ).json()
    assert set(body) == {
        "found",
        "available",
        "requested_session_id",
        "requested_input_fingerprint",
        "receipt",
        "receipt_source",
    }
    assert ReasoningRunReceiptInspectionRead.model_validate(body)
    assert ReasoningRunReceiptRead.model_validate(body["receipt"])

    not_found = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": "c" * 64}
    ).json()
    assert set(not_found) == {
        "found",
        "available",
        "requested_session_id",
        "requested_input_fingerprint",
        "receipt",
        "receipt_source",
    }
    assert ReasoningRunReceiptInspectionRead.model_validate(not_found)


def test_inspection_schema_rejects_extra_fields() -> None:
    from pydantic import ValidationError

    base = {
        "found": True,
        "available": True,
        "requested_session_id": str(uuid4()),
        "requested_input_fingerprint": "a" * 64,
        "receipt": None,
        "receipt_source": REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137,
    }
    smuggled = dict(base)
    smuggled["smuggled"] = True
    with pytest.raises(ValidationError):
        ReasoningRunReceiptInspectionRead.model_validate(smuggled)

    receipt_extra = dict(base)
    receipt_extra["receipt"] = {
        "id": str(uuid4()),
        "session_id": base["requested_session_id"],
        "input_fingerprint": "a" * 64,
        "exogenous_snapshot": {},
        "outcome": "COMPLETED",
        "created_at": "2026-10-01T00:00:00+00:00",
        "smuggled": True,
    }
    with pytest.raises(ValidationError):
        ReasoningRunReceiptInspectionRead.model_validate(receipt_extra)


# ---------------------------------------------------------------------------
# Service-level direct checks
# ---------------------------------------------------------------------------


def test_service_missing_identity_direct() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        result = ReasoningRunReceiptService().inspect(db, UUID(sid), "d" * 64)
    assert result["found"] is False
    assert result["receipt"] is None


def test_service_matching_identity_direct() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)
    with TestingSessionLocal() as db:
        result = ReasoningRunReceiptService().inspect(db, UUID(sid), fingerprint)
    assert result["found"] is True
    assert result["receipt"]["input_fingerprint"] == fingerprint
    assert result["receipt"]["session_id"] == sid

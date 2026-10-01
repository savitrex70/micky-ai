"""Task 139: receipt provenance consistency audit tests.

Proves the strictly read-only provenance audit boundary over persisted
COMPLETED receipts: canonical invariants, explicit invalid-vs-missing
distinction, exact session isolation, deterministic findings, zero
side effects, historical (never recomputed) provenance, strict
schemas, unchanged Task 137/138 contracts, and no model/provider
integration. No execution, no replay, no writes, no network.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Generator
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.models.reasoning_run_receipt import ReasoningRunReceipt
from rop.schemas.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditRead,
    ReasoningRunReceiptProvenanceFindingRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
    ReasoningRunInputSnapshotService,
)
from rop.services.reasoning_run_receipt import (
    REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137,
)
from rop.services.reasoning_run_receipt_provenance_audit import (
    REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_SOURCE_TASK_139,
    ReasoningRunReceiptProvenanceAuditService,
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

AUDIT_URL = "/sessions/{sid}/reasoning-run/receipt/provenance-audit"
HISTORY_URL = "/sessions/{sid}/reasoning-run/history"
RECEIPT_URL = "/sessions/{sid}/reasoning-run/receipt"

AUDIT_KEYS = {
    "available",
    "audit_consistent",
    "session_id",
    "completed_receipts_examined",
    "valid_receipts",
    "invalid_receipts",
    "findings",
    "audit_source",
}
FINDING_KEYS = {
    "receipt_id",
    "input_fingerprint",
    "receipt_consistent",
    "fingerprint_binding",
    "provenance_issues",
}
RECEIPT_KEYS = {
    "id",
    "session_id",
    "input_fingerprint",
    "exogenous_snapshot",
    "outcome",
    "created_at",
}


@pytest.fixture(autouse=True)
def _reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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
            "metadata": {"source": "provenance-audit-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _valid_exogenous(session_id: UUID) -> dict[str, object]:
    """A structurally canonical Task 124 exogenous projection."""
    return {
        "session_id": str(session_id),
        "user_input": "Patient reports chest pain",
        "observations": [],
        "entities": [],
    }


def _canonical_snapshot(session_id: UUID) -> dict[str, object]:
    """A canonical Task 124 input snapshot with empty collections."""
    return {
        "session_id": str(session_id),
        "user_input": "Patient reports chest pain",
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_matches": [],
        "candidates": [],
        "evidence": [],
        "candidate_order": [],
        "evidence_order": [],
        "snapshot_source": REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
    }


def _insert_receipt(
    session_id: UUID,
    input_fingerprint: str,
    outcome: str = "COMPLETED",
    created_at: datetime | None = None,
    exogenous: dict[str, object] | None = None,
    input_snapshot: dict[str, object] | None = None,
) -> ReasoningRunReceipt:
    row = ReasoningRunReceipt(
        session_id=session_id,
        input_fingerprint=input_fingerprint,
        exogenous_snapshot=(
            exogenous if exogenous is not None else _valid_exogenous(session_id)
        ),
        input_snapshot=input_snapshot,
        outcome=outcome,
    )
    if created_at is not None:
        row.created_at = created_at
    with TestingSessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in Base.metadata.sorted_tables
        }


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


# ---------------------------------------------------------------------------
# Basic audit
# ---------------------------------------------------------------------------


def test_audit_of_valid_completed_receipts_is_consistent() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64)
    _insert_receipt(sid, hashlib.sha256(b"rop-canonical-input").hexdigest())

    r = client.get(AUDIT_URL.format(sid=sid))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == AUDIT_KEYS
    assert body["available"] is True
    assert body["audit_consistent"] is True
    assert body["session_id"] == str(sid)
    assert body["completed_receipts_examined"] == 2
    assert body["valid_receipts"] == 2
    assert body["invalid_receipts"] == 0
    assert body["audit_source"] == (
        REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_SOURCE_TASK_139
    )
    assert len(body["findings"]) == 2
    for finding in body["findings"]:
        assert set(finding) == FINDING_KEYS
        assert finding["receipt_consistent"] is True
        assert finding["provenance_issues"] == []
    ReasoningRunReceiptProvenanceAuditRead.model_validate(body)


def test_audit_missing_history_is_distinct_from_invalid() -> None:
    sid = UUID(_create_session())

    r = client.get(AUDIT_URL.format(sid=sid))
    assert r.status_code == 200
    body = r.json()
    assert body["completed_receipts_examined"] == 0
    assert body["valid_receipts"] == 0
    assert body["invalid_receipts"] == 0
    assert body["findings"] == []
    assert body["audit_consistent"] is True


def test_audit_nonexistent_session_returns_404() -> None:
    r = client.get(AUDIT_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------------------------


def test_audit_valid_lowercase_sha256_fingerprint_passes() -> None:
    sid = UUID(_create_session())
    fingerprint = hashlib.sha256(b"exact canonical snapshot bytes").hexdigest()
    assert len(fingerprint) == 64 and fingerprint.islower()
    _insert_receipt(sid, fingerprint)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["audit_consistent"] is True
    assert body["findings"][0]["input_fingerprint"] == fingerprint
    assert body["findings"][0]["provenance_issues"] == []


def test_audit_malformed_fingerprint_is_invalid() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "z" * 64)  # 64 chars, non-hex

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["completed_receipts_examined"] == 1
    assert body["invalid_receipts"] == 1
    assert body["audit_consistent"] is False
    finding = body["findings"][0]
    assert finding["receipt_consistent"] is False
    assert "MALFORMED_FINGERPRINT" in finding["provenance_issues"]


def test_audit_uppercase_fingerprint_is_invalid() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "A" * 64)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["invalid_receipts"] == 1
    assert body["audit_consistent"] is False
    assert "MALFORMED_FINGERPRINT" in body["findings"][0]["provenance_issues"]


def test_audit_wrong_length_fingerprint_is_invalid() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 63)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["invalid_receipts"] == 1
    assert body["audit_consistent"] is False
    assert "MALFORMED_FINGERPRINT" in body["findings"][0]["provenance_issues"]


def test_audit_invalid_receipt_is_not_silently_missing() -> None:
    invalid_sid = UUID(_create_session())
    _insert_receipt(invalid_sid, "A" * 64)
    empty_sid = UUID(_create_session())

    invalid_body = client.get(AUDIT_URL.format(sid=invalid_sid)).json()
    missing_body = client.get(AUDIT_URL.format(sid=empty_sid)).json()

    # The invalid receipt exists, is examined, and is reported invalid.
    assert invalid_body["completed_receipts_examined"] == 1
    assert invalid_body["invalid_receipts"] == 1
    assert len(invalid_body["findings"]) == 1
    assert invalid_body["audit_consistent"] is False
    # Missing history is a distinct shape: examined == 0, no findings.
    assert missing_body["completed_receipts_examined"] == 0
    assert missing_body["findings"] == []


def test_audit_malformed_exogenous_snapshot_is_invalid() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, exogenous={"source": "not-canonical"})
    _insert_receipt(
        sid,
        "d" * 64,
        exogenous={
            "session_id": str(sid),
            "user_input": "Patient reports chest pain",
            "observations": "not-a-list",
            "entities": [],
        },
    )

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["completed_receipts_examined"] == 2
    assert body["invalid_receipts"] == 2
    assert body["audit_consistent"] is False
    for finding in body["findings"]:
        assert "EXOGENOUS_SNAPSHOT_MALFORMED" in finding["provenance_issues"]


def test_audit_exogenous_session_mismatch_is_invalid() -> None:
    sid = UUID(_create_session())
    snapshot = _valid_exogenous(sid)
    snapshot["session_id"] = str(uuid4())
    _insert_receipt(sid, "e" * 64, exogenous=snapshot)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["invalid_receipts"] == 1
    issues = body["findings"][0]["provenance_issues"]
    assert "EXOGENOUS_SESSION_MISMATCH" in issues
    assert "EXOGENOUS_SNAPSHOT_MALFORMED" not in issues


def test_audit_issues_include_unreadable_projection() -> None:
    sid = UUID(_create_session())
    row = _insert_receipt(sid, "f" * 64)
    with TestingSessionLocal() as db:
        persisted = db.get(ReasoningRunReceipt, row.id)
        assert persisted is not None
        persisted.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["invalid_receipts"] == 1
    issues = body["findings"][0]["provenance_issues"]
    assert "RECEIPT_UNREADABLE" in issues
    assert "EXOGENOUS_SNAPSHOT_MALFORMED" in issues


def test_audit_non_completed_receipts_excluded_from_completed_audit() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, outcome="PENDING")
    _insert_receipt(sid, "d" * 64, outcome="COMPLETED")

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["completed_receipts_examined"] == 1
    assert [f["input_fingerprint"] for f in body["findings"]] == ["d" * 64]

    only_pending_sid = UUID(_create_session())
    _insert_receipt(only_pending_sid, "e" * 64, outcome="PENDING")
    pending_body = client.get(AUDIT_URL.format(sid=only_pending_sid)).json()
    assert pending_body["completed_receipts_examined"] == 0
    assert pending_body["findings"] == []


def test_audit_issues_are_sorted_deterministically() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "A" * 64, exogenous={})

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    issues = body["findings"][0]["provenance_issues"]
    assert issues == sorted(issues)
    assert issues == ["EXOGENOUS_SNAPSHOT_MALFORMED", "MALFORMED_FINGERPRINT"]


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_audit_never_audits_another_sessions_receipts() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_receipt(sid_a, "a" * 64)
    _insert_receipt(sid_b, "b" * 64)
    _insert_receipt(sid_b, "c" * 64)

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        ids_a = {
            str(r.id)
            for r in ReasoningRunReceiptRepository().list_completed_by_session(
                db, sid_a
            )
        }
        ids_b = {
            str(r.id)
            for r in ReasoningRunReceiptRepository().list_completed_by_session(
                db, sid_b
            )
        }

    body_a = client.get(AUDIT_URL.format(sid=sid_a)).json()
    body_b = client.get(AUDIT_URL.format(sid=sid_b)).json()
    assert body_a["session_id"] == str(sid_a)
    assert body_b["session_id"] == str(sid_b)
    assert body_a["completed_receipts_examined"] == 1
    assert body_b["completed_receipts_examined"] == 2
    assert {f["receipt_id"] for f in body_a["findings"]} == ids_a
    assert {f["receipt_id"] for f in body_b["findings"]} == ids_b
    assert ids_a.isdisjoint(ids_b)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_audit_repeated_requests_are_byte_identical() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64, created_at=datetime(2024, 5, 1, 0, 0, 0))
    _insert_receipt(sid, "b" * 64, created_at=datetime(2024, 5, 1, 0, 0, 0))

    first = client.get(AUDIT_URL.format(sid=sid))
    assert first.status_code == 200
    for _ in range(3):
        again = client.get(AUDIT_URL.format(sid=sid))
        assert again.status_code == 200
        assert again.content == first.content


def test_audit_findings_are_deterministically_ordered() -> None:
    sid = UUID(_create_session())
    t0 = datetime(2024, 3, 1, 12, 0, 0)
    t1 = datetime(2024, 3, 2, 12, 0, 0)
    _insert_receipt(sid, "d" * 64, created_at=t1)
    _insert_receipt(sid, "e" * 64, created_at=t0)
    _insert_receipt(sid, "f" * 64, created_at=t0)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        repo_order = [
            str(r.id)
            for r in ReasoningRunReceiptRepository().list_completed_by_session(db, sid)
        ]
    finding_order = [f["receipt_id"] for f in body["findings"]]
    assert finding_order == repo_order

    history = client.get(HISTORY_URL.format(sid=sid)).json()
    assert finding_order == [r["id"] for r in history["receipts"]]
    assert [r["created_at"] for r in history["receipts"]] == [
        t0.isoformat(),
        t0.isoformat(),
        t1.isoformat(),
    ]

    again = client.get(AUDIT_URL.format(sid=sid)).json()
    assert [f["receipt_id"] for f in again["findings"]] == finding_order


# ---------------------------------------------------------------------------
# Read-only behavior
# ---------------------------------------------------------------------------


def test_audit_performs_no_writes_no_execution_no_replay() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.missing_information import MissingInformationService

        receipts_before = ReasoningRunReceiptRepository().count_by_session(
            db, UUID(sid)
        )
        candidates_before = len(
            CandidateGenerationService().list_by_session(db, UUID(sid))
        )
        missing_before = len(MissingInformationService().list_by_session(db, UUID(sid)))
    counts_before = _counts()

    for _ in range(2):
        r = client.get(AUDIT_URL.format(sid=sid))
        assert r.status_code == 200
        assert r.json()["completed_receipts_examined"] == receipts_before

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.missing_information import MissingInformationService

        assert (
            ReasoningRunReceiptRepository().count_by_session(db, UUID(sid))
            == receipts_before
        )
        assert (
            len(CandidateGenerationService().list_by_session(db, UUID(sid)))
            == candidates_before
        )
        assert (
            len(MissingInformationService().list_by_session(db, UUID(sid)))
            == missing_before
        )
    # Every table (receipts, observations, hypotheses, candidates,
    # missing information, sessions, ...) is untouched: no insert, no
    # update, no delete, no commit-visible change.
    assert _counts() == counts_before


def test_audit_service_and_endpoint_sources_are_read_only() -> None:
    from rop.services import reasoning_run_receipt_provenance_audit as audit_mod

    service_source = inspect.getsource(audit_mod)
    for token in (
        "db.commit",
        "db.add",
        "db.flush",
        "db.delete",
        "record_completed",
        "compute_snapshot_fingerprint",
        "build_snapshot",
        "ReasoningRunExecutionService",
        "ReasoningRunReplayService",
        "execute_idempotent",
        "httpx",
    ):
        assert token not in service_source

    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(
        sessions_mod.audit_reasoning_run_receipt_provenance
    )
    for token in ("db.commit", "db.add", "db.flush", "execute_idempotent"):
        assert token not in endpoint_source


def test_audit_service_direct_call_matches_endpoint_and_is_read_only() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunReceiptProvenanceAuditService().audit(db, sid)
    assert _counts() == counts_before

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert _counts() == counts_before
    assert body == direct


# ---------------------------------------------------------------------------
# Historical provenance
# ---------------------------------------------------------------------------


def test_audit_uses_persisted_receipt_not_current_session_state() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    executed_fingerprint = _executed_fingerprint(sid)

    first = client.get(AUDIT_URL.format(sid=sid)).json()
    assert first["audit_consistent"] is True
    assert first["findings"][0]["input_fingerprint"] == executed_fingerprint

    # Mutate current session state; persisted provenance must not move.
    _add_observation(sid, "Patient reports dizziness after rest")
    second = client.get(AUDIT_URL.format(sid=sid)).json()
    assert second == first

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        persisted_rows = ReasoningRunReceiptRepository().list_completed_by_session(
            db, UUID(sid)
        )
        assert len(persisted_rows) == 1
        persisted = persisted_rows[0].input_fingerprint
        current_fingerprint = compute_snapshot_fingerprint(
            ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
        )

    # The audit reports the historical persisted fingerprint, never a
    # fingerprint recomputed from current mutable state.
    assert persisted == executed_fingerprint
    assert first["findings"][0]["input_fingerprint"] == persisted
    assert current_fingerprint != persisted


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_audit_schema_rejects_top_level_extra_fields() -> None:
    payload = {
        "available": True,
        "audit_consistent": True,
        "session_id": str(uuid4()),
        "completed_receipts_examined": 0,
        "valid_receipts": 0,
        "invalid_receipts": 0,
        "findings": [],
        "audit_source": REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_SOURCE_TASK_139,
        "smuggled": True,
    }
    with pytest.raises(ValidationError):
        ReasoningRunReceiptProvenanceAuditRead.model_validate(payload)


def test_audit_schema_rejects_nested_finding_extra_fields() -> None:
    payload = {
        "available": True,
        "audit_consistent": False,
        "session_id": str(uuid4()),
        "completed_receipts_examined": 1,
        "valid_receipts": 0,
        "invalid_receipts": 1,
        "findings": [
            {
                "receipt_id": str(uuid4()),
                "input_fingerprint": "a" * 64,
                "receipt_consistent": False,
                "provenance_issues": ["MALFORMED_FINGERPRINT"],
                "smuggled": True,
            }
        ],
        "audit_source": REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_SOURCE_TASK_139,
    }
    with pytest.raises(ValidationError):
        ReasoningRunReceiptProvenanceAuditRead.model_validate(payload)
    with pytest.raises(ValidationError):
        ReasoningRunReceiptProvenanceFindingRead.model_validate(payload["findings"][0])


def test_audit_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert set(body) == AUDIT_KEYS
    assert set(body["findings"][0]) == FINDING_KEYS
    assert ReasoningRunReceiptProvenanceAuditRead.model_validate(body)


# ---------------------------------------------------------------------------
# Task 137 regression: single-receipt inspection contract unchanged
# ---------------------------------------------------------------------------


def test_task_137_inspection_endpoint_remains_unchanged() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        RECEIPT_URL.format(sid=sid),
        params={"input_fingerprint": fingerprint},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "found",
        "available",
        "requested_session_id",
        "requested_input_fingerprint",
        "receipt",
        "receipt_source",
    }
    assert body["found"] is True
    assert body["available"] is True
    assert body["requested_session_id"] == sid
    assert body["requested_input_fingerprint"] == fingerprint
    assert body["receipt_source"] == REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137
    assert set(body["receipt"]) == RECEIPT_KEYS
    assert body["receipt"]["input_fingerprint"] == fingerprint
    assert body["receipt"]["outcome"] == "COMPLETED"

    # Malformed fingerprint still fails request validation (422), never
    # normalized; a well-formed unknown identity still reports found=False.
    malformed = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": "A" * 64}
    )
    assert malformed.status_code == 422
    missing = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": "0" * 64}
    )
    assert missing.status_code == 200
    assert missing.json()["found"] is False
    assert missing.json()["receipt"] is None


# ---------------------------------------------------------------------------
# Task 138 regression: history endpoint unchanged
# ---------------------------------------------------------------------------


def test_task_138_history_endpoint_remains_unchanged() -> None:
    other_sid = UUID(_create_session())
    _insert_receipt(other_sid, "b" * 64)

    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)
    _insert_receipt(UUID(sid), "c" * 64, outcome="PENDING")

    counts_before = _counts()
    first = client.get(HISTORY_URL.format(sid=sid))
    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"session_id", "receipts"}
    assert body["session_id"] == sid
    assert len(body["receipts"]) == 1
    receipt = body["receipts"][0]
    assert set(receipt) == RECEIPT_KEYS
    assert receipt["input_fingerprint"] == fingerprint
    assert receipt["outcome"] == "COMPLETED"
    assert receipt["session_id"] == sid
    assert all(item["outcome"] == "COMPLETED" for item in body["receipts"])

    again = client.get(HISTORY_URL.format(sid=sid))
    assert again.json() == body
    assert _counts() == counts_before


# ---------------------------------------------------------------------------
# Architecture: no provider/model integration
# ---------------------------------------------------------------------------


def test_task_139_introduces_no_provider_or_model_integration() -> None:
    from pathlib import Path

    import rop

    root = Path(rop.__file__).parent
    modules = (
        root / "services" / "reasoning_run_receipt_provenance_audit.py",
        root / "schemas" / "reasoning_run_receipt_provenance_audit.py",
        root / "api" / "sessions.py",
    )
    banned = (
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "claude",
        "api_key",
        "apikey",
    )
    for path in modules:
        source = path.read_text(encoding="utf-8").lower()
        for token in banned:
            assert token not in source, f"{path.name} contains {token!r}"


# ---------------------------------------------------------------------------
# Task 139 correction: fingerprint-to-provenance binding (Task 125)
# ---------------------------------------------------------------------------


def test_audit_binds_fingerprint_to_persisted_snapshot() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    fingerprint = compute_snapshot_fingerprint(snapshot)
    _insert_receipt(sid, fingerprint, input_snapshot=snapshot)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["audit_consistent"] is True
    finding = body["findings"][0]
    assert finding["fingerprint_binding"] == "BOUND"
    assert finding["provenance_issues"] == []
    assert finding["input_fingerprint"] == fingerprint


def test_audit_detects_fingerprint_provenance_mismatch() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    fingerprint = compute_snapshot_fingerprint(snapshot)
    forged = hashlib.sha256(b"forged-provenance").hexdigest()
    assert forged != fingerprint
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["completed_receipts_examined"] == 1
    assert body["invalid_receipts"] == 1
    assert body["audit_consistent"] is False
    finding = body["findings"][0]
    assert finding["fingerprint_binding"] == "INVALID"
    assert "FINGERPRINT_PROVENANCE_MISMATCH" in finding["provenance_issues"]
    # Invalid, never silently missing: the receipt is still examined.
    assert finding["receipt_consistent"] is False


def test_audit_detects_exogenous_projection_mismatch() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    fingerprint = compute_snapshot_fingerprint(snapshot)
    tampered_exogenous = _valid_exogenous(sid)
    tampered_exogenous["user_input"] = "Patient reports something else"
    _insert_receipt(
        sid,
        fingerprint,
        exogenous=tampered_exogenous,
        input_snapshot=snapshot,
    )

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    finding = body["findings"][0]
    assert finding["fingerprint_binding"] == "BOUND"
    assert "EXOGENOUS_PROJECTION_MISMATCH" in finding["provenance_issues"]
    assert body["invalid_receipts"] == 1


def test_audit_flags_malformed_persisted_input_snapshot() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    broken = dict(snapshot)
    del broken["candidate_order"]  # fails the strict Task 124 schema
    broken_fingerprint = compute_snapshot_fingerprint(broken)
    _insert_receipt(sid, broken_fingerprint, input_snapshot=broken)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    finding = body["findings"][0]
    # The hash still binds the stored bytes; the structure is what fails.
    assert finding["fingerprint_binding"] == "BOUND"
    assert "INPUT_SNAPSHOT_MALFORMED" in finding["provenance_issues"]
    assert body["invalid_receipts"] == 1


def test_audit_legacy_receipt_binding_is_explicit_not_silent() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64)  # receipt predates persisted binding evidence

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    finding = body["findings"][0]
    assert finding["fingerprint_binding"] == "NOT_PERSISTED"
    assert finding["receipt_consistent"] is True
    assert finding["provenance_issues"] == []
    assert body["completed_receipts_examined"] == 1


def test_audit_verifies_binding_for_real_execution_receipt() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    body = client.get(AUDIT_URL.format(sid=sid)).json()
    assert body["audit_consistent"] is True
    finding = body["findings"][0]
    assert finding["input_fingerprint"] == fingerprint
    assert finding["fingerprint_binding"] == "BOUND"
    assert finding["provenance_issues"] == []

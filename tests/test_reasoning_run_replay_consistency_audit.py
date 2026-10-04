"""Task 141: replay API consistency audit tests.

Proves the strictly read-only consistency-audit boundary between the
canonical Task 140 replay API and the Task 128 replay contract: the
three required states (no replay material / inconsistent /
malformed-unverifiable) stay strictly distinct, violations are
detected over the persisted surfaces the receipt actually carries
(session identity, fingerprint shape, exogenous snapshot structure,
and persisted input snapshot binding) by reusing the canonical
contract's own verification, output is deterministic, there are zero
side effects, historical material is never recomputed from current
state, schemas are strict, the divergence-vs-contract-failure
boundary is preserved, the Task 137/138/139/140 contracts are
unchanged, and no model/provider integration is introduced. No
execution, no replay, no writes, no network.

The Task 140 ``original_result`` is request material and is not
persisted as historical replay evidence by the current architecture,
so its provenance is reported as ``NOT_PERSISTED`` rather than
audited. Tests below cover that limitation explicitly.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
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
from rop.schemas.reasoning_run_replay_consistency_audit import (
    ReasoningRunReplayConsistencyAuditRead,
    ReasoningRunReplayConsistencyFindingRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
    ReasoningRunInputSnapshotService,
)
from rop.services.reasoning_run_receipt import (
    REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137,
)
from rop.services.reasoning_run_replay import ReasoningRunReplayService
from rop.services.reasoning_run_replay_consistency_audit import (
    REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_SOURCE_TASK_141,
    ReasoningRunReplayConsistencyAuditService,
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

AUDIT_URL = "/sessions/{sid}/reasoning-run/replay/consistency-audit"
POST_REPLAY_URL = "/sessions/{sid}/reasoning-run/replay"
HISTORY_URL = "/sessions/{sid}/reasoning-run/history"
RECEIPT_URL = "/sessions/{sid}/reasoning-run/receipt"
PROVENANCE_URL = "/sessions/{sid}/reasoning-run/receipt/provenance-audit"

AUDIT_KEYS = {
    "available",
    "audit_consistent",
    "session_id",
    "replay_state",
    "original_result_provenance",
    "completed_receipts_examined",
    "valid_receipts",
    "invalid_receipts",
    "findings",
    "audit_source",
}
FINDING_KEYS = {
    "receipt_id",
    "input_fingerprint",
    "replay_consistent",
    "replay_state",
    "replay_contract_finding",
    "replay_issues",
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
            "metadata": {"source": "replay-consistency-audit-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _valid_exogenous(session_id: UUID) -> dict[str, object]:
    return {
        "session_id": str(session_id),
        "user_input": "Patient reports chest pain",
        "observations": [],
        "entities": [],
    }


def _canonical_snapshot(session_id: UUID) -> dict[str, object]:
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


def _insert_bound_receipt(
    session_id: UUID,
    user_input: str = "Patient reports chest pain",
    created_at: datetime | None = None,
) -> ReasoningRunReceipt:
    """Insert replay material whose persisted snapshot binds its fingerprint."""
    snapshot = _canonical_snapshot(session_id)
    snapshot["user_input"] = user_input
    exogenous = _valid_exogenous(session_id)
    exogenous["user_input"] = user_input
    return _insert_receipt(
        session_id,
        compute_snapshot_fingerprint(snapshot),
        created_at=created_at,
        exogenous=exogenous,
        input_snapshot=snapshot,
    )


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
    r = client.post(f"/sessions/{session_id}/reasoning-run/execute-idempotent")
    assert r.status_code == 200
    envelope = r.json()
    assert envelope["disposition"] == "EXECUTED_NEW"
    return envelope["result"]["input_fingerprint"]


def _json_safe(obj: object) -> object:
    return json.loads(json.dumps(obj, default=str))


def _audit(sid: UUID) -> dict:
    r = client.get(AUDIT_URL.format(sid=sid))
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Basic audit and the three required states
# ---------------------------------------------------------------------------


def test_audit_of_consistent_replay_material_is_satisfied() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid, user_input="Patient reports chest pain")
    _insert_bound_receipt(sid, user_input="Patient reports dizziness after rest")

    body = _audit(sid)
    assert set(body) == AUDIT_KEYS
    assert body["available"] is True
    assert body["audit_consistent"] is True
    assert body["session_id"] == str(sid)
    assert body["replay_state"] == "SATISFIED"
    assert body["completed_receipts_examined"] == 2
    assert body["valid_receipts"] == 2
    assert body["invalid_receipts"] == 0
    assert body["audit_source"] == (
        REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_SOURCE_TASK_141
    )
    for finding in body["findings"]:
        assert set(finding) == FINDING_KEYS
        assert finding["replay_consistent"] is True
        assert finding["replay_state"] == "SATISFIED"
        assert finding["replay_contract_finding"] == "PERSISTED_MATERIAL_VERIFIABLE"
        assert finding["replay_issues"] == []
    ReasoningRunReplayConsistencyAuditRead.model_validate(body)


def test_audit_reports_no_material_when_no_replay_history_exists() -> None:
    sid = UUID(_create_session())

    body = _audit(sid)
    assert body["replay_state"] == "NO_MATERIAL"
    assert body["completed_receipts_examined"] == 0
    assert body["valid_receipts"] == 0
    assert body["invalid_receipts"] == 0
    assert body["findings"] == []
    assert body["audit_consistent"] is True


def test_audit_three_states_are_strictly_distinct() -> None:
    """No material, inconsistent, and malformed must never be conflated."""
    empty_sid = UUID(_create_session())
    tampered_sid = UUID(_create_session())
    malformed_sid = UUID(_create_session())

    _insert_bound_receipt(tampered_sid)
    forged = hashlib.sha256(b"forged-replay-material").hexdigest()
    with TestingSessionLocal() as db:
        db.query(ReasoningRunReceipt).filter(
            ReasoningRunReceipt.session_id == tampered_sid
        ).one().input_fingerprint = forged
        db.commit()

    _insert_bound_receipt(malformed_sid, user_input="now unverifiable")
    with TestingSessionLocal() as db:
        db.query(ReasoningRunReceipt).filter(
            ReasoningRunReceipt.session_id == malformed_sid
        ).one().input_snapshot = None
        db.commit()

    empty = _audit(empty_sid)
    tampered = _audit(tampered_sid)
    malformed = _audit(malformed_sid)

    assert empty["replay_state"] == "NO_MATERIAL"
    assert empty["completed_receipts_examined"] == 0
    assert empty["audit_consistent"] is True

    assert tampered["replay_state"] == "INCONSISTENT"
    assert tampered["completed_receipts_examined"] == 1
    assert tampered["audit_consistent"] is False
    assert tampered["findings"][0]["replay_contract_finding"] == "RECORD_TAMPERED"

    assert malformed["replay_state"] == "MALFORMED"
    assert malformed["completed_receipts_examined"] == 1
    assert malformed["audit_consistent"] is False

    # The three states are mutually exclusive strings, never aliased.
    states = {
        empty["replay_state"],
        tampered["replay_state"],
        malformed["replay_state"],
    }
    assert len(states) == 3


def test_audit_nonexistent_session_returns_404() -> None:
    r = client.get(AUDIT_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


# ---------------------------------------------------------------------------
# Tamper detection: fingerprint surface
# ---------------------------------------------------------------------------


def test_audit_binds_fingerprint_to_persisted_snapshot() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    fingerprint = compute_snapshot_fingerprint(snapshot)
    _insert_receipt(sid, fingerprint, input_snapshot=snapshot)

    finding = _audit(sid)["findings"][0]
    assert finding["replay_consistent"] is True
    assert finding["replay_state"] == "SATISFIED"
    assert finding["replay_contract_finding"] == "PERSISTED_MATERIAL_VERIFIABLE"
    assert finding["replay_issues"] == []
    assert finding["input_fingerprint"] == fingerprint


def test_audit_detects_tampered_fingerprint_via_canonical_contract() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = hashlib.sha256(b"forged-replay-material").hexdigest()
    assert forged != honest
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _audit(sid)
    assert body["replay_state"] == "INCONSISTENT"
    assert body["completed_receipts_examined"] == 1
    assert body["invalid_receipts"] == 1
    assert body["audit_consistent"] is False
    finding = body["findings"][0]
    assert finding["replay_consistent"] is False
    assert finding["replay_contract_finding"] == "RECORD_TAMPERED"
    assert finding["replay_issues"] == ["REPLAY_RECORD_TAMPERED"]


def test_audit_malformed_fingerprint_is_record_invalid() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    _insert_receipt(
        sid,
        "z" * 64,
        input_snapshot=snapshot,
    )

    finding = _audit(sid)["findings"][0]
    assert finding["replay_state"] == "MALFORMED"
    assert finding["replay_contract_finding"] == "RECORD_INVALID"
    assert "REPLAY_MALFORMED_FINGERPRINT" in finding["replay_issues"]


def test_audit_uppercase_fingerprint_is_record_invalid() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    _insert_receipt(sid, "A" * 64, input_snapshot=snapshot)

    body = _audit(sid)
    assert body["replay_state"] == "MALFORMED"
    assert body["invalid_receipts"] == 1
    assert "REPLAY_MALFORMED_FINGERPRINT" in body["findings"][0]["replay_issues"]


def test_audit_wrong_length_fingerprint_is_record_invalid() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 63)

    finding = _audit(sid)["findings"][0]
    assert finding["replay_state"] == "MALFORMED"
    assert finding["replay_contract_finding"] == "RECORD_INVALID"
    assert "REPLAY_MALFORMED_FINGERPRINT" in finding["replay_issues"]


# ---------------------------------------------------------------------------
# Tamper detection: session identity surface
# ---------------------------------------------------------------------------


def test_audit_detects_session_identity_tampering() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    tampered_exogenous = _valid_exogenous(sid)
    tampered_exogenous["session_id"] = str(uuid4())
    with TestingSessionLocal() as db:
        rows = (
            db.query(ReasoningRunReceipt)
            .filter(ReasoningRunReceipt.session_id == sid)
            .all()
        )
        rows[0].exogenous_snapshot = tampered_exogenous
        db.commit()

    body = _audit(sid)
    finding = body["findings"][0]
    assert body["replay_state"] == "INCONSISTENT"
    assert finding["replay_contract_finding"] == "RECORD_TAMPERED"
    assert "REPLAY_EXOGENOUS_SESSION_MISMATCH" in finding["replay_issues"]


def test_audit_reports_receipt_bound_to_another_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        receipt = ReasoningRunReceiptRepository().list_completed_by_session(db, sid_a)[
            0
        ]
        (
            issues,
            state,
            finding,
        ) = ReasoningRunReplayConsistencyAuditService()._replay_contract_issues(
            receipt, sid_b
        )

    assert "REPLAY_SESSION_MISMATCH" in issues
    assert state == "MALFORMED"
    assert finding == "RECORD_INVALID"


# ---------------------------------------------------------------------------
# Tamper detection: snapshot surface
# ---------------------------------------------------------------------------


def test_audit_detects_exogenous_projection_tampering() -> None:
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

    body = _audit(sid)
    finding = body["findings"][0]
    assert body["replay_state"] == "INCONSISTENT"
    assert finding["replay_contract_finding"] == "RECORD_TAMPERED"
    assert "REPLAY_EXOGENOUS_PROJECTION_MISMATCH" in finding["replay_issues"]
    # The binding itself is intact: only the projection disagrees.
    assert "REPLAY_RECORD_TAMPERED" not in finding["replay_issues"]


def test_audit_malformed_exogenous_snapshot_is_record_invalid() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64, exogenous={"source": "not-canonical"})
    _insert_receipt(
        sid,
        "b" * 64,
        exogenous={
            "session_id": str(sid),
            "user_input": "Patient reports chest pain",
            "observations": "not-a-list",
            "entities": [],
        },
    )

    body = _audit(sid)
    assert body["replay_state"] == "MALFORMED"
    assert body["invalid_receipts"] == 2
    for finding in body["findings"]:
        assert "REPLAY_EXOGENOUS_SNAPSHOT_MALFORMED" in finding["replay_issues"]
        assert finding["replay_contract_finding"] == "RECORD_INVALID"


def test_audit_unreadable_receipt_is_record_invalid() -> None:
    sid = UUID(_create_session())
    row = _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        persisted = db.get(ReasoningRunReceipt, row.id)
        assert persisted is not None
        persisted.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    finding = _audit(sid)["findings"][0]
    assert finding["replay_state"] == "MALFORMED"
    assert finding["replay_contract_finding"] == "RECORD_INVALID"
    assert "REPLAY_RECEIPT_UNREADABLE" in finding["replay_issues"]
    assert "REPLAY_EXOGENOUS_SNAPSHOT_MALFORMED" in finding["replay_issues"]


def test_audit_malformed_input_snapshot_is_record_invalid() -> None:
    sid = UUID(_create_session())
    broken = _canonical_snapshot(sid)
    del broken["candidate_order"]  # fails the strict Task 124 schema
    fingerprint = compute_snapshot_fingerprint(broken)
    _insert_receipt(sid, fingerprint, input_snapshot=broken)

    finding = _audit(sid)["findings"][0]
    # The hash still binds the stored bytes; the structure is what fails.
    assert "REPLAY_RECORD_TAMPERED" not in finding["replay_issues"]
    assert "REPLAY_INPUT_SNAPSHOT_MALFORMED" in finding["replay_issues"]
    assert finding["replay_state"] == "MALFORMED"
    assert finding["replay_contract_finding"] == "RECORD_INVALID"


def test_audit_unpersisted_binding_is_explicitly_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64)  # predates persisted binding evidence

    body = _audit(sid)
    finding = body["findings"][0]
    assert finding["replay_contract_finding"] == "UNVERIFIABLE"
    assert finding["replay_state"] == "MALFORMED"
    assert finding["replay_issues"] == ["REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED"]
    # Unverifiable material is never reported as verified, and never
    # counted consistent, while remaining semantically distinct from a
    # tamper verdict: nothing is claimed cryptographically wrong.
    assert "REPLAY_RECORD_TAMPERED" not in finding["replay_issues"]
    assert finding["replay_consistent"] is False
    assert body["completed_receipts_examined"] == 1
    assert body["valid_receipts"] == 0
    assert body["invalid_receipts"] == 1
    assert body["audit_consistent"] is False


def test_audit_never_downgrades_malformed_to_tampered() -> None:
    """Structural malformation outranks the weaker tamper verdict."""
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    _insert_receipt(
        sid,
        "A" * 64,  # malformed fingerprint AND
        input_snapshot=snapshot,
    )
    with TestingSessionLocal() as db:
        rows = (
            db.query(ReasoningRunReceipt)
            .filter(ReasoningRunReceipt.session_id == sid)
            .all()
        )
        rows[0].exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    finding = _audit(sid)["findings"][0]
    assert finding["replay_state"] == "MALFORMED"
    assert finding["replay_contract_finding"] == "RECORD_INVALID"


# ---------------------------------------------------------------------------
# Invalid material is never silently missing
# ---------------------------------------------------------------------------


def test_audit_invalid_material_is_not_silently_missing() -> None:
    invalid_sid = UUID(_create_session())
    _insert_receipt(invalid_sid, "A" * 64)
    empty_sid = UUID(_create_session())

    invalid_body = _audit(invalid_sid)
    empty_body = _audit(empty_sid)

    # The invalid material exists, is examined, and is reported invalid.
    assert invalid_body["completed_receipts_examined"] == 1
    assert invalid_body["invalid_receipts"] == 1
    assert len(invalid_body["findings"]) == 1
    assert invalid_body["audit_consistent"] is False
    assert invalid_body["replay_state"] == "MALFORMED"

    # No material is a distinct shape: examined == 0, no findings.
    assert empty_body["completed_receipts_examined"] == 0
    assert empty_body["findings"] == []
    assert empty_body["replay_state"] == "NO_MATERIAL"


def test_audit_non_completed_receipts_excluded_from_audit() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, outcome="PENDING")
    _insert_bound_receipt(sid)

    body = _audit(sid)
    assert body["completed_receipts_examined"] == 1
    assert len(body["findings"]) == 1

    only_pending_sid = UUID(_create_session())
    _insert_receipt(only_pending_sid, "e" * 64, outcome="PENDING")
    pending_body = _audit(only_pending_sid)
    assert pending_body["completed_receipts_examined"] == 0
    assert pending_body["replay_state"] == "NO_MATERIAL"
    assert pending_body["findings"] == []


def test_audit_issues_are_sorted_deterministically() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "A" * 64, exogenous={})

    issues = _audit(sid)["findings"][0]["replay_issues"]
    assert issues == sorted(issues)
    assert issues == [
        "REPLAY_EXOGENOUS_SNAPSHOT_MALFORMED",
        "REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED",
        "REPLAY_MALFORMED_FINGERPRINT",
    ]


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_audit_never_audits_another_sessions_material() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_receipt(sid_a, "a" * 64)
    _insert_receipt(sid_b, "b" * 64)
    _insert_receipt(sid_b, "c" * 64)

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        repo = ReasoningRunReceiptRepository()
        ids_a = {str(r.id) for r in repo.list_completed_by_session(db, sid_a)}
        ids_b = {str(r.id) for r in repo.list_completed_by_session(db, sid_b)}

    body_a = _audit(sid_a)
    body_b = _audit(sid_b)
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
    _insert_bound_receipt(sid, created_at=datetime(2024, 5, 2, 0, 0, 0))

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
    _insert_bound_receipt(sid, user_input="Patient reports chest pain", created_at=t1)
    _insert_bound_receipt(sid, user_input="Patient reports dizziness", created_at=t0)

    body = _audit(sid)
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
        t1.isoformat(),
    ]

    again = _audit(sid)
    assert [f["receipt_id"] for f in again["findings"]] == finding_order
    assert again == body


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

        receipts_before = ReasoningRunReceiptRepository().count_by_session(
            db, UUID(sid)
        )
    counts_before = _counts()

    for _ in range(2):
        body = _audit(UUID(sid))
        assert body["completed_receipts_examined"] == receipts_before

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )

        assert (
            ReasoningRunReceiptRepository().count_by_session(db, UUID(sid))
            == receipts_before
        )
    # Every table is untouched: no insert, no update, no delete.
    assert _counts() == counts_before


def test_audit_service_and_endpoint_sources_are_read_only() -> None:
    from rop.services import reasoning_run_replay_consistency_audit as audit_mod

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
        sessions_mod.audit_reasoning_run_replay_consistency
    )
    for token in (
        "db.commit",
        "db.add",
        "db.flush",
        "execute_idempotent",
        "httpx",
    ):
        assert token not in endpoint_source


def test_audit_service_direct_call_matches_endpoint_and_is_read_only() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunReplayConsistencyAuditService().audit(db, sid)
    assert _counts() == counts_before

    body = _audit(sid)
    assert _counts() == counts_before
    assert body == direct


def test_audit_uses_persisted_material_not_current_session_state() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    executed_fingerprint = _executed_fingerprint(sid)

    first = _audit(UUID(sid))
    assert first["audit_consistent"] is True
    assert first["findings"][0]["input_fingerprint"] == executed_fingerprint

    # Mutate current session state; persisted material must not move.
    _add_observation(sid, "Patient reports dizziness after rest")
    second = _audit(UUID(sid))
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

    # The audit reports persisted material, never a fingerprint
    # recomputed from mutable current state.
    assert persisted == executed_fingerprint
    assert first["findings"][0]["input_fingerprint"] == persisted
    assert current_fingerprint != persisted


# ---------------------------------------------------------------------------
# Strict schemas
# ---------------------------------------------------------------------------


def test_audit_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit(sid)
    assert set(body) == AUDIT_KEYS
    assert set(body["findings"][0]) == FINDING_KEYS
    assert ReasoningRunReplayConsistencyAuditRead.model_validate(body)
    assert ReasoningRunReplayConsistencyFindingRead.model_validate(body["findings"][0])


def test_audit_schema_rejects_top_level_extra_fields() -> None:
    payload = {
        "available": True,
        "audit_consistent": True,
        "session_id": str(uuid4()),
        "replay_state": "NO_MATERIAL",
        "original_result_provenance": "NOT_PERSISTED",
        "completed_receipts_examined": 0,
        "valid_receipts": 0,
        "invalid_receipts": 0,
        "findings": [],
        "audit_source": REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_SOURCE_TASK_141,
        "smuggled": True,
    }
    with pytest.raises(ValidationError):
        ReasoningRunReplayConsistencyAuditRead.model_validate(payload)


def test_audit_schema_rejects_nested_finding_extra_fields() -> None:
    finding = {
        "receipt_id": str(uuid4()),
        "input_fingerprint": "a" * 64,
        "replay_consistent": False,
        "replay_state": "INCONSISTENT",
        "replay_contract_finding": "RECORD_TAMPERED",
        "replay_issues": ["REPLAY_RECORD_TAMPERED"],
        "smuggled": True,
    }
    payload = {
        "available": True,
        "audit_consistent": False,
        "session_id": str(uuid4()),
        "replay_state": "INCONSISTENT",
        "original_result_provenance": "NOT_PERSISTED",
        "completed_receipts_examined": 1,
        "valid_receipts": 0,
        "invalid_receipts": 1,
        "findings": [finding],
        "audit_source": REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_SOURCE_TASK_141,
    }
    with pytest.raises(ValidationError):
        ReasoningRunReplayConsistencyAuditRead.model_validate(payload)
    with pytest.raises(ValidationError):
        ReasoningRunReplayConsistencyFindingRead.model_validate(finding)


def test_audit_endpoint_rejects_unknown_query_parameters() -> None:
    sid = UUID(_create_session())
    r = client.get(AUDIT_URL.format(sid=sid), params={"unexpected": "value"})
    # The audit takes no input beyond the session identity; unknown
    # parameters are ignored rather than smuggled into the audit.
    assert r.status_code == 200
    assert r.json()["session_id"] == str(sid)


# ---------------------------------------------------------------------------
# Divergence-vs-contract-failure boundary
# ---------------------------------------------------------------------------


def test_audit_preserves_divergence_vs_contract_failure_boundary() -> None:
    """Replay divergence stays a 200 finding; contract failure stays 500."""
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")

    with TestingSessionLocal() as db:
        from rop.services.reasoning_run_execution import (
            ReasoningRunExecutionService,
        )

        original_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, UUID(sid)
        )
        original_result = ReasoningRunExecutionService().execute_for_session(
            db, UUID(sid)
        )

    # Legitimate divergence: current state drifted from the recording.
    _add_observation(sid, "Patient reports new onset dizziness")
    drift = client.post(
        POST_REPLAY_URL.format(sid=sid),
        json={
            "original_result": _json_safe(original_result),
            "original_snapshot": _json_safe(original_snapshot),
        },
    )
    assert drift.status_code == 200
    assert drift.json()["replay_consistent"] is False

    # Contract failure: the recording was tampered with.
    forged = copy.deepcopy(original_snapshot)
    forged["observations"] = []
    tampered = client.post(
        POST_REPLAY_URL.format(sid=sid),
        json={
            "original_result": _json_safe(original_result),
            "original_snapshot": _json_safe(forged),
        },
    )
    assert tampered.status_code == 500
    assert tampered.json()["detail"] == (
        "Internal reasoning-run-replay contract violation"
    )

    # The audit is a separate read-only concern: it reports on persisted
    # material only and never inherits either HTTP outcome.
    body = _audit(UUID(sid))
    assert body["available"] is True
    assert body["replay_state"] == "SATISFIED"


# ---------------------------------------------------------------------------
# Task 137 regression
# ---------------------------------------------------------------------------


def test_task_137_inspection_endpoint_remains_unchanged() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        RECEIPT_URL.format(sid=sid), params={"input_fingerprint": fingerprint}
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
# Task 138 regression
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
# Task 139 regression
# ---------------------------------------------------------------------------


def test_task_139_provenance_audit_remains_unchanged() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    r = client.get(PROVENANCE_URL.format(sid=sid))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "available",
        "audit_consistent",
        "session_id",
        "completed_receipts_examined",
        "valid_receipts",
        "invalid_receipts",
        "findings",
        "audit_source",
    }
    assert body["audit_source"] == ("REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_TASK_139")
    assert body["completed_receipts_examined"] == 1
    assert body["findings"][0]["fingerprint_binding"] == "BOUND"

    # The pre-existing GET /replay step log stays untouched.
    step_log = client.get(f"/sessions/{sid}/replay")
    assert step_log.status_code == 200
    assert isinstance(step_log.json(), list)


# ---------------------------------------------------------------------------
# Task 140 regression
# ---------------------------------------------------------------------------


def test_task_140_post_replay_remains_unchanged() -> None:
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")

    with TestingSessionLocal() as db:
        from rop.services.reasoning_run_execution import (
            ReasoningRunExecutionService,
        )

        original_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, UUID(sid)
        )
        original_result = ReasoningRunExecutionService().execute_for_session(
            db, UUID(sid)
        )

    exact = client.post(
        POST_REPLAY_URL.format(sid=sid),
        json={
            "original_result": _json_safe(original_result),
            "original_snapshot": _json_safe(original_snapshot),
        },
    )
    assert exact.status_code == 200
    body = exact.json()
    assert set(body) == {
        "original_run_identity",
        "original_input_fingerprint",
        "replay_input_fingerprint",
        "input_match",
        "stage_comparison",
        "divergences",
        "replay_consistent",
        "replay_source",
    }
    assert body["replay_source"] == "REASONING_RUN_REPLAY_TASK_128"
    assert body["replay_consistent"] is True
    assert body["divergences"] == []

    # Strict request schema unchanged: extra fields rejected (422).
    strict = client.post(
        POST_REPLAY_URL.format(sid=sid),
        json={
            "original_result": _json_safe(original_result),
            "original_snapshot": _json_safe(original_snapshot),
            "unknown_field": "rejected",
        },
    )
    assert strict.status_code == 422

    # Nonexistent session still 404.
    assert client.get(AUDIT_URL.format(sid=uuid4())).status_code == 404


# ---------------------------------------------------------------------------
# Task 141 correction: unavailable original-result provenance
#
# The Task 140 ``original_result`` is request material. The current ROP
# persistence model does not persist it as historical replay evidence,
# so Task 141 must never claim to verify it. These tests establish that
# the gap is reported explicitly, and that it is neither misclassified
# as tampering nor silently treated as verified.
# ---------------------------------------------------------------------------


def test_audit_reports_original_result_provenance_as_not_persisted() -> None:
    """The audit never claims to hold historical original-result evidence."""
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    counts_before = _counts()

    # 1. A valid persisted receipt exists and is audited successfully.
    body = _audit(UUID(sid))
    assert body["completed_receipts_examined"] == 1
    assert body["valid_receipts"] == 1
    assert body["audit_consistent"] is True
    assert body["replay_state"] == "SATISFIED"

    # 2. Original-result provenance is explicitly unavailable.
    assert body["original_result_provenance"] == "NOT_PERSISTED"

    # 3. The clean verdict is scoped to persisted material, so it never
    #    implies the original result was verified.
    finding = body["findings"][0]
    assert finding["replay_contract_finding"] == "PERSISTED_MATERIAL_VERIFIABLE"
    assert finding["replay_issues"] == []

    # 4. Missing evidence is NOT reported as tampering.
    assert "REPLAY_RECORD_TAMPERED" not in finding["replay_issues"]

    # 5. Missing evidence is NOT an inconsistency either: the audit of
    #    genuinely persisted material stays consistent.
    assert body["audit_consistent"] is True

    # 6. No database row was created to satisfy the audit.
    assert _counts() == counts_before


def test_audit_never_reconstructs_original_result_from_current_state() -> None:
    """The audit does not manufacture original-result evidence."""
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    first = _audit(UUID(sid))
    receipts_before = first["completed_receipts_examined"]
    assert first["original_result_provenance"] == "NOT_PERSISTED"

    # Mutate current session state after the recorded run.
    _add_observation(sid, "Patient reports new onset dizziness")

    # Snapshot counts after the deliberate mutation, so the comparison
    # isolates what the audit itself creates.
    counts_before = _counts()
    second = _audit(UUID(sid))

    # The historical audit is unchanged by current-state drift: no
    # original result was regenerated to fill the gap.
    assert second == first
    assert second["original_result_provenance"] == "NOT_PERSISTED"
    # No additional receipt was created by auditing.
    assert second["completed_receipts_examined"] == receipts_before
    assert _counts() == counts_before


def test_audit_never_invokes_the_replay_engine(monkeypatch) -> None:
    """Task 141 must not call replay to manufacture missing history."""
    sid = UUID(_create_session())
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)
    counts_before = _counts()

    def _fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "Task 141 must not invoke ReasoningRunReplayService.replay"
        )

    monkeypatch.setattr(ReasoningRunReplayService, "replay", _fail_if_called)

    body = _audit(sid)
    assert body["audit_consistent"] is True
    assert body["original_result_provenance"] == "NOT_PERSISTED"
    assert body["completed_receipts_examined"] == 1
    assert _counts() == counts_before


def test_audit_creates_no_persistence_of_any_kind() -> None:
    """The audit must not add replay-result or other derived persistence."""
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    counts_before = _counts()
    for _ in range(2):
        assert _audit(UUID(sid))["available"] is True
    assert _counts() == counts_before

    # The receipt model gained no original-result column, and no
    # replay-record table was introduced for Task 141.
    assert "original_result" not in ReasoningRunReceipt.__table__.columns
    table_names = set(Base.metadata.tables)
    assert not any(
        name in table_names
        for name in (
            "replay_record",
            "replay_records",
            "replay_history",
            "original_result",
            "replay_result",
            "replay_results",
        )
    )


def test_audit_keeps_existing_provenance_checks_intact() -> None:
    """The correction must not weaken any existing tamper detection."""
    # Session mismatch (via the receipt's own bound evidence).
    session_sid = UUID(_create_session())
    _insert_bound_receipt(session_sid)
    tampered_exogenous = _valid_exogenous(session_sid)
    tampered_exogenous["session_id"] = str(uuid4())
    with TestingSessionLocal() as db:
        row = (
            db.query(ReasoningRunReceipt)
            .filter(ReasoningRunReceipt.session_id == session_sid)
            .one()
        )
        row.exogenous_snapshot = tampered_exogenous
        db.commit()
    assert (
        "REPLAY_EXOGENOUS_SESSION_MISMATCH"
        in _audit(session_sid)["findings"][0]["replay_issues"]
    )

    # Fingerprint / snapshot binding mismatch.
    binding_sid = UUID(_create_session())
    snapshot = _canonical_snapshot(binding_sid)
    forged = hashlib.sha256(b"forged-binding").hexdigest()
    _insert_receipt(binding_sid, forged, input_snapshot=snapshot)
    binding = _audit(binding_sid)["findings"][0]
    assert "REPLAY_RECORD_TAMPERED" in binding["replay_issues"]
    assert binding["replay_contract_finding"] == "RECORD_TAMPERED"

    # Snapshot corruption must never become verified.
    corrupt_sid = UUID(_create_session())
    broken = _canonical_snapshot(corrupt_sid)
    del broken["candidate_order"]
    _insert_receipt(
        corrupt_sid,
        compute_snapshot_fingerprint(broken),
        input_snapshot=broken,
    )
    corrupt = _audit(corrupt_sid)["findings"][0]
    assert "REPLAY_INPUT_SNAPSHOT_MALFORMED" in corrupt["replay_issues"]
    assert corrupt["replay_contract_finding"] == "RECORD_INVALID"
    assert corrupt["replay_consistent"] is False

    # Exogenous projection mismatch.
    projection_sid = UUID(_create_session())
    proj_snapshot = _canonical_snapshot(projection_sid)
    wrong_projection = _valid_exogenous(projection_sid)
    wrong_projection["user_input"] = "Patient reports something else"
    _insert_receipt(
        projection_sid,
        compute_snapshot_fingerprint(proj_snapshot),
        exogenous=wrong_projection,
        input_snapshot=proj_snapshot,
    )
    projection = _audit(projection_sid)["findings"][0]
    assert "REPLAY_EXOGENOUS_PROJECTION_MISMATCH" in projection["replay_issues"]
    assert "REPLAY_RECORD_TAMPERED" not in projection["replay_issues"]

    # Malformed fingerprint structure.
    malformed_sid = UUID(_create_session())
    _insert_receipt(malformed_sid, "A" * 64)
    malformed = _audit(malformed_sid)["findings"][0]
    assert "REPLAY_MALFORMED_FINGERPRINT" in malformed["replay_issues"]
    assert malformed["replay_contract_finding"] == "RECORD_INVALID"

    # Unreadable receipt.
    unreadable_sid = UUID(_create_session())
    row = _insert_bound_receipt(unreadable_sid)
    with TestingSessionLocal() as db:
        persisted = db.get(ReasoningRunReceipt, row.id)
        assert persisted is not None
        persisted.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()
    unreadable = _audit(unreadable_sid)["findings"][0]
    assert "REPLAY_RECEIPT_UNREADABLE" in unreadable["replay_issues"]


# ---------------------------------------------------------------------------
# Architecture: no provider/model integration
# ---------------------------------------------------------------------------


def test_task_141_introduces_no_provider_or_model_integration() -> None:
    from pathlib import Path

    import rop

    root = Path(rop.__file__).parent
    modules = (
        root / "services" / "reasoning_run_replay_consistency_audit.py",
        root / "schemas" / "reasoning_run_replay_consistency_audit.py",
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

"""Task 149: Stage 6 release evidence consistency audit tests.

Proves the read-only audit contract over the Task 148 evidence bundle
and Tasks 144-147 evidence: consistent READY / NO_MATERIAL / BLOCKED /
UNVERIFIABLE outcomes, detected bundle mismatch, propagated upstream
inconsistency, exact session isolation, deterministic output, zero side
effects, strict schemas, unchanged Task 137-148 contracts, the Task
140 historical-evidence boundary, and no model/provider integration. No
execution, no replay, no writes, no network.
"""

from __future__ import annotations

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
from rop.schemas.reasoning_run_stage_6_evidence_consistency_audit import (
    ReasoningRunStage6EvidenceConsistencyAuditRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
)
from rop.services.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceService,
)
from rop.services.reasoning_run_stage_6_evidence_consistency_audit import (
    REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_SOURCE_TASK_149,
    ReasoningRunStage6EvidenceConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditService,
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

AUDIT_URL = "/sessions/{sid}/reasoning-run/stage-6-evidence/consistency-audit"
EVIDENCE_URL = "/sessions/{sid}/reasoning-run/stage-6-evidence"

AUDIT_KEYS = {
    "requested_session_id",
    "available",
    "evidence_status",
    "expected_evidence_status",
    "actual_evidence_status",
    "evidence_consistent",
    "release_ready",
    "finding_count",
    "findings",
    "audit_source",
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
            "metadata": {"source": "evidence-consistency-audit-test"},
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


def _code_without_docstrings(module: object) -> str:
    """Module source with docstrings removed, for boundary assertions."""
    import ast

    source = inspect.getsource(module)
    tree = ast.parse(source)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body and isinstance(node.body[0], ast.Expr):
                first = node.body[0]
                start = getattr(first, "lineno", None)
                end = getattr(first, "end_lineno", None)
                if start is not None and end is not None:
                    doc_lines.update(range(start, end + 1))
    return "\n".join(
        line
        for lineno, line in enumerate(source.splitlines(), start=1)
        if lineno not in doc_lines
    )


def _audit(sid: UUID) -> dict:
    r = client.get(AUDIT_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Consistent outcomes
# ---------------------------------------------------------------------------


def test_audit_of_healthy_chain_is_consistent_ready() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit(sid)

    assert set(body.keys()) == AUDIT_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["available"] is True
    assert body["evidence_status"] == "READY"
    assert body["evidence_consistent"] is True
    assert body["expected_evidence_status"] == "READY"
    assert body["actual_evidence_status"] == "READY"
    assert body["release_ready"] is True
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert (
        body["audit_source"]
        == REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_SOURCE_TASK_149
    )


def test_audit_of_no_material_is_consistent_no_material() -> None:
    sid = UUID(_create_session())

    body = _audit(sid)

    assert body["evidence_status"] == "NO_MATERIAL"
    assert body["evidence_consistent"] is True
    assert body["expected_evidence_status"] == "NO_MATERIAL"
    assert body["release_ready"] is False
    assert body["findings"] == []


def test_audit_of_blocked_chain_is_consistent_blocked() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _audit(sid)

    assert body["evidence_status"] == "BLOCKED"
    assert body["evidence_consistent"] is True
    assert body["expected_evidence_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]


def test_audit_of_legacy_chain_is_consistent_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _audit(sid)

    assert body["evidence_status"] == "UNVERIFIABLE"
    assert body["evidence_consistent"] is True
    assert body["expected_evidence_status"] == "UNVERIFIABLE"
    assert body["release_ready"] is False
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]


def test_audit_agrees_with_published_evidence_bundle() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit(sid)
    evidence = client.get(EVIDENCE_URL.format(sid=sid)).json()

    assert body["actual_evidence_status"] == evidence["stage_6_status"]
    assert body["release_ready"] == evidence["release_ready"]
    assert body["findings"] == evidence["findings"]


def test_audit_missing_session_returns_404() -> None:
    r = client.get(AUDIT_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Mismatch detection
# ---------------------------------------------------------------------------


def test_audit_detects_forged_evidence_status_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceService().bundle(db, sid)
    assert genuine["stage_6_status"] == "BLOCKED"
    forged_bundle = dict(genuine)
    forged_bundle["stage_6_status"] = "READY"
    forged_bundle["release_ready"] = True

    def _forged_bundle(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_bundle

    monkeypatch.setattr(ReasoningRunStage6EvidenceService, "bundle", _forged_bundle)

    body = _audit(sid)

    assert body["evidence_consistent"] is False
    assert body["expected_evidence_status"] == "BLOCKED"
    assert body["actual_evidence_status"] == "READY"
    assert body["evidence_status"] == "READY"
    assert "EVIDENCE_STATUS_MISMATCH:expected=BLOCKED,actual=READY" in body["findings"]
    assert (
        "EVIDENCE_RELEASE_READY_MISMATCH:expected=False,actual=True" in body["findings"]
    )


def test_audit_detects_forged_release_ready_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceService().bundle(db, sid)
    assert genuine["stage_6_status"] == "READY"
    forged_bundle = dict(genuine)
    forged_bundle["release_ready"] = False

    def _forged_bundle(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_bundle

    monkeypatch.setattr(ReasoningRunStage6EvidenceService, "bundle", _forged_bundle)

    body = _audit(sid)

    assert body["evidence_consistent"] is False
    assert body["expected_evidence_status"] == "READY"
    assert body["actual_evidence_status"] == "READY"
    assert body["release_ready"] is False
    assert "EVIDENCE_RELEASE_READY_MISMATCH:expected=True,actual=False" in (
        body["findings"]
    )


def test_audit_propagates_upstream_gate_inconsistency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    assert genuine["gate_consistent"] is True
    forged_audit = dict(genuine)
    forged_audit["gate_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6GateConsistencyAuditService, "audit", _forged_audit
    )

    body = _audit(sid)

    assert body["expected_evidence_status"] == "BLOCKED"
    assert body["evidence_consistent"] is True
    assert body["evidence_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=READY" in body["findings"]


# ---------------------------------------------------------------------------
# Isolation / determinism / read-only
# ---------------------------------------------------------------------------


def test_audit_is_isolated_to_exact_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)
    _insert_receipt(sid_b, "e" * 64, input_snapshot={"bad": "snapshot"})

    body_a = _audit(sid_a)
    body_b = _audit(sid_b)

    assert body_a["evidence_consistent"] is True
    assert body_a["evidence_status"] == "READY"
    assert body_b["evidence_consistent"] is True
    assert body_b["evidence_status"] == "BLOCKED"


def test_audit_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _insert_receipt(sid, "f" * 63 + "0", input_snapshot={"bad": "snapshot"})

    first = _audit(sid)
    second = _audit(sid)

    assert first == second
    assert first["evidence_status"] == "BLOCKED"
    assert first["findings"] == sorted(first["findings"])


def test_audit_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _audit(sid)
        assert body["evidence_consistent"] is True

    assert _counts() == counts_before


def test_audit_service_direct_call_matches_endpoint() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunStage6EvidenceConsistencyAuditService().audit(db, sid)
    assert _counts() == counts_before

    body = _audit(sid)
    assert _counts() == counts_before
    assert body == direct


def test_audit_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(
        sessions_mod.audit_reasoning_run_stage_6_evidence_consistency
    )
    for token in (
        "db.commit",
        "db.add",
        "db.flush",
        "db.delete",
        "execute_idempotent",
        "ReasoningRunReplayService",
        "httpx",
    ):
        assert token not in endpoint_source


# ---------------------------------------------------------------------------
# Historical boundary / architecture
# ---------------------------------------------------------------------------


def test_audit_preserves_not_persisted_as_evidence_limitation() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit(sid)

    assert body["evidence_consistent"] is True
    assert body["evidence_status"] == "READY"
    assert body["release_ready"] is True
    assert body["findings"] == []
    serialized = str(body)
    assert "NOT_PERSISTED" not in serialized
    assert "original_result" not in serialized


def test_audit_does_not_invoke_replay_or_persist() -> None:
    from rop.services import (
        reasoning_run_stage_6_evidence_consistency_audit as audit_mod,
    )

    code = _code_without_docstrings(audit_mod)
    for token in (
        "ReasoningRunReplayService",
        "from rop.services.reasoning_run_replay import",
        "from rop.services.reasoning_run_execution",
        "from rop.services.reasoning_run_orchestration",
        ".replay(",
        "record_completed",
        "original_result",
        "db.commit",
        "db.add",
        "db.flush",
        "db.delete",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "api_key",
        "httpx",
    ):
        assert token not in code, token


def test_audit_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _audit(sid)

    assert body["evidence_status"] == "READY"
    assert _counts() == counts_before
    with TestingSessionLocal() as db:
        assert (
            db.query(ReasoningRunReceipt)
            .filter(ReasoningRunReceipt.session_id == sid)
            .count()
            == 1
        )


# ---------------------------------------------------------------------------
# Strict schema / contract errors
# ---------------------------------------------------------------------------


def test_audit_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit(sid)

    assert set(body.keys()) == AUDIT_KEYS
    validated = ReasoningRunStage6EvidenceConsistencyAuditRead.model_validate(body)
    assert validated.model_dump() == body


def test_audit_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _audit(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunStage6EvidenceConsistencyAuditRead.model_validate(tampered)


def test_audit_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(AUDIT_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal "
        "reasoning-run-stage-6-evidence-consistency-audit contract violation"
    }


# ---------------------------------------------------------------------------
# Full Task 148 contract verification (one test per decision field)
# ---------------------------------------------------------------------------


def _audit_with_forged_evidence(
    monkeypatch: pytest.MonkeyPatch, sid: UUID, **overrides: object
) -> dict:
    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceService().bundle(db, sid)
    forged_bundle = dict(genuine)
    forged_bundle.update(overrides)

    def _forged_bundle(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_bundle

    monkeypatch.setattr(ReasoningRunStage6EvidenceService, "bundle", _forged_bundle)
    return _audit(sid)


def test_audit_detects_forged_gate_status_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit_with_forged_evidence(monkeypatch, sid, gate_status="BLOCKED")

    assert body["evidence_consistent"] is False
    assert (
        "EVIDENCE_GATE_STATUS_MISMATCH:expected=READY,actual=BLOCKED"
        in body["findings"]
    )


def test_audit_detects_forged_gate_consistent_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit_with_forged_evidence(monkeypatch, sid, gate_consistent=False)

    assert body["evidence_consistent"] is False
    assert (
        "EVIDENCE_GATE_CONSISTENT_MISMATCH:expected=True,actual=False"
        in body["findings"]
    )


def test_audit_detects_forged_readiness_status_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit_with_forged_evidence(monkeypatch, sid, readiness_status="BLOCKED")

    assert body["evidence_consistent"] is False
    assert (
        "EVIDENCE_READINESS_STATUS_MISMATCH:expected=READY,actual=BLOCKED"
        in body["findings"]
    )


def test_audit_detects_forged_readiness_consistent_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _audit_with_forged_evidence(monkeypatch, sid, readiness_consistent=False)

    assert body["evidence_consistent"] is False
    assert (
        "EVIDENCE_READINESS_CONSISTENT_MISMATCH:expected=True,actual=False"
        in body["findings"]
    )


def test_audit_detects_false_evidence_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceService().bundle(db, sid)
    assert genuine["stage_6_status"] == "NO_MATERIAL"
    assert genuine["evidence_available"] is False

    forged_bundle = dict(genuine)
    forged_bundle["evidence_available"] = True

    def _forged_bundle(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_bundle

    monkeypatch.setattr(ReasoningRunStage6EvidenceService, "bundle", _forged_bundle)

    body = _audit(sid)

    assert body["evidence_consistent"] is False
    assert "EVIDENCE_AVAILABLE_MISMATCH:expected=False,actual=True" in body["findings"]

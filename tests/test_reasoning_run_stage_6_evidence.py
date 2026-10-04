"""Task 148: canonical Stage 6 release evidence bundle tests.

Proves the read-only evidence contract over Tasks 144-147: compact
evidence index with cross-surface consistency, release readiness never
reported when gate or readiness consistency fails, exact session
isolation, deterministic output, zero side effects, strict schemas,
unchanged Task 137-147 contracts, the Task 140 historical-evidence
boundary, and no model/provider integration. No execution, no replay,
no writes, no network.
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
from rop.schemas.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
)
from rop.services.reasoning_run_stage_6_evidence import (
    REASONING_RUN_STAGE_6_EVIDENCE_SOURCE_TASK_148,
    ReasoningRunStage6EvidenceService,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessService,
)
from rop.services.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditService,
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

EVIDENCE_URL = "/sessions/{sid}/reasoning-run/stage-6-evidence"
GATE_URL = "/sessions/{sid}/reasoning-run/stage-6-gate"
READINESS_URL = "/sessions/{sid}/reasoning-run/stage-6-readiness"

EVIDENCE_KEYS = {
    "requested_session_id",
    "evidence_available",
    "stage_6_status",
    "release_ready",
    "gate_status",
    "gate_consistent",
    "readiness_status",
    "readiness_consistent",
    "finding_count",
    "findings",
    "evidence_source",
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
            "metadata": {"source": "stage-6-evidence-test"},
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


def _evidence(sid: UUID) -> dict:
    r = client.get(EVIDENCE_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Evidence states
# ---------------------------------------------------------------------------


def test_evidence_of_healthy_material_is_available_ready() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _evidence(sid)

    assert set(body.keys()) == EVIDENCE_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["evidence_available"] is True
    assert body["stage_6_status"] == "READY"
    assert body["release_ready"] is True
    assert body["gate_status"] == "READY"
    assert body["gate_consistent"] is True
    assert body["readiness_status"] == "READY"
    assert body["readiness_consistent"] is True
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert body["evidence_source"] == REASONING_RUN_STAGE_6_EVIDENCE_SOURCE_TASK_148


def test_evidence_of_no_material_is_unavailable_no_material() -> None:
    sid = UUID(_create_session())

    body = _evidence(sid)

    assert body["evidence_available"] is False
    assert body["stage_6_status"] == "NO_MATERIAL"
    assert body["release_ready"] is False
    assert body["gate_status"] == "NO_MATERIAL"
    assert body["readiness_status"] == "NO_MATERIAL"
    assert body["findings"] == []


def test_evidence_of_tampered_material_is_blocked() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _evidence(sid)

    assert body["evidence_available"] is True
    assert body["stage_6_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]


def test_evidence_of_legacy_material_is_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _evidence(sid)

    assert body["evidence_available"] is True
    assert body["stage_6_status"] == "UNVERIFIABLE"
    assert body["release_ready"] is False
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]


def test_evidence_reflects_gate_and_readiness_consistency() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _evidence(sid)
    gate = client.get(GATE_URL.format(sid=sid)).json()
    readiness = client.get(READINESS_URL.format(sid=sid)).json()

    assert body["gate_status"] == gate["gate_status"]
    assert body["readiness_status"] == readiness["readiness_status"]
    assert body["findings"] == sorted(
        set(gate["findings"]) | set(readiness["findings"])
    )


def test_evidence_never_ready_when_gate_consistency_fails(
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

    body = _evidence(sid)

    assert body["gate_status"] == "READY"
    assert body["gate_consistent"] is False
    assert body["stage_6_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=READY" in body["findings"]


def test_evidence_never_ready_when_readiness_consistency_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReadinessConsistencyAuditService().audit(db, sid)
    assert genuine["readiness_consistent"] is True
    forged_audit = dict(genuine)
    forged_audit["readiness_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "READINESS_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6ReadinessConsistencyAuditService,
        "audit",
        _forged_audit,
    )

    body = _evidence(sid)

    assert body["readiness_status"] == "READY"
    assert body["readiness_consistent"] is False
    assert body["stage_6_status"] == "BLOCKED"
    assert body["release_ready"] is False


def test_evidence_missing_session_returns_404() -> None:
    r = client.get(EVIDENCE_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Isolation / determinism / read-only
# ---------------------------------------------------------------------------


def test_evidence_is_isolated_to_exact_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)
    _insert_receipt(sid_b, "e" * 64, input_snapshot={"bad": "snapshot"})

    body_a = _evidence(sid_a)
    body_b = _evidence(sid_b)

    assert body_a["stage_6_status"] == "READY"
    assert body_b["stage_6_status"] == "BLOCKED"
    assert "INPUT_SNAPSHOT_MALFORMED" in body_b["findings"]
    assert "INPUT_SNAPSHOT_MALFORMED" not in body_a["findings"]


def test_evidence_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _insert_receipt(sid, "f" * 63 + "0", input_snapshot={"bad": "snapshot"})

    first = _evidence(sid)
    second = _evidence(sid)

    assert first == second
    assert first["stage_6_status"] == "BLOCKED"
    assert first["findings"] == sorted(first["findings"])


def test_evidence_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _evidence(sid)
        assert body["stage_6_status"] == "READY"

    assert _counts() == counts_before


def test_evidence_service_direct_call_matches_endpoint() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunStage6EvidenceService().bundle(db, sid)
    assert _counts() == counts_before

    body = _evidence(sid)
    assert _counts() == counts_before
    assert body == direct


def test_evidence_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(
        sessions_mod.bundle_reasoning_run_stage_6_evidence
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


def test_evidence_preserves_not_persisted_as_evidence_limitation() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _evidence(sid)

    assert body["stage_6_status"] == "READY"
    assert body["release_ready"] is True
    assert body["findings"] == []
    serialized = str(body)
    assert "NOT_PERSISTED" not in serialized
    assert "original_result" not in serialized


def test_evidence_does_not_invoke_replay_or_persist() -> None:
    from rop.services import reasoning_run_stage_6_evidence as evidence_mod

    code = _code_without_docstrings(evidence_mod)
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


def test_evidence_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _evidence(sid)

    assert body["stage_6_status"] == "READY"
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


def test_evidence_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _evidence(sid)

    assert set(body.keys()) == EVIDENCE_KEYS
    validated = ReasoningRunStage6EvidenceRead.model_validate(body)
    assert validated.model_dump() == body


def test_evidence_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _evidence(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunStage6EvidenceRead.model_validate(tampered)


def test_evidence_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(EVIDENCE_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal reasoning-run-stage-6-evidence contract violation"
    }


# ---------------------------------------------------------------------------
# Upstream boolean/health invariants (no silent READY)
# ---------------------------------------------------------------------------


def test_evidence_blocked_when_gate_ready_flag_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateService().evaluate(db, sid)
    forged_gate = dict(genuine)
    forged_gate["ready"] = False

    def _forged_evaluate(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_gate

    monkeypatch.setattr(ReasoningRunStage6GateService, "evaluate", _forged_evaluate)

    body = _evidence(sid)

    assert body["stage_6_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "GATE_READY_INCOHERENT:status=READY,ready=False" in body["findings"]


def test_evidence_blocked_when_readiness_release_ready_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReadinessService().report(db, sid)
    forged_report = dict(genuine)
    forged_report["release_ready"] = False

    def _forged_report(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_report

    monkeypatch.setattr(ReasoningRunStage6ReadinessService, "report", _forged_report)

    body = _evidence(sid)

    assert body["stage_6_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert (
        "READINESS_RELEASE_READY_INCOHERENT:status=READY,release_ready=False"
        in body["findings"]
    )


def test_evidence_blocked_when_diagnostics_not_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateService().evaluate(db, sid)
    forged_gate = dict(genuine)
    forged_gate["diagnostics_status"] = "UNHEALTHY"

    def _forged_evaluate(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_gate

    monkeypatch.setattr(ReasoningRunStage6GateService, "evaluate", _forged_evaluate)

    body = _evidence(sid)

    assert body["stage_6_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "DIAGNOSTICS_NOT_HEALTHY:UNHEALTHY" in body["findings"]

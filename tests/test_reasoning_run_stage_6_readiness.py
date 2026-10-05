"""Task 146: canonical Stage 6 release readiness report tests.

Proves the read-only readiness contract over the Task 144 gate and
Task 145 gate consistency audit: READY requires a READY gate plus a
consistent audit plus no blocking contradiction; BLOCKED /
UNVERIFIABLE / NO_MATERIAL semantics; readiness never reported when
the gate audit disagrees; exact session isolation; deterministic
output; zero side effects; strict schemas; unchanged Task 137-145
contracts; the Task 140 historical-evidence boundary; and no
model/provider integration. No execution, no replay, no writes, no
network.
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
from rop.schemas.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_readiness import (
    REASONING_RUN_STAGE_6_READINESS_SOURCE_TASK_146,
    ReasoningRunStage6ReadinessService,
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

READINESS_URL = "/sessions/{sid}/reasoning-run/stage-6-readiness"
GATE_URL = "/sessions/{sid}/reasoning-run/stage-6-gate"
GATE_AUDIT_URL = "/sessions/{sid}/reasoning-run/stage-6-gate/consistency-audit"

READINESS_KEYS = {
    "requested_session_id",
    "readiness_status",
    "release_ready",
    "gate_status",
    "gate_consistent",
    "diagnostics_status",
    "finding_count",
    "findings",
    "readiness_source",
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
            "metadata": {"source": "stage-6-readiness-test"},
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


def _readiness(sid: UUID) -> dict:
    r = client.get(READINESS_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# READY / NO_MATERIAL / BLOCKED / UNVERIFIABLE / missing session
# ---------------------------------------------------------------------------


def test_readiness_of_healthy_material_is_ready() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _readiness(sid)

    assert set(body.keys()) == READINESS_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["readiness_status"] == "READY"
    assert body["release_ready"] is True
    assert body["gate_status"] == "READY"
    assert body["gate_consistent"] is True
    assert body["diagnostics_status"] == "HEALTHY"
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert body["readiness_source"] == REASONING_RUN_STAGE_6_READINESS_SOURCE_TASK_146


def test_readiness_of_no_material_is_no_material() -> None:
    sid = UUID(_create_session())

    body = _readiness(sid)

    assert body["readiness_status"] == "NO_MATERIAL"
    assert body["release_ready"] is False
    assert body["gate_status"] == "NO_MATERIAL"
    assert body["findings"] == []


def test_readiness_of_tampered_material_is_blocked() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _readiness(sid)

    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert body["gate_status"] == "BLOCKED"
    assert body["diagnostics_status"] == "UNHEALTHY"
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]


def test_readiness_of_legacy_material_is_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _readiness(sid)

    assert body["readiness_status"] == "UNVERIFIABLE"
    assert body["release_ready"] is False
    assert body["diagnostics_status"] == "DEGRADED"
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]


def test_readiness_missing_session_returns_404() -> None:
    r = client.get(READINESS_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


def test_readiness_agrees_with_gate_and_gate_audit() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _readiness(sid)
    gate = client.get(GATE_URL.format(sid=sid)).json()
    gate_audit = client.get(GATE_AUDIT_URL.format(sid=sid)).json()

    assert body["gate_status"] == gate["gate_status"]
    assert body["gate_consistent"] == gate_audit["gate_consistent"]
    assert body["diagnostics_status"] == gate["diagnostics_status"]
    assert body["findings"] == sorted(
        set(gate["findings"]) | set(gate_audit["findings"])
    )


def test_readiness_never_ready_when_gate_audit_disagrees(
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

    body = _readiness(sid)

    assert body["gate_status"] == "READY"
    assert body["gate_consistent"] is False
    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=READY" in body["findings"]


# ---------------------------------------------------------------------------
# Isolation / determinism / read-only
# ---------------------------------------------------------------------------


def test_readiness_is_isolated_to_exact_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)
    _insert_receipt(sid_b, "e" * 64, input_snapshot={"bad": "snapshot"})

    body_a = _readiness(sid_a)
    body_b = _readiness(sid_b)

    assert body_a["readiness_status"] == "READY"
    assert body_b["readiness_status"] == "BLOCKED"
    assert "INPUT_SNAPSHOT_MALFORMED" in body_b["findings"]
    assert "INPUT_SNAPSHOT_MALFORMED" not in body_a["findings"]


def test_readiness_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _insert_receipt(sid, "f" * 63 + "0", input_snapshot={"bad": "snapshot"})

    first = _readiness(sid)
    second = _readiness(sid)

    assert first == second
    assert first["readiness_status"] == "BLOCKED"
    assert first["findings"] == sorted(first["findings"])


def test_readiness_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _readiness(sid)
        assert body["readiness_status"] == "READY"

    assert _counts() == counts_before


def test_readiness_service_direct_call_matches_endpoint() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunStage6ReadinessService().report(db, sid)
    assert _counts() == counts_before

    body = _readiness(sid)
    assert _counts() == counts_before
    assert body == direct


def test_readiness_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(
        sessions_mod.report_reasoning_run_stage_6_readiness
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


def test_readiness_preserves_not_persisted_as_evidence_limitation() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _readiness(sid)

    assert body["readiness_status"] == "READY"
    assert body["release_ready"] is True
    assert body["findings"] == []
    serialized = str(body)
    assert "NOT_PERSISTED" not in serialized
    assert "original_result" not in serialized


def test_readiness_does_not_invoke_replay_or_persist() -> None:
    from rop.services import reasoning_run_stage_6_readiness as readiness_mod

    code = _code_without_docstrings(readiness_mod)
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


def test_readiness_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _readiness(sid)

    assert body["readiness_status"] == "READY"
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


def test_readiness_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _readiness(sid)

    assert set(body.keys()) == READINESS_KEYS
    validated = ReasoningRunStage6ReadinessRead.model_validate(body)
    assert validated.model_dump() == body


def test_readiness_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _readiness(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunStage6ReadinessRead.model_validate(tampered)


def test_readiness_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(READINESS_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal reasoning-run-stage-6-readiness contract violation"
    }


# ---------------------------------------------------------------------------
# Complete readiness contract: status/boolean coherence
# ---------------------------------------------------------------------------


def _readiness_with_forged_gate(
    monkeypatch: pytest.MonkeyPatch, sid: UUID, **overrides: object
) -> dict:
    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateService().evaluate(db, sid)
    forged_gate = dict(genuine)
    forged_gate.update(overrides)

    def _forged_evaluate(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_gate

    monkeypatch.setattr(ReasoningRunStage6GateService, "evaluate", _forged_evaluate)
    r = client.get(READINESS_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


def _readiness_with_forged_gate_audit(
    monkeypatch: pytest.MonkeyPatch, sid: UUID, **overrides: object
) -> dict:
    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    forged_audit = dict(genuine)
    forged_audit.update(overrides)

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6GateConsistencyAuditService, "audit", _forged_audit
    )
    r = client.get(READINESS_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


def test_readiness_status_and_release_ready_agree_in_all_states() -> None:
    cases = [
        ("Patient reports chest pain", "READY", True),
        ("Patient reports dizziness", "READY", True),
    ]
    for user_input, status, release_ready in cases:
        sid = UUID(_create_session(user_input=user_input))
        _insert_bound_receipt(sid, user_input=user_input)
        body = _readiness(sid)
        assert body["readiness_status"] == status
        assert body["release_ready"] is release_ready

    tampered_sid = UUID(_create_session())
    snapshot = _canonical_snapshot(tampered_sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(tampered_sid, forged, input_snapshot=snapshot)
    tampered = _readiness(tampered_sid)
    assert tampered["readiness_status"] == "BLOCKED"
    assert tampered["release_ready"] is False
    assert tampered["diagnostics_status"] == "UNHEALTHY"

    legacy_sid = UUID(_create_session())
    _insert_receipt(legacy_sid, "c" * 64, input_snapshot=None)
    legacy = _readiness(legacy_sid)
    assert legacy["readiness_status"] == "UNVERIFIABLE"
    assert legacy["release_ready"] is False
    assert legacy["diagnostics_status"] == "DEGRADED"

    empty_sid = UUID(_create_session())
    empty = _readiness(empty_sid)
    assert empty["readiness_status"] == "NO_MATERIAL"
    assert empty["release_ready"] is False


def test_readiness_blocked_when_gate_ready_flag_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _readiness_with_forged_gate(monkeypatch, sid, ready=False)

    assert body["gate_status"] == "READY"
    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "GATE_READY_INCOHERENT:status=READY,ready=False" in body["findings"]


# ---------------------------------------------------------------------------
# Precedence: a genuine Task 145 contradiction outranks NO_MATERIAL
# ---------------------------------------------------------------------------


def test_readiness_of_no_material_with_inconsistent_gate_audit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact defect: NO_MATERIAL must never hide a Task 145 contradiction."""
    sid = UUID(_create_session())
    with TestingSessionLocal() as db:
        genuine_audit = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    assert genuine_audit["gate_consistent"] is True
    contradiction = "GATE_STATUS_MISMATCH:expected=NO_MATERIAL,actual=READY"
    forged_findings = list(genuine_audit["findings"]) + [contradiction]

    body = _readiness_with_forged_gate_audit(
        monkeypatch,
        sid,
        gate_consistent=False,
        findings=forged_findings,
        finding_count=len(forged_findings),
    )

    assert body["gate_status"] == "NO_MATERIAL"
    assert body["gate_consistent"] is False
    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert contradiction in body["findings"]


def test_readiness_of_no_material_with_coherent_gate_audit_is_no_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: the legitimate empty-session verdict survives interception."""
    sid = UUID(_create_session())

    body = _readiness_with_forged_gate_audit(monkeypatch, sid)

    assert body["gate_status"] == "NO_MATERIAL"
    assert body["gate_consistent"] is True
    assert body["readiness_status"] == "NO_MATERIAL"
    assert body["release_ready"] is False
    assert body["findings"] == []


def test_readiness_of_blocked_gate_with_inconsistent_audit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged_fp = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged_fp, input_snapshot=snapshot)
    contradiction = "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    forged_findings = [contradiction]

    body = _readiness_with_forged_gate_audit(
        monkeypatch,
        sid,
        gate_consistent=False,
        findings=forged_findings,
        finding_count=len(forged_findings),
    )

    assert body["gate_status"] == "BLOCKED"
    assert body["gate_consistent"] is False
    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False


def test_readiness_of_unverifiable_gate_with_inconsistent_audit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stronger contradiction must not be weakened to UNVERIFIABLE."""
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)
    contradiction = "GATE_DIAGNOSTICS_MISMATCH:expected=DEGRADED,actual=HEALTHY"
    forged_findings = [contradiction]

    body = _readiness_with_forged_gate_audit(
        monkeypatch,
        sid,
        gate_consistent=False,
        findings=forged_findings,
        finding_count=len(forged_findings),
    )

    assert body["gate_status"] == "UNVERIFIABLE"
    assert body["gate_consistent"] is False
    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert contradiction in body["findings"]


def test_readiness_of_ready_gate_with_degraded_diagnostics_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READY + DEGRADED diagnostics demotes to UNVERIFIABLE once Task 145
    is coherent. The coherent audit is captured before the gate is
    forged because the genuine Task 145 audit re-evaluates the gate and
    would (correctly) flag the forgery -- that stronger-contradiction
    path is the subject of the next test."""
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine_gate = ReasoningRunStage6GateService().evaluate(db, sid)
        coherent_audit = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    assert coherent_audit["gate_consistent"] is True
    forged_gate = dict(genuine_gate)
    forged_gate["diagnostics_status"] = "DEGRADED"

    def _forged_evaluate(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_gate

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return coherent_audit

    monkeypatch.setattr(ReasoningRunStage6GateService, "evaluate", _forged_evaluate)
    monkeypatch.setattr(
        ReasoningRunStage6GateConsistencyAuditService, "audit", _forged_audit
    )

    body = _readiness(sid)

    assert body["gate_status"] == "READY"
    assert body["gate_consistent"] is True
    assert body["diagnostics_status"] == "DEGRADED"
    assert body["readiness_status"] == "UNVERIFIABLE"
    assert body["release_ready"] is False


def test_readiness_of_ready_gate_with_degraded_diagnostics_and_inconsistent_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degraded diagnostics never weaken a genuine Task 145 contradiction.

    The gate alone is forged; the Task 145 audit then runs genuinely
    over the forged gate and itself reports the gate inconsistent --
    the exact contradiction the readiness precedence must not hide.
    """
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine_gate = ReasoningRunStage6GateService().evaluate(db, sid)
    forged_gate = dict(genuine_gate)
    forged_gate["diagnostics_status"] = "DEGRADED"

    def _forged_evaluate(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_gate

    monkeypatch.setattr(ReasoningRunStage6GateService, "evaluate", _forged_evaluate)

    with TestingSessionLocal() as db:
        genuine_audit = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    assert genuine_audit["gate_consistent"] is False

    body = _readiness(sid)

    assert body["gate_status"] == "READY"
    assert body["diagnostics_status"] == "DEGRADED"
    assert body["gate_consistent"] is False
    assert body["readiness_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert body["findings"] == sorted(
        set(forged_gate["findings"]) | set(genuine_audit["findings"])
    )


def test_readiness_inherits_gate_findings_deterministically() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _readiness(sid)
    gate = client.get(GATE_URL.format(sid=sid)).json()

    assert set(gate["findings"]) <= set(body["findings"])
    assert body["findings"] == sorted(body["findings"])

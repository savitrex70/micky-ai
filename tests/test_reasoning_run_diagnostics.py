"""Task 143: Stage 6 operational diagnostics boundary tests.

Proves the read-only diagnostics contract over the existing Task 142
unified inspection bundle: exact session identity, coarse deterministic
statuses, preserved findings, the Task 140 historical-evidence boundary
(NOT_PERSISTED never drives a status), deterministic output, zero side
effects, strict schemas, unchanged Task 137-142 contracts, and no
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
from rop.schemas.reasoning_run_diagnostics import ReasoningRunDiagnosticsRead
from rop.services.reasoning_run_diagnostics import (
    REASONING_RUN_DIAGNOSTICS_SOURCE_TASK_143,
    ReasoningRunDiagnosticsService,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
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

DIAGNOSTICS_URL = "/sessions/{sid}/reasoning-run/diagnostics"
INSPECTION_URL = "/sessions/{sid}/reasoning-run/inspection"

DIAGNOSTICS_KEYS = {
    "requested_session_id",
    "session_exists",
    "completed_receipts",
    "inspection_status",
    "provenance_status",
    "replay_consistency_status",
    "finding_count",
    "findings",
    "diagnostics_source",
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
            "metadata": {"source": "diagnostics-boundary-test"},
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


def _diagnose(sid: UUID) -> dict:
    r = client.get(DIAGNOSTICS_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Healthy material / empty material / missing session
# ---------------------------------------------------------------------------


def test_diagnostics_of_healthy_material_reports_consistent_statuses() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _diagnose(sid)

    assert set(body.keys()) == DIAGNOSTICS_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["session_exists"] is True
    assert body["completed_receipts"] == 1
    assert body["inspection_status"] == "VERIFIABLE"
    assert body["provenance_status"] == "CONSISTENT"
    assert body["replay_consistency_status"] == "CONSISTENT"
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert body["diagnostics_source"] == REASONING_RUN_DIAGNOSTICS_SOURCE_TASK_143


def test_diagnostics_of_session_with_no_material() -> None:
    sid = UUID(_create_session())

    body = _diagnose(sid)

    assert body["requested_session_id"] == str(sid)
    assert body["session_exists"] is True
    assert body["completed_receipts"] == 0
    assert body["inspection_status"] == "NO_MATERIAL"
    assert body["provenance_status"] == "NO_MATERIAL"
    assert body["replay_consistency_status"] == "NO_MATERIAL"
    assert body["finding_count"] == 0
    assert body["findings"] == []


def test_diagnostics_of_missing_session_returns_404() -> None:
    r = client.get(DIAGNOSTICS_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Inconsistent / unverifiable material
# ---------------------------------------------------------------------------


def test_diagnostics_of_tampered_material_reports_inconsistent() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _diagnose(sid)

    assert body["completed_receipts"] == 1
    assert body["inspection_status"] == "INCONSISTENT"
    assert body["provenance_status"] == "INCONSISTENT"
    assert body["replay_consistency_status"] == "INCONSISTENT"
    assert body["finding_count"] == len(body["findings"])
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]
    assert "FINGERPRINT_PROVENANCE_MISMATCH" in body["findings"]
    assert body["findings"] == sorted(body["findings"])


def test_diagnostics_of_legacy_material_reports_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _diagnose(sid)

    assert body["completed_receipts"] == 1
    assert body["inspection_status"] == "UNVERIFIABLE"
    assert body["provenance_status"] == "UNVERIFIABLE"
    assert body["replay_consistency_status"] == "UNVERIFIABLE"
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]


def test_diagnostics_matches_task_142_bundle_statuses() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid, user_input="Patient reports chest pain")
    _insert_bound_receipt(sid, user_input="Patient reports dizziness")

    body = _diagnose(sid)
    bundle = client.get(INSPECTION_URL.format(sid=sid)).json()

    assert body["completed_receipts"] == len(bundle["receipt_history"]["receipts"])
    assert body["inspection_status"] == bundle["overall_status"]
    assert body["findings"] == bundle["findings"]
    assert body["finding_count"] == len(bundle["findings"])


# ---------------------------------------------------------------------------
# Session isolation / determinism / read-only
# ---------------------------------------------------------------------------


def test_diagnostics_is_isolated_to_exact_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)
    _insert_receipt(sid_b, "e" * 64, input_snapshot={"bad": "snapshot"})

    body_a = _diagnose(sid_a)
    body_b = _diagnose(sid_b)

    assert body_a["inspection_status"] == "VERIFIABLE"
    assert body_a["completed_receipts"] == 1
    assert body_b["inspection_status"] == "INCONSISTENT"
    assert body_b["completed_receipts"] == 1
    assert "INPUT_SNAPSHOT_MALFORMED" in body_b["findings"]
    assert "INPUT_SNAPSHOT_MALFORMED" not in body_a["findings"]


def test_diagnostics_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _insert_receipt(sid, "f" * 63 + "0", input_snapshot={"bad": "snapshot"})

    first = _diagnose(sid)
    second = _diagnose(sid)

    assert first == second
    assert first["inspection_status"] == "INCONSISTENT"
    assert first["findings"] == sorted(first["findings"])


def test_diagnostics_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _diagnose(sid)
        assert body["inspection_status"] == "VERIFIABLE"

    assert _counts() == counts_before


def test_diagnostics_service_direct_call_matches_endpoint() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunDiagnosticsService().diagnose(db, sid)
    assert _counts() == counts_before

    body = _diagnose(sid)
    assert _counts() == counts_before
    assert body == direct


def test_diagnostics_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(sessions_mod.diagnose_reasoning_run)
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


def test_diagnostics_preserves_not_persisted_as_evidence_limitation() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _diagnose(sid)

    assert body["inspection_status"] == "VERIFIABLE"
    assert body["provenance_status"] == "CONSISTENT"
    assert body["replay_consistency_status"] == "CONSISTENT"
    assert body["findings"] == []
    serialized = str(body)
    assert "NOT_PERSISTED" not in serialized
    assert "original_result" not in serialized


def test_diagnostics_does_not_invoke_replay_or_persist() -> None:
    from rop.services import reasoning_run_diagnostics as diagnostics_mod

    code = _code_without_docstrings(diagnostics_mod)
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


def test_diagnostics_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _diagnose(sid)

    assert body["completed_receipts"] == 1
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


def test_diagnostics_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _diagnose(sid)

    assert set(body.keys()) == DIAGNOSTICS_KEYS
    validated = ReasoningRunDiagnosticsRead.model_validate(body)
    assert validated.model_dump() == body


def test_diagnostics_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _diagnose(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunDiagnosticsRead.model_validate(tampered)


def test_diagnostics_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(DIAGNOSTICS_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal reasoning-run-diagnostics contract violation"
    }

"""Task 142: unified deterministic reasoning-run inspection bundle tests.

Proves the read-only aggregation contract over the existing Task 137
(receipt inspection), Task 138 (receipt history), Task 139 (provenance
audit), and Task 141 (replay consistency audit) surfaces: exact session
identity, all inspection sections present, deterministic overall status
(NO_MATERIAL / VERIFIABLE / INCONSISTENT / UNVERIFIABLE), preserved
underlying findings, the Task 140 historical-evidence boundary
(original_result never reconstructed, replay engine never invoked,
nothing persisted, NOT_PERSISTED never reported as tampering),
deterministic output, zero side effects, strict schemas, unchanged
Task 137-141 contracts, and no model/provider integration. No
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
from rop.schemas.reasoning_run_inspection import ReasoningRunInspectionRead
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
)
from rop.services.reasoning_run_inspection import (
    REASONING_RUN_INSPECTION_SOURCE_TASK_142,
    ReasoningRunInspectionService,
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

INSPECTION_URL = "/sessions/{sid}/reasoning-run/inspection"

BUNDLE_KEYS = {
    "requested_session_id",
    "receipt_inspections",
    "receipt_history",
    "provenance_audit",
    "replay_consistency_audit",
    "overall_status",
    "findings",
    "inspection_source",
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
            "metadata": {"source": "inspection-bundle-test"},
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


def _inspect(sid: UUID) -> dict:
    r = client.get(INSPECTION_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Basic API
# ---------------------------------------------------------------------------


def test_inspection_of_session_with_valid_material_returns_unified_bundle() -> None:
    sid = UUID(_create_session())
    receipt = _insert_bound_receipt(sid)

    body = _inspect(sid)

    assert set(body.keys()) == BUNDLE_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["inspection_source"] == REASONING_RUN_INSPECTION_SOURCE_TASK_142
    assert len(body["receipt_inspections"]) == 1
    inspection = body["receipt_inspections"][0]
    assert inspection["found"] is True
    assert inspection["requested_session_id"] == str(sid)
    assert inspection["requested_input_fingerprint"] == receipt.input_fingerprint
    assert inspection["receipt"]["id"] == str(receipt.id)
    assert body["receipt_history"]["session_id"] == str(sid)
    assert len(body["receipt_history"]["receipts"]) == 1
    assert body["provenance_audit"]["session_id"] == str(sid)
    assert body["replay_consistency_audit"]["session_id"] == str(sid)


def test_inspection_of_session_with_no_material_is_no_material() -> None:
    sid = UUID(_create_session())

    body = _inspect(sid)

    assert body["requested_session_id"] == str(sid)
    assert body["overall_status"] == "NO_MATERIAL"
    assert body["findings"] == []
    assert body["receipt_inspections"] == []
    assert body["receipt_history"]["receipts"] == []
    assert body["provenance_audit"]["completed_receipts_examined"] == 0
    assert body["provenance_audit"]["audit_consistent"] is True
    assert body["replay_consistency_audit"]["completed_receipts_examined"] == 0
    assert body["replay_consistency_audit"]["replay_state"] == "NO_MATERIAL"


def test_inspection_of_missing_session_returns_404() -> None:
    r = client.get(INSPECTION_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Valid material
# ---------------------------------------------------------------------------


def test_inspection_of_valid_material_is_verifiable() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _inspect(sid)

    assert body["overall_status"] == "VERIFIABLE"
    assert body["findings"] == []
    assert body["provenance_audit"]["audit_consistent"] is True
    assert body["replay_consistency_audit"]["audit_consistent"] is True
    assert body["replay_consistency_audit"]["replay_state"] == "SATISFIED"


# ---------------------------------------------------------------------------
# Tampered / inconsistent material: findings are preserved
# ---------------------------------------------------------------------------


def test_inspection_preserves_session_mismatch_as_inconsistent() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        tampered = _valid_exogenous(sid)
        tampered["session_id"] = str(uuid4())
        row.exogenous_snapshot = tampered
        db.commit()

    body = _inspect(sid)

    assert body["overall_status"] == "INCONSISTENT"
    assert "REPLAY_EXOGENOUS_SESSION_MISMATCH" in body["findings"]
    assert "EXOGENOUS_SESSION_MISMATCH" in body["findings"]
    assert body["findings"] == sorted(body["findings"])


def test_inspection_preserves_malformed_fingerprint_as_inconsistent() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    _insert_receipt(sid, "not-a-fingerprint", input_snapshot=snapshot)

    body = _inspect(sid)

    assert body["overall_status"] == "INCONSISTENT"
    assert "REPLAY_MALFORMED_FINGERPRINT" in body["findings"]
    assert "MALFORMED_FINGERPRINT" in body["findings"]


def test_inspection_preserves_fingerprint_snapshot_mismatch_as_inconsistent() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _inspect(sid)

    assert body["overall_status"] == "INCONSISTENT"
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]
    assert "FINGERPRINT_PROVENANCE_MISMATCH" in body["findings"]


def test_inspection_preserves_malformed_snapshot_as_inconsistent() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "b" * 64, input_snapshot={"not": "a-snapshot"})

    body = _inspect(sid)

    assert body["overall_status"] == "INCONSISTENT"
    assert "REPLAY_INPUT_SNAPSHOT_MALFORMED" in body["findings"]
    assert "INPUT_SNAPSHOT_MALFORMED" in body["findings"]


def test_inspection_preserves_exogenous_projection_mismatch_as_inconsistent() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    fingerprint = compute_snapshot_fingerprint(snapshot)
    tampered_exogenous = _valid_exogenous(sid)
    tampered_exogenous["user_input"] = "Patient reports something else"
    _insert_receipt(
        sid, fingerprint, exogenous=tampered_exogenous, input_snapshot=snapshot
    )

    body = _inspect(sid)

    assert body["overall_status"] == "INCONSISTENT"
    assert "REPLAY_EXOGENOUS_PROJECTION_MISMATCH" in body["findings"]
    assert "EXOGENOUS_PROJECTION_MISMATCH" in body["findings"]


def test_inspection_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(INSPECTION_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal reasoning-run-inspection contract violation"
    }


def test_inspection_non_completed_outcome_is_no_material_not_inconsistent() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "d" * 64, outcome="PENDING")

    body = _inspect(sid)

    assert body["overall_status"] == "NO_MATERIAL"
    assert body["findings"] == []


def test_inspection_legacy_receipt_without_binding_evidence_is_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _inspect(sid)

    assert body["overall_status"] == "UNVERIFIABLE"
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED" in body["findings"]
    # An evidence gap is never reported as tampering.
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]
    assert "FINGERPRINT_PROVENANCE_MISMATCH" not in body["findings"]


# ---------------------------------------------------------------------------
# Historical replay-result boundary
# ---------------------------------------------------------------------------


def test_inspection_preserves_not_persisted_provenance_without_tampering() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _inspect(sid)

    assert (
        body["replay_consistency_audit"]["original_result_provenance"]
        == "NOT_PERSISTED"
    )
    # The architectural gap never drives the bundle verdict.
    assert body["overall_status"] == "VERIFIABLE"
    assert body["findings"] == []
    # No original replay result is reconstructed anywhere in the bundle.
    serialized = str(body)
    assert "original_result" not in serialized.replace("original_result_provenance", "")


def test_inspection_does_not_reconstruct_original_result_or_call_replay() -> None:
    from rop.services import reasoning_run_inspection as inspection_mod

    code = _code_without_docstrings(inspection_mod)
    for token in (
        "ReasoningRunReplayService",
        "from rop.services.reasoning_run_replay import",
        "from rop.services.reasoning_run_execution",
        "from rop.services.reasoning_run_orchestration",
        ".replay(",
        "record_completed",
        "original_result_provenance",
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


def test_inspection_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _inspect(sid)

    assert body["overall_status"] == "VERIFIABLE"
    assert _counts() == counts_before
    with TestingSessionLocal() as db:
        assert (
            db.query(ReasoningRunReceipt)
            .filter(ReasoningRunReceipt.session_id == sid)
            .count()
            == 1
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_inspection_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid, user_input="Patient reports chest pain")
    _insert_bound_receipt(sid, user_input="Patient reports dizziness")

    first = _inspect(sid)
    second = _inspect(sid)

    assert first == second
    assert first["findings"] == sorted(first["findings"])
    # Inspection order follows deterministic history order exactly.
    assert [
        item["requested_input_fingerprint"] for item in first["receipt_inspections"]
    ] == [item["input_fingerprint"] for item in first["receipt_history"]["receipts"]]


def test_inspection_findings_order_is_stable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "not-a-fingerprint", input_snapshot={"bad": "snapshot"})

    first = _inspect(sid)
    second = _inspect(sid)

    assert first["findings"] == second["findings"] == sorted(first["findings"])
    assert first["overall_status"] == "INCONSISTENT"


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def test_inspection_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _inspect(sid)
        assert body["overall_status"] == "VERIFIABLE"

    assert _counts() == counts_before


def test_inspection_service_direct_call_matches_endpoint_and_is_read_only() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunInspectionService().inspect(db, sid)
    assert _counts() == counts_before

    body = _inspect(sid)
    assert _counts() == counts_before
    assert body == direct


def test_inspection_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(sessions_mod.inspect_reasoning_run)
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
# Strict schema
# ---------------------------------------------------------------------------


def test_inspection_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _inspect(sid)

    assert set(body.keys()) == BUNDLE_KEYS
    validated = ReasoningRunInspectionRead.model_validate(body)
    assert validated.model_dump() == body


def test_inspection_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _inspect(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunInspectionRead.model_validate(tampered)

    nested = dict(body["provenance_audit"])
    nested["unexpected_nested"] = "boom"
    tampered_nested = dict(body)
    tampered_nested["provenance_audit"] = nested
    with pytest.raises(ValidationError):
        ReasoningRunInspectionRead.model_validate(tampered_nested)

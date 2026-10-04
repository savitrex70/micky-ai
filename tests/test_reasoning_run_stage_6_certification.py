"""Task 152: final Stage 6 deterministic release certification tests.

Proves the read-only certification contract over the canonical Stage 6
chain (Tasks 144-151): CERTIFIED only when every invariant holds, each
upstream failure independently preventing certification, exact session
isolation, deterministic output, zero side effects, strict schemas,
unchanged Task 137-151 contracts, the Task 140 historical-evidence
boundary, no model/provider integration, and no Stage 7. No execution,
no replay, no writes, no network.
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
from rop.schemas.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
)
from rop.services.reasoning_run_stage_6_certification import (
    REASONING_RUN_STAGE_6_CERTIFICATION_SOURCE_TASK_152,
    ReasoningRunStage6CertificationService,
)
from rop.services.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceService,
)
from rop.services.reasoning_run_stage_6_evidence_consistency_audit import (
    ReasoningRunStage6EvidenceConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_manifest_consistency_audit import (
    ReasoningRunStage6ManifestConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessService,
)
from rop.services.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_release_manifest import (
    ReasoningRunStage6ReleaseManifestService,
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

CERTIFICATION_URL = "/sessions/{sid}/reasoning-run/stage-6-certification"

CERTIFICATION_KEYS = {
    "requested_session_id",
    "certification_status",
    "certified",
    "release_ready",
    "gate_status",
    "gate_consistent",
    "readiness_status",
    "readiness_consistent",
    "evidence_status",
    "evidence_consistent",
    "manifest_status",
    "manifest_consistent",
    "finding_count",
    "findings",
    "certification_source",
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
            "metadata": {"source": "stage-6-certification-test"},
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


def _certify(sid: UUID) -> dict:
    r = client.get(CERTIFICATION_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# CERTIFIED / NO_MATERIAL / BLOCKED / UNVERIFIABLE / missing session
# ---------------------------------------------------------------------------


def test_certification_of_healthy_chain_is_certified() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _certify(sid)

    assert set(body.keys()) == CERTIFICATION_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["certification_status"] == "CERTIFIED"
    assert body["certified"] is True
    assert body["release_ready"] is True
    assert body["gate_status"] == "READY"
    assert body["gate_consistent"] is True
    assert body["readiness_status"] == "READY"
    assert body["readiness_consistent"] is True
    assert body["evidence_status"] == "READY"
    assert body["evidence_consistent"] is True
    assert body["manifest_status"] == "READY"
    assert body["manifest_consistent"] is True
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert (
        body["certification_source"]
        == REASONING_RUN_STAGE_6_CERTIFICATION_SOURCE_TASK_152
    )


def test_certification_of_no_material_is_no_material() -> None:
    sid = UUID(_create_session())

    body = _certify(sid)

    assert body["certification_status"] == "NO_MATERIAL"
    assert body["certified"] is False
    assert body["release_ready"] is False
    assert body["findings"] == []


def test_certification_of_contradiction_is_blocked() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert body["release_ready"] is False
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]


def test_certification_of_insufficient_evidence_is_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _certify(sid)

    assert body["certification_status"] == "UNVERIFIABLE"
    assert body["certified"] is False
    assert body["release_ready"] is False
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]


def test_certification_missing_session_returns_404() -> None:
    r = client.get(CERTIFICATION_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Every invariant is enforced
# ---------------------------------------------------------------------------


def _forged_service_result(
    monkeypatch: pytest.MonkeyPatch,
    service_cls: type,
    method: str,
    session_id: UUID,
    key: str,
    value: object,
) -> None:
    with TestingSessionLocal() as db:
        genuine = getattr(service_cls(), method)(db, session_id)
    forged_result = dict(genuine)
    forged_result[key] = value

    def _forged(self: object, db: Session, sid: UUID) -> dict:
        _ = (self, db, sid)
        return forged_result

    monkeypatch.setattr(service_cls, method, _forged)


def test_gate_non_ready_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6GateService,
        "evaluate",
        sid,
        "gate_status",
        "BLOCKED",
    )

    body = _certify(sid)

    assert body["gate_status"] == "BLOCKED"
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert body["release_ready"] is False


def test_gate_inconsistency_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    forged_audit = dict(genuine)
    forged_audit["gate_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(ReasoningRunStage6GateConsistencyAuditService, "audit", _forged)

    body = _certify(sid)

    assert body["gate_consistent"] is False
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


def test_readiness_non_ready_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6ReadinessService,
        "report",
        sid,
        "readiness_status",
        "BLOCKED",
    )

    body = _certify(sid)

    assert body["readiness_status"] == "BLOCKED"
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


def test_readiness_inconsistency_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReadinessConsistencyAuditService().audit(db, sid)
    forged_audit = dict(genuine)
    forged_audit["readiness_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "READINESS_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6ReadinessConsistencyAuditService, "audit", _forged
    )

    body = _certify(sid)

    assert body["readiness_consistent"] is False
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


def test_evidence_unavailable_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6EvidenceService,
        "bundle",
        sid,
        "stage_6_status",
        "BLOCKED",
    )

    body = _certify(sid)

    assert body["evidence_status"] == "BLOCKED"
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


def test_evidence_inconsistency_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceConsistencyAuditService().audit(db, sid)
    forged_audit = dict(genuine)
    forged_audit["evidence_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "EVIDENCE_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6EvidenceConsistencyAuditService, "audit", _forged
    )

    body = _certify(sid)

    assert body["evidence_consistent"] is False
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


def test_manifest_contradiction_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6ReleaseManifestService,
        "manifest",
        sid,
        "manifest_status",
        "BLOCKED",
    )

    body = _certify(sid)

    assert body["manifest_status"] == "BLOCKED"
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


def test_manifest_inconsistency_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ManifestConsistencyAuditService().audit(db, sid)
    forged_audit = dict(genuine)
    forged_audit["manifest_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "MANIFEST_STATUS_MISMATCH:expected=BLOCKED,actual=READY"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6ManifestConsistencyAuditService, "audit", _forged
    )

    body = _certify(sid)

    assert body["manifest_consistent"] is False
    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False


# ---------------------------------------------------------------------------
# Isolation / determinism / read-only
# ---------------------------------------------------------------------------


def test_certification_is_isolated_to_exact_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)
    _insert_receipt(sid_b, "e" * 64, input_snapshot={"bad": "snapshot"})

    body_a = _certify(sid_a)
    body_b = _certify(sid_b)

    assert body_a["certification_status"] == "CERTIFIED"
    assert body_b["certification_status"] == "BLOCKED"
    assert "INPUT_SNAPSHOT_MALFORMED" in body_b["findings"]
    assert "INPUT_SNAPSHOT_MALFORMED" not in body_a["findings"]


def test_certification_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _insert_receipt(sid, "f" * 63 + "0", input_snapshot={"bad": "snapshot"})

    first = _certify(sid)
    second = _certify(sid)

    assert first == second
    assert first["certification_status"] == "BLOCKED"
    assert first["findings"] == sorted(first["findings"])


def test_certification_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _certify(sid)
        assert body["certification_status"] == "CERTIFIED"

    assert _counts() == counts_before


def test_certification_service_direct_call_matches_endpoint() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunStage6CertificationService().certify(db, sid)
    assert _counts() == counts_before

    body = _certify(sid)
    assert _counts() == counts_before
    assert body == direct


def test_certification_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(sessions_mod.certify_reasoning_run_stage_6)
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
# Historical boundary / architecture (Stage 7 not started)
# ---------------------------------------------------------------------------


def test_certification_preserves_not_persisted_as_evidence_limitation() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _certify(sid)

    assert body["certification_status"] == "CERTIFIED"
    assert body["certified"] is True
    assert body["release_ready"] is True
    assert body["findings"] == []
    serialized = str(body)
    assert "NOT_PERSISTED" not in serialized
    assert "original_result" not in serialized


def test_certification_does_not_invoke_replay_or_persist() -> None:
    from rop.services import (
        reasoning_run_stage_6_certification as certification_mod,
    )

    code = _code_without_docstrings(certification_mod)
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
        "llm",
        "LLM",
        "Stage 7",
        "Stage7",
    ):
        assert token not in code, token


def test_certification_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _certify(sid)

    assert body["certification_status"] == "CERTIFIED"
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


def test_certification_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _certify(sid)

    assert set(body.keys()) == CERTIFICATION_KEYS
    validated = ReasoningRunStage6CertificationRead.model_validate(body)
    assert validated.model_dump() == body


def test_certification_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _certify(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunStage6CertificationRead.model_validate(tampered)


def test_certification_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(CERTIFICATION_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal reasoning-run-stage-6-certification contract " "violation"
    }


# ---------------------------------------------------------------------------
# Status/boolean/component invariants (every contradiction blocks)
# ---------------------------------------------------------------------------


def test_gate_ready_false_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6GateService,
        "evaluate",
        sid,
        "ready",
        False,
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert body["release_ready"] is False
    assert "GATE_READY_INCOHERENT:status=READY,ready=False" in body["findings"]


def test_readiness_release_ready_false_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6ReadinessService,
        "report",
        sid,
        "release_ready",
        False,
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert (
        "READINESS_RELEASE_READY_INCOHERENT:status=READY,release_ready=False"
        in body["findings"]
    )


def test_evidence_release_ready_false_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6EvidenceService,
        "bundle",
        sid,
        "release_ready",
        False,
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert (
        "EVIDENCE_RELEASE_READY_INCOHERENT:status=READY,release_ready=False"
        in body["findings"]
    )


def test_forged_evidence_available_false_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6EvidenceService,
        "bundle",
        sid,
        "evidence_available",
        False,
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert "EVIDENCE_UNAVAILABLE" in body["findings"]


def test_manifest_release_ready_false_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _forged_service_result(
        monkeypatch,
        ReasoningRunStage6ReleaseManifestService,
        "manifest",
        sid,
        "release_ready",
        False,
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert (
        "MANIFEST_RELEASE_READY_INCOHERENT:status=READY,release_ready=False"
        in body["findings"]
    )


def test_manifest_component_unavailable_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.services.reasoning_run_stage_6_release_manifest import (
        ReasoningRunStage6ReleaseManifestService,
    )

    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReleaseManifestService().manifest(db, sid)
    forged_manifest = dict(genuine)
    forged_manifest["components"] = [dict(c) for c in genuine["components"]]
    forged_manifest["components"][2]["available"] = False

    def _forged_manifest(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_manifest

    monkeypatch.setattr(
        ReasoningRunStage6ReleaseManifestService, "manifest", _forged_manifest
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert (
        "MANIFEST_COMPONENT_NOT_AVAILABLE:REASONING_RUN_STAGE_6_GATE_TASK_144"
        in body["findings"]
    )


def test_manifest_component_inconsistent_prevents_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.services.reasoning_run_stage_6_release_manifest import (
        ReasoningRunStage6ReleaseManifestService,
    )

    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReleaseManifestService().manifest(db, sid)
    forged_manifest = dict(genuine)
    forged_manifest["components"] = [dict(c) for c in genuine["components"]]
    forged_manifest["components"][6]["consistent"] = False

    def _forged_manifest(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_manifest

    monkeypatch.setattr(
        ReasoningRunStage6ReleaseManifestService, "manifest", _forged_manifest
    )

    body = _certify(sid)

    assert body["certification_status"] == "BLOCKED"
    assert body["certified"] is False
    assert (
        "MANIFEST_COMPONENT_INCONSISTENT:"
        "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148" in body["findings"]
    )

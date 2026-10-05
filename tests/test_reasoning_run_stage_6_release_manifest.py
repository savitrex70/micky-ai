"""Task 150: canonical Stage 6 release package manifest tests.

Proves the read-only manifest contract over the eight canonical Stage
6 surfaces (Tasks 142-149): exact component set/order, READY /
NO_MATERIAL / BLOCKED / UNVERIFIABLE package states, release readiness
never overriding upstream inconsistency, exact session isolation,
deterministic output, zero side effects, strict schemas (including the
nested component schema), unchanged Task 137-149 contracts, the Task
140 historical-evidence boundary, and no model/provider integration. No
execution, no replay, no writes, no network.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator
from datetime import datetime
from typing import Any
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
from rop.schemas.reasoning_run_stage_6_release_manifest import (
    ReasoningRunStage6ReleaseManifestComponentRead,
    ReasoningRunStage6ReleaseManifestRead,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
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
from rop.services.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessService,
)
from rop.services.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_release_manifest import (
    REASONING_RUN_STAGE_6_RELEASE_MANIFEST_SOURCE_TASK_150,
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

MANIFEST_URL = "/sessions/{sid}/reasoning-run/stage-6-release-manifest"
GATE_URL = "/sessions/{sid}/reasoning-run/stage-6-gate"
GATE_AUDIT_URL = "/sessions/{sid}/reasoning-run/stage-6-gate/consistency-audit"
READINESS_URL = "/sessions/{sid}/reasoning-run/stage-6-readiness"
READINESS_AUDIT_URL = (
    "/sessions/{sid}/reasoning-run/stage-6-readiness/consistency-audit"
)
EVIDENCE_URL = "/sessions/{sid}/reasoning-run/stage-6-evidence"
EVIDENCE_AUDIT_URL = "/sessions/{sid}/reasoning-run/stage-6-evidence/consistency-audit"

MANIFEST_KEYS = {
    "requested_session_id",
    "manifest_status",
    "release_ready",
    "finding_count",
    "findings",
    "components",
    "manifest_source",
}

COMPONENT_KEYS = {
    "component_id",
    "component_kind",
    "status",
    "consistent",
    "available",
}

EXPECTED_COMPONENT_IDS = [
    "REASONING_RUN_INSPECTION_TASK_142",
    "REASONING_RUN_DIAGNOSTICS_TASK_143",
    "REASONING_RUN_STAGE_6_GATE_TASK_144",
    "REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145",
    "REASONING_RUN_STAGE_6_READINESS_TASK_146",
    "REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147",
    "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148",
    "REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149",
]


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
            "metadata": {"source": "release-manifest-test"},
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


def _manifest(sid: UUID) -> dict:
    r = client.get(MANIFEST_URL.format(sid=sid))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Package states / component set
# ---------------------------------------------------------------------------


def test_manifest_of_healthy_package_is_ready() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest(sid)

    assert set(body.keys()) == MANIFEST_KEYS
    assert body["requested_session_id"] == str(sid)
    assert body["manifest_status"] == "READY"
    assert body["release_ready"] is True
    assert body["finding_count"] == 0
    assert body["findings"] == []
    assert (
        body["manifest_source"]
        == REASONING_RUN_STAGE_6_RELEASE_MANIFEST_SOURCE_TASK_150
    )
    assert [c["component_id"] for c in body["components"]] == (EXPECTED_COMPONENT_IDS)
    for component in body["components"]:
        assert set(component.keys()) == COMPONENT_KEYS
        assert component["available"] is True


def test_manifest_of_no_material_is_no_material() -> None:
    sid = UUID(_create_session())

    body = _manifest(sid)

    assert body["manifest_status"] == "NO_MATERIAL"
    assert body["release_ready"] is False
    assert [c["component_id"] for c in body["components"]] == (EXPECTED_COMPONENT_IDS)
    assert body["findings"] == []


def test_manifest_of_blocked_package_is_blocked() -> None:
    sid = UUID(_create_session())
    snapshot = _canonical_snapshot(sid)
    honest = compute_snapshot_fingerprint(snapshot)
    forged = ("0" if honest[0] != "0" else "1") + honest[1:]
    _insert_receipt(sid, forged, input_snapshot=snapshot)

    body = _manifest(sid)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "REPLAY_RECORD_TAMPERED" in body["findings"]
    by_id = {c["component_id"]: c for c in body["components"]}
    assert by_id["REASONING_RUN_STAGE_6_GATE_TASK_144"]["status"] == "BLOCKED"


def test_manifest_of_legacy_package_is_unverifiable() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _manifest(sid)

    assert body["manifest_status"] == "UNVERIFIABLE"
    assert body["release_ready"] is False
    assert "FINGERPRINT_PROVENANCE_NOT_PERSISTED" in body["findings"]
    assert "REPLAY_RECORD_TAMPERED" not in body["findings"]


def test_manifest_never_ready_when_upstream_consistency_fails(
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

    body = _manifest(sid)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    by_id = {c["component_id"]: c for c in body["components"]}
    assert (
        by_id["REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145"]["consistent"]
        is False
    )


def test_manifest_missing_session_returns_404() -> None:
    r = client.get(MANIFEST_URL.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json() == {"detail": "Session not found"}


# ---------------------------------------------------------------------------
# Isolation / determinism / read-only
# ---------------------------------------------------------------------------


def test_manifest_is_isolated_to_exact_session() -> None:
    sid_a = UUID(_create_session())
    sid_b = UUID(_create_session())
    _insert_bound_receipt(sid_a)
    _insert_receipt(sid_b, "e" * 64, input_snapshot={"bad": "snapshot"})

    body_a = _manifest(sid_a)
    body_b = _manifest(sid_b)

    assert body_a["manifest_status"] == "READY"
    assert body_b["manifest_status"] == "BLOCKED"
    assert "INPUT_SNAPSHOT_MALFORMED" in body_b["findings"]
    assert "INPUT_SNAPSHOT_MALFORMED" not in body_a["findings"]


def test_manifest_repeated_requests_produce_equivalent_output() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    _insert_receipt(sid, "f" * 63 + "0", input_snapshot={"bad": "snapshot"})

    first = _manifest(sid)
    second = _manifest(sid)

    assert first == second
    assert first["manifest_status"] == "BLOCKED"
    assert first["findings"] == sorted(first["findings"])
    assert [c["component_id"] for c in first["components"]] == (EXPECTED_COMPONENT_IDS)


def test_manifest_performs_no_writes() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    for _ in range(2):
        body = _manifest(sid)
        assert body["manifest_status"] == "READY"

    assert _counts() == counts_before


def test_manifest_service_direct_call_matches_endpoint() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    with TestingSessionLocal() as db:
        direct = ReasoningRunStage6ReleaseManifestService().manifest(db, sid)
    assert _counts() == counts_before

    body = _manifest(sid)
    assert _counts() == counts_before
    assert body == direct


def test_manifest_endpoint_source_is_read_only() -> None:
    from rop.api import sessions as sessions_mod

    endpoint_source = inspect.getsource(
        sessions_mod.manifest_reasoning_run_stage_6_release
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


def test_manifest_preserves_not_persisted_as_evidence_limitation() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest(sid)

    assert body["manifest_status"] == "READY"
    assert body["release_ready"] is True
    assert body["findings"] == []
    serialized = str(body)
    assert "NOT_PERSISTED" not in serialized
    assert "original_result" not in serialized


def test_manifest_does_not_invoke_replay_or_persist() -> None:
    from rop.services import (
        reasoning_run_stage_6_release_manifest as manifest_mod,
    )

    code = _code_without_docstrings(manifest_mod)
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


def test_manifest_creates_no_persistence() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    counts_before = _counts()

    body = _manifest(sid)

    assert body["manifest_status"] == "READY"
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


def test_manifest_response_shape_is_exact() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest(sid)

    assert set(body.keys()) == MANIFEST_KEYS
    validated = ReasoningRunStage6ReleaseManifestRead.model_validate(body)
    assert validated.model_dump() == body
    for component in body["components"]:
        ReasoningRunStage6ReleaseManifestComponentRead.model_validate(component)


def test_manifest_rejects_unexpected_response_fields() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    body = _manifest(sid)

    tampered = dict(body)
    tampered["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunStage6ReleaseManifestRead.model_validate(tampered)

    tampered_component = dict(body["components"][0])
    tampered_component["unexpected_nested"] = "boom"
    with pytest.raises(ValidationError):
        ReasoningRunStage6ReleaseManifestComponentRead.model_validate(
            tampered_component
        )


def test_manifest_of_unreadable_receipt_is_contract_failure() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)
    with TestingSessionLocal() as db:
        row = db.query(ReasoningRunReceipt).one()
        row.exogenous_snapshot = ["not", "a", "dict"]
        db.commit()

    r = client.get(MANIFEST_URL.format(sid=sid))

    assert r.status_code == 500
    assert r.json() == {
        "detail": "Internal reasoning-run-stage-6-release-manifest "
        "contract violation"
    }


# ---------------------------------------------------------------------------
# Component derivation rules (status/consistency from owning responses)
# ---------------------------------------------------------------------------


def test_diagnostics_component_carries_canonical_health() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest(sid)

    by_id = {c["component_id"]: c for c in body["components"]}
    diagnostics = by_id["REASONING_RUN_DIAGNOSTICS_TASK_143"]
    assert diagnostics["component_kind"] == "diagnostics"
    assert diagnostics["status"] == "HEALTHY"
    assert diagnostics["consistent"] is True
    assert diagnostics["available"] is True


def test_diagnostics_component_reflects_degraded_health() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "c" * 64, input_snapshot=None)

    body = _manifest(sid)

    by_id = {c["component_id"]: c for c in body["components"]}
    assert by_id["REASONING_RUN_DIAGNOSTICS_TASK_143"]["status"] == "DEGRADED"
    assert body["manifest_status"] == "UNVERIFIABLE"


def test_verdict_components_agree_with_governing_audits() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest(sid)

    gate = client.get(GATE_URL.format(sid=sid)).json()
    gate_audit = client.get(GATE_AUDIT_URL.format(sid=sid)).json()
    readiness = client.get(READINESS_URL.format(sid=sid)).json()
    readiness_audit = client.get(READINESS_AUDIT_URL.format(sid=sid)).json()
    evidence = client.get(EVIDENCE_URL.format(sid=sid)).json()
    evidence_audit = client.get(EVIDENCE_AUDIT_URL.format(sid=sid)).json()

    by_id = {c["component_id"]: c for c in body["components"]}
    assert by_id["REASONING_RUN_STAGE_6_GATE_TASK_144"]["status"] == gate["gate_status"]
    assert by_id["REASONING_RUN_STAGE_6_GATE_TASK_144"]["consistent"] == (
        gate_audit["gate_consistent"]
    )
    assert (
        by_id["REASONING_RUN_STAGE_6_READINESS_TASK_146"]["status"]
        == readiness["readiness_status"]
    )
    assert (
        by_id["REASONING_RUN_STAGE_6_READINESS_TASK_146"]["consistent"]
        == readiness_audit["readiness_consistent"]
    )
    assert (
        by_id["REASONING_RUN_STAGE_6_EVIDENCE_TASK_148"]["status"]
        == evidence["stage_6_status"]
    )
    assert (
        by_id["REASONING_RUN_STAGE_6_EVIDENCE_TASK_148"]["consistent"]
        == evidence_audit["evidence_consistent"]
    )


# ---------------------------------------------------------------------------
# Independent precedence reconstruction (Task 150 correction)
# ---------------------------------------------------------------------------


class _StaticGateService(ReasoningRunStage6GateService):
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def evaluate(self, db: Session, session_id: UUID) -> dict[str, Any]:
        _ = (db, session_id)
        return self._result


class _StaticReadinessService(ReasoningRunStage6ReadinessService):
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def report(self, db: Session, session_id: UUID) -> dict[str, Any]:
        _ = (db, session_id)
        return self._result


class _StaticEvidenceService(ReasoningRunStage6EvidenceService):
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def bundle(self, db: Session, session_id: UUID) -> dict[str, Any]:
        _ = (db, session_id)
        return self._result


def _manifest_with_forged_gate_view(sid: UUID, **overrides: object) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateService().evaluate(db, sid)
        forged = dict(genuine)
        forged.update(overrides)
        return ReasoningRunStage6ReleaseManifestService(
            gate_service=_StaticGateService(forged)
        ).manifest(db, sid)


def _manifest_with_forged_readiness_view(
    sid: UUID, **overrides: object
) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReadinessService().report(db, sid)
        forged = dict(genuine)
        forged.update(overrides)
        return ReasoningRunStage6ReleaseManifestService(
            readiness_service=_StaticReadinessService(forged)
        ).manifest(db, sid)


def _manifest_with_forged_evidence_view(
    sid: UUID, **overrides: object
) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceService().bundle(db, sid)
        forged = dict(genuine)
        forged.update(overrides)
        return ReasoningRunStage6ReleaseManifestService(
            evidence_service=_StaticEvidenceService(forged)
        ).manifest(db, sid)


def test_manifest_of_no_material_with_inconsistent_gate_audit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6GateConsistencyAuditService().audit(db, sid)
    assert genuine["gate_consistent"] is True
    forged_audit = dict(genuine)
    forged_audit["gate_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "GATE_STATUS_MISMATCH:expected=BLOCKED,actual=NO_MATERIAL"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6GateConsistencyAuditService, "audit", _forged_audit
    )

    body = _manifest(sid)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    by_id = {c["component_id"]: c for c in body["components"]}
    assert (
        by_id["REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145"]["consistent"]
        is False
    )


def test_manifest_of_no_material_with_inconsistent_readiness_audit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6ReadinessConsistencyAuditService().audit(db, sid)
    assert genuine["readiness_consistent"] is True
    forged_audit = dict(genuine)
    forged_audit["readiness_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "READINESS_STATUS_MISMATCH:expected=BLOCKED,actual=NO_MATERIAL"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6ReadinessConsistencyAuditService, "audit", _forged_audit
    )

    body = _manifest(sid)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    by_id = {c["component_id"]: c for c in body["components"]}
    assert (
        by_id["REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147"][
            "consistent"
        ]
        is False
    )


def test_manifest_of_no_material_with_inconsistent_evidence_audit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = UUID(_create_session())

    with TestingSessionLocal() as db:
        genuine = ReasoningRunStage6EvidenceConsistencyAuditService().audit(db, sid)
    assert genuine["evidence_consistent"] is True
    forged_audit = dict(genuine)
    forged_audit["evidence_consistent"] = False
    forged_audit["findings"] = list(genuine["findings"]) + [
        "EVIDENCE_STATUS_MISMATCH:expected=BLOCKED,actual=NO_MATERIAL"
    ]
    forged_audit["finding_count"] = len(forged_audit["findings"])

    def _forged_audit(self: object, db: Session, session_id: UUID) -> dict:
        _ = (db, session_id)
        return forged_audit

    monkeypatch.setattr(
        ReasoningRunStage6EvidenceConsistencyAuditService, "audit", _forged_audit
    )

    body = _manifest(sid)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    by_id = {c["component_id"]: c for c in body["components"]}
    assert (
        by_id["REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149"]["consistent"]
        is False
    )


def test_manifest_derives_blocked_when_gate_ready_flag_forged_false() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest_with_forged_gate_view(sid, ready=False)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "MANIFEST_GATE_READY_INCOHERENT:status=READY,ready=False" in body["findings"]


def test_manifest_derives_blocked_when_readiness_release_ready_forged_false() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest_with_forged_readiness_view(sid, release_ready=False)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert (
        "MANIFEST_READINESS_RELEASE_READY_INCOHERENT:status=READY,release_ready=False"
        in body["findings"]
    )


def test_manifest_derives_blocked_when_evidence_release_ready_forged_false() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest_with_forged_evidence_view(sid, release_ready=False)

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert (
        "MANIFEST_EVIDENCE_RELEASE_READY_INCOHERENT:status=READY,release_ready=False"
        in body["findings"]
    )


def test_manifest_derives_unverifiable_when_diagnostics_degraded() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest_with_forged_gate_view(sid, diagnostics_status="DEGRADED")

    assert body["manifest_status"] == "UNVERIFIABLE"
    assert body["release_ready"] is False
    assert "MANIFEST_DIAGNOSTICS_NOT_HEALTHY:DEGRADED" in body["findings"]
    by_id = {c["component_id"]: c for c in body["components"]}
    assert by_id["REASONING_RUN_DIAGNOSTICS_TASK_143"]["status"] == "DEGRADED"


def test_manifest_derives_blocked_when_diagnostics_unhealthy() -> None:
    sid = UUID(_create_session())
    _insert_bound_receipt(sid)

    body = _manifest_with_forged_gate_view(sid, diagnostics_status="UNHEALTHY")

    assert body["manifest_status"] == "BLOCKED"
    assert body["release_ready"] is False
    assert "MANIFEST_DIAGNOSTICS_NOT_HEALTHY:UNHEALTHY" in body["findings"]

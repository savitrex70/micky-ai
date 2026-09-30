"""Task 133: final deterministic ROP core release gate.

Proves ROP independently executes, audits, fingerprints, replays, and
exposes its deterministic reasoning workflow with no model runtime or
external AI service. Fake/test doubles only where a boundary needs an
injected collaborator; no real model, no network, no keys. If every
test here is green, the deterministic ROP core stands on its own.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app

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


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


CHEST_PAIN = "Patient reports chest pain and sweating"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _create_session(user_input: str = CHEST_PAIN) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "core-release-gate"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(session_id: str, text: str = CHEST_PAIN) -> None:
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


def _db() -> Any:
    gen = app.dependency_overrides[get_db]()
    return gen, next(gen)


def _executed(user_input: str = CHEST_PAIN) -> tuple[str, dict[str, Any]]:
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService

    sid = _create_session(user_input)
    _add_observation(sid, user_input)
    gen, db = _db()
    try:
        result = ReasoningRunExecutionService().execute_for_session(db, UUID(sid))
    finally:
        gen.close()
    assert result["outcome"] == "COMPLETED"
    return sid, result


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


# ---------------------------------------------------------------------------
# Core reasoning
# ---------------------------------------------------------------------------


def test_gate_core_observation_extraction() -> None:
    from rop.services.observation import ObservationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        observations = ObservationService().list_by_session(db, UUID(sid))
    assert observations
    assert all(o.text.strip() for o in observations)


def test_gate_core_entity_recognition() -> None:
    from rop.services.medical_entity_recognition import (
        MedicalEntityRecognitionService,
    )
    from rop.services.observation import ObservationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        observations = ObservationService().list_by_session(db, UUID(sid))
    first = MedicalEntityRecognitionService().recognize(observations)
    second = MedicalEntityRecognitionService().recognize(observations)
    assert len(first) == len(second)
    assert [str(e) for e in first] == [str(e) for e in second]


def test_gate_core_missing_information_detection() -> None:
    from rop.services.missing_information import MissingInformationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        items = MissingInformationService().list_by_session(db, UUID(sid))
    assert items
    assert all(item.template and item.item for item in items)


def test_gate_core_template_matching() -> None:
    from rop.services.template_match import TemplateMatchService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        matches = TemplateMatchService().list_by_session(db, UUID(sid))
    assert matches
    assert all(m.template_name for m in matches)


def test_gate_core_candidate_generation() -> None:
    from rop.services.candidate_generation import CandidateGenerationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
    assert candidates
    assert len({str(c.id) for c in candidates}) == len(candidates)


def test_gate_core_evidence_evaluation() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        evidence = EvidenceEvaluationService().list_by_session(db, UUID(sid))
    assert evidence


def test_gate_core_evidence_aggregation() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.evidence_aggregation import EvidenceAggregationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        summaries = EvidenceAggregationService().summarize_session(
            db, UUID(sid), candidates
        )
        consistency = EvidenceAggregationService().analyze_session_consistency(
            db, UUID(sid), candidates=candidates
        )
    assert summaries
    assert consistency is not None


def test_gate_core_hypothesis_scoring() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.hypothesis_scoring import HypothesisScoringService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        scores = HypothesisScoringService().score_session(db, UUID(sid), candidates)
    assert len(scores) == len(candidates)
    assert {str(s["hypothesis_id"]) for s in scores} == {str(c.id) for c in candidates}


def test_gate_core_differential_ranking() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.differential_ranking import DifferentialRankingService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        ranked = DifferentialRankingService().rank_session(db, UUID(sid), candidates)
    assert [r["rank"] for r in ranked] == sorted(r["rank"] for r in ranked)
    assert ranked[0]["rank"] == 1


def test_gate_core_decision_chain_in_pipeline() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.reasoning_pipeline import ReasoningPipelineService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        pipeline = ReasoningPipelineService().build_for_session(
            db, UUID(sid), candidates
        )
    sources = [stage["stage_source"] for stage in pipeline["stages"]]
    assert any("TASK_03" in source for source in sources)
    assert pipeline["final_execution"] is not None
    assert pipeline["pipeline_consistent"] is True


def test_gate_core_reasoning_pipeline() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.reasoning_pipeline import ReasoningPipelineService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
        pipeline = ReasoningPipelineService().build_for_session(
            db, UUID(sid), candidates
        )
    assert pipeline["available"] is True
    assert pipeline["pipeline_complete"] is True


def test_gate_core_reasoning_run_composition() -> None:
    from rop.services.reasoning_run import ReasoningRunService

    sid, _ = _executed()
    gen, db = _db()
    try:
        run = ReasoningRunService().build_for_session(db, UUID(sid))
    finally:
        gen.close()
    assert run["run_complete"] is True
    assert run["run_consistent"] is True


def test_gate_core_reasoning_run_execution() -> None:
    _, result = _executed()
    assert result["outcome"] == "COMPLETED"
    assert result["execution_consistent"] is True
    assert result["completed_stage_count"] == result["stage_count"] == 8


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_gate_integrity_input_snapshot() -> None:
    from rop.services.reasoning_run_input_snapshot import (
        REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
        ReasoningRunInputSnapshotService,
    )

    sid, _ = _executed()
    gen, db = _db()
    try:
        snapshot = ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
    finally:
        gen.close()
    assert snapshot["snapshot_source"] == REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124
    assert snapshot["observations"]


def test_gate_integrity_input_fingerprint() -> None:
    from rop.services.reasoning_run_fingerprint import (
        compute_snapshot_fingerprint,
        verify_snapshot_fingerprint,
    )
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    sid = _create_session()
    _add_observation(sid)
    gen, db = _db()
    try:
        pre = ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
    finally:
        gen.close()
    fingerprint = compute_snapshot_fingerprint(pre)
    assert len(fingerprint) == 64
    assert verify_snapshot_fingerprint(pre, fingerprint) == []
    assert verify_snapshot_fingerprint(pre, "0" * 64) == [
        "input fingerprint mismatch: snapshot does not match run"
    ]
    assert verify_snapshot_fingerprint(pre, "short") == [
        "claimed input fingerprint is malformed"
    ]


def test_gate_integrity_stage_provenance() -> None:
    _, result = _executed()
    sources = [stage["stage_source"] for stage in result["stages"]]
    assert all(source.endswith("_TASK_044") for source in sources)
    assert result["execution_source"] == "REASONING_RUN_EXECUTION_TASK_044"
    assert result["reasoning_run"]["run_source"] == "REASONING_RUN_TASK_042"


def test_gate_integrity_cross_stage_consistency() -> None:
    from rop.services.reasoning_chain_audit import ReasoningChainAuditService

    sid, _ = _executed()
    gen, db = _db()
    try:
        audit = ReasoningChainAuditService().audit_session(db, UUID(sid))
    finally:
        gen.close()
    assert audit["chain_consistent"] is True


def test_gate_integrity_lineage() -> None:
    from rop.services.evidence_hypothesis_lineage import (
        EvidenceHypothesisLineageService,
    )

    sid, _ = _executed()
    gen, db = _db()
    try:
        lineage = EvidenceHypothesisLineageService().build_for_session(db, UUID(sid))
    finally:
        gen.close()
    assert lineage["lineage_consistent"] is True


def test_gate_integrity_lifecycle() -> None:
    from rop.services.missing_information_lifecycle import (
        MissingInformationLifecycleService,
    )
    from rop.services.observation import ObservationService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        observations = ObservationService().list_by_session(db, UUID(sid))
        record = MissingInformationLifecycleService().evaluate(
            db, UUID(sid), observations
        )
    assert record["available"] is True


def test_gate_integrity_replay() -> None:
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )
    from rop.services.reasoning_run_replay import ReasoningRunReplayService

    sid = _create_session()
    _add_observation(sid)
    gen, db = _db()
    try:
        pre = ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
        result = ReasoningRunExecutionService().execute_for_session(db, UUID(sid))
        assert result["outcome"] == "COMPLETED"
        # Re-seed exogenous state is unchanged (observations reused), so
        # replay over the recorded pre-run snapshot is consistent.
        replayed = ReasoningRunReplayService().replay(
            db, UUID(sid), original_result=result, original_snapshot=pre
        )
    finally:
        gen.close()
    assert replayed["replay_consistent"] is True


def test_gate_integrity_idempotent_execution() -> None:
    from rop.repositories.reasoning_run_receipt import (
        ReasoningRunReceiptRepository,
    )
    from rop.services.reasoning_run_fingerprint import (
        compute_snapshot_fingerprint,
    )
    from rop.services.reasoning_run_idempotency import (
        DISPOSITION_EXECUTED_NEW,
        DISPOSITION_REUSED_IDENTICAL,
        ReasoningRunIdempotencyService,
    )
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    # The exact round-trip: the returned input fingerprint is usable
    # directly on the next identical request.
    sid = _create_session()
    _add_observation(sid)
    with TestingSessionLocal() as db:
        first = ReasoningRunIdempotencyService().execute_idempotent(db, UUID(sid))
    assert first["disposition"] == DISPOSITION_EXECUTED_NEW
    known = first["result"]["input_fingerprint"]
    with TestingSessionLocal() as db:
        # A stored COMPLETED run binds this exact identity.
        receipt = ReasoningRunReceiptRepository().find_completed(db, UUID(sid), known)
        assert receipt is not None
        assert receipt.input_fingerprint == known
        envelope = ReasoningRunIdempotencyService().execute_idempotent(
            db, UUID(sid), known_input_fingerprint=known
        )
    assert envelope["disposition"] == DISPOSITION_REUSED_IDENTICAL
    assert envelope["result"]["input_fingerprint"] == known
    with TestingSessionLocal() as db:
        # Reuse wrote nothing: exactly one receipt in history.
        assert ReasoningRunReceiptRepository().count_by_session(db, UUID(sid)) == 1
    # A matching fingerprint with no completed run behind it executes.
    fresh = _create_session()
    _add_observation(fresh)
    with TestingSessionLocal() as db:
        observed = compute_snapshot_fingerprint(
            ReasoningRunInputSnapshotService().build_snapshot(db, UUID(fresh))
        )
        assert (
            ReasoningRunReceiptRepository().find_completed(db, UUID(fresh), observed)
            is None
        )
        envelope = ReasoningRunIdempotencyService().execute_idempotent(
            db, UUID(fresh), known_input_fingerprint=observed
        )
    assert envelope["disposition"] == DISPOSITION_EXECUTED_NEW


def test_gate_integrity_atomicity() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService

    sid, _ = _executed()
    with TestingSessionLocal() as db:
        evidence_before = {
            str(e.id)
            for e in EvidenceEvaluationService().list_by_session(db, UUID(sid))
        }
    assert evidence_before

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    with TestingSessionLocal() as db:
        failed = ReasoningRunExecutionService(
            evidence_evaluation_service=_BoomEvidence()
        ).execute_for_session(db, UUID(sid))
    assert failed["outcome"] == "FAILED"
    # Whole-run rollback: the failed attempt persisted nothing, so the
    # previously committed evidence set is byte-identical.
    with TestingSessionLocal() as db:
        evidence_after = {
            str(e.id)
            for e in EvidenceEvaluationService().list_by_session(db, UUID(sid))
        }
    assert evidence_after == evidence_before


def test_gate_integrity_whole_run_rollback() -> None:
    """A late-stage failure rolls back earlier writes from the same
    attempt, while pre-existing committed state survives."""
    from rop.services.evidence_evaluation import EvidenceEvaluationService
    from rop.services.observation import ObservationService
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    sid = _create_session()
    with TestingSessionLocal() as db:
        failed = ReasoningRunExecutionService(
            evidence_evaluation_service=_BoomEvidence()
        ).execute_for_session(db, UUID(sid))
    assert failed["outcome"] == "FAILED"
    with TestingSessionLocal() as db:
        assert ObservationService().list_by_session(db, UUID(sid)) == []
        assert EvidenceEvaluationService().list_by_session(db, UUID(sid)) == []

    seeded = _create_session()
    _add_observation(seeded)
    with TestingSessionLocal() as db:
        before = [
            str(o.id) for o in ObservationService().list_by_session(db, UUID(seeded))
        ]
        failed = ReasoningRunExecutionService(
            evidence_evaluation_service=_BoomEvidence()
        ).execute_for_session(db, UUID(seeded))
    assert failed["outcome"] == "FAILED"
    with TestingSessionLocal() as db:
        after = [
            str(o.id) for o in ObservationService().list_by_session(db, UUID(seeded))
        ]
    assert after == before


def test_gate_integrity_failure_containment() -> None:
    from rop.services.evidence_evaluation import EvidenceEvaluationService
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService

    class _BoomEvidence(EvidenceEvaluationService):
        def evaluate_session(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("evaluation exploded")

    sid = _create_session()
    _add_observation(sid)
    with TestingSessionLocal() as db:
        result = ReasoningRunExecutionService(
            evidence_evaluation_service=_BoomEvidence()
        ).execute_for_session(db, UUID(sid))
    assert result["outcome"] == "FAILED"
    assert result["available"] is False
    assert result["reasoning_run"] is None
    failed_stages = [s for s in result["stages"] if s["status"] == "FAILED"]
    assert [s["stage_id"] for s in failed_stages] == ["EVIDENCE_EVALUATION"]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_gate_api_orchestration() -> None:
    from rop.services.reasoning_run_orchestration import (
        ReasoningRunOrchestrationService,
    )

    sid = _create_session()
    _add_observation(sid)
    with TestingSessionLocal() as db:
        result = ReasoningRunOrchestrationService().orchestrate(db, UUID(sid))
    assert result["orchestration_consistent"] is True
    assert result["failure_stage"] is None


def test_gate_api_read_only_inspection_endpoints() -> None:
    sid, _ = _executed()
    for path in (
        f"/sessions/{sid}/reasoning-run",
        f"/sessions/{sid}/reasoning-pipeline",
        f"/sessions/{sid}/reasoning-run-consistency",
        f"/sessions/{sid}/replay",
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_gate_api_execution_endpoints() -> None:
    sid = _create_session()
    _add_observation(sid)
    for path in (
        f"/sessions/{sid}/reasoning-run/execute",
        f"/sessions/{sid}/reasoning-run/execute-audited",
        f"/sessions/{sid}/reasoning-run/execute-fully-audited",
    ):
        response = client.post(path)
        assert response.status_code == 200, path
    assert (
        client.post(f"/sessions/{sid}/reasoning-run/execute").json()["outcome"]
        == "COMPLETED"
    )


def test_gate_api_audited_result_endpoint() -> None:
    sid = _create_session()
    _add_observation(sid)
    bundle = client.post(f"/sessions/{sid}/reasoning-run/execute-audited").json()
    assert bundle["bundle_consistent"] is True
    assert bundle["execution"]["outcome"] == "COMPLETED"


def test_gate_api_stable_schema_contracts() -> None:
    sid, _ = _executed()
    payload = client.post(f"/sessions/{sid}/reasoning-run/execute").json()
    assert payload["outcome"] == "COMPLETED"
    assert len(payload["input_fingerprint"]) == 64
    assert payload["execution_source"] == "REASONING_RUN_EXECUTION_TASK_044"


def test_gate_api_http_failure_mapping() -> None:
    missing = str(uuid4())
    assert client.post(f"/sessions/{missing}/reasoning-run/execute").status_code == (
        404
    )
    assert client.get(f"/sessions/{missing}/replay").status_code == 404


# ---------------------------------------------------------------------------
# Architectural prohibitions
# ---------------------------------------------------------------------------


def test_gate_prohibition_no_model_runtime() -> None:
    import rop.services as services_pkg

    package_dir = Path(services_pkg.__file__).resolve().parent
    assert not (package_dir / "ollama_reasoning_provider.py").exists()
    assert not hasattr(services_pkg, "OllamaReasoningProvider")
    sources = [
        path.read_text(encoding="utf-8").lower()
        for path in (*sorted(package_dir.glob("*.py")),)
    ]
    for token in ("ollama", "openai", "gemini", "anthropic", "claude"):
        assert not any(token in source for source in sources), token


def test_gate_prohibition_no_keys_or_servers() -> None:
    from rop.config import get_settings
    from rop.services.llm_reasoning import LLMReasoningService

    fields = list(type(get_settings()).model_fields.keys())
    lowered = [name.lower() for name in fields]
    for token in ("api_key", "apikey", "provider", "model", "ollama"):
        assert not any(token in name for name in lowered), token
    assert LLMReasoningService().provider is None


def test_gate_prohibition_no_network_in_reasoning() -> None:
    from rop.services.reasoning_run_orchestration import (
        ReasoningRunOrchestrationService,
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network used by deterministic reasoning")

    sid = _create_session()
    _add_observation(sid)
    original_create = socket.create_connection
    original_connect = socket.socket.connect
    socket.create_connection = _boom  # type: ignore[method-assign]
    socket.socket.connect = _boom  # type: ignore[method-assign]
    try:
        with TestingSessionLocal() as db:
            result = ReasoningRunOrchestrationService().orchestrate(db, UUID(sid))
    finally:
        socket.create_connection = original_create  # type: ignore[method-assign]
        socket.socket.connect = original_connect  # type: ignore[method-assign]
    assert result["orchestration_consistent"] is True


def test_gate_prohibition_no_db_writes_on_read_endpoints() -> None:
    from rop.database import Base as _Base

    sid, _ = _executed()

    def _counts() -> dict[str, int]:
        with TestingSessionLocal() as db:
            return {
                table.name: db.execute(
                    sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
                ).scalar_one()
                for table in _Base.metadata.sorted_tables
            }

    before = _counts()
    for path in (
        f"/sessions/{sid}/reasoning-run",
        f"/sessions/{sid}/reasoning-pipeline",
        f"/sessions/{sid}/reasoning-run-consistency",
        f"/sessions/{sid}/replay",
    ):
        assert client.get(path).status_code == 200
    assert _counts() == before


def test_gate_prohibition_no_raw_prompt_persistence() -> None:
    sid, _ = _executed()
    with TestingSessionLocal() as db:
        from rop.services.reasoning_run_orchestration import (
            ReasoningRunOrchestrationService,
        )

        result = ReasoningRunOrchestrationService().orchestrate(db, UUID(sid))
    keys = _all_keys(result)
    assert "prompt" not in keys
    assert "raw_text" not in keys
    blob = json.dumps(result, default=str)
    assert "api_key" not in blob
    assert "BEGIN PRIVATE" not in blob
    assert "postgresql://" not in blob


def test_gate_prohibition_no_decision_authority() -> None:
    sid, _ = _executed()
    with TestingSessionLocal() as db:
        from rop.services.reasoning_run_orchestration import (
            ReasoningRunOrchestrationService,
        )

        result = ReasoningRunOrchestrationService().orchestrate(db, UUID(sid))
    forbidden = {
        "winner",
        "diagnosis",
        "treatment",
        "recommendation",
    }
    assert not (forbidden & _all_keys(result))


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_gate_reproducibility_fingerprint_and_order() -> None:
    from rop.services.reasoning_chain_audit import ReasoningChainAuditService
    from rop.services.reasoning_run_fingerprint import (
        compute_snapshot_fingerprint,
    )
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    sid, first = _executed()
    gen, db = _db()
    try:
        first_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, UUID(sid)
        )
    finally:
        gen.close()
    gen, db = _db()
    try:
        # Independently reconstructed snapshots of the same state hash
        # identically: reproducibility across reconstructions, not a
        # snapshot hashing equal to itself.
        second_snapshot = ReasoningRunInputSnapshotService().build_snapshot(
            db, UUID(sid)
        )
        first_audit = ReasoningChainAuditService().audit_session(db, UUID(sid))
        second_audit = ReasoningChainAuditService().audit_session(db, UUID(sid))
    finally:
        gen.close()
    assert first_snapshot == second_snapshot
    assert compute_snapshot_fingerprint(first_snapshot) == compute_snapshot_fingerprint(
        second_snapshot
    )
    assert first_audit["consistency_issues"] == second_audit["consistency_issues"]
    assert first["completed_stage_count"] == 8


def test_gate_single_canonical_snapshot() -> None:
    """Orchestration reports exactly the fingerprint its nested
    execution ran under: one canonical snapshot, no silent rebuild."""
    sid = _create_session()
    _add_observation(sid)
    with TestingSessionLocal() as db:
        from rop.services.reasoning_run_orchestration import (
            ReasoningRunOrchestrationService,
        )

        result = ReasoningRunOrchestrationService().orchestrate(db, UUID(sid))
    assert result["orchestration_consistent"] is True
    assert result["input_fingerprint"] == result["execution"]["input_fingerprint"]


def test_gate_reproducibility_replay_result() -> None:
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )
    from rop.services.reasoning_run_replay import ReasoningRunReplayService

    sid = _create_session()
    _add_observation(sid)
    gen, db = _db()
    try:
        pre = ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
        result = ReasoningRunExecutionService().execute_for_session(db, UUID(sid))
        assert result["outcome"] == "COMPLETED"
        replayed = ReasoningRunReplayService().replay(
            db, UUID(sid), original_result=result, original_snapshot=pre
        )
    finally:
        gen.close()
    # Observations were pre-seeded, so extraction is skipped and
    # exogenous inputs are stable: replay over the recorded pre-run
    # snapshot is consistent.
    assert replayed["input_match"] is True
    assert replayed["replay_consistent"] is True


def test_gate_reproducibility_replay_detects_derived_change() -> None:
    """A derived-state change with identical stage metadata still
    diverges replay: full equivalence, not metadata comparison."""
    from rop.models import EvaluatedEvidence
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )
    from rop.services.reasoning_run_replay import ReasoningRunReplayService

    sid = _create_session()
    _add_observation(sid)
    gen, db = _db()
    try:
        pre = ReasoningRunInputSnapshotService().build_snapshot(db, UUID(sid))
        result = ReasoningRunExecutionService().execute_for_session(db, UUID(sid))
        assert result["outcome"] == "COMPLETED"
        rows = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(sid))
            .all()
        )
        assert rows
        db.delete(rows[0])
        db.commit()
        replayed = ReasoningRunReplayService().replay(
            db, UUID(sid), original_result=result, original_snapshot=pre
        )
    finally:
        gen.close()
    assert replayed["input_match"] is True
    assert (
        "DERIVED_RUN_STATE_DIVERGED" in replayed["divergences"]
        or "DERIVED_AUDIT_STATE_DIVERGED" in replayed["divergences"]
    )
    assert replayed["replay_consistent"] is False


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_gate_safety_no_fabrication_or_bypass() -> None:
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.reasoning_chain_audit import ReasoningChainAuditService

    sid, _ = _executed()
    gen, db = _db()
    try:
        audit = ReasoningChainAuditService().audit_session(db, UUID(sid))
        candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
    finally:
        gen.close()
    assert audit["chain_consistent"] is True
    assert candidates
    assert all(c.name.strip() and c.trigger_reason.strip() for c in candidates)
    # Repeat execution invents nothing extra: candidate count is stable
    # and every candidate still traces to the same session.
    from rop.services.reasoning_run_execution import ReasoningRunExecutionService

    gen, db = _db()
    try:
        rerun = ReasoningRunExecutionService().execute_for_session(db, UUID(sid))
    finally:
        gen.close()
    assert rerun["outcome"] == "COMPLETED"
    gen, db = _db()
    try:
        rerun_candidates = CandidateGenerationService().list_by_session(db, UUID(sid))
    finally:
        gen.close()
    assert len(rerun_candidates) == len(candidates)

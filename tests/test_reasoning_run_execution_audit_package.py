"""Tests for Task 048 fully audited reasoning-run execution package.

Task 048 composes Task 046's execution bundle with Task 047's bundle
audit into one package. It is a composition layer only.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import reasoning_run_execution_audit_package as mod
from rop.services.reasoning_run_execution_audit_package import (
    REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048,
    ReasoningRunExecutionAuditPackageContractError,
    ReasoningRunExecutionAuditPackageService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)
client = TestClient(app)

PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "execution_bundle",
    "bundle_consistency",
    "package_source",
)


def _service() -> ReasoningRunExecutionAuditPackageService:
    return ReasoningRunExecutionAuditPackageService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-048-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _package_via_service(session_id: str) -> dict[str, Any]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return _service().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


def _valid_package() -> dict[str, Any]:
    sid = _create_session("Patient reports chest pain")
    return _package_via_service(sid)


# ---------------------------------------------------------------------------
# Valid packages
# ---------------------------------------------------------------------------


def test_valid_package_shape() -> None:
    package = _valid_package()
    assert set(package) == set(PACKAGE_FIELDS)
    assert package["available"] is True
    assert package["package_consistent"] is True


def test_package_source_fixed() -> None:
    package = _valid_package()
    assert (
        package["package_source"]
        == REASONING_RUN_EXECUTION_AUDIT_PACKAGE_SOURCE_TASK_048
    )


def test_nested_bundle_present() -> None:
    package = _valid_package()
    b = package["execution_bundle"]
    assert b["bundle_source"] == "REASONING_RUN_EXECUTION_BUNDLE_TASK_046"
    assert b["available"] is True


def test_nested_consistency_present() -> None:
    package = _valid_package()
    c = package["bundle_consistency"]
    assert c["available"] is True
    assert (
        c["bundle_consistency_source"]
        == "REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_TASK_047"
    )


def test_package_consistent_matches_task047() -> None:
    package = _valid_package()
    assert package["package_consistent"] == (
        package["bundle_consistency"]["bundle_consistent"]
    )


def test_valid_failed_task044_execution() -> None:
    """A legitimately-FAILED Task 044 execution must still produce a
    valid package."""
    from rop.services.observation_extraction import ObservationExtractionService

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced")

    ObservationExtractionService.extract_and_store = boom
    try:
        sid = _create_session("Patient reports chest pain")
        package = _package_via_service(sid)
    finally:
        ObservationExtractionService.extract_and_store = original

    assert package["available"] is True
    assert package["package_consistent"] is True
    exec_ = package["execution_bundle"]["execution"]
    assert exec_["outcome"] == "FAILED"


def test_valid_package_with_task046_bundle_consistent_false() -> None:
    """Task 046 bundle_consistent may be False (legitimately inconsistent
    underlying execution) while Task 047 still reports the bundle
    contract as internally consistent -> Task 048 package_consistent True.
    """
    sid = _create_session("Patient reports chest pain")
    # Produce a bundle whose Task 045 audit reports the execution as
    # inconsistent. Tamper the nested Task 042 source.
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    execution = r.json()
    execution["reasoning_run"]["run_source"] = "WRONG"

    from rop.services.reasoning_run_execution_bundle import (
        ReasoningRunExecutionBundleService,
    )
    from rop.services.reasoning_run_execution_bundle_consistency import (
        ReasoningRunExecutionBundleConsistencyService,
    )
    from rop.services.reasoning_run_execution_consistency import (
        ReasoningRunExecutionConsistencyService,
    )

    audit = ReasoningRunExecutionConsistencyService().build(
        execution=execution
    )
    bundle = ReasoningRunExecutionBundleService().build(
        session_id=UUID(sid),
        execution=execution,
        execution_consistency=audit,
    )
    assert bundle["bundle_consistent"] is False

    consistency = ReasoningRunExecutionBundleConsistencyService().build(
        bundle=bundle
    )
    assert consistency["bundle_consistent"] is True

    package = _service().build(
        session_id=UUID(sid),
        execution_bundle=bundle,
        bundle_consistency=consistency,
    )
    assert package["available"] is True
    assert package["package_consistent"] is True
    assert (
        package["execution_bundle"]["bundle_consistent"] is False
    )


# ---------------------------------------------------------------------------
# Missing / malformed nested contracts
# ---------------------------------------------------------------------------


def test_missing_execution_bundle() -> None:
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=uuid4(),
            execution_bundle=None,
            bundle_consistency={},
        )
    assert ei.value.invariant == "MISSING_EXECUTION_BUNDLE"


def test_missing_bundle_consistency() -> None:
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=uuid4(),
            execution_bundle={},
            bundle_consistency=None,
        )
    assert ei.value.invariant == "MISSING_BUNDLE_CONSISTENCY"


def test_malformed_task046_contract() -> None:
    package = _valid_package()
    tampered_bundle = copy.deepcopy(package["execution_bundle"])
    del tampered_bundle["bundle_source"]
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=package["session_id"],
            execution_bundle=tampered_bundle,
            bundle_consistency=package["bundle_consistency"],
        )
    assert ei.value.invariant == "INVALID_EXECUTION_BUNDLE"


def test_malformed_task047_contract() -> None:
    package = _valid_package()
    tampered_consistency = copy.deepcopy(package["bundle_consistency"])
    del tampered_consistency["bundle_consistency_source"]
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=package["session_id"],
            execution_bundle=package["execution_bundle"],
            bundle_consistency=tampered_consistency,
        )
    assert ei.value.invariant == "INVALID_BUNDLE_CONSISTENCY"


# ---------------------------------------------------------------------------
# Session mismatch
# ---------------------------------------------------------------------------


def test_session_mismatch() -> None:
    package = _valid_package()
    other_session = uuid4()
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=other_session,
            execution_bundle=package["execution_bundle"],
            bundle_consistency=package["bundle_consistency"],
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_bundle_audit_unavailable() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package["bundle_consistency"])
    tampered["available"] = False
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=package["session_id"],
            execution_bundle=package["execution_bundle"],
            bundle_consistency=tampered,
        )
    assert ei.value.invariant in (
        "BUNDLE_AUDIT_UNAVAILABLE",
        "INVALID_BUNDLE_CONSISTENCY",
    )


def test_bundle_audit_session_inconsistent() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package["bundle_consistency"])
    tampered["session_consistent"] = False
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=package["session_id"],
            execution_bundle=package["execution_bundle"],
            bundle_consistency=tampered,
        )
    assert ei.value.invariant in (
        "BUNDLE_AUDIT_SESSION_INCONSISTENT",
        "INVALID_BUNDLE_CONSISTENCY",
    )


# ---------------------------------------------------------------------------
# Source mismatches
# ---------------------------------------------------------------------------


def test_wrong_task046_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package["execution_bundle"])
    tampered["bundle_source"] = "WRONG"
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=package["session_id"],
            execution_bundle=tampered,
            bundle_consistency=package["bundle_consistency"],
        )
    assert ei.value.invariant in (
        "INVALID_EXECUTION_BUNDLE",
        "INVALID_BUNDLE_SOURCE",
    )


def test_wrong_task047_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package["bundle_consistency"])
    tampered["bundle_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=package["session_id"],
            execution_bundle=package["execution_bundle"],
            bundle_consistency=tampered,
        )
    assert ei.value.invariant in (
        "INVALID_BUNDLE_CONSISTENCY",
        "INVALID_BUNDLE_CONSISTENCY_SOURCE",
    )


def test_wrong_task048_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        ReasoningRunExecutionAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "INVALID_PACKAGE_SOURCE"


# ---------------------------------------------------------------------------
# Package consistency relationship
# ---------------------------------------------------------------------------


def test_package_consistent_mismatch_rejected() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(
        ReasoningRunExecutionAuditPackageContractError
    ) as ei:
        ReasoningRunExecutionAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_CONSISTENT_MISMATCH"


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_task046_called_exactly_once(monkeypatch) -> None:
    from rop.services.reasoning_run_execution_bundle import (
        ReasoningRunExecutionBundleService,
    )

    calls = {"n": 0}
    original = ReasoningRunExecutionBundleService.build_for_session

    def spy(self, db, session_id):
        calls["n"] += 1
        return original(self, db, session_id)

    monkeypatch.setattr(
        ReasoningRunExecutionBundleService, "build_for_session", spy
    )

    sid = _create_session("Patient reports chest pain")
    _package_via_service(sid)
    assert calls["n"] == 1


def test_exact_bundle_passed_to_task047(monkeypatch) -> None:
    from rop.services.reasoning_run_execution_bundle_consistency import (
        ReasoningRunExecutionBundleConsistencyService,
    )

    captured: dict[str, Any] = {}
    original = ReasoningRunExecutionBundleConsistencyService.build

    def spy(self, *, bundle=None):
        captured["bundle"] = bundle
        return original(self, bundle=bundle)

    monkeypatch.setattr(
        ReasoningRunExecutionBundleConsistencyService, "build", spy
    )

    sid = _create_session("Patient reports chest pain")
    package = _package_via_service(sid)

    # The bundle passed to Task 047 is the exact one embedded in the
    # package (deep-equal).
    assert captured["bundle"] == package["execution_bundle"]


# ---------------------------------------------------------------------------
# No mutation
# ---------------------------------------------------------------------------


def test_inputs_not_mutated() -> None:
    package = _valid_package()
    bundle_before = copy.deepcopy(package["execution_bundle"])
    consistency_before = copy.deepcopy(package["bundle_consistency"])

    _service().build(
        session_id=package["session_id"],
        execution_bundle=package["execution_bundle"],
        bundle_consistency=package["bundle_consistency"],
    )

    assert package["execution_bundle"] == bundle_before
    assert package["bundle_consistency"] == consistency_before


def test_deterministic() -> None:
    package = _valid_package()
    s = _service()
    a = s.build(
        session_id=package["session_id"],
        execution_bundle=package["execution_bundle"],
        bundle_consistency=package["bundle_consistency"],
    )
    b = s.build(
        session_id=package["session_id"],
        execution_bundle=package["execution_bundle"],
        bundle_consistency=package["bundle_consistency"],
    )
    assert a == b


# ---------------------------------------------------------------------------
# No side effects outside Task 046 / Task 047
# ---------------------------------------------------------------------------


def test_no_direct_database_access() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "get_db",
        "session.query",
        "db.execute",
        "Repository(",
    ):
        assert forbidden not in src


def test_no_direct_task044_calls() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionService(" not in src
    assert "execute_for_session" not in src


def test_no_direct_task045_calls() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionConsistencyService(" not in src


def test_no_decision_or_llm_logic() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "DecisionPolicy",
        "CandidateGeneration",
        "EvidenceEvaluation",
        "openai",
        "gemini",
        "ollama",
        "llm",
        "rag",
        "winner",
        "recommendation",
    ):
        assert forbidden not in src.lower()

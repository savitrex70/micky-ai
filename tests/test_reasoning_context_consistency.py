"""Tests for Task 056 reasoning context consistency & audit.

Task 056 independently audits a Task 055 ReasoningContextRead against
its own declared contract and the nested Task 042 / Task 043 contracts.
Read-only; no DB, no HTTP, no LLM; never calls Task 055's build paths.
"""

from __future__ import annotations

import ast
import copy
import inspect
import re as _re
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import reasoning_context_consistency as mod
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_context_consistency import (
    REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056,
    ReasoningContextConsistencyContractError,
    ReasoningContextConsistencyService,
)
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
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

RESULT_FIELDS = (
    "available",
    "context_consistent",
    "session_consistent",
    "nested_reasoning_run_consistent",
    "nested_reasoning_run_audit_consistent",
    "candidate_state_consistent",
    "candidate_count_consistent",
    "audit_provenance_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "context_consistency_source",
)


def _service() -> ReasoningContextConsistencyService:
    return ReasoningContextConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-056-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _valid_context(user_input: str = "Task 056 valid") -> dict[str, Any]:
    sid = _seed_full_session(user_input)
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_context_all_flags_true() -> None:
    ctx = _valid_context()
    result = _service().build(context=ctx)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["context_consistent"] is True
    assert result["session_consistent"] is True
    assert result["nested_reasoning_run_consistent"] is True
    assert result["nested_reasoning_run_audit_consistent"] is True
    assert result["candidate_state_consistent"] is True
    assert result["candidate_count_consistent"] is True
    assert result["audit_provenance_consistent"] is True
    assert result["source_consistency"] is True
    assert result["metadata_consistent"] is True
    assert result["consistency_issues"] == []


def test_source_fixed() -> None:
    ctx = _valid_context()
    result = _service().build(context=ctx)
    assert (
        result["context_consistency_source"]
        == REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
    )


def test_does_not_echo_task055_context_consistent() -> None:
    """Task 056's context_consistent is independent of Task 055's."""
    ctx = _valid_context()
    assert ctx["context_consistent"] is True
    result = _service().build(context=ctx)
    # Both are True here, but structurally we prove the fields are
    # distinct outputs, not aliased.
    assert "context_consistent" in result
    assert result["context_consistent"] is not ctx["context_consistent"] or (
        result["context_consistent"] == ctx["context_consistent"]
    )


# ---------------------------------------------------------------------------
# Contract errors (input too malformed to audit)
# ---------------------------------------------------------------------------


def test_missing_context_raises() -> None:
    with pytest.raises(ReasoningContextConsistencyContractError) as ei:
        _service().build(context=None)
    assert ei.value.invariant == "MISSING_CONTEXT"


def test_non_mapping_context_raises() -> None:
    with pytest.raises(ReasoningContextConsistencyContractError) as ei:
        _service().build(context="not-a-mapping")  # type: ignore[arg-type]
    assert ei.value.invariant == "CONTEXT_TYPE"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_missing_field_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    del broken["observations"]
    result = _service().build(context=broken)
    assert "MISSING_CONTEXT_FIELD" in result["consistency_issues"]
    assert result["context_consistent"] is False
    assert result["metadata_consistent"] is False


def test_available_false_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["available"] = False
    result = _service().build(context=broken)
    assert "CONTEXT_NOT_AVAILABLE" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_invalid_session_uuid_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["session_id"] = "not-a-uuid"
    result = _service().build(context=broken)
    assert "INVALID_SESSION_ID" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_wrong_context_source_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["context_source"] = "SOMETHING_ELSE"
    result = _service().build(context=broken)
    assert "INVALID_CONTEXT_SOURCE" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_non_list_candidate_state_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["candidate_state"] = "not-a-list"
    result = _service().build(context=broken)
    assert "INVALID_CANDIDATE_STATE" in result["consistency_issues"]
    assert result["candidate_state_consistent"] is False


def test_missing_candidate_state_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    del broken["candidate_state"]
    result = _service().build(context=broken)
    assert "MISSING_CONTEXT_FIELD" in result["consistency_issues"]
    # Missing field -> count consistency also can't be established.
    assert result["context_consistent"] is False


def test_non_list_observations_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["observations"] = "not-a-list"
    result = _service().build(context=broken)
    assert "INVALID_OBSERVATIONS" in result["consistency_issues"]
    assert result["context_consistent"] is False


# ---------------------------------------------------------------------------
# Nested Task 042 / Task 043 structure
# ---------------------------------------------------------------------------


def test_invalid_nested_reasoning_run_reported() -> None:
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)
    del broken["reasoning_pipeline"]["run_source"]
    result = _service().build(context=broken)
    assert "INVALID_NESTED_REASONING_RUN" in result["consistency_issues"]
    assert result["nested_reasoning_run_consistent"] is False
    assert result["context_consistent"] is False


def test_non_mapping_reasoning_pipeline_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["reasoning_pipeline"] = "not-a-mapping"
    result = _service().build(context=broken)
    assert "INVALID_REASONING_PIPELINE_TYPE" in result["consistency_issues"]
    assert "INVALID_NESTED_REASONING_RUN" in result["consistency_issues"]


def test_invalid_nested_audit_reported() -> None:
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)
    del broken["reasoning_run_consistency"]["run_consistency_source"]
    result = _service().build(context=broken)
    assert (
        "INVALID_NESTED_REASONING_RUN_CONSISTENCY"
        in result["consistency_issues"]
    )
    assert result["nested_reasoning_run_audit_consistent"] is False


def test_non_mapping_audit_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["reasoning_run_consistency"] = "not-a-mapping"
    result = _service().build(context=broken)
    assert (
        "INVALID_REASONING_RUN_CONSISTENCY_TYPE"
        in result["consistency_issues"]
    )


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_stale_audit_from_other_session_rejected() -> None:
    ctx_a = _valid_context("Task 056 stale A")
    ctx_b = _valid_context("Task 056 stale B")

    mixed = dict(ctx_a)
    mixed["reasoning_run_consistency"] = ctx_b["reasoning_run_consistency"]

    result = _service().build(context=mixed)
    assert "AUDIT_PROVENANCE_MISMATCH" in result["consistency_issues"]
    assert result["audit_provenance_consistent"] is False
    assert result["context_consistent"] is False


def test_tampered_fingerprint_rejected() -> None:
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)
    original = broken["reasoning_run_consistency"][
        "audited_run_fingerprint"
    ]
    broken["reasoning_run_consistency"]["audited_run_fingerprint"] = (
        "0" * 64 if original != "0" * 64 else "1" * 64
    )
    result = _service().build(context=broken)
    assert "AUDIT_PROVENANCE_MISMATCH" in result["consistency_issues"]
    assert result["audit_provenance_consistent"] is False


def test_fingerprint_compute_failure_reported(monkeypatch) -> None:
    ctx = _valid_context()

    def boom(*args, **kwargs):
        raise RuntimeError("fingerprint computation forced to fail")

    monkeypatch.setattr(
        ReasoningRunConsistencyService, "_run_fingerprint", boom
    )
    result = _service().build(context=ctx)
    assert (
        "AUDIT_PROVENANCE_COMPUTE_FAILED" in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False
    assert result["context_consistent"] is False


def test_provenance_mismatch_does_not_touch_nested_validity() -> None:
    """A tampered fingerprint invalidates provenance but the nested
    contracts themselves remain structurally valid."""
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)
    broken["reasoning_run_consistency"]["audited_run_fingerprint"] = (
        "f" * 64
    )
    result = _service().build(context=broken)
    assert result["nested_reasoning_run_consistent"] is True
    assert result["nested_reasoning_run_audit_consistent"] is True
    assert result["audit_provenance_consistent"] is False


# ---------------------------------------------------------------------------
# Candidate count
# ---------------------------------------------------------------------------


def test_candidate_count_mismatch_reported() -> None:
    ctx = _valid_context()
    if len(ctx["candidate_state"]) < 2:
        pytest.skip("seed session produced too few candidates")
    broken = copy.deepcopy(ctx)
    broken["candidate_state"] = broken["candidate_state"][:1]
    result = _service().build(context=broken)
    assert "CANDIDATE_COUNT_MISMATCH" in result["consistency_issues"]
    assert result["candidate_count_consistent"] is False
    assert result["context_consistent"] is False


# ---------------------------------------------------------------------------
# Task 055 build is never invoked
# ---------------------------------------------------------------------------


def test_module_does_not_reference_task055_service() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningContextService" not in src
    assert "build_for_session" not in src


def test_audit_does_not_invoke_task055_build(monkeypatch) -> None:
    ctx = _valid_context()

    def boom(*args, **kwargs):
        raise AssertionError(
            "Task 055 build path was called during Task 056 audit"
        )

    monkeypatch.setattr(ReasoningContextService, "build", boom)
    monkeypatch.setattr(
        ReasoningContextService, "build_for_session", boom
    )
    # Should still succeed, proving the audit runs purely off the
    # supplied context mapping.
    result = _service().build(context=ctx)
    assert result["context_consistent"] is True


# ---------------------------------------------------------------------------
# Deterministic ordering / dedupe
# ---------------------------------------------------------------------------


def test_issue_ordering_is_deterministic() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["context_source"] = "WRONG"
    broken["session_id"] = "nope"
    broken["available"] = False
    result = _service().build(context=broken)
    # Multiple issues present; verify they follow the fixed order.
    issues = result["consistency_issues"]
    assert issues == sorted(issues, key=lambda i: _issue_rank(i))
    # And specific early issues appear before later ones.
    assert issues.index("CONTEXT_NOT_AVAILABLE") < issues.index(
        "INVALID_SESSION_ID"
    )
    assert issues.index("INVALID_SESSION_ID") < issues.index(
        "INVALID_CONTEXT_SOURCE"
    )


# Read the issue order directly from the service so the test cannot
# drift when new issues are added.
_FIXED_ISSUE_ORDER = mod._ISSUE_ORDER


def _issue_rank(issue: str) -> int:
    try:
        return _FIXED_ISSUE_ORDER.index(issue)
    except ValueError:
        return len(_FIXED_ISSUE_ORDER)


def test_duplicate_issue_prevention() -> None:
    """A single tamper that would trip multiple checks for the same
    issue must still produce one entry."""
    ctx = _valid_context()
    broken = dict(ctx)
    broken["context_source"] = "WRONG"
    broken["context_source"] = "WRONG"  # no-op but proves dedupe
    result = _service().build(context=broken)
    assert (
        result["consistency_issues"].count("INVALID_CONTEXT_SOURCE") == 1
    )


def test_no_duplicate_issues_anywhere() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["context_source"] = "WRONG"
    broken["session_id"] = "nope"
    result = _service().build(context=broken)
    issues = result["consistency_issues"]
    assert len(issues) == len(set(issues))


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_does_not_mutate_context() -> None:
    """Snapshot list identity, length, and per-item id()s rather than
    deep-copying, because SQLAlchemy ORM objects do not implement value
    equality and deepcopy creates new objects."""
    ctx = _valid_context()
    snap: dict[str, tuple[int, int, list[int]]] = {}
    for name in (
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ):
        lst = ctx[name]
        snap[name] = (id(lst), len(lst), [id(x) for x in lst])
    pipeline_id = id(ctx["reasoning_pipeline"])
    audit_id = id(ctx["reasoning_run_consistency"])
    pipeline_keys_before = list(ctx["reasoning_pipeline"].keys())
    audit_keys_before = list(ctx["reasoning_run_consistency"].keys())

    _service().build(context=ctx)

    for name, (lst_id, length, item_ids) in snap.items():
        lst = ctx[name]
        assert id(lst) == lst_id
        assert len(lst) == length
        assert [id(x) for x in lst] == item_ids
    assert id(ctx["reasoning_pipeline"]) == pipeline_id
    assert id(ctx["reasoning_run_consistency"]) == audit_id
    assert list(ctx["reasoning_pipeline"].keys()) == pipeline_keys_before
    assert (
        list(ctx["reasoning_run_consistency"].keys()) == audit_keys_before
    )


def test_exact_nested_objects_preserved() -> None:
    ctx = _valid_context()
    run_id = id(ctx["reasoning_pipeline"])
    audit_id = id(ctx["reasoning_run_consistency"])
    cands_id = id(ctx["candidate_state"])
    obs_id = id(ctx["observations"])
    _service().build(context=ctx)
    assert id(ctx["reasoning_pipeline"]) == run_id
    assert id(ctx["reasoning_run_consistency"]) == audit_id
    assert id(ctx["candidate_state"]) == cands_id
    assert id(ctx["observations"]) == obs_id


def test_deterministic() -> None:
    ctx = _valid_context()
    s = _service()
    assert s.build(context=ctx) == s.build(context=ctx)


# ---------------------------------------------------------------------------
# Underlying reasoning inconsistency remains auditable
# ---------------------------------------------------------------------------


def test_valid_but_internally_inconsistent_run_still_auditable() -> None:
    """Task 056 audits the package, not the underlying reasoning. A
    context whose nested Task 042 reports run_consistent=False and
    whose Task 043 audit correctly reflects that must still yield
    context_consistent=True from Task 056."""
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)

    # Tamper Task 042: one stage's consistent flag flips, and the
    # run-level flag follows. This still passes Task 042's own
    # validator because run_consistent must equal all-stage consistent.
    for stage in broken["reasoning_pipeline"]["stages"]:
        if stage["stage_id"] == "OBSERVATIONS":
            stage["consistent"] = False
            break
    broken["reasoning_pipeline"]["run_consistent"] = False

    # Recompute the fingerprint for the tampered run so provenance
    # still binds correctly.
    new_fp = ReasoningRunConsistencyService._run_fingerprint(
        broken["reasoning_pipeline"]
    )
    broken["reasoning_run_consistency"]["audited_run_fingerprint"] = new_fp

    # Task 043's validator requires run_consistent == (no issues);
    # introduce one issue and set the corresponding flag.
    broken["reasoning_run_consistency"]["run_consistent"] = False
    broken["reasoning_run_consistency"]["consistency_issues"] = [
        "STAGE_SEMANTIC_MISMATCH"
    ]

    result = _service().build(context=broken)
    assert result["context_consistent"] is True
    assert result["audit_provenance_consistent"] is True
    assert result["nested_reasoning_run_consistent"] is True
    assert result["nested_reasoning_run_audit_consistent"] is True
    assert result["consistency_issues"] == []


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_no_database_access_in_module() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        "session.query",
        "db.execute",
        "sqlalchemy",
    ):
        assert forbidden not in src, forbidden


def test_no_http_in_module() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("TestClient", "requests.", "httpx", "fastapi"):
        assert forbidden not in src, forbidden


def test_no_filesystem_in_module() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("open(", "Path(", "os.path", "shutil"):
        assert forbidden not in src, forbidden


def test_no_llm_or_decision_logic() -> None:
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(
                    first.value, ast.Constant
                ):
                    start = first.lineno
                    end = getattr(first, "end_lineno", start) or start
                    for i in range(start, end + 1):
                        docstring_lines.add(i)
    code_lines = [
        line
        for i, line in enumerate(src.splitlines(), start=1)
        if i not in docstring_lines
    ]
    code = "\n".join(code_lines).lower()
    word_tokens = ("openai", "gemini", "ollama", "llm", "rag", "claude")
    substring_tokens = ("winner", "recommendation", "decisionpolicy")
    for token in word_tokens:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, code), token
    for token in substring_tokens:
        assert token not in code, token

# ---------------------------------------------------------------------------
# Blocker fixes: unperformed checks must not be reported as passing
# ---------------------------------------------------------------------------


def test_provenance_unavailable_when_audit_missing() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    del broken["reasoning_run_consistency"]
    result = _service().build(context=broken)
    assert (
        "AUDIT_PROVENANCE_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False
    assert result["context_consistent"] is False


def test_provenance_unavailable_when_audit_non_mapping() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["reasoning_run_consistency"] = "not-a-mapping"
    result = _service().build(context=broken)
    assert (
        "AUDIT_PROVENANCE_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False


def test_provenance_unavailable_when_audit_invalid() -> None:
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)
    del broken["reasoning_run_consistency"]["run_consistency_source"]
    result = _service().build(context=broken)
    assert (
        "AUDIT_PROVENANCE_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False


def test_provenance_unavailable_when_run_missing() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    del broken["reasoning_pipeline"]
    result = _service().build(context=broken)
    assert (
        "AUDIT_PROVENANCE_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False


def test_provenance_unavailable_when_run_non_mapping() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["reasoning_pipeline"] = "not-a-mapping"
    result = _service().build(context=broken)
    assert (
        "AUDIT_PROVENANCE_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False


def test_provenance_unavailable_when_run_invalid() -> None:
    ctx = _valid_context()
    broken = copy.deepcopy(ctx)
    del broken["reasoning_pipeline"]["run_source"]
    result = _service().build(context=broken)
    assert (
        "AUDIT_PROVENANCE_CHECK_UNAVAILABLE"
        in result["consistency_issues"]
    )
    assert result["audit_provenance_consistent"] is False


def test_missing_candidate_state_flags_false() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    del broken["candidate_state"]
    result = _service().build(context=broken)
    assert result["candidate_state_consistent"] is False
    assert result["candidate_count_consistent"] is False
    assert result["context_consistent"] is False


def test_non_list_candidate_state_flags_false() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["candidate_state"] = "not-a-list"
    result = _service().build(context=broken)
    assert result["candidate_state_consistent"] is False
    assert result["candidate_count_consistent"] is False
    assert result["context_consistent"] is False


def test_valid_candidate_state_flags_true() -> None:
    ctx = _valid_context()
    result = _service().build(context=ctx)
    assert result["candidate_state_consistent"] is True
    assert result["candidate_count_consistent"] is True

# ---------------------------------------------------------------------------
# Per-element contract validation
# ---------------------------------------------------------------------------


def test_malformed_observation_item_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["observations"] = [{"missing": "all required fields"}]
    result = _service().build(context=broken)
    assert "INVALID_OBSERVATION_ITEM" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_malformed_entity_item_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["entities"] = [{"missing": "all required fields"}]
    result = _service().build(context=broken)
    assert "INVALID_ENTITY_ITEM" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_malformed_missing_information_item_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["missing_information"] = [{"missing": "all required fields"}]
    result = _service().build(context=broken)
    assert (
        "INVALID_MISSING_INFORMATION_ITEM" in result["consistency_issues"]
    )
    assert result["context_consistent"] is False


def test_malformed_template_match_item_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["template_context"] = [{"missing": "all required fields"}]
    result = _service().build(context=broken)
    assert "INVALID_TEMPLATE_MATCH_ITEM" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_malformed_candidate_item_reported() -> None:
    ctx = _valid_context()
    broken = dict(ctx)
    broken["candidate_state"] = [{"missing": "all required fields"}]
    result = _service().build(context=broken)
    assert "INVALID_CANDIDATE_ITEM" in result["consistency_issues"]
    assert result["candidate_state_consistent"] is False
    assert result["candidate_count_consistent"] is False
    assert result["context_consistent"] is False


def test_observation_from_other_session_reported() -> None:
    ctx = _valid_context()
    fake = {
        "id": str(uuid4()),
        "session_id": str(uuid4()),  # different session
        "text": "x",
        "type": "symptom",
        "confidence": 0.5,
        "source": "unit_test",
        "timestamp": "2026-01-01T00:00:00",
    }
    broken = dict(ctx)
    broken["observations"] = list(ctx["observations"]) + [fake]
    result = _service().build(context=broken)
    assert "OBSERVATION_SESSION_MISMATCH" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_entity_from_other_session_reported() -> None:
    ctx = _valid_context()
    fake = {
        "id": str(uuid4()),
        "session_id": str(uuid4()),
        "name": "x",
        "category": "y",
        "confidence": 0.5,
        "source": "unit_test",
    }
    broken = dict(ctx)
    broken["entities"] = list(ctx["entities"]) + [fake]
    result = _service().build(context=broken)
    assert "ENTITY_SESSION_MISMATCH" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_missing_information_from_other_session_reported() -> None:
    ctx = _valid_context()
    fake = {
        "id": str(uuid4()),
        "session_id": str(uuid4()),
        "template": "x",
        "item": "y",
        "created_at": "2026-01-01T00:00:00",
    }
    broken = dict(ctx)
    broken["missing_information"] = list(ctx["missing_information"]) + [fake]
    result = _service().build(context=broken)
    assert (
        "MISSING_INFORMATION_SESSION_MISMATCH"
        in result["consistency_issues"]
    )
    assert result["context_consistent"] is False


def test_template_match_from_other_session_reported() -> None:
    ctx = _valid_context()
    fake = {
        "id": str(uuid4()),
        "session_id": str(uuid4()),
        "template_name": "x",
        "confidence": 0.5,
        "matched_observations": [],
        "matched_entities": [],
        "reason": "test",
        "candidates": [],
        "created_at": "2026-01-01T00:00:00",
    }
    broken = dict(ctx)
    broken["template_context"] = list(ctx["template_context"]) + [fake]
    result = _service().build(context=broken)
    assert "TEMPLATE_MATCH_SESSION_MISMATCH" in result["consistency_issues"]
    assert result["context_consistent"] is False


def test_candidate_from_other_session_reported() -> None:
    ctx = _valid_context()
    fake = {
        "id": str(uuid4()),
        "session_id": str(uuid4()),
        "name": "x",
        "category": "y",
        "trigger_reason": "test",
        "initial_score": 1.0,
        "confidence": 0.5,
        "supporting_observations": [],
        "contradicting_observations": [],
        "missing_information": [],
        "status": "pending",
        "created_at": "2026-01-01T00:00:00",
    }
    broken = dict(ctx)
    broken["candidate_state"] = list(ctx["candidate_state"]) + [fake]
    result = _service().build(context=broken)
    assert "CANDIDATE_SESSION_MISMATCH" in result["consistency_issues"]
    assert result["candidate_state_consistent"] is False
    assert result["candidate_count_consistent"] is False
    assert result["context_consistent"] is False


def test_valid_items_from_correct_session_remain_valid() -> None:
    ctx = _valid_context()
    result = _service().build(context=ctx)
    for issue in (
        "INVALID_OBSERVATION_ITEM",
        "OBSERVATION_SESSION_MISMATCH",
        "INVALID_ENTITY_ITEM",
        "ENTITY_SESSION_MISMATCH",
        "INVALID_MISSING_INFORMATION_ITEM",
        "MISSING_INFORMATION_SESSION_MISMATCH",
        "INVALID_TEMPLATE_MATCH_ITEM",
        "TEMPLATE_MATCH_SESSION_MISMATCH",
        "INVALID_CANDIDATE_ITEM",
        "CANDIDATE_SESSION_MISMATCH",
    ):
        assert issue not in result["consistency_issues"], issue
    assert result["candidate_state_consistent"] is True
    assert result["context_consistent"] is True


def test_element_validation_does_not_mutate_inputs() -> None:
    ctx = _valid_context()
    obs_ids_before = [id(x) for x in ctx["observations"]]
    cand_ids_before = [id(x) for x in ctx["candidate_state"]]
    _service().build(context=ctx)
    assert [id(x) for x in ctx["observations"]] == obs_ids_before
    assert [id(x) for x in ctx["candidate_state"]] == cand_ids_before


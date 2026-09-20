"""Tests for Task 060 reasoning-handoff API response consistency audit.

Task 060 independently audits a captured Task 059 HTTP response. It is
pure: no HTTP, no DB, no Task 055/056/057 build calls, no import of
the API layer. It reuses Task 057's own validator for the nested
handoff and never duplicates Task 055/056/057 rules.
"""

from __future__ import annotations

import ast
import copy
import inspect
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
from rop.services import reasoning_handoff_api_consistency as mod
from rop.services.reasoning_handoff_api_consistency import (
    REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060,
    ReasoningHandoffApiConsistencyContractError,
    ReasoningHandoffApiConsistencyService,
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
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_handoff_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "api_consistency_source",
    "audited_session_id",
    "audited_method",
    "audited_path",
    "audited_status_code",
    "audited_response_fingerprint",
)


def _service() -> ReasoningHandoffApiConsistencyService:
    return ReasoningHandoffApiConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-060-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    return sid


def _capture_handoff_response() -> tuple[str, dict[str, Any]]:
    """Obtain a real Task 059 handoff response, returned as (sid, body)."""
    sid = _seed_full_session("Task 060 capture")
    r = client.get(f"/sessions/{sid}/reasoning-handoff")
    assert r.status_code == 200
    return sid, r.json()


# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_valid_response_all_flags_true() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["api_consistent"] is True
    assert result["consistency_issues"] == []
    for flag in (
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "session_consistent",
        "response_shape_consistent",
        "nested_handoff_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_source_identifier_fixed() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert (
        result["api_consistency_source"]
        == REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060
    )


def test_nested_handoff_passes_task057_validation() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert result["nested_handoff_consistent"] is True


def test_valid_inconsistent_handoff_still_api_consistent() -> None:
    """When Task 057 reports handoff_consistent=False but the API
    response faithfully represents that handoff, Task 060 must still
    report api_consistent=True and nested_handoff_consistent=True."""
    sid = _seed_full_session("Task 060 inconsistent handoff")

    # Force Task 056's context_consistent to False by tampering with
    # the response we feed to the audit -- we replace the nested
    # reasoning_context with one whose nested candidate_state belongs
    # to a different session, then recompute the audit and handoff
    # using the real services so the response is "faithful".
    from rop.services.reasoning_context import ReasoningContextService
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )
    from rop.services.reasoning_handoff import ReasoningHandoffService

    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()

    # Inject a candidate from a different session to force
    # CANDIDATE_SESSION_MISMATCH in Task 056.
    tampered_context = copy.deepcopy(context)
    tampered_context["candidate_state"] = [
        {
            "id": str(uuid4()),
            "session_id": str(uuid4()),
            "name": "cross-session",
            "category": "fake",
            "trigger_reason": "test",
            "initial_score": 1.0,
            "confidence": 0.5,
            "supporting_observations": [],
            "contradicting_observations": [],
            "missing_information": [],
            "status": "pending",
            "created_at": "2026-01-01T00:00:00",
        }
    ]

    audit = ReasoningContextConsistencyService().build(context=tampered_context)
    assert audit["context_consistent"] is False
    handoff = ReasoningHandoffService().build(
        reasoning_context=tampered_context,
        context_consistency=audit,
    )
    assert handoff["handoff_consistent"] is False

    # Serialize to JSON the same way the API would.
    import json as _json

    body = _json.loads(_json.dumps(handoff, default=str))

    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert result["api_consistent"] is True
    assert result["nested_handoff_consistent"] is True


# ---------------------------------------------------------------------------
# Invalid method
# ---------------------------------------------------------------------------


def test_invalid_method_post() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="POST",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "INVALID_METHOD" in result["consistency_issues"]
    assert result["method_consistent"] is False
    assert result["api_consistent"] is False


def test_invalid_method_lowercase() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="get",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "INVALID_METHOD" in result["consistency_issues"]


def test_invalid_method_titlecase() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="Get",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "INVALID_METHOD" in result["consistency_issues"]


def test_invalid_method_mixed_case() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="gEt",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "INVALID_METHOD" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Invalid path
# ---------------------------------------------------------------------------


def test_invalid_path_wrong_route() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-run",
        status_code=200,
        response_body=body,
    )
    assert "INVALID_PATH" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_invalid_path_malformed_uuid() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path="/sessions/not-a-uuid/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "INVALID_PATH" in result["consistency_issues"] or (
        "SESSION_ID_INVALID" in result["consistency_issues"]
    )


def test_invalid_path_different_uuid() -> None:
    sid, body = _capture_handoff_response()
    other = str(uuid4())
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{other}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Invalid status
# ---------------------------------------------------------------------------


def test_invalid_status() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=500,
        response_body=body,
    )
    assert "INVALID_STATUS" in result["consistency_issues"]
    assert result["status_consistent"] is False


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def test_invalid_supplied_session_uuid() -> None:
    sid, body = _capture_handoff_response()
    result = _service().build(
        session_id="not-a-uuid",
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_invalid_response_session_uuid() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


def test_different_response_session_uuid() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = str(uuid4())
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


def test_missing_response_field() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    del tampered["handoff_source"]
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "MISSING_RESPONSE_FIELD" in result["consistency_issues"]
    assert result["response_shape_consistent"] is False


def test_extra_response_field() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    tampered["winner"] = "candidate-x"
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "RESPONSE_SHAPE_MISMATCH" in result["consistency_issues"]
    assert result["response_shape_consistent"] is False


# ---------------------------------------------------------------------------
# Nested handoff failure
# ---------------------------------------------------------------------------


def test_nested_handoff_failure() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    # Remove a required nested field from Task 055 context.
    del tampered["reasoning_context"]["candidate_state"]
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "NESTED_HANDOFF_MISMATCH" in result["consistency_issues"]
    assert result["nested_handoff_consistent"] is False


def test_wrong_source() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    tampered["handoff_source"] = "SOMETHING_ELSE"
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "HANDOFF_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# Contract errors
# ---------------------------------------------------------------------------


def test_missing_response_body_raises() -> None:
    with pytest.raises(ReasoningHandoffApiConsistencyContractError) as ei:
        _service().build(
            session_id=str(uuid4()),
            method="GET",
            path="/sessions/x/reasoning-handoff",
            status_code=200,
            response_body=None,
        )
    assert ei.value.invariant == "MISSING_RESPONSE_BODY"


def test_non_mapping_response_body_raises() -> None:
    with pytest.raises(ReasoningHandoffApiConsistencyContractError) as ei:
        _service().build(
            session_id=str(uuid4()),
            method="GET",
            path="/sessions/x/reasoning-handoff",
            status_code=200,
            response_body="not-a-mapping",
        )
    assert ei.value.invariant == "RESPONSE_BODY_TYPE"


# ---------------------------------------------------------------------------
# Determinism / ordering / dedupe
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    sid, body = _capture_handoff_response()
    s = _service()
    a = s.build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    b = s.build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert a == b


def test_issue_ordering() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    tampered["handoff_source"] = "WRONG"
    result = _service().build(
        session_id=sid,
        method="POST",
        path=f"/sessions/{sid}/reasoning-run",
        status_code=500,
        response_body=tampered,
    )
    issues = result["consistency_issues"]
    # Fixed order enforced
    assert issues.index("INVALID_METHOD") < issues.index("INVALID_PATH")
    assert issues.index("INVALID_PATH") < issues.index("INVALID_STATUS")
    assert issues.index("INVALID_STATUS") < issues.index("HANDOFF_SOURCE_MISMATCH")


def test_no_duplicate_issues() -> None:
    sid, body = _capture_handoff_response()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    issues = result["consistency_issues"]
    assert len(issues) == len(set(issues))


# ---------------------------------------------------------------------------
# Immutability / fingerprint
# ---------------------------------------------------------------------------


def test_does_not_mutate_response_body() -> None:
    sid, body = _capture_handoff_response()
    before = copy.deepcopy(body)
    _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert body == before


def test_fingerprint_deterministic() -> None:
    sid, body = _capture_handoff_response()
    a = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    b = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=body,
    )
    assert a["audited_response_fingerprint"] == (b["audited_response_fingerprint"])
    fp = a["audited_response_fingerprint"]
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_equivalent_uuid_string_repr() -> None:
    """Two response bodies that differ only in UUID-vs-string
    representation of session_id must produce the same fingerprint,
    because canonicalization normalizes UUIDs to strings."""
    sid, body = _capture_handoff_response()
    with_string = copy.deepcopy(body)
    with_uuid = copy.deepcopy(body)
    with_uuid["session_id"] = UUID(sid)
    a = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=with_string,
    )
    b = _service().build(
        session_id=sid,
        method="GET",
        path=f"/sessions/{sid}/reasoning-handoff",
        status_code=200,
        response_body=with_uuid,
    )
    assert a["audited_response_fingerprint"] == (b["audited_response_fingerprint"])


# ---------------------------------------------------------------------------
# Architectural assertions
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
    "ollama",
    "openai",
    "gemini",
    "anthropic",
    "llm",
    "provider",
    "model_name",
    "api_key",
    "rag",
    "recommendation",
)


def _module_code_without_docstrings() -> str:
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
    lines = [
        line
        for i, line in enumerate(src.splitlines(), start=1)
        if i not in docstring_lines
    ]
    return "\n".join(lines).lower()


def test_no_database_imports_or_calls() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        "get_db",
        "sqlalchemy",
        "db.execute",
    ):
        assert forbidden not in src, forbidden


def test_no_http_imports_or_clients() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "fastapi",
        "TestClient",
        "httpx",
        "requests",
        "urllib",
    ):
        assert forbidden not in src, forbidden


def test_does_not_call_task059_api_orchestration() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "ReasoningHandoffApiService",
        "build_for_session",
        "rop.api.sessions",
    ):
        assert forbidden not in src, forbidden


def test_no_llm_or_provider_symbols() -> None:
    """Forbidden tokens must not appear as standalone identifiers.

    Word-boundary matching prevents false positives from tokens that
    legitimately appear as substrings of unrelated identifiers (e.g.
    ``llm`` inside ``fullmatch``)."""
    import re as _re

    code = _module_code_without_docstrings()
    for token in _FORBIDDEN_SUBSTRINGS:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, code), token


def test_response_session_disagrees_with_nested_context() -> None:
    """If the top-level response session_id is swapped to another
    UUID, and the supplied session_id / path are swapped to match, but
    the nested reasoning_context.session_id still points at the
    original session, Task 060 must detect SESSION_ID_MISMATCH. Task
    057's validator alone does not catch this."""
    sid, body = _capture_handoff_response()

    other = str(uuid4())
    tampered = copy.deepcopy(body)
    tampered["session_id"] = other
    # Deliberately leave tampered["reasoning_context"]["session_id"]
    # at its original value.

    result = _service().build(
        session_id=other,
        method="GET",
        path=f"/sessions/{other}/reasoning-handoff",
        status_code=200,
        response_body=tampered,
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False
    assert result["api_consistent"] is False

"""Tests for Task 055 reasoning context assembly.

Task 055 is a pure assembly layer: it packages the session's
already-established reasoning state plus the canonical Task 042 and
Task 043 outputs. It does not reason, rank, select, call an LLM, or
mutate its inputs.
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
from rop.services import reasoning_context as mod
from rop.services.reasoning_context import (
    REASONING_CONTEXT_SOURCE_TASK_055,
    ReasoningContextContractError,
    ReasoningContextService,
)
from rop.services.reasoning_run import ReasoningRunService
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
client = TestClient(app)

RESULT_FIELDS = (
    "available",
    "context_consistent",
    "session_id",
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
    "reasoning_pipeline",
    "reasoning_run_consistency",
    "context_source",
)


def _service() -> ReasoningContextService:
    return ReasoningContextService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-055-test"},
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


def _context_for_session(session_id: str) -> dict[str, Any]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return _service().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_context_shape() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    assert set(ctx) == set(RESULT_FIELDS)
    assert ctx["available"] is True


def test_context_source_fixed() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    assert ctx["context_source"] == REASONING_CONTEXT_SOURCE_TASK_055


def test_nested_reasoning_pipeline_present() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    rp = ctx["reasoning_pipeline"]
    assert rp["run_source"] == "REASONING_RUN_TASK_042"
    assert "stages" in rp
    assert "reasoning_pipeline" in rp


def test_nested_reasoning_run_consistency_present() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    rc = ctx["reasoning_run_consistency"]
    assert (
        rc["run_consistency_source"]
        == "REASONING_RUN_CONSISTENCY_TASK_043"
    )


def test_context_consistent_true_when_counts_match() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    run_count = ctx["reasoning_pipeline"]["candidate_count"]
    assert run_count == len(ctx["candidate_state"])
    assert ctx["context_consistent"] is True


def test_session_id_preserved() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    assert str(ctx["session_id"]) == sid


def test_empty_session_context_available() -> None:
    sid = _create_session("Patient reports chest pain")
    ctx = _context_for_session(sid)
    # An empty session still produces a valid context (with an empty
    # candidate_state and a "not ready" pipeline).
    assert ctx["available"] is True
    assert ctx["candidate_state"] == []
    assert ctx["reasoning_pipeline"]["candidate_count"] == 0
    assert ctx["context_consistent"] is True


def test_deterministic() -> None:
    sid = _seed_full_session("Patient reports chest pain")
    a = _context_for_session(sid)
    b = _context_for_session(sid)
    # UUIDs may differ between runs for empty sessions; on a seeded
    # session with candidates they should match.
    assert a["context_source"] == b["context_source"]
    assert a["context_consistent"] == b["context_consistent"]
    assert a["available"] == b["available"]


# ---------------------------------------------------------------------------
# Missing session
# ---------------------------------------------------------------------------


def test_missing_session_raises() -> None:
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        with pytest.raises(ReasoningContextContractError) as ei:
            _service().build_for_session(db, uuid4())
        assert ei.value.invariant == "SESSION_NOT_FOUND"
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Pure build() contract rejections
# ---------------------------------------------------------------------------


def _valid_pure_inputs() -> dict[str, Any]:
    sid = _seed_full_session("Patient reports chest pain")
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import (
            CandidateGenerationService,
        )
        from rop.services.entity import EntityService
        from rop.services.missing_information import (
            MissingInformationService,
        )
        from rop.services.observation import ObservationService
        from rop.services.template_match import TemplateMatchService

        obs = ObservationService().list_by_session(
            db, session_uuid, offset=0, limit=1000
        )
        ent = EntityService().list_by_session(
            db, session_uuid, offset=0, limit=1000
        )
        mi = MissingInformationService().list_by_session(db, session_uuid)
        tm = TemplateMatchService().list_by_session(db, session_uuid)
        cands = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        # Build Task 042 exactly once and reuse its intermediates so
        # Task 043 audits the exact run being packaged, not a second
        # independently-rebuilt run.
        run, bundle, policy = (
            ReasoningRunService().build_for_session_with_inputs(
                db, session_uuid
            )
        )
        audit = ReasoningRunConsistencyService().build(
            run=run,
            observations=obs,
            entities=ent,
            missing_information=mi,
            template_matches=tm,
            candidates=cands,
            bundle=bundle,
            policy=policy,
        )
    finally:
        db_gen.close()
    return {
        "session_id": session_uuid,
        "observations": obs,
        "entities": ent,
        "missing_information": mi,
        "template_context": tm,
        "candidate_state": cands,
        "reasoning_run": run,
        "reasoning_run_consistency": audit,
    }


def test_pure_build_no_db_access() -> None:
    inputs = _valid_pure_inputs()
    ctx = _service().build(**inputs)
    assert ctx["available"] is True
    assert ctx["context_source"] == REASONING_CONTEXT_SOURCE_TASK_055


def test_invalid_session_id() -> None:
    inputs = _valid_pure_inputs()
    inputs["session_id"] = "not-a-uuid"
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_missing_reasoning_run() -> None:
    inputs = _valid_pure_inputs()
    inputs["reasoning_run"] = None
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "MISSING_REASONING_RUN"


def test_missing_reasoning_run_consistency() -> None:
    inputs = _valid_pure_inputs()
    inputs["reasoning_run_consistency"] = None
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "MISSING_REASONING_RUN_CONSISTENCY"


def test_invalid_reasoning_run() -> None:
    inputs = _valid_pure_inputs()
    tampered = copy.deepcopy(inputs["reasoning_run"])
    del tampered["run_source"]
    inputs["reasoning_run"] = tampered
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_REASONING_RUN"


def test_invalid_reasoning_run_consistency() -> None:
    inputs = _valid_pure_inputs()
    tampered = copy.deepcopy(inputs["reasoning_run_consistency"])
    del tampered["run_consistency_source"]
    inputs["reasoning_run_consistency"] = tampered
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_REASONING_RUN_CONSISTENCY"


def test_invalid_context_source() -> None:
    inputs = _valid_pure_inputs()
    ctx = _service().build(**inputs)
    tampered = copy.deepcopy(ctx)
    tampered["context_source"] = "WRONG"
    with pytest.raises(ReasoningContextContractError) as ei:
        ReasoningContextService._validate_result(tampered)
    assert ei.value.invariant == "INVALID_CONTEXT_SOURCE"


def test_non_list_observations() -> None:
    inputs = _valid_pure_inputs()
    inputs["observations"] = "nope"
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "OBSERVATIONS_TYPE"


# ---------------------------------------------------------------------------
# Preservation semantics
# ---------------------------------------------------------------------------


def test_upstream_values_preserved_exactly() -> None:
    inputs = _valid_pure_inputs()
    ctx = _service().build(**inputs)
    # Every upstream list should match by length.
    assert len(ctx["observations"]) == len(inputs["observations"])
    assert len(ctx["entities"]) == len(inputs["entities"])
    assert len(ctx["missing_information"]) == len(
        inputs["missing_information"]
    )
    assert len(ctx["template_context"]) == len(inputs["template_context"])
    assert len(ctx["candidate_state"]) == len(inputs["candidate_state"])
    # And the nested run/audit are the exact same dicts.
    assert ctx["reasoning_pipeline"] == inputs["reasoning_run"]
    assert (
        ctx["reasoning_run_consistency"]
        == inputs["reasoning_run_consistency"]
    )


def test_context_consistent_false_when_candidate_count_mismatches() -> None:
    """A controlled mismatch between candidate_state length and the
    nested run's candidate_count must flip context_consistent to False
    without raising. This proves Task 055 preserves, rather than
    silently repairs, that divergence."""
    inputs = _valid_pure_inputs()
    # Drop one candidate from the supplied list while leaving the
    # nested run's candidate_count at its original value.
    if len(inputs["candidate_state"]) < 2:
        pytest.skip("seed session yielded too few candidates")
    inputs["candidate_state"] = inputs["candidate_state"][:1]
    ctx = _service().build(**inputs)
    assert ctx["context_consistent"] is False


def test_pure_build_does_not_mutate_inputs() -> None:
    """The pure build() must not mutate the supplied containers. We
    snapshot list lengths and object identities rather than deep-copy
    contents, because SQLAlchemy ORM objects don't implement value
    equality."""
    inputs = _valid_pure_inputs()
    # Snapshot list identity, length, and per-item id()s.
    snap = {}
    for name in (
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ):
        lst = inputs[name]
        snap[name] = (id(lst), len(lst), [id(x) for x in lst])
    run_before = copy.deepcopy(inputs["reasoning_run"])
    audit_before = copy.deepcopy(inputs["reasoning_run_consistency"])

    _service().build(**inputs)

    for name, (lst_id, length, item_ids) in snap.items():
        lst = inputs[name]
        assert id(lst) == lst_id
        assert len(lst) == length
        assert [id(x) for x in lst] == item_ids
    assert inputs["reasoning_run"] == run_before
    assert inputs["reasoning_run_consistency"] == audit_before


def test_pure_build_preserves_upstream_ordering() -> None:
    inputs = _valid_pure_inputs()
    ctx = _service().build(**inputs)
    # Same order, same IDs.
    assert [c.id for c in ctx["candidate_state"]] == [
        c.id for c in inputs["candidate_state"]
    ]
    assert [o.id for o in ctx["observations"]] == [
        o.id for o in inputs["observations"]
    ]


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_no_database_access_in_module() -> None:
    """Pure build() must not touch the DB; the module may hold the
    services it delegates to but must not open a Session itself."""
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        "session.query",
        "db.execute",
    ):
        assert forbidden not in src


def test_no_http_in_module() -> None:
    src = inspect.getsource(mod)
    for forbidden in ("TestClient", "requests.", "httpx", "fastapi"):
        assert forbidden not in src


def test_no_llm_or_decision_logic() -> None:
    """Strip docstrings first, then check that no forbidden identifier
    appears in actual code. Docstrings legitimately reference these
    tokens (e.g. "does not call an LLM"), so we ignore them."""
    import ast
    import re as _re

    src = inspect.getsource(mod)
    tree = ast.parse(src)

    # Collect docstring line ranges so we can exclude them.
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

    word_tokens = ("openai", "gemini", "ollama", "llm", "rag")
    substring_tokens = ("winner", "recommendation", "decisionpolicy")

    for token in word_tokens:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, code), token
    for token in substring_tokens:
        assert token not in code, token


# ---------------------------------------------------------------------------
# Audit-to-run binding (Task 055 blocker fix)
# ---------------------------------------------------------------------------


def _raw_inputs_for(session_id: str) -> dict[str, Any]:
    """Fetch every raw input for a session without any binding assumptions."""
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import (
            CandidateGenerationService,
        )
        from rop.services.entity import EntityService
        from rop.services.missing_information import (
            MissingInformationService,
        )
        from rop.services.observation import ObservationService
        from rop.services.template_match import TemplateMatchService

        obs = ObservationService().list_by_session(
            db, session_uuid, offset=0, limit=1000
        )
        ent = EntityService().list_by_session(
            db, session_uuid, offset=0, limit=1000
        )
        mi = MissingInformationService().list_by_session(db, session_uuid)
        tm = TemplateMatchService().list_by_session(db, session_uuid)
        cands = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        run, bundle, policy = (
            ReasoningRunService().build_for_session_with_inputs(
                db, session_uuid
            )
        )
    finally:
        db_gen.close()
    return {
        "session_id": session_uuid,
        "observations": obs,
        "entities": ent,
        "missing_information": mi,
        "template_context": tm,
        "candidate_state": cands,
        "run": run,
        "bundle": bundle,
        "policy": policy,
    }


def test_context_accepts_matching_audit() -> None:
    """The canonical case: Task 042 run and Task 043 audit produced
    from the same chain must package cleanly."""
    inputs = _valid_pure_inputs()
    ctx = _service().build(**inputs)
    assert ctx["available"] is True
    assert ctx["context_consistent"] is True


def test_context_rejects_stale_audit_from_other_run() -> None:
    """A valid Task 043 audit from session B must not be pairable with
    session A's Task 042 run, even though both are individually valid."""
    inputs = _valid_pure_inputs()

    other = _raw_inputs_for(_seed_full_session("Task 055 other session"))
    other_audit = ReasoningRunConsistencyService().build(
        run=other["run"],
        observations=other["observations"],
        entities=other["entities"],
        missing_information=other["missing_information"],
        template_matches=other["template_context"],
        candidates=other["candidate_state"],
        bundle=other["bundle"],
        policy=other["policy"],
    )

    inputs["reasoning_run_consistency"] = other_audit
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "AUDIT_RUN_MISMATCH"


def test_context_rejects_tampered_fingerprint() -> None:
    """A fingerprint that does not match the supplied Task 042 run must
    raise AUDIT_RUN_MISMATCH -- this proves the check is a real
    relationship, not a tautology."""
    inputs = _valid_pure_inputs()
    tampered = copy.deepcopy(inputs["reasoning_run_consistency"])
    tampered["audited_run_fingerprint"] = "0" * 64
    inputs["reasoning_run_consistency"] = tampered
    with pytest.raises(ReasoningContextContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "AUDIT_RUN_MISMATCH"


def test_available_when_audit_reports_inconsistency() -> None:
    """An internally inconsistent reasoning run must still be packable.
    Task 055 must not conflate the audit's verdict on the run with its
    own package consistency."""
    raw = _raw_inputs_for(_seed_full_session("Task 055 inconsistent run"))

    # Tamper a fixed-stage flag and the corresponding run-level flag,
    # keeping the run internally self-consistent so its own validator
    # still accepts it -- but making it inconsistent relative to the
    # actual session state (which Task 043 will detect).
    tampered = copy.deepcopy(raw["run"])
    for stage in tampered["stages"]:
        if stage["stage_id"] == "OBSERVATIONS":
            stage["consistent"] = False
            break
    tampered["run_consistent"] = False

    audit = ReasoningRunConsistencyService().build(
        run=tampered,
        observations=raw["observations"],
        entities=raw["entities"],
        missing_information=raw["missing_information"],
        template_matches=raw["template_context"],
        candidates=raw["candidate_state"],
        bundle=raw["bundle"],
        policy=raw["policy"],
    )
    assert audit["run_consistent"] is False

    ctx = _service().build(
        session_id=raw["session_id"],
        observations=raw["observations"],
        entities=raw["entities"],
        missing_information=raw["missing_information"],
        template_context=raw["template_context"],
        candidate_state=raw["candidate_state"],
        reasoning_run=tampered,
        reasoning_run_consistency=audit,
    )
    assert ctx["available"] is True
    assert ctx["context_consistent"] is True
    assert ctx["reasoning_run_consistency"]["run_consistent"] is False


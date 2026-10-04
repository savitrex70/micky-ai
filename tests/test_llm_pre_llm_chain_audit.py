"""Tests for Task 110 pre-LLM chain audit.

Independent end-to-end audit of the model-independent-to-LLM-boundary
chain: 055 context -> 056 consistency -> 057 boundary -> 103 audit ->
104 serialization -> 105 output validation -> 106 normalization ->
107 isolation -> 108 privacy -> 109 inspection.

Conventions mirror tests/test_llm_reasoning.py: sqlite-memory
TestClient, seeded sessions, fake provider pattern. Every stage uses
only real canonical functions. One full session is seeded and reused.
"""

from __future__ import annotations

import copy
import importlib
import inspect
import json
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
from rop.services.llm_output_validation import (
    LLM_OUTPUT_VALIDATION_SOURCE_TASK_105,
    validate_raw_proposal,
)
from rop.services.llm_privacy_boundary import (
    LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108,
    check_adversarial_text,
    check_payload_privacy,
    validate_llm_input_boundary,
)
from rop.services.llm_proposal_normalization import (
    LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106,
    compute_normalized_fingerprint,
    normalize_proposal,
    validate_normalized,
)
from rop.services.llm_provider_isolation import (
    LLM_PROVIDER_ISOLATION_SOURCE_TASK_107,
    ProviderFailureBoundary,
)
from rop.services.llm_reasoning import (
    LLM_REASONING_TASK_057,
    LLMReasoningService,
)
from rop.services.llm_reasoning_audit import (
    LLM_REASONING_AUDIT_TASK_103,
    LLMReasoningAuditService,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderResponse,
)
from rop.services.llm_request_serialization import (
    LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104,
    compute_fingerprint,
    serialize_context,
    to_json_safe,
    validate_payload,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_context_consistency import (
    REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056,
    ReasoningContextConsistencyService,
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


# ---------------------------------------------------------------------------
# Fake providers (only fakes; no real provider dependency)
# ---------------------------------------------------------------------------


class FakeProvider:
    """Injectable fake provider used for the whole chain."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        response_text: str | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls = 0
        self.last_request: Any = None

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        self.calls += 1
        self.last_request = request
        if self.raise_error is not None:
            raise self.raise_error
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=self.response_text or "",
        )


class FakeSuspiciousProvider:
    """Fake provider carrying DB-like attributes for isolation checks."""

    provider_name = "fake-suspicious"
    model_name = "fake-model"
    db_session = None
    engine = None

    def commit(self) -> None:
        pass

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text='{"candidate_assessments": []}',
        )


# ---------------------------------------------------------------------------
# Session helpers (ONE full session is seeded and reused)
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-110-test"},
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


def _seed_empty_session(user_input: str) -> str:
    return _create_session(user_input)


def _open_db() -> Any:
    gen = app.dependency_overrides[get_db]()
    return gen, next(gen)


def _session_count() -> int:
    from rop.models.reasoning_session import ReasoningSession

    gen, db = _open_db()
    try:
        return int(db.query(ReasoningSession).count())
    finally:
        gen.close()


def _valid_model_output(context: dict[str, Any]) -> str:
    assessments = []
    for candidate in context["candidate_state"]:
        assessments.append(
            {
                "candidate_id": str(candidate.id),
                "assessment": "UNCLEAR",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "insufficient evidence to decide",
                "uncertainty_flags": ["insufficient_evidence"],
            }
        )
    return json.dumps({"candidate_assessments": assessments})


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _freeze(v) for k, v in sorted(value.items())}
    try:
        from collections.abc import Mapping as _Mapping

        if isinstance(value, _Mapping):
            items = sorted(value.items(), key=lambda kv: str(kv[0]))
            return {str(k): _freeze(v) for k, v in items}
    except Exception:
        pass
    if isinstance(value, (list, tuple)):
        return [_freeze(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return {
            str(k): _freeze(v)
            for k, v in sorted(attrs.items(), key=lambda kv: str(kv[0]))
            if k != "_sa_instance_state"
        }
    return repr(value)


_CHAIN_CACHE: dict[str, Any] = {}
_EMPTY_CACHE: dict[str, Any] = {}


def _get_chain() -> dict[str, Any]:
    if _CHAIN_CACHE:
        return _CHAIN_CACHE
    sid = _seed_full_session("Task 110 chain audit")
    session_uuid = UUID(sid)
    gen, db = _open_db()
    try:
        context = ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        gen.close()
    consistency = ReasoningContextConsistencyService().build(context=context)
    serialized = serialize_context(context)
    fingerprint = compute_fingerprint(serialized)
    provider = FakeProvider(response_text=_valid_model_output(context))
    proposal = LLMReasoningService(provider=provider).build(context=context)
    audit = LLMReasoningAuditService.build(proposal=proposal, context=context)
    normalized = normalize_proposal(proposal)
    normalized_fp = compute_normalized_fingerprint(normalized)
    _CHAIN_CACHE.update(
        {
            "session_id": sid,
            "session_uuid": session_uuid,
            "context": context,
            "consistency": consistency,
            "serialized": serialized,
            "fingerprint": fingerprint,
            "provider": provider,
            "proposal": proposal,
            "audit": audit,
            "normalized": normalized,
            "normalized_fp": normalized_fp,
        }
    )
    return _CHAIN_CACHE


def _get_empty_chain() -> dict[str, Any]:
    if _EMPTY_CACHE:
        return _EMPTY_CACHE
    sid = _seed_empty_session("Task 110 empty session")
    session_uuid = UUID(sid)
    gen, db = _open_db()
    try:
        context = ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        gen.close()
    unavailable = dict(context)
    unavailable["available"] = False
    unavailable["context_consistent"] = False
    provider = FakeProvider(response_text="")
    proposal = LLMReasoningService(provider=provider).build(context=unavailable)
    audit = LLMReasoningAuditService.build(proposal=proposal, context=unavailable)
    _EMPTY_CACHE.update(
        {
            "session_id": sid,
            "session_uuid": session_uuid,
            "context": context,
            "unavailable_context": unavailable,
            "provider": provider,
            "proposal": proposal,
            "audit": audit,
        }
    )
    return _EMPTY_CACHE


def _resolve_inspection() -> tuple[Any, Any, Any, Any]:
    try:
        module = importlib.import_module("rop.services.llm_proposal_inspection")
    except ImportError as exc:
        pytest.skip(f"Task 109 inspection module missing: {exc}")
    service = getattr(module, "LLMProposalInspectionService", None)
    error = getattr(module, "LLMProposalInspectionContractError", None)
    constant = getattr(module, "LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109", None)
    if service is None or error is None or constant is None:
        pytest.skip(
            "Task 109 inspection interface incomplete "
            "(expected LLMProposalInspectionService, "
            "LLMProposalInspectionContractError, "
            "LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109)"
        )
    return module, service, error, constant


def _build_inspection(proposal: dict[str, Any]) -> dict[str, Any]:
    _, service, _, _ = _resolve_inspection()
    build = getattr(service, "build", None)
    assert build is not None
    return dict(build(proposal=proposal))


# ---------------------------------------------------------------------------
# Session identity through all stages
# ---------------------------------------------------------------------------


def test_chain_session_identity_exact_through_all_stages() -> None:
    chain = _get_chain()
    sid = chain["session_id"]
    context = chain["context"]
    proposal = chain["proposal"]
    serialized = chain["serialized"]
    normalized = chain["normalized"]

    assert str(context["session_id"]) == sid
    assert str(UUID(sid)) == sid
    assert str(proposal["session_id"]) == sid
    assert str(serialized["session_id"]) == sid
    assert str(normalized["session_id"]) == sid

    _, service, _, _ = _resolve_inspection()
    inspection = dict(service.build(proposal=proposal))
    assert str(inspection["session_id"]) == sid


# ---------------------------------------------------------------------------
# Fingerprint equality (057 == recomputed via compute_fingerprint)
# ---------------------------------------------------------------------------


def test_context_fingerprint_equality_recomputed() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    provider = chain["provider"]

    recomputed = compute_fingerprint(serialize_context(context))
    assert proposal["context_fingerprint"] == recomputed
    assert chain["fingerprint"] == recomputed
    assert provider.last_request is not None
    assert provider.last_request.context_fingerprint == recomputed
    assert len(recomputed) == 64
    assert all(c in "0123456789abcdef" for c in recomputed)


# ---------------------------------------------------------------------------
# Provenance / source identifiers
# ---------------------------------------------------------------------------


def test_provenance_source_identifiers_present_and_correct() -> None:
    chain = _get_chain()
    proposal = chain["proposal"]
    audit = chain["audit"]

    assert LLM_REASONING_TASK_057 == "LLM_REASONING_TASK_057"
    assert proposal["llm_reasoning_source"] == LLM_REASONING_TASK_057
    assert LLM_REASONING_AUDIT_TASK_103 == "LLM_REASONING_AUDIT_TASK_103"
    assert audit["audit_source"] == LLM_REASONING_AUDIT_TASK_103
    assert (
        LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104
        == "LLM_REQUEST_SERIALIZATION_TASK_104"
    )
    assert LLM_OUTPUT_VALIDATION_SOURCE_TASK_105 == "LLM_OUTPUT_VALIDATION_TASK_105"
    assert (
        LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106
        == "LLM_PROPOSAL_NORMALIZATION_TASK_106"
    )
    assert LLM_PROVIDER_ISOLATION_SOURCE_TASK_107 == "LLM_PROVIDER_ISOLATION_TASK_107"
    assert LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108 == "LLM_PRIVACY_BOUNDARY_TASK_108"

    _, _, _, constant = _resolve_inspection()
    assert constant == "LLM_PROPOSAL_INSPECTION_TASK_109"
    inspection = _build_inspection(proposal)
    assert inspection["inspection_source"] == constant

    context = chain["context"]
    consistency = chain["consistency"]
    assert context["context_source"] == "REASONING_CONTEXT_TASK_055"
    assert (
        consistency["context_consistency_source"]
        == REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
    )
    assert (
        REASONING_CONTEXT_CONSISTENCY_SOURCE_TASK_056
        == "REASONING_CONTEXT_CONSISTENCY_TASK_056"
    )


# ---------------------------------------------------------------------------
# Deterministic serialization
# ---------------------------------------------------------------------------


def test_deterministic_serialization_twice_equal() -> None:
    chain = _get_chain()
    context = chain["context"]
    first = serialize_context(context)
    second = serialize_context(context)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert compute_fingerprint(first) == compute_fingerprint(second)
    assert validate_payload(first) == []
    assert to_json_safe({"b": 1, "a": 2}) == {"a": 2, "b": 1}


# ---------------------------------------------------------------------------
# Candidate / evidence reference integrity
# ---------------------------------------------------------------------------


def test_candidate_evidence_reference_integrity() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    normalized = chain["normalized"]

    candidate_ids = {str(c.id) for c in context["candidate_state"]}
    observation_ids = {str(o.id) for o in context["observations"]}
    entity_ids = {str(e.id) for e in context["entities"]}
    evidence_ids = observation_ids | entity_ids
    missing_ids = {str(m.id) for m in context["missing_information"]}

    assert len(proposal["candidate_assessments"]) == len(candidate_ids)
    seen: set[str] = set()
    for item in proposal["candidate_assessments"]:
        cid = str(item["candidate_id"])
        assert cid in candidate_ids
        assert cid not in seen
        seen.add(cid)
        for eid in item["supporting_evidence_ids"]:
            assert str(eid) in evidence_ids
        for eid in item["contradicting_evidence_ids"]:
            assert str(eid) in evidence_ids
        for mid in item["unresolved_information_ids"]:
            assert str(mid) in missing_ids

    norm_ids = [str(a["candidate_id"]) for a in normalized["candidate_assessments"]]
    assert norm_ids == [
        str(a["candidate_id"]) for a in proposal["candidate_assessments"]
    ]

    raw = json.loads(_valid_model_output(context))
    assert validate_raw_proposal(raw, context) == []
    assert validate_normalized(normalized) == []


# ---------------------------------------------------------------------------
# Legitimate unavailable and False states
# ---------------------------------------------------------------------------


def test_legitimate_unavailable_empty_session_false_states() -> None:
    empty = _get_empty_chain()
    proposal = empty["proposal"]
    audit = empty["audit"]
    provider = empty["provider"]

    assert proposal["available"] is False
    assert proposal["proposal_consistent"] is False
    assert proposal["candidate_assessments"] == []
    assert provider.calls == 0
    assert audit["available"] is False
    assert audit["proposal_consistent"] is False
    assert audit["candidate_assessments_consistent"] is True

    inspection = _build_inspection(proposal)
    assert inspection["available"] is False
    assert inspection["proposal_consistent"] is False
    assert inspection["candidate_assessments"] == []


# ---------------------------------------------------------------------------
# No fallback to false success
# ---------------------------------------------------------------------------


def test_no_fallback_tampered_fingerprint_rejected_at_audit() -> None:
    chain = _get_chain()
    proposal = chain["proposal"]
    tampered = copy.deepcopy(proposal)
    tampered["context_fingerprint"] = "g" * 64
    audit = LLMReasoningAuditService.build(proposal=tampered, context=chain["context"])
    assert audit["fingerprint_consistent"] is False
    assert audit["proposal_consistent"] is False
    assert "invalid_fingerprint_format" in audit["consistency_issues"]
    assert tampered["context_fingerprint"] != proposal["context_fingerprint"]


def test_no_fallback_tampered_candidate_id_rejected_at_105() -> None:
    chain = _get_chain()
    context = chain["context"]
    raw = json.loads(_valid_model_output(context))
    raw["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    issues = validate_raw_proposal(raw, context)
    assert len(issues) > 0
    assert any("not found in context" in i for i in issues)


def test_tampered_fingerprint_swap_never_repaired() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    tampered = copy.deepcopy(proposal)
    tampered["context_fingerprint"] = "0" * 64
    if tampered["context_fingerprint"] == proposal["context_fingerprint"]:
        tampered["context_fingerprint"] = "f" * 64
    recomputed = compute_fingerprint(serialize_context(context))
    assert tampered["context_fingerprint"] != recomputed
    audit = LLMReasoningAuditService.build(proposal=tampered, context=context)
    assert audit["available"] == proposal["available"]
    assert tampered["context_fingerprint"] != recomputed


def test_tampered_extra_top_level_field_detected_later() -> None:
    chain = _get_chain()
    context = chain["context"]
    raw = json.loads(_valid_model_output(context))
    raw["winner"] = "candidate-x"
    issues = validate_raw_proposal(raw, context)
    assert len(issues) > 0
    assert any("Top-level schema validation failed" in i for i in issues)
    assert "winner" in raw


def test_tampered_reordered_assessments_detected_later() -> None:
    chain = _get_chain()
    context = chain["context"]
    if len(context["candidate_state"]) < 2:
        pytest.skip("seed session produced only one candidate")
    raw = json.loads(_valid_model_output(context))
    raw["candidate_assessments"] = list(reversed(raw["candidate_assessments"]))
    issues = validate_raw_proposal(raw, context)
    assert len(issues) > 0
    assert any("order does not match" in i for i in issues)


# ---------------------------------------------------------------------------
# Deterministic repeated full chain
# ---------------------------------------------------------------------------


def test_deterministic_repeated_full_chain_twice_equal() -> None:
    first = _get_chain()
    context = first["context"]
    snapshot = copy.deepcopy(first["proposal"])

    provider = FakeProvider(response_text=_valid_model_output(context))
    second_proposal = LLMReasoningService(provider=provider).build(context=context)
    assert second_proposal == snapshot
    assert second_proposal == first["proposal"]

    second_audit = LLMReasoningAuditService.build(
        proposal=second_proposal, context=context
    )
    assert second_audit == first["audit"]
    assert normalize_proposal(second_proposal) == first["normalized"]
    assert (
        compute_normalized_fingerprint(normalize_proposal(second_proposal))
        == first["normalized_fp"]
    )
    assert serialize_context(context) == first["serialized"]

    inspection_one = _build_inspection(snapshot)
    inspection_two = _build_inspection(second_proposal)
    assert inspection_one == inspection_two


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_input_immutability_deepcopy_before_after_each_stage() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    serialized = chain["serialized"]
    normalized = chain["normalized"]

    frozen_context = _freeze(context)
    frozen_proposal = copy.deepcopy(proposal)
    frozen_serialized = copy.deepcopy(serialized)
    frozen_normalized = copy.deepcopy(normalized)

    ReasoningContextConsistencyService().build(context=context)
    assert _freeze(context) == frozen_context

    serialize_context(context)
    assert _freeze(context) == frozen_context

    validate_raw_proposal(json.loads(_valid_model_output(context)), context)
    assert _freeze(context) == frozen_context

    LLMReasoningAuditService.build(proposal=proposal, context=context)
    assert proposal == frozen_proposal

    normalize_proposal(proposal)
    assert proposal == frozen_proposal

    validate_normalized(normalized)
    assert normalized == frozen_normalized

    check_payload_privacy(serialized)
    validate_llm_input_boundary(serialized)
    assert serialized == frozen_serialized

    _build_inspection(proposal)
    assert proposal == frozen_proposal


# ---------------------------------------------------------------------------
# No DB writes from pure stages
# ---------------------------------------------------------------------------


def test_no_db_writes_from_pure_stages() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    serialized = chain["serialized"]
    normalized = chain["normalized"]

    before = _session_count()
    ReasoningContextConsistencyService().build(context=context)
    serialize_context(context)
    compute_fingerprint(serialized)
    validate_payload(serialized)
    to_json_safe({"a": [UUID(chain["session_id"])]})
    validate_raw_proposal(json.loads(_valid_model_output(context)), context)
    LLMReasoningAuditService.build(proposal=proposal, context=context)
    normalize_proposal(proposal)
    compute_normalized_fingerprint(normalized)
    validate_normalized(normalized)
    ProviderFailureBoundary.normalize_failure(RuntimeError("boom"))
    ProviderFailureBoundary.sanitize_provider_text("text")
    ProviderFailureBoundary.check_provider_cannot_mutate_rop(chain["provider"])
    check_payload_privacy(serialized)
    check_adversarial_text("routine clinical note")
    validate_llm_input_boundary(serialized)
    _build_inspection(proposal)
    after = _session_count()
    assert before == after


# ---------------------------------------------------------------------------
# No network activity
# ---------------------------------------------------------------------------


def test_no_network_activity_no_socket_imports() -> None:
    import ast as _ast

    import rop.services.llm_output_validation as m105
    import rop.services.llm_privacy_boundary as m108
    import rop.services.llm_proposal_normalization as m106
    import rop.services.llm_provider_isolation as m107
    import rop.services.llm_reasoning as m057
    import rop.services.llm_reasoning_audit as m103
    import rop.services.llm_request_serialization as m104
    import rop.services.reasoning_context as m055
    import rop.services.reasoning_context_consistency as m056

    modules = [m055, m056, m057, m103, m104, m105, m106, m107, m108]
    try:
        mod109 = importlib.import_module("rop.services.llm_proposal_inspection")
        modules.append(mod109)
    except ImportError:
        pass
    for mod in modules:
        src = inspect.getsource(mod)
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in (
                        "socket",
                        "httpx",
                        "requests",
                        "urllib",
                    ), f"{mod.__name__}: {alias.name}"
            if isinstance(node, _ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in (
                    "socket",
                    "httpx",
                    "requests",
                    "urllib",
                ), f"{mod.__name__}: {node.module}"


# ---------------------------------------------------------------------------
# No real provider dependency
# ---------------------------------------------------------------------------


def test_no_real_provider_dependency_all_fakes() -> None:
    chain = _get_chain()
    provider = chain["provider"]
    assert type(provider).__name__ == "FakeProvider"
    assert provider.__class__.__module__ == __name__
    assert provider.provider_name == "fake"
    assert provider.model_name == "fake-model"
    assert isinstance(provider.last_request.payload, dict)
    src = inspect.getsource(provider.__class__)
    assert "FakeProvider" in src

    import rop.services.llm_reasoning as mod

    src = inspect.getsource(mod)
    assert "OllamaReasoningProvider" not in src
    assert "openai" not in src.lower()


# ---------------------------------------------------------------------------
# Provider isolation boundary
# ---------------------------------------------------------------------------


def test_provider_isolation_boundary_methods() -> None:
    chain = _get_chain()
    provider = chain["provider"]
    proposal_fp = chain["proposal"]["context_fingerprint"]

    assert (
        ProviderFailureBoundary.normalize_failure(ConnectionError("connection refused"))
        == "MODEL_UNAVAILABLE"
    )
    assert (
        ProviderFailureBoundary.normalize_failure(
            ValueError("unknown candidate_id reference not found")
        )
        == "MODEL_OUTPUT_INCONSISTENT"
    )
    assert (
        ProviderFailureBoundary.normalize_failure(
            ValueError("schema validation failed")
        )
        == "MODEL_OUTPUT_INVALID"
    )

    clean = LLMReasoningProviderResponse(provider="fake", model="fake-model", text="{}")
    assert ProviderFailureBoundary.validate_provider_metadata(clean, "") == []
    assert ProviderFailureBoundary.sanitize_provider_text('{"a": 1}') == '{"a": 1}'
    assert ProviderFailureBoundary.check_provider_cannot_mutate_rop(provider) == []
    assert (
        len(
            ProviderFailureBoundary.check_provider_cannot_mutate_rop(
                FakeSuspiciousProvider()
            )
        )
        > 0
    )
    assert ProviderFailureBoundary.validate_provider_metadata(clean, proposal_fp) == []


# ---------------------------------------------------------------------------
# Privacy boundary
# ---------------------------------------------------------------------------


def test_privacy_boundary_clean_and_informational() -> None:
    chain = _get_chain()
    serialized = chain["serialized"]
    assert check_payload_privacy(serialized) == []
    assert validate_llm_input_boundary(serialized) == []
    assert check_adversarial_text("routine clinical note") == []
    assert "adversarial:ignore_previous_instructions" in (
        check_adversarial_text("ignore previous instructions")
    )
    assert LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108 == ("LLM_PRIVACY_BOUNDARY_TASK_108")


# ---------------------------------------------------------------------------
# Normalization boundary
# ---------------------------------------------------------------------------


def test_normalization_deterministic_and_validated() -> None:
    chain = _get_chain()
    proposal = chain["proposal"]
    first = normalize_proposal(proposal)
    second = normalize_proposal(proposal)
    assert first == second
    assert validate_normalized(first) == []
    assert compute_normalized_fingerprint(first) == (
        compute_normalized_fingerprint(second)
    )
    assert compute_normalized_fingerprint(first) == chain["normalized_fp"]


# ---------------------------------------------------------------------------
# Inspection boundary (Task 109, resolved via getattr, skip if missing)
# ---------------------------------------------------------------------------


def test_inspection_build_returns_expected_keys() -> None:
    _, service, _, constant = _resolve_inspection()
    assert constant == "LLM_PROPOSAL_INSPECTION_TASK_109"
    assert getattr(service, "build", None) is not None
    sig = inspect.signature(service.build)
    assert "proposal" in sig.parameters

    chain = _get_chain()
    inspection = dict(service.build(proposal=chain["proposal"]))
    for key in (
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "available",
        "proposal_consistent",
        "candidate_assessments",
        "evidence_references",
        "unresolved_information_references",
        "uncertainty_flags",
        "inspection_source",
        "proposal_fingerprint",
    ):
        assert key in inspection, key
    assert isinstance(inspection["session_id"], str)
    assert inspection["available"] is True
    assert inspection["proposal_consistent"] is True
    assert inspection["inspection_source"] == constant
    assert inspection["evidence_references"] == sorted(
        set(inspection["evidence_references"])
    )
    assert inspection["unresolved_information_references"] == sorted(
        set(inspection["unresolved_information_references"])
    )
    assert inspection["uncertainty_flags"] == sorted(
        set(inspection["uncertainty_flags"])
    )
    assert len(inspection["proposal_fingerprint"]) == 64


def test_inspection_candidate_evidence_integrity() -> None:
    _, service, _, _ = _resolve_inspection()
    chain = _get_chain()
    context = chain["context"]
    inspection = dict(service.build(proposal=chain["proposal"]))
    candidate_ids = {str(c.id) for c in context["candidate_state"]}
    assessed = {str(a["candidate_id"]) for a in inspection["candidate_assessments"]}
    assert assessed == candidate_ids


def test_inspection_tampered_proposal_never_repaired() -> None:
    _, service, _, _ = _resolve_inspection()
    chain = _get_chain()
    proposal = chain["proposal"]
    tampered = copy.deepcopy(proposal)
    tampered["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    inspection = dict(service.build(proposal=tampered))
    original_ids = {str(a["candidate_id"]) for a in proposal["candidate_assessments"]}
    tampered_ids = {str(a["candidate_id"]) for a in inspection["candidate_assessments"]}
    assert tampered_ids != original_ids

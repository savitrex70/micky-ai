"""Tests for Task 112 pre-LLM release gate.

Final release gate for the entire pre-LLM boundary (Tasks 103-111
over the 055-102 foundation). Test layer only; no redesigns, no real
provider. Conventions mirror tests/test_llm_pre_llm_chain_audit.py:
sqlite-memory TestClient, seeded sessions, fake provider pattern.
Every stage uses only real canonical functions.
"""

from __future__ import annotations

import ast
import copy
import importlib
import inspect
import json
import re
from collections.abc import Generator, Mapping
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
    LLMReasoningAuditContractError,
    LLMReasoningAuditService,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderResponse,
)
from rop.services.llm_request_serialization import (
    ALLOWED_PAYLOAD_FIELDS,
    ELEMENT_SERIALIZERS,
    LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104,
    compute_fingerprint,
    serialize_context,
    to_json_safe,
    validate_payload,
)
from rop.services.reasoning_context import ReasoningContextService

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


class FakeProvider:
    """Injectable fake provider used for the whole gate."""

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


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-112-test"},
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


def _collect_str_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(_collect_str_values(v))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_str_values(item))
    return found


_CHAIN_CACHE: dict[str, Any] = {}
_EMPTY_CACHE: dict[str, Any] = {}


def _get_chain() -> dict[str, Any]:
    if _CHAIN_CACHE:
        return _CHAIN_CACHE
    sid = _seed_full_session("Task 112 release gate")
    session_uuid = UUID(sid)
    gen, db = _open_db()
    try:
        context = ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        gen.close()
    raw_text = _valid_model_output(context)
    provider = FakeProvider(response_text=raw_text)
    proposal = LLMReasoningService(provider=provider).build(context=context)
    audit = LLMReasoningAuditService.build(proposal=proposal, context=context)
    serialized = serialize_context(context)
    fingerprint = compute_fingerprint(serialized)
    normalized = normalize_proposal(proposal)
    normalized_fp = compute_normalized_fingerprint(normalized)
    inspection = _build_inspection(proposal)
    _CHAIN_CACHE.update(
        {
            "session_id": sid,
            "session_uuid": session_uuid,
            "context": context,
            "raw_text": raw_text,
            "provider": provider,
            "proposal": proposal,
            "audit": audit,
            "serialized": serialized,
            "fingerprint": fingerprint,
            "normalized": normalized,
            "normalized_fp": normalized_fp,
            "inspection": inspection,
        }
    )
    return _CHAIN_CACHE


def _get_empty_chain() -> dict[str, Any]:
    if _EMPTY_CACHE:
        return _EMPTY_CACHE
    sid = _create_session("Task 112 empty session")
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
    inspection = _build_inspection(proposal)
    _EMPTY_CACHE.update(
        {
            "session_id": sid,
            "session_uuid": session_uuid,
            "context": context,
            "unavailable_context": unavailable,
            "provider": provider,
            "proposal": proposal,
            "audit": audit,
            "inspection": inspection,
        }
    )
    return _EMPTY_CACHE


def _resolve_inspection() -> tuple[Any, Any, Any, Any]:
    module = importlib.import_module("rop.services.llm_proposal_inspection")
    service = getattr(module, "LLMProposalInspectionService", None)
    error = getattr(module, "LLMProposalInspectionContractError", None)
    constant = getattr(module, "LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109", None)
    assert service is not None
    assert error is not None
    assert constant is not None
    return module, service, error, constant


def _build_inspection(proposal: dict[str, Any]) -> dict[str, Any]:
    _, service, _, _ = _resolve_inspection()
    return dict(service.build(proposal=proposal))


def _new_modules() -> list[Any]:
    import rop.services.llm_output_validation as m105
    import rop.services.llm_privacy_boundary as m108
    import rop.services.llm_proposal_inspection as m109
    import rop.services.llm_proposal_normalization as m106
    import rop.services.llm_provider_isolation as m107
    import rop.services.llm_reasoning_audit as m103
    import rop.services.llm_request_serialization as m104

    return [m103, m104, m105, m106, m107, m108, m109]


# ---------------------------------------------------------------------------
# Required contracts exist and export correctly
# ---------------------------------------------------------------------------


def test_release_contracts_importable_from_services_root() -> None:
    import rop.services as root

    required = [
        "LLMReasoningAuditService",
        "LLMReasoningAuditContractError",
        "serialize_context",
        "to_json_safe",
        "compute_fingerprint",
        "validate_payload",
        "ALLOWED_PAYLOAD_FIELDS",
        "ELEMENT_SERIALIZERS",
        "validate_raw_proposal",
        "normalize_proposal",
        "compute_normalized_fingerprint",
        "validate_normalized",
        "ProviderFailureBoundary",
        "check_payload_privacy",
        "check_adversarial_text",
        "validate_llm_input_boundary",
        "LLMProposalInspectionService",
        "LLMProposalInspectionContractError",
        "LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104",
        "LLM_OUTPUT_VALIDATION_SOURCE_TASK_105",
        "LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106",
        "LLM_PROVIDER_ISOLATION_SOURCE_TASK_107",
        "LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108",
        "LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109",
    ]
    for name in required:
        assert hasattr(root, name), name
        assert name in root.__all__, name
    # Module-level fixed identifiers are canonical at modules.
    assert LLM_REASONING_AUDIT_TASK_103 == "LLM_REASONING_AUDIT_TASK_103"
    assert LLM_REASONING_TASK_057 == "LLM_REASONING_TASK_057"
    # Direct references keep serialization boundary imports live.
    assert set(ALLOWED_PAYLOAD_FIELDS) == {
        "session_id",
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
        "reasoning_pipeline",
    }
    assert len(ELEMENT_SERIALIZERS) == 5


def test_release_schemas_exported_from_schemas_root() -> None:
    import rop.schemas as root

    for name in [
        "LLMReasoningAuditRead",
        "NormalizedCandidateAssessmentRead",
        "NormalizedLLMReasoningProposalRead",
        "LLMProposalInspectionRead",
    ]:
        assert hasattr(root, name), name
        assert name in root.__all__, name
    from rop.schemas.llm_proposal_inspection import (
        LLMProposalInspectionRead,
    )
    from rop.schemas.llm_proposal_normalization import (
        NormalizedCandidateAssessmentRead,
        NormalizedLLMReasoningProposalRead,
    )
    from rop.schemas.llm_reasoning_audit import LLMReasoningAuditRead

    assert LLMReasoningAuditRead is not None
    assert NormalizedCandidateAssessmentRead is not None
    assert NormalizedLLMReasoningProposalRead is not None
    assert LLMProposalInspectionRead is not None


# ---------------------------------------------------------------------------
# Fixed source identifiers present
# ---------------------------------------------------------------------------


def test_release_source_identifiers_fixed() -> None:
    assert LLM_REASONING_TASK_057 == "LLM_REASONING_TASK_057"
    assert LLM_REASONING_AUDIT_TASK_103 == ("LLM_REASONING_AUDIT_TASK_103")
    assert LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104 == (
        "LLM_REQUEST_SERIALIZATION_TASK_104"
    )
    assert LLM_OUTPUT_VALIDATION_SOURCE_TASK_105 == ("LLM_OUTPUT_VALIDATION_TASK_105")
    assert LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106 == (
        "LLM_PROPOSAL_NORMALIZATION_TASK_106"
    )
    assert LLM_PROVIDER_ISOLATION_SOURCE_TASK_107 == ("LLM_PROVIDER_ISOLATION_TASK_107")
    assert LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108 == ("LLM_PRIVACY_BOUNDARY_TASK_108")
    _, _, _, constant = _resolve_inspection()
    assert constant == "LLM_PROPOSAL_INSPECTION_TASK_109"
    pairs = [
        (LLM_REASONING_TASK_057, "057"),
        (LLM_REASONING_AUDIT_TASK_103, "103"),
        (LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104, "104"),
        (LLM_OUTPUT_VALIDATION_SOURCE_TASK_105, "105"),
        (LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106, "106"),
        (LLM_PROVIDER_ISOLATION_SOURCE_TASK_107, "107"),
        (LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108, "108"),
        (constant, "109"),
    ]
    for value, number in pairs:
        assert isinstance(value, str)
        assert len(value) > 0
        assert number in value


# ---------------------------------------------------------------------------
# Fingerprints deterministic lowercase SHA-256 where applicable
# ---------------------------------------------------------------------------


def test_release_fingerprints_deterministic_sha256() -> None:
    chain = _get_chain()
    serialized = chain["serialized"]
    normalized = chain["normalized"]
    pattern = re.compile(r"^[0-9a-f]{64}$")
    first = compute_fingerprint(serialized)
    second = compute_fingerprint(serialized)
    assert first == second
    assert pattern.match(first) is not None
    assert first == chain["fingerprint"]
    nfirst = compute_normalized_fingerprint(normalized)
    nsecond = compute_normalized_fingerprint(normalized)
    assert nfirst == nsecond
    assert pattern.match(nfirst) is not None
    assert nfirst == chain["normalized_fp"]


# ---------------------------------------------------------------------------
# Audited fingerprints bind audited structures
# ---------------------------------------------------------------------------


def test_release_audited_fingerprints_bind_structures() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    audit = chain["audit"]
    inspection = chain["inspection"]
    recomputed = compute_fingerprint(serialize_context(context))
    assert proposal["context_fingerprint"] == recomputed
    assert chain["fingerprint"] == recomputed
    assert audit["fingerprint_consistent"] is True
    assert audit["consistency_issues"] == []
    expected = compute_normalized_fingerprint(normalize_proposal(proposal))
    assert inspection["proposal_fingerprint"] == expected
    assert inspection["proposal_fingerprint"] == (chain["normalized_fp"])


# ---------------------------------------------------------------------------
# Session identity consistent
# ---------------------------------------------------------------------------


def test_release_session_identity_consistent() -> None:
    chain = _get_chain()
    sid = chain["session_id"]
    context = chain["context"]
    proposal = chain["proposal"]
    serialized = chain["serialized"]
    normalized = chain["normalized"]
    inspection = chain["inspection"]
    audit = chain["audit"]
    assert str(context["session_id"]) == sid
    assert str(proposal["session_id"]) == sid
    assert str(serialized["session_id"]) == sid
    assert str(normalized["session_id"]) == sid
    assert str(inspection["session_id"]) == sid
    assert str(UUID(sid)) == sid
    assert audit["session_consistent"] is True


# ---------------------------------------------------------------------------
# No or-fallback substituting fingerprint/provenance values
# ---------------------------------------------------------------------------


def _assert_no_or_fallback(module: Any) -> None:
    src = inspect.getsource(module)
    tree = ast.parse(src)
    parents: dict[int, Any] = {}

    def _visit(node: Any, parent: Any) -> None:
        parents[id(node)] = parent
        for child in ast.iter_child_nodes(node):
            _visit(child, node)

    _visit(tree, None)
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            seg = ast.get_source_segment(src, node) or ""
            low = seg.lower()
            if "fingerprint" not in low and "source" not in low:
                continue
            cur: Any = node
            in_guard = False
            while cur is not None:
                parent = parents.get(id(cur))
                if isinstance(parent, (ast.If, ast.While)):
                    if parent.test is cur or (
                        isinstance(parent.test, ast.BoolOp)
                        and node in ast.walk(parent.test)
                    ):
                        in_guard = True
                        break
                if isinstance(parent, ast.Assert):
                    in_guard = True
                    break
                if isinstance(parent, ast.BoolOp):
                    cur = parent
                    continue
                break
            assert in_guard, (
                f"{module.__name__}: or-fallback near "
                f"fingerprint/source: {seg[:120]!r}"
            )


def test_release_no_or_fallback_fingerprint_provenance() -> None:
    import rop.services.llm_proposal_inspection as m109
    import rop.services.llm_proposal_normalization as m106
    import rop.services.llm_reasoning_audit as m103

    for mod in (m103, m106, m109):
        _assert_no_or_fallback(mod)


# ---------------------------------------------------------------------------
# Legitimate false/unavailable/inconsistent states stay so
# ---------------------------------------------------------------------------


def test_release_legitimate_unavailable_states_stay_so() -> None:
    empty = _get_empty_chain()
    proposal = empty["proposal"]
    audit = empty["audit"]
    inspection = empty["inspection"]
    provider = empty["provider"]
    assert proposal["available"] is False
    assert proposal["proposal_consistent"] is False
    assert proposal["candidate_assessments"] == []
    assert provider.calls == 0
    assert audit["available"] is False
    assert audit["proposal_consistent"] is False
    assert audit["consistency_issues"] == []
    assert audit["candidate_assessments_consistent"] is True
    assert audit["metadata_consistent"] is True
    assert audit["session_consistent"] is True
    assert audit["fingerprint_consistent"] is True
    assert audit["provenance_consistent"] is True
    assert inspection["available"] is False
    assert inspection["proposal_consistent"] is False
    assert inspection["candidate_assessments"] == []
    assert inspection["evidence_references"] == []
    assert inspection["uncertainty_flags"] == []


# ---------------------------------------------------------------------------
# Malformed states cannot become false successes
# ---------------------------------------------------------------------------


def test_release_malformed_audit_none_raises() -> None:
    with pytest.raises(LLMReasoningAuditContractError):
        LLMReasoningAuditService.build(proposal=None)


def test_release_malformed_audit_non_mapping_raises() -> None:
    with pytest.raises(LLMReasoningAuditContractError):
        LLMReasoningAuditService.build(proposal="bad")  # type: ignore


def test_release_malformed_audit_missing_field_false() -> None:
    chain = _get_chain()
    tampered = copy.deepcopy(chain["proposal"])
    del tampered["session_id"]
    audit = LLMReasoningAuditService.build(proposal=tampered, context=chain["context"])
    assert audit["proposal_consistent"] is False
    assert audit["metadata_consistent"] is False
    assert len(audit["consistency_issues"]) > 0


def test_release_malformed_audit_bad_fingerprint_false() -> None:
    chain = _get_chain()
    tampered = copy.deepcopy(chain["proposal"])
    tampered["context_fingerprint"] = "g" * 64
    audit = LLMReasoningAuditService.build(proposal=tampered, context=chain["context"])
    assert audit["fingerprint_consistent"] is False
    assert audit["proposal_consistent"] is False
    assert "invalid_fingerprint_format" in audit["consistency_issues"]


def test_release_malformed_audit_bad_source_false() -> None:
    chain = _get_chain()
    tampered = copy.deepcopy(chain["proposal"])
    tampered["llm_reasoning_source"] = "WRONG"
    audit = LLMReasoningAuditService.build(proposal=tampered, context=chain["context"])
    assert audit["provenance_consistent"] is False
    assert audit["proposal_consistent"] is False


def test_release_malformed_audit_empty_explanation_false() -> None:
    chain = _get_chain()
    tampered = copy.deepcopy(chain["proposal"])
    tampered["candidate_assessments"][0]["explanation"] = ""
    audit = LLMReasoningAuditService.build(proposal=tampered, context=chain["context"])
    assert audit["candidate_assessments_consistent"] is False
    assert audit["proposal_consistent"] is False


def test_release_malformed_inspection_rejects() -> None:
    _, service, error, _ = _resolve_inspection()
    chain = _get_chain()
    with pytest.raises(error):
        service.build(proposal=None)
    with pytest.raises(error):
        service.build(proposal="bad")  # type: ignore
    missing = copy.deepcopy(chain["proposal"])
    del missing["session_id"]
    with pytest.raises(error):
        service.build(proposal=missing)
    wrong_source = copy.deepcopy(chain["proposal"])
    wrong_source["llm_reasoning_source"] = "WRONG"
    with pytest.raises(error) as ei:
        service.build(proposal=wrong_source)
    assert ei.value.invariant == "INVALID_SOURCE"
    available_empty = copy.deepcopy(chain["proposal"])
    available_empty["candidate_assessments"] = []
    available_empty["available"] = True
    with pytest.raises(error) as ei2:
        service.build(proposal=available_empty)
    assert ei2.value.invariant == "PROPOSAL_INCONSISTENT"
    tampered = copy.deepcopy(chain["proposal"])
    tampered["proposal_fingerprint"] = "0" * 64
    with pytest.raises(error) as ei3:
        service.build(proposal=tampered)
    assert ei3.value.invariant == "FINGERPRINT_MISMATCH"
    for forbidden in ("text", "raw_text", "prompt"):
        leaked = copy.deepcopy(chain["proposal"])
        leaked[forbidden] = "leaked provider text"
        with pytest.raises(error):
            service.build(proposal=leaked)


def test_release_malformed_output_validation_never_clean() -> None:
    chain = _get_chain()
    context = chain["context"]
    raw = json.loads(_valid_model_output(context))
    bad_id = copy.deepcopy(raw)
    bad_id["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    issues = validate_raw_proposal(bad_id, context)
    assert len(issues) > 0
    extra = copy.deepcopy(raw)
    extra["winner"] = "candidate-x"
    issues2 = validate_raw_proposal(extra, context)
    assert len(issues2) > 0
    assert any("Top-level schema validation failed" in i for i in issues2)
    if len(context["candidate_state"]) < 2:
        pytest.skip("seed session produced only one candidate")
    reordered = copy.deepcopy(raw)
    reordered["candidate_assessments"] = list(
        reversed(reordered["candidate_assessments"])
    )
    issues3 = validate_raw_proposal(reordered, context)
    assert len(issues3) > 0
    assert any("order does not match" in i for i in issues3)


def test_release_malformed_normalized_never_clean() -> None:
    chain = _get_chain()
    normalized = chain["normalized"]
    broken = copy.deepcopy(normalized)
    del broken["session_id"]
    assert len(validate_normalized(broken)) > 0
    broken2 = copy.deepcopy(normalized)
    broken2["candidate_assessments"][0]["assessment"] = "BOGUS"
    assert len(validate_normalized(broken2)) > 0


# ---------------------------------------------------------------------------
# No caller-input mutation
# ---------------------------------------------------------------------------


def _freeze(value: Any) -> Any:
    """Canonical snapshot for immutability comparison.

    Plain deepcopy equality fails for contexts holding SQLAlchemy ORM
    objects (identity-based __eq__), so snapshots convert ORM instances
    to sorted attribute dicts (minus _sa_instance_state) with UUIDs as
    strings. Any in-place mutation changes the snapshot.
    """
    if isinstance(value, Mapping):
        return {str(k): _freeze(v) for k, v in sorted(value.items(), key=str)}
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


def test_release_no_caller_input_mutation() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    serialized = chain["serialized"]
    normalized = chain["normalized"]
    frozen_context = _freeze(context)
    frozen_proposal = copy.deepcopy(proposal)
    frozen_serialized = copy.deepcopy(serialized)
    frozen_normalized = copy.deepcopy(normalized)
    serialize_context(context)
    assert _freeze(context) == frozen_context
    to_json_safe(serialized)
    assert serialized == frozen_serialized
    compute_fingerprint(serialized)
    assert serialized == frozen_serialized
    validate_payload(serialized)
    assert serialized == frozen_serialized
    LLMReasoningAuditService.build(proposal=proposal, context=context)
    assert proposal == frozen_proposal
    normalize_proposal(proposal)
    assert proposal == frozen_proposal
    compute_normalized_fingerprint(normalized)
    assert normalized == frozen_normalized
    validate_normalized(normalized)
    assert normalized == frozen_normalized
    _build_inspection(proposal)
    assert proposal == frozen_proposal


# ---------------------------------------------------------------------------
# No DB writes in pure services
# ---------------------------------------------------------------------------


def test_release_no_db_writes_in_pure_services() -> None:
    chain = _get_chain()
    context = chain["context"]
    proposal = chain["proposal"]
    serialized = chain["serialized"]
    normalized = chain["normalized"]
    before = _session_count()
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
# No internal HTTP calls
# ---------------------------------------------------------------------------


def test_release_no_internal_http_calls() -> None:
    import rop.services.llm_reasoning as m057
    import rop.services.reasoning_context as m055
    import rop.services.reasoning_context_consistency as m056

    modules = _new_modules() + [m055, m056, m057]
    forbidden = ("httpx", "requests", "socket", "urllib")
    for mod in modules:
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden, f"{mod.__name__}: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in forbidden, f"{mod.__name__}: {node.module}"
        for token in ("TestClient", "urlopen"):
            assert token not in src, f"{mod.__name__}: {token}"


# ---------------------------------------------------------------------------
# No real network dependency
# ---------------------------------------------------------------------------


def test_release_no_real_network_dependency() -> None:
    modules = _new_modules()
    forbidden = ("httpx", "requests", "socket", "urllib")
    for mod in modules:
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden, f"{mod.__name__}: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in forbidden, f"{mod.__name__}: {node.module}"


# ---------------------------------------------------------------------------
# No real LLM/provider dependency
# ---------------------------------------------------------------------------


def test_release_no_real_llm_provider_dependency() -> None:
    modules = _new_modules()
    forbidden_roots = ("openai", "gemini", "anthropic", "ollama")
    for mod in modules:
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0].lower()
                    assert root not in forbidden_roots, f"{mod.__name__}: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0].lower()
                assert root not in forbidden_roots, f"{mod.__name__}: {node.module}"
            if isinstance(node, ast.Call):
                func = node.func
                label = ""
                if isinstance(func, ast.Name):
                    label = func.id
                elif isinstance(func, ast.Attribute):
                    label = func.attr
                low = label.lower()
                for stem in ("openai", "anthropic", "gemini"):
                    assert stem not in low, f"{mod.__name__}: client {label}"
                if low == "ollama" or "ollamaclient" in low:
                    raise AssertionError(f"{mod.__name__}: client {label}")
    chain = _get_chain()
    provider = chain["provider"]
    assert type(provider).__name__ == "FakeProvider"
    assert provider.provider_name == "fake"
    assert provider.model_name == "fake-model"


# ---------------------------------------------------------------------------
# No API keys/secrets introduced
# ---------------------------------------------------------------------------


def test_release_no_api_keys_secrets_introduced() -> None:
    for mod in _new_modules():
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        targets.append(t.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    targets.append(node.target.id)
            for name in targets:
                low = name.lower()
                assert "api_key" not in low, f"{mod.__name__}: {name}"
                assert "passwd" not in low, f"{mod.__name__}: {name}"
                assert "secret" not in low, f"{mod.__name__}: {name}"


# ---------------------------------------------------------------------------
# No ranking/selection/recommendation/treatment authority
# ---------------------------------------------------------------------------


def test_release_no_ranking_selection_treatment_authority() -> None:
    stems = (
        "winner",
        "select",
        "rank",
        "recommend",
        "treatment",
        "diagnos",
    )
    for mod in _new_modules():
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            label = ""
            if isinstance(node, ast.Name):
                label = node.id
            elif isinstance(node, ast.Attribute):
                label = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                label = node.name
            elif isinstance(node, ast.ClassDef):
                label = node.name
            else:
                continue
            low = label.lower()
            for stem in stems:
                assert stem not in low, f"{mod.__name__}: {label} " f"contains {stem!r}"


# ---------------------------------------------------------------------------
# Raw model text never a public artifact
# ---------------------------------------------------------------------------


def test_release_raw_model_text_never_public_artifact() -> None:
    chain = _get_chain()
    raw_text = chain["raw_text"]
    assert len(raw_text) > 0
    audit = chain["audit"]
    inspection = chain["inspection"]
    assert set(audit.keys()) is not None
    for forbidden in ("text", "raw_text", "prompt"):
        assert forbidden not in audit
        assert forbidden not in inspection
    for value in _collect_str_values(audit):
        assert value != raw_text
        assert raw_text not in value
    for value in _collect_str_values(inspection):
        assert value != raw_text
        assert raw_text not in value


# ---------------------------------------------------------------------------
# Chain deterministic + independently auditable
# ---------------------------------------------------------------------------


def test_release_chain_deterministic_independently_auditable() -> None:
    first = _get_chain()
    context = first["context"]
    snapshot_proposal = copy.deepcopy(first["proposal"])
    snapshot_audit = copy.deepcopy(first["audit"])
    snapshot_normalized = copy.deepcopy(first["normalized"])
    snapshot_inspection = copy.deepcopy(first["inspection"])
    provider = FakeProvider(response_text=_valid_model_output(context))
    second_proposal = LLMReasoningService(provider=provider).build(context=context)
    assert second_proposal == snapshot_proposal
    second_audit = LLMReasoningAuditService.build(
        proposal=second_proposal, context=context
    )
    assert second_audit == snapshot_audit
    assert normalize_proposal(second_proposal) == snapshot_normalized
    assert (
        compute_normalized_fingerprint(normalize_proposal(second_proposal))
        == first["normalized_fp"]
    )
    assert serialize_context(context) == first["serialized"]
    assert compute_fingerprint(serialize_context(context)) == first["fingerprint"]
    assert _build_inspection(second_proposal) == snapshot_inspection

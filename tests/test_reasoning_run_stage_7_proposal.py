"""Task 158: Stage 7 provider response boundary tests.

Covers the raw-response validation seam over the Task 157 dispatch
result. The canonical Task 057 pipeline order (provider metadata ->
text type -> strict JSON -> schema -> Task 105 reference validation ->
public proposal construction) is preserved unchanged, every failure
maps to a canonical Task 057 outcome value, and the raw provider
response and raw provider text never appear in the returned
projection. No heuristic repair, no regex correction, no retry loop,
and no provider invocation while validating an already-produced
response.

Provenance is bound before any raw response is read: the supplied
dispatch mapping must itself validate against the strict Task 157
projection, and the supplied canonical context must be bound to the
dispatched session, report itself available and consistent, and
serialize to exactly the dispatched request fingerprint. A forged
dispatch or a foreign context for the very same session therefore fails
closed as ``UNAVAILABLE`` instead of validating model output.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from collections.abc import Generator
from pathlib import Path
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
from rop.schemas.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalRead,
)
from rop.services.llm_boundary_contract import (
    ALLOWED_BOUNDARY_OUTCOMES,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
)
from rop.services.llm_reasoning import LLM_REASONING_TASK_057, LLMReasoningService
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_dispatch import (
    ReasoningRunStage7DispatchService,
)
from rop.services.reasoning_run_stage_7_proposal import (
    REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158,
    ReasoningRunStage7ProposalService,
)
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
from rop.services.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditService,
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

PROPOSAL_KEYS = {
    "proposal_status",
    "available",
    "session_id",
    "context_fingerprint",
    "provider",
    "model",
    "proposal",
    "proposal_source",
}

_CANONICAL_MODEL_OUTCOMES = (
    OUTCOME_MODEL_UNAVAILABLE,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
)

_CONCRETE_PROVIDER_TOKENS = ("ollama", "openai", "gemini", "anthropic", "claude")
_PROHIBITED_SOURCE_TOKENS = (
    *_CONCRETE_PROVIDER_TOKENS,
    "httpx",
    "aiohttp",
    "urllib3",
    "requests",
    "os.environ",
    "getenv",
    "api_key",
    "socket",
    "entry_points",
)


class _CertificationStub:
    """Returns one coherent Stage 6 verdict for the real admission path."""

    def __init__(self, status: str = "CERTIFIED") -> None:
        self._status = status
        self.calls: list[UUID] = []

    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        self.calls.append(session_id)
        certified = self._status == "CERTIFIED"
        return {
            "requested_session_id": str(session_id),
            "certification_status": self._status,
            "certified": certified,
            "release_ready": certified,
        }


class _FakeProvider:
    """Deterministic test-only provider. No network, no model, no state."""

    def __init__(self) -> None:
        self.provider_name = "fake-provider"
        self.model_name = "fake-model"
        self.response: object = LLMReasoningProviderResponse(
            provider="fake-provider",
            model="fake-model",
            text='{"candidate_assessments": []}',
        )
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        return self.response


class _FailingProvider:
    """Test-only provider that raises one canonical failure."""

    def __init__(self, error: Exception) -> None:
        self.provider_name = "failing-provider"
        self.model_name = "failing-model"
        self.error = error
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        raise self.error


class _HostileResponse:
    """Response whose every metadata read raises a hostile exception."""

    @property
    def provider(self) -> str:
        raise RuntimeError("hostile provider read")

    @property
    def model(self) -> str:
        raise RuntimeError("hostile model read")

    @property
    def text(self) -> str:
        raise RuntimeError("hostile text read")

    def __str__(self) -> str:
        raise RuntimeError("hostile __str__")


class _ExtraFieldResponse:
    """Response smuggling a provider-specific field past the boundary."""

    def __init__(self, text: str) -> None:
        self.provider = "fake-provider"
        self.model = "fake-model"
        self.text = text
        self.extra_field = "smuggled"


class _WrongFingerprintResponse:
    """Response echoing a context fingerprint that was never computed."""

    def __init__(self, text: str) -> None:
        self.provider = "fake-provider"
        self.model = "fake-model"
        self.text = text
        self.context_fingerprint = "0" * 64


class _Uncopyable:
    def __deepcopy__(self, memo: dict) -> _Uncopyable:
        raise RuntimeError("uncopyable")


@pytest.fixture(autouse=True)
def _reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-proposal-test"},
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


def _context(db: Session, sid: str) -> dict:
    context = ReasoningContextService().build_for_session(db, UUID(sid))
    assert context["available"] is True
    return context


def _build_package(db: Session, sid: str) -> dict:
    service = ReasoningRunStage7RequestService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    package = service.build(db, UUID(sid))
    assert package["request_status"] == "PACKAGED"
    return package


def _audit(db: Session, package: object) -> dict:
    service = ReasoningRunStage7RequestAuditService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    audit = service.audit(db, package)
    assert audit["request_audit_status"] == "CONSISTENT"
    return audit


def _dispatch(db: Session, sid: str, provider: object) -> tuple[dict, dict]:
    package = _build_package(db, sid)
    audit = _audit(db, package)
    result = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=audit
    )
    assert result["dispatch_status"] == "DISPATCHED"
    return result, package


def _valid_model_output(context: dict) -> str:
    assessments = [
        {
            "candidate_id": str(candidate.id),
            "assessment": "UNCLEAR",
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "unresolved_information_ids": [],
            "explanation": "insufficient evidence to decide",
            "uncertainty_flags": ["insufficient_evidence"],
        }
        for candidate in context["candidate_state"]
    ]
    return json.dumps({"candidate_assessments": assessments})


def _response(text: str) -> LLMReasoningProviderResponse:
    return LLMReasoningProviderResponse(
        provider="fake-provider", model="fake-model", text=text
    )


def _swap_response(dispatch_result: dict, response: object) -> dict:
    return {**dispatch_result, "provider_response": response}


def _propose(dispatch_result: object, context: object) -> dict:
    return ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch_result, context=context
    )


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_output_is_validated() -> None:
    sid = _seed_full_session("Task 158 valid output")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, package = _dispatch(db, sid, provider)
        result = _propose(dispatch, context)

    assert set(result) == PROPOSAL_KEYS
    assert result["proposal_status"] == "VALIDATED"
    assert result["available"] is True
    assert result["session_id"] == sid
    assert result["context_fingerprint"] == package["context_fingerprint"]
    assert result["provider"] == "fake-provider"
    assert result["model"] == "fake-model"
    assert result["proposal_source"] == REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158
    proposal = result["proposal"]
    assert proposal["session_id"] == sid
    assert proposal["context_fingerprint"] == package["context_fingerprint"]
    assert proposal["provider"] == "fake-provider"
    assert proposal["model"] == "fake-model"
    assert proposal["available"] is True
    assert proposal["proposal_consistent"] is True
    assert proposal["llm_reasoning_source"] == LLM_REASONING_TASK_057
    assert len(proposal["candidate_assessments"]) == len(context["candidate_state"])
    assert len(provider.calls) == 1
    assert dispatch["provider_response"] is provider.response


def test_valid_evidence_reference_is_validated() -> None:
    sid = _seed_full_session("Task 158 valid evidence reference")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        output = json.loads(_valid_model_output(context))
        output["candidate_assessments"][0]["supporting_evidence_ids"] = [
            str(context["observations"][0].id)
        ]
        provider.response = _response(json.dumps(output))
        dispatch, _ = _dispatch(db, sid, provider)
        result = _propose(dispatch, context)

    assert result["proposal_status"] == "VALIDATED"
    assert result["proposal"]["candidate_assessments"][0][
        "supporting_evidence_ids"
    ] == [str(context["observations"][0].id)]


# ---------------------------------------------------------------------------
# Output failures: invalid JSON and schema-invalid JSON
# ---------------------------------------------------------------------------


def test_invalid_json_is_model_output_invalid() -> None:
    sid = _seed_full_session("Task 158 invalid json")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response("this is not json at all")
        dispatch, _ = _dispatch(db, sid, provider)
        result = _propose(dispatch, context)

    assert result["proposal_status"] == "MODEL_OUTPUT_INVALID"
    assert result["available"] is False
    assert result["proposal"] is None
    assert result["context_fingerprint"] is None
    assert result["provider"] is None
    assert result["model"] is None
    assert result["session_id"] == sid


def test_schema_invalid_json_is_model_output_invalid() -> None:
    sid = _seed_full_session("Task 158 schema invalid json")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)

        # A smuggled "winner" key must fail top-level schema validation.
        smuggled = json.loads(_valid_model_output(context))
        smuggled["winner"] = smuggled["candidate_assessments"][0]["candidate_id"]
        winner_result = _propose(
            _swap_response(dispatch, _response(json.dumps(smuggled))), context
        )

        # A structurally malformed assessments container is schema-invalid too.
        malformed = json.loads(_valid_model_output(context))
        malformed["candidate_assessments"] = {"candidate_id": "not-a-list"}
        malformed_result = _propose(
            _swap_response(dispatch, _response(json.dumps(malformed))), context
        )

    assert winner_result["proposal_status"] == "MODEL_OUTPUT_INVALID"
    assert malformed_result["proposal_status"] == "MODEL_OUTPUT_INVALID"


# ---------------------------------------------------------------------------
# Output failures: reference validation (canonical Task 105 taxonomy)
# ---------------------------------------------------------------------------


def test_unknown_candidate_is_model_output_inconsistent() -> None:
    sid = _seed_full_session("Task 158 unknown candidate")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)
        output = json.loads(_valid_model_output(context))
        output["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        result = _propose(
            _swap_response(dispatch, _response(json.dumps(output))), context
        )

    assert result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"
    assert result["available"] is False
    assert result["proposal"] is None


def test_unknown_evidence_is_model_output_inconsistent() -> None:
    sid = _seed_full_session("Task 158 unknown evidence")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)

        supporting = json.loads(_valid_model_output(context))
        supporting["candidate_assessments"][0]["supporting_evidence_ids"] = [
            str(uuid4())
        ]
        supporting_result = _propose(
            _swap_response(dispatch, _response(json.dumps(supporting))), context
        )

        contradicting = json.loads(_valid_model_output(context))
        contradicting["candidate_assessments"][0]["contradicting_evidence_ids"] = [
            str(uuid4())
        ]
        contradicting_result = _propose(
            _swap_response(dispatch, _response(json.dumps(contradicting))), context
        )

        unresolved = json.loads(_valid_model_output(context))
        unresolved["candidate_assessments"][0]["unresolved_information_ids"] = [
            str(uuid4())
        ]
        unresolved_result = _propose(
            _swap_response(dispatch, _response(json.dumps(unresolved))), context
        )

    assert supporting_result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"
    assert contradicting_result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"
    assert unresolved_result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"


def test_wrong_candidate_order_is_model_output_inconsistent() -> None:
    sid = _seed_full_session("Task 158 wrong order")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)
        output = json.loads(_valid_model_output(context))
        output["candidate_assessments"].reverse()
        result = _propose(
            _swap_response(dispatch, _response(json.dumps(output))), context
        )

    assert len(context["candidate_state"]) >= 2
    assert result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"


def test_duplicate_candidate_is_model_output_inconsistent() -> None:
    sid = _seed_full_session("Task 158 duplicate candidate")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)
        output = json.loads(_valid_model_output(context))
        output["candidate_assessments"].append(
            copy.deepcopy(output["candidate_assessments"][0])
        )
        result = _propose(
            _swap_response(dispatch, _response(json.dumps(output))), context
        )

    assert result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"


def test_missing_candidate_is_model_output_inconsistent() -> None:
    sid = _seed_full_session("Task 158 missing candidate")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)
        output = json.loads(_valid_model_output(context))
        output["candidate_assessments"] = output["candidate_assessments"][:-1]
        result = _propose(
            _swap_response(dispatch, _response(json.dumps(output))), context
        )

    assert result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"


def test_empty_explanation_is_model_output_inconsistent() -> None:
    sid = _seed_full_session("Task 158 empty explanation")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)
        output = json.loads(_valid_model_output(context))
        output["candidate_assessments"][0]["explanation"] = ""
        result = _propose(
            _swap_response(dispatch, _response(json.dumps(output))), context
        )

    assert result["proposal_status"] == "MODEL_OUTPUT_INCONSISTENT"


# ---------------------------------------------------------------------------
# Malformed provider metadata (Task 107 gate)
# ---------------------------------------------------------------------------


def test_malformed_provider_metadata_is_model_output_invalid() -> None:
    sid = _seed_full_session("Task 158 malformed metadata")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        good_text = _valid_model_output(context)
        provider.response = _response(good_text)
        dispatch, _ = _dispatch(db, sid, provider)

        empty_provider = _propose(
            _swap_response(
                dispatch,
                LLMReasoningProviderResponse(provider="", model="fake", text=good_text),
            ),
            context,
        )
        non_string_text = _propose(
            _swap_response(
                dispatch,
                LLMReasoningProviderResponse(provider="fake", model="fake", text=123),
            ),
            context,
        )
        wrong_fingerprint = _propose(
            _swap_response(dispatch, _WrongFingerprintResponse(good_text)), context
        )
        extra_field = _propose(
            _swap_response(dispatch, _ExtraFieldResponse(good_text)), context
        )

    for result in (empty_provider, non_string_text, wrong_fingerprint, extra_field):
        assert result["proposal_status"] == "MODEL_OUTPUT_INVALID"
        assert result["available"] is False


def test_hostile_provider_response_is_contained() -> None:
    sid = _seed_full_session("Task 158 hostile response")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _HostileResponse()
        dispatch, _ = _dispatch(db, sid, provider)
        result = _propose(dispatch, context)

    assert result["proposal_status"] == "MODEL_OUTPUT_INVALID"
    assert result["available"] is False
    assert "hostile" not in json.dumps(result)


# ---------------------------------------------------------------------------
# Canonical provider failures travel through the dispatch outcome verbatim
# ---------------------------------------------------------------------------


def test_canonical_provider_failures_pass_through() -> None:
    sid = _seed_full_session("Task 158 provider failures")
    cases = (
        (
            LLMReasoningProviderError("connection to model host failed"),
            "MODEL_UNAVAILABLE",
        ),
        (ValueError("invalid json output"), "MODEL_OUTPUT_INVALID"),
        (ValueError("unknown candidate reference"), "MODEL_OUTPUT_INCONSISTENT"),
    )
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        for error, expected in cases:
            provider = _FailingProvider(error)
            package = _build_package(db, sid)
            audit = _audit(db, package)
            dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
                request=package, request_audit=audit
            )
            assert dispatch["dispatch_status"] == "UNAVAILABLE"
            assert dispatch["outcome"] == expected
            result = _propose(dispatch, context)
            assert result["proposal_status"] == expected
            assert result["available"] is False
            assert result["proposal"] is None
            assert result["session_id"] == sid
            assert len(provider.calls) == 1

    for outcome in _CANONICAL_MODEL_OUTCOMES:
        assert outcome in ALLOWED_BOUNDARY_OUTCOMES


# ---------------------------------------------------------------------------
# Missing / mismatched material fails closed as UNAVAILABLE
# ---------------------------------------------------------------------------


def test_missing_or_mismatched_material_is_unavailable() -> None:
    sid = _seed_full_session("Task 158 missing material")
    other_sid = _seed_full_session("Task 158 foreign session")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        other_context = _context(db, other_sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, package = _dispatch(db, sid, provider)

        assert _propose(None, context)["proposal_status"] == "UNAVAILABLE"
        assert _propose({}, context)["proposal_status"] == "UNAVAILABLE"

        blocked = _propose({**dispatch, "dispatch_status": "BLOCKED"}, context)
        assert blocked["proposal_status"] == "UNAVAILABLE"

        no_response = _propose({**dispatch, "provider_response": None}, context)
        assert no_response["proposal_status"] == "UNAVAILABLE"

        no_fingerprint = _propose({**dispatch, "request_fingerprint": None}, context)
        assert no_fingerprint["proposal_status"] == "UNAVAILABLE"

        assert _propose(dispatch, None)["proposal_status"] == "UNAVAILABLE"
        assert _propose(dispatch, {})["proposal_status"] == "UNAVAILABLE"

        unavailable_context = _propose(dispatch, {**context, "available": False})
        assert unavailable_context["proposal_status"] == "UNAVAILABLE"

        foreign_context = _propose(dispatch, other_context)
        assert foreign_context["proposal_status"] == "UNAVAILABLE"

        unconsumable = _propose(dispatch, {**context, "probe": _Uncopyable()})
        assert unconsumable["proposal_status"] == "UNAVAILABLE"

        foreign_session = _propose({**dispatch, "session_id": other_sid}, context)
        assert foreign_session["proposal_status"] == "UNAVAILABLE"

    assert dispatch["session_id"] == sid
    assert dispatch["request_fingerprint"] == package["context_fingerprint"]


# ---------------------------------------------------------------------------
# Provenance binding: dispatched context fingerprint (Task 158 correction)
# ---------------------------------------------------------------------------


def test_same_session_foreign_context_is_unavailable() -> None:
    sid = _seed_full_session("Task 158 same session foreign context")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        dispatched_context = _context(db, sid)
        provider.response = _response(_valid_model_output(dispatched_context))
        dispatch, package = _dispatch(db, sid, provider)
        calls_after_dispatch = len(provider.calls)

    later = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient later reports shortness of breath",
            "type": "symptom",
            "confidence": 0.8,
            "source": "unit_test",
        },
    )
    assert later.status_code == 201
    with TestingSessionLocal() as db:
        stale_context = _context(db, sid)

    assert dispatch["request_fingerprint"] == package["context_fingerprint"]
    assert stale_context["session_id"] == dispatched_context["session_id"]
    assert stale_context["available"] is True
    assert stale_context["context_consistent"] is True
    assert serialize_context(stale_context) != serialize_context(dispatched_context)
    assert (
        compute_fingerprint(serialize_context(stale_context))
        != dispatch["request_fingerprint"]
    )

    tampered_context = {
        **dispatched_context,
        "reasoning_pipeline": {
            **dispatched_context["reasoning_pipeline"],
            "stage_7": "tampered",
        },
    }
    assert (
        compute_fingerprint(serialize_context(tampered_context))
        != dispatch["request_fingerprint"]
    )

    stale_result = _propose(dispatch, stale_context)
    tampered_result = _propose(dispatch, tampered_context)
    stale_hostile = _propose(
        _swap_response(dispatch, _HostileResponse()), stale_context
    )
    control = _propose(dispatch, dispatched_context)

    for result in (stale_result, tampered_result, stale_hostile):
        assert set(result) == PROPOSAL_KEYS
        assert result["proposal_status"] == "UNAVAILABLE"
        assert result["available"] is False
        assert result["proposal"] is None
        assert result["context_fingerprint"] is None
        assert result["provider"] is None
        assert result["model"] is None
        assert result["session_id"] == sid
        assert (
            result["proposal_source"] == REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158
        )

    assert control["proposal_status"] == "VALIDATED"
    assert control["context_fingerprint"] == dispatch["request_fingerprint"]
    assert len(provider.calls) == calls_after_dispatch


def test_inconsistent_context_is_unavailable() -> None:
    sid = _seed_full_session("Task 158 inconsistent context")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, package = _dispatch(db, sid, provider)

    inconsistent = {**context, "context_consistent": False}
    missing_flag = {
        key: value for key, value in context.items() if key != "context_consistent"
    }
    assert inconsistent["available"] is True
    assert missing_flag["available"] is True
    # The serialization never carries the consistency flag, so only the
    # explicit gate can reject these two contexts.
    assert (
        compute_fingerprint(serialize_context(inconsistent))
        == package["context_fingerprint"]
    )
    assert (
        compute_fingerprint(serialize_context(missing_flag))
        == package["context_fingerprint"]
    )

    inconsistent_result = _propose(dispatch, inconsistent)
    missing_flag_result = _propose(dispatch, missing_flag)
    inconsistent_hostile = _propose(
        _swap_response(dispatch, _HostileResponse()), inconsistent
    )
    control = _propose(dispatch, context)

    for result in (inconsistent_result, missing_flag_result, inconsistent_hostile):
        assert result["proposal_status"] == "UNAVAILABLE"
        assert result["available"] is False
        assert result["proposal"] is None
        assert result["context_fingerprint"] is None
        assert result["provider"] is None
        assert result["model"] is None
        assert result["session_id"] == sid

    assert control["proposal_status"] == "VALIDATED"


# ---------------------------------------------------------------------------
# Provenance binding: the Task 157 dispatch projection (Task 158 correction)
# ---------------------------------------------------------------------------


def test_forged_dispatch_projection_is_unavailable() -> None:
    sid = _seed_full_session("Task 158 forged dispatch projection")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, package = _dispatch(db, sid, provider)

        forgeries = (
            {**dispatch, "available": False},
            {**dispatch, "request_status": "BLOCKED"},
            {**dispatch, "request_status": "UNAVAILABLE"},
            {**dispatch, "request_audit_status": "INCONSISTENT"},
            {**dispatch, "request_audit_status": "UNAVAILABLE"},
            {**dispatch, "request_fingerprint": None},
            {**dispatch, "outcome": OUTCOME_MODEL_UNAVAILABLE},
            {**dispatch, "dispatch_status": "FORGED"},
            {**dispatch, "provider": "smuggled"},
        )
        results = [
            _propose(_swap_response(forgery, _HostileResponse()), context)
            for forgery in forgeries
        ]
        valid_results = [_propose(forgery, context) for forgery in forgeries]
        control = _propose(dispatch, context)

    assert len(dispatch) == 9
    assert dispatch["request_fingerprint"] == package["context_fingerprint"]
    for result in (*results, *valid_results):
        assert set(result) == PROPOSAL_KEYS
        assert result["proposal_status"] == "UNAVAILABLE"
        assert result["available"] is False
        assert result["proposal"] is None
        assert result["context_fingerprint"] is None
        assert result["provider"] is None
        assert result["model"] is None
        assert result["session_id"] == sid

    assert control["proposal_status"] == "VALIDATED"


def test_minimal_forged_dispatch_is_unavailable() -> None:
    sid = _seed_full_session("Task 158 minimal forged dispatch")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        good_output = _valid_model_output(context)
        provider.response = _response(good_output)
        dispatch, package = _dispatch(db, sid, provider)

        # The exact forgery the reviewer described: a mapping claiming
        # DISPATCHED with a valid-looking fingerprint and a raw response,
        # never produced by the Task 157 boundary.
        forged = {
            "dispatch_status": "DISPATCHED",
            "session_id": sid,
            "request_fingerprint": package["context_fingerprint"],
            "provider_response": _response(good_output),
        }
        forged_result = _propose(forged, context)

        forged_hostile = _propose(
            {**forged, "provider_response": _HostileResponse()}, context
        )

        # A minimal non-dispatched mapping is not a Task 157 result, so
        # its outcome must not travel through as a model failure.
        minimal = {
            "dispatch_status": "UNAVAILABLE",
            "outcome": OUTCOME_MODEL_UNAVAILABLE,
        }
        minimal_result = _propose(minimal, context)

        control = _propose(dispatch, context)

    assert forged_result["proposal_status"] == "UNAVAILABLE"
    assert forged_result["available"] is False
    assert forged_result["proposal"] is None
    assert forged_result["context_fingerprint"] is None
    assert forged_result["provider"] is None
    assert forged_result["model"] is None
    assert forged_result["session_id"] == sid

    assert forged_hostile["proposal_status"] == "UNAVAILABLE"
    assert forged_hostile["proposal"] is None

    assert minimal_result["proposal_status"] == "UNAVAILABLE"
    assert minimal_result["available"] is False
    assert minimal_result["proposal"] is None

    assert control["proposal_status"] == "VALIDATED"


def test_valid_task_157_failures_still_pass_through() -> None:
    sid = _seed_full_session("Task 158 valid failure pass-through")
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        package = _build_package(db, sid)
        audit = _audit(db, package)
        provider = _FailingProvider(ValueError("invalid json output"))
        dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
            request=package, request_audit=audit
        )
        assert dispatch["dispatch_status"] == "UNAVAILABLE"
        assert dispatch["outcome"] == OUTCOME_MODEL_OUTPUT_INVALID
        result = _propose(dispatch, context)

    assert result["proposal_status"] == OUTCOME_MODEL_OUTPUT_INVALID
    assert result["available"] is False
    assert result["proposal"] is None
    assert result["session_id"] == sid


# ---------------------------------------------------------------------------
# Read-only, deterministic, and isolated
# ---------------------------------------------------------------------------


def test_validation_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 158 read-only")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)
    before = _table_counts()
    calls_before = len(provider.calls)

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("write or provider call attempted during validation")

    monkeypatch.setattr(Session, "add", _forbidden)
    monkeypatch.setattr(Session, "merge", _forbidden)
    monkeypatch.setattr(Session, "delete", _forbidden)
    monkeypatch.setattr(Session, "commit", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build_for_session", _forbidden)
    monkeypatch.setattr(ReasoningRunStage7DispatchService, "dispatch", _forbidden)
    monkeypatch.setattr(_FakeProvider, "generate_reasoning", _forbidden)

    result = _propose(dispatch, context)

    assert result["proposal_status"] == "VALIDATED"
    assert len(provider.calls) == calls_before
    assert _table_counts() == before


def test_validation_is_deterministic_and_non_mutating() -> None:
    sid = _seed_full_session("Task 158 determinism")
    provider = _FakeProvider()
    with TestingSessionLocal() as db:
        context = _context(db, sid)
        provider.response = _response(_valid_model_output(context))
        dispatch, _ = _dispatch(db, sid, provider)

    dispatch_snapshot = copy.deepcopy(dispatch)
    context_snapshot = serialize_context(context)

    first = _propose(dispatch, context)
    second = _propose(dispatch, context)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert dispatch == dispatch_snapshot
    assert serialize_context(context) == context_snapshot


# ---------------------------------------------------------------------------
# Schema strictness and provider-neutral source
# ---------------------------------------------------------------------------


def test_proposal_schema_is_strict() -> None:
    valid = {
        "proposal_status": "VALIDATED",
        "available": True,
        "session_id": "session-1",
        "context_fingerprint": "a" * 64,
        "provider": "fake-provider",
        "model": "fake-model",
        "proposal": {"session_id": "session-1"},
        "proposal_source": REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158,
    }
    validated = ReasoningRunStage7ProposalRead.model_validate(valid)
    assert validated.available is True

    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate({**valid, "extra": 1})
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate(
            {**valid, "proposal_status": "DONE"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate({**valid, "available": False})
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate({**valid, "proposal": None})
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate(
            {**valid, "context_fingerprint": None}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate({**valid, "provider": None})
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalRead.model_validate({**valid, "model": None})

    for outcome in (*_CANONICAL_MODEL_OUTCOMES, "UNAVAILABLE"):
        failure = ReasoningRunStage7ProposalRead.model_validate(
            {
                **valid,
                "proposal_status": outcome,
                "available": False,
                "context_fingerprint": None,
                "provider": None,
                "model": None,
                "proposal": None,
            }
        )
        assert failure.available is False
        assert failure.proposal is None


def test_proposal_service_is_provider_free() -> None:
    init = inspect.signature(ReasoningRunStage7ProposalService.__init__)
    assert "provider" not in init.parameters

    import rop.services.reasoning_run_stage_7_proposal as module

    for attr in (
        "PROVIDER_REGISTRY",
        "DEFAULT_PROVIDER",
        "AUTO_PROVIDER",
        "PROVIDER_FACTORY",
    ):
        assert not hasattr(module, attr)


def test_no_concrete_provider_module_present() -> None:
    import rop

    root = Path(rop.__file__).resolve().parent
    stems = [path.stem.lower() for path in root.rglob("*.py")]
    for token in _CONCRETE_PROVIDER_TOKENS:
        assert not any(token in stem for stem in stems)
        assert importlib.util.find_spec(f"rop.services.{token}") is None


def test_proposal_module_source_is_clean() -> None:
    import rop.schemas.reasoning_run_stage_7_proposal as schema_module
    import rop.services.reasoning_run_stage_7_proposal as module

    for source in (inspect.getsource(module), inspect.getsource(schema_module)):
        lowered = source.lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert token not in lowered

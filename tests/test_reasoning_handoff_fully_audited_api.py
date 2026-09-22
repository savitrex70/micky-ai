"""Tests for Task 065 fully audited reasoning handoff API.

The endpoint exposes the Task 063 audit bundle: the exact Task 061
audited API package, the exact Task 062 audit of that package, the
session identity, and the fixed Task 063 bundle source. It is a thin
API boundary over ``ReasoningHandoffFullyAuditedApiService``, which
builds the Task 059 response body exactly once and derives Tasks 060,
061, 062, and 063 from that exact object without any internal HTTP call.
"""

from __future__ import annotations

import copy
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
from rop.services import reasoning_handoff_fully_audited_api as mod
from rop.services.reasoning_handoff_api_audit_bundle import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063,
    ReasoningHandoffApiAuditBundleContractError,
)
from rop.services.reasoning_handoff_api_audit_package import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062,
    ReasoningHandoffApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_api_consistency import (
    REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060,
)
from rop.services.reasoning_handoff_fully_audited_api import (
    ReasoningHandoffFullyAuditedApiService,
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

ENDPOINT = "/sessions/{sid}/reasoning-handoff/fully-audited"

BUNDLE_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)

PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "response",
    "api_consistency",
    "package_source",
)

RESPONSE_FIELDS = (
    "available",
    "handoff_consistent",
    "session_id",
    "reasoning_context",
    "context_consistency",
    "handoff_source",
)


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-065-test"},
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


def _inconsistent_handoff(sid: UUID) -> dict[str, Any]:
    """Build a genuinely inconsistent but structurally valid Task 057
    handoff for the supplied session, using the real upstream services.
    """
    from rop.services.reasoning_context import ReasoningContextService
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )
    from rop.services.reasoning_handoff import ReasoningHandoffService

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, sid)
    finally:
        db_gen.close()

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
    audit_055 = ReasoningContextConsistencyService().build(context=tampered_context)
    handoff = ReasoningHandoffService().build(
        reasoning_context=tampered_context,
        context_consistency=audit_055,
    )
    assert handoff["handoff_consistent"] is False
    return json.loads(json.dumps(handoff, default=str))


# ---------------------------------------------------------------------------
# Valid endpoint
# ---------------------------------------------------------------------------


def test_valid_session_returns_200() -> None:
    sid = _seed_full_session("Task 065 valid")
    r = client.get(ENDPOINT.format(sid=sid))
    assert r.status_code == 200


def test_response_has_exact_bundle_fields() -> None:
    sid = _seed_full_session("Task 065 shape")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    assert set(payload) == set(BUNDLE_FIELDS)


def test_bundle_is_available_and_consistent() -> None:
    sid = _seed_full_session("Task 065 available")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    assert payload["available"] is True
    assert payload["bundle_consistent"] is True


def test_bundle_source_correct() -> None:
    sid = _seed_full_session("Task 065 bundle source")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    assert payload["bundle_source"] == (
        REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063
    )


def test_nested_package_shape_preserved() -> None:
    sid = _seed_full_session("Task 065 nested package")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    package = payload["api_audit_package"]
    assert set(package) == set(PACKAGE_FIELDS)
    assert package["package_source"] == (
        REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061
    )
    assert package["available"] is True
    assert package["package_consistent"] is True


def test_nested_package_consistency_source_preserved() -> None:
    sid = _seed_full_session("Task 065 nested audit")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    consistency = payload["api_audit_package_consistency"]
    assert consistency["package_consistency_source"] == (
        REASONING_HANDOFF_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_062
    )
    assert consistency["available"] is True
    assert consistency["package_consistent"] is True


def test_nested_api_consistency_source_preserved() -> None:
    sid = _seed_full_session("Task 065 api audit")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    api_consistency = payload["api_audit_package"]["api_consistency"]
    assert api_consistency["api_consistency_source"] == (
        REASONING_HANDOFF_API_CONSISTENCY_SOURCE_TASK_060
    )


def test_nested_response_is_task057_handoff_shape() -> None:
    sid = _seed_full_session("Task 065 nested response")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    response = payload["api_audit_package"]["response"]
    assert set(response) == set(RESPONSE_FIELDS)


def test_session_identity_agrees_across_layers() -> None:
    sid = _seed_full_session("Task 065 session identity")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    assert payload["session_id"] == sid
    assert payload["api_audit_package"]["session_id"] == sid
    assert payload["api_audit_package"]["response"]["session_id"] == sid
    assert payload["api_audit_package"]["api_consistency"]["audited_session_id"] == sid


def test_bundle_consistent_mirrors_nested_package_consistency() -> None:
    sid = _seed_full_session("Task 065 relationship")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    assert (
        payload["bundle_consistent"]
        == payload["api_audit_package_consistency"]["package_consistent"]
    )


def test_transport_metadata_is_the_audited_route() -> None:
    sid = _seed_full_session("Task 065 transport")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    package = payload["api_audit_package"]
    assert package["method"] == "GET"
    assert package["status_code"] == 200
    assert package["path"] == f"/sessions/{sid}/reasoning-handoff"


def test_nested_response_fingerprint_provenance_holds() -> None:
    """The nested Task 060 audit must bind to the nested Task 059
    response by fingerprint, recomputed independently here."""
    from rop.services.reasoning_handoff_api_consistency import (
        ReasoningHandoffApiConsistencyService,
    )

    sid = _seed_full_session("Task 065 response provenance")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    package = payload["api_audit_package"]
    expected = ReasoningHandoffApiConsistencyService._response_fingerprint(
        package["response"]
    )
    assert package["api_consistency"]["audited_response_fingerprint"] == expected


def test_nested_package_fingerprint_provenance_holds() -> None:
    """The nested Task 062 audit must bind to the nested Task 061
    package by fingerprint, recomputed independently here."""
    sid = _seed_full_session("Task 065 package provenance")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    expected = ReasoningHandoffApiAuditPackageConsistencyService._package_fingerprint(
        payload["api_audit_package"]
    )
    assert (
        payload["api_audit_package_consistency"]["audited_package_fingerprint"]
        == expected
    )


def test_nested_response_equals_task059_endpoint_body() -> None:
    """The bundled response must be exactly the body the Task 059
    endpoint transmits -- same fields, same representation."""
    sid = _seed_full_session("Task 065 transport equality")
    handoff_body = client.get(f"/sessions/{sid}/reasoning-handoff").json()
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    assert payload["api_audit_package"]["response"] == handoff_body


def test_nested_fingerprints_are_provable_from_the_received_body() -> None:
    """A consumer holding only the received JSON must be able to
    recompute the nested Task 060 and Task 062 fingerprints. This is the
    provenance property the transport representation exists to preserve."""
    from rop.services.reasoning_handoff_api_consistency import (
        ReasoningHandoffApiConsistencyService,
    )

    sid = _seed_full_session("Task 065 cross-boundary provenance")
    payload = client.get(ENDPOINT.format(sid=sid)).json()
    package = payload["api_audit_package"]

    assert (
        ReasoningHandoffApiConsistencyService._response_fingerprint(package["response"])
        == package["api_consistency"]["audited_response_fingerprint"]
    )
    assert (
        ReasoningHandoffApiAuditPackageConsistencyService._package_fingerprint(package)
        == payload["api_audit_package_consistency"]["audited_package_fingerprint"]
    )


def test_transport_body_matches_the_task057_response_model() -> None:
    """``_transport_body`` must reproduce exactly what the Task 059
    endpoint transmits for its own ``ReasoningHandoffRead`` model."""
    from rop.schemas.reasoning_handoff import ReasoningHandoffRead
    from rop.services.reasoning_handoff_api import ReasoningHandoffApiService

    sid_str = _seed_full_session("Task 065 transport helper")
    sid = UUID(sid_str)

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        raw = ReasoningHandoffApiService().build_for_session(db, sid)
    finally:
        db_gen.close()

    body = mod._transport_body(raw)
    assert body == client.get(f"/sessions/{sid_str}/reasoning-handoff").json()
    assert body == ReasoningHandoffRead.model_validate(dict(raw)).model_dump(
        mode="json"
    )


def test_transport_body_does_not_mutate_its_input() -> None:
    from rop.services.reasoning_handoff_api import ReasoningHandoffApiService

    sid_str = _seed_full_session("Task 065 transport no mutation")
    sid = UUID(sid_str)

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        raw = ReasoningHandoffApiService().build_for_session(db, sid)
    finally:
        db_gen.close()

    before = copy.deepcopy(raw)
    mod._transport_body(raw)
    assert raw == before


# ---------------------------------------------------------------------------
# Failure boundaries
# ---------------------------------------------------------------------------


def test_missing_session_returns_404() -> None:
    r = client.get(ENDPOINT.format(sid=uuid4()))
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


def test_post_method_is_not_allowed() -> None:
    sid = _seed_full_session("Task 065 post")
    r = client.post(ENDPOINT.format(sid=sid))
    assert r.status_code == 405


def test_forced_handoff_contract_error_returns_generic_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.api import sessions as sessions_module
    from rop.services.reasoning_handoff import ReasoningHandoffContractError

    sid = _seed_full_session("Task 065 forced handoff failure")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ReasoningHandoffContractError(
            "FORCED_TEST_FAILURE", "raw internal detail must not leak"
        )

    orchestration = sessions_module.reasoning_handoff_fully_audited_api_service
    monkeypatch.setattr(
        orchestration.reasoning_handoff_api_service,
        "build_for_session",
        boom,
    )
    r = client.get(ENDPOINT.format(sid=sid))
    assert r.status_code == 500
    assert "raw internal detail" not in r.json()["detail"]
    assert (
        r.json()["detail"]
        == "Internal reasoning-handoff fully-audited contract violation"
    )


def test_forced_bundle_contract_error_returns_generic_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rop.api import sessions as sessions_module

    sid = _seed_full_session("Task 065 forced bundle failure")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ReasoningHandoffApiAuditBundleContractError(
            "FORCED_TEST_FAILURE", "raw internal detail must not leak"
        )

    orchestration = sessions_module.reasoning_handoff_fully_audited_api_service
    monkeypatch.setattr(
        orchestration.reasoning_handoff_api_audit_bundle_service,
        "build",
        boom,
    )
    r = client.get(ENDPOINT.format(sid=sid))
    assert r.status_code == 500
    assert "raw internal detail" not in r.json()["detail"]


def test_unavailable_nested_audit_is_not_downgraded_to_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable Task 062 audit must never be silently downgraded
    into a successful audited response."""
    from rop.api import sessions as sessions_module

    sid = _seed_full_session("Task 065 unavailable audit")
    orchestration = sessions_module.reasoning_handoff_fully_audited_api_service
    consistency_service = (
        orchestration.reasoning_handoff_api_audit_package_consistency_service
    )
    real_build = consistency_service.build

    def unavailable(*, package: Any) -> dict[str, Any]:
        result = real_build(package=package)
        result["available"] = False
        return result

    monkeypatch.setattr(consistency_service, "build", unavailable)
    r = client.get(ENDPOINT.format(sid=sid))
    assert r.status_code == 500


def test_malformed_nested_response_is_not_downgraded_to_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed Task 059 response body must surface as an internal
    failure, never as a 200 that reports available=False."""
    from rop.api import sessions as sessions_module

    sid = _seed_full_session("Task 065 malformed response")

    def malformed(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"available": True}

    orchestration = sessions_module.reasoning_handoff_fully_audited_api_service
    monkeypatch.setattr(
        orchestration.reasoning_handoff_api_service,
        "build_for_session",
        malformed,
    )
    r = client.get(ENDPOINT.format(sid=sid))
    assert r.status_code == 500


def test_legitimate_underlying_inconsistency_still_returns_audited_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid response whose underlying handoff legitimately reports
    ``handoff_consistent = False`` must still produce a 200 whose bundle
    faithfully represents it with ``bundle_consistent = True``."""
    from rop.api import sessions as sessions_module

    sid_str = _seed_full_session("Task 065 legitimate inconsistency")
    handoff = _inconsistent_handoff(UUID(sid_str))

    def stub(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return handoff

    orchestration = sessions_module.reasoning_handoff_fully_audited_api_service
    monkeypatch.setattr(
        orchestration.reasoning_handoff_api_service,
        "build_for_session",
        stub,
    )
    r = client.get(ENDPOINT.format(sid=sid_str))
    assert r.status_code == 200
    payload = r.json()
    assert payload["api_audit_package"]["response"]["handoff_consistent"] is False
    assert payload["api_audit_package"]["api_consistency"]["api_consistent"] is True
    assert payload["api_audit_package"]["package_consistent"] is True
    assert payload["api_audit_package_consistency"]["package_consistent"] is True
    assert payload["bundle_consistent"] is True
    assert payload["available"] is True


# ---------------------------------------------------------------------------
# Read-only and determinism
# ---------------------------------------------------------------------------


def test_response_is_deterministic() -> None:
    sid = _seed_full_session("Task 065 determinism")
    first = client.get(ENDPOINT.format(sid=sid)).json()
    second = client.get(ENDPOINT.format(sid=sid)).json()
    assert first == second


def test_endpoint_is_read_only() -> None:
    sid = _seed_full_session("Task 065 read-only")
    before_run = client.get(f"/sessions/{sid}/reasoning-run").json()
    before_candidates = client.get(f"/sessions/{sid}/candidates").json()

    for _ in range(3):
        assert client.get(ENDPOINT.format(sid=sid)).status_code == 200

    assert client.get(f"/sessions/{sid}/reasoning-run").json() == before_run
    assert client.get(f"/sessions/{sid}/candidates").json() == before_candidates


def test_existing_reasoning_handoff_endpoint_unchanged() -> None:
    sid = _seed_full_session("Task 065 existing endpoint")
    r = client.get(f"/sessions/{sid}/reasoning-handoff")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESPONSE_FIELDS)
    assert "bundle_source" not in payload


# ---------------------------------------------------------------------------
# Orchestration identity: the Task 059 body flows unchanged through 060-063
# ---------------------------------------------------------------------------


class _StubHandoffApiService:
    """Records the session passed in; returns a sentinel body."""

    def __init__(self, sentinel: object) -> None:
        self.sentinel = sentinel
        self.calls: list[tuple[object, object]] = []

    def build_for_session(self, db: object, session_id: object) -> object:
        self.calls.append((db, session_id))
        return self.sentinel


class _StubAuditService:
    """Records the exact body it received; returns a sentinel audit."""

    def __init__(self, sentinel: object) -> None:
        self.sentinel = sentinel
        self.received_bodies: list[object] = []
        self.kwargs: list[dict[str, Any]] = []

    def build(self, **kwargs: Any) -> object:
        self.received_bodies.append(kwargs.get("response_body"))
        self.kwargs.append(kwargs)
        return self.sentinel


class _StubPackageService:
    """Records the exact body and audit it received."""

    def __init__(self, sentinel: object) -> None:
        self.sentinel = sentinel
        self.received_bodies: list[object] = []
        self.received_audits: list[object] = []

    def build(self, **kwargs: Any) -> object:
        self.received_bodies.append(kwargs.get("response"))
        self.received_audits.append(kwargs.get("api_consistency"))
        return self.sentinel


class _StubPackageConsistencyService:
    """Records the exact package it received."""

    def __init__(self, sentinel: object) -> None:
        self.sentinel = sentinel
        self.received_packages: list[object] = []

    def build(self, *, package: object) -> object:
        self.received_packages.append(package)
        return self.sentinel


class _StubBundleService:
    """Records the exact package and audit it received."""

    def __init__(self, sentinel: object) -> None:
        self.sentinel = sentinel
        self.received_packages: list[object] = []
        self.received_audits: list[object] = []

    def build(self, **kwargs: Any) -> object:
        self.received_packages.append(kwargs.get("api_audit_package"))
        self.received_audits.append(kwargs.get("api_audit_package_consistency"))
        return self.sentinel


def _wired_stubs() -> tuple[Any, ...]:
    sentinels: dict[str, object] = {
        "response": {"sentinel": "response"},
        "audit": {"sentinel": "audit"},
        "package": {"sentinel": "package"},
        "package_consistency": {"sentinel": "package_consistency"},
        "bundle": {"sentinel": "bundle"},
    }
    handoff_stub = _StubHandoffApiService(sentinels["response"])
    audit_stub = _StubAuditService(sentinels["audit"])
    package_stub = _StubPackageService(sentinels["package"])
    consistency_stub = _StubPackageConsistencyService(sentinels["package_consistency"])
    bundle_stub = _StubBundleService(sentinels["bundle"])
    service = ReasoningHandoffFullyAuditedApiService(
        reasoning_handoff_api_service=handoff_stub,  # type: ignore[arg-type]
        reasoning_handoff_api_consistency_service=audit_stub,  # type: ignore[arg-type]
        reasoning_handoff_api_audit_package_service=package_stub,  # type: ignore[arg-type]
        reasoning_handoff_api_audit_package_consistency_service=(
            consistency_stub  # type: ignore[arg-type]
        ),
        reasoning_handoff_api_audit_bundle_service=bundle_stub,  # type: ignore[arg-type]
    )
    return (
        service,
        handoff_stub,
        audit_stub,
        package_stub,
        consistency_stub,
        bundle_stub,
        sentinels,
    )


def test_orchestration_passes_exact_same_represented_body() -> None:
    """Task 065 must represent the Task 059 body once and pass that exact
    represented object into both Task 060 and Task 061. Identity, not
    equality: a refactor that represents the body twice must fail this
    test."""
    (
        service,
        handoff_stub,
        audit_stub,
        package_stub,
        consistency_stub,
        bundle_stub,
        sentinels,
    ) = _wired_stubs()

    session_id = uuid4()
    result = service.build_for_session(db=None, session_id=session_id)

    assert len(handoff_stub.calls) == 1
    assert len(audit_stub.received_bodies) == 1
    assert len(package_stub.received_bodies) == 1
    assert len(package_stub.received_audits) == 1
    assert len(consistency_stub.received_packages) == 1
    assert len(bundle_stub.received_packages) == 1
    assert len(bundle_stub.received_audits) == 1

    # The exact object audited by Task 060 is the exact object packaged
    # by Task 061 -- one representation, not two.
    assert package_stub.received_bodies[0] is audit_stub.received_bodies[0]
    assert audit_stub.received_bodies[0] == sentinels["response"]
    assert package_stub.received_audits[0] is sentinels["audit"]
    assert consistency_stub.received_packages[0] is sentinels["package"]
    assert bundle_stub.received_packages[0] is sentinels["package"]
    assert bundle_stub.received_audits[0] is sentinels["package_consistency"]
    assert result is sentinels["bundle"]


def test_representation_does_not_mutate_the_task059_result() -> None:
    """Representing the body must never mutate the Task 059 result."""
    (
        service,
        handoff_stub,
        _audit_stub,
        _package_stub,
        _consistency_stub,
        _bundle_stub,
        sentinels,
    ) = _wired_stubs()

    original = copy.deepcopy(sentinels["response"])
    service.build_for_session(db=None, session_id=uuid4())
    assert handoff_stub.calls
    assert sentinels["response"] == original


def test_orchestration_does_not_rebuild_the_response() -> None:
    """Task 059 must be called exactly once per request."""
    (
        service,
        handoff_stub,
        _audit_stub,
        _package_stub,
        _consistency_stub,
        _bundle_stub,
        _sentinels,
    ) = _wired_stubs()

    service.build_for_session(db=None, session_id=uuid4())
    assert len(handoff_stub.calls) == 1


def test_orchestration_uses_the_audited_route_transport() -> None:
    """The transport metadata audited at this layer must be the Task 065
    GET route for the supplied session."""
    (
        service,
        _handoff_stub,
        audit_stub,
        _package_stub,
        _consistency_stub,
        _bundle_stub,
        _sentinels,
    ) = _wired_stubs()

    session_id = uuid4()
    service.build_for_session(db=None, session_id=session_id)

    kwargs = audit_stub.kwargs[0]
    assert kwargs["session_id"] == session_id
    assert kwargs["method"] == "GET"
    assert kwargs["status_code"] == 200
    assert kwargs["path"] == f"/sessions/{session_id}/reasoning-handoff"


# ---------------------------------------------------------------------------
# Architectural assertions
# ---------------------------------------------------------------------------

_FORBIDDEN = (
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


def test_service_has_no_http_client_or_api_module_dependency() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "fastapi",
        "TestClient",
        "httpx",
        "requests",
        "urllib",
        "rop.api.sessions",
        "APIRouter",
    ):
        assert forbidden not in src, forbidden


def test_service_has_no_database_writes() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        "get_db",
        "commit",
        "add(",
        "flush",
    ):
        assert forbidden not in src, forbidden


def test_service_has_no_llm_or_provider_symbols() -> None:
    import re as _re

    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token


def test_endpoint_does_not_invoke_upstream_services_directly() -> None:
    import rop.api.sessions as sessions_module

    src = inspect.getsource(sessions_module)
    start = src.find("def get_reasoning_handoff_fully_audited")
    assert start != -1
    body = src[start : start + 3000]
    for forbidden in (
        "ReasoningHandoffApiService",
        "ReasoningHandoffApiConsistencyService",
        "ReasoningHandoffApiAuditPackageService",
        "ReasoningHandoffApiAuditPackageConsistencyService",
        "ReasoningHandoffApiAuditBundleService",
        "ReasoningContextService",
        "ReasoningHandoffService",
    ):
        assert forbidden not in body, forbidden

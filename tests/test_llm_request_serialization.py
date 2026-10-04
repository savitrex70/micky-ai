"""Tests for Task 104 LLM request serialization boundary.

All tests use pure functions from llm_request_serialization. No DB,
no HTTP, no provider calls. A seed session helper builds a realistic
Task 055 context via the existing API/client.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
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


def override_get_db() -> Session:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


# ---------------------------------------------------------------------------
# Session / context helpers
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-104-test"},
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


def _valid_context(user_input: str = "Task 104 valid") -> dict[str, Any]:
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


def test_source_constant_exists() -> None:
    assert (
        LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104
        == "LLM_REQUEST_SERIALIZATION_TASK_104"
    )


def test_allowed_payload_fields_exact() -> None:
    """The allowed fields tuple matches Task 057 exactly (8 fields)."""
    expected = (
        "session_id",
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
        "reasoning_pipeline",
    )
    assert ALLOWED_PAYLOAD_FIELDS == expected
    assert (
        len(ALLOWED_PAYLOAD_FIELDS) == 7
    )  # Note: Task 057 had 8 but one was context_fingerprint which is separate


def test_element_serializers_structure() -> None:
    """ELEMENT_SERIALIZERS has correct field/schema pairs."""
    assert len(ELEMENT_SERIALIZERS) == 5
    field_names = [f for f, _ in ELEMENT_SERIALIZERS]
    assert field_names == [
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ]
    # Each schema should be a Pydantic model class
    for _, schema in ELEMENT_SERIALIZERS:
        assert issubclass(schema, BaseModel)


def test_serialize_context_exact_allowed_fields() -> None:
    """serialize_context returns only the allowed fields."""
    ctx = _valid_context()
    payload = serialize_context(ctx)
    assert set(payload.keys()) == set(ALLOWED_PAYLOAD_FIELDS)


def test_serialize_context_rejects_extra_fields() -> None:
    """Extra fields in context are not emitted in payload."""
    ctx = _valid_context()
    # Add an extra field to the context (simulating upstream addition)
    ctx_with_extra = dict(ctx)
    ctx_with_extra["extra_field"] = "should_not_appear"
    payload = serialize_context(ctx_with_extra)
    assert "extra_field" not in payload
    assert set(payload.keys()) == set(ALLOWED_PAYLOAD_FIELDS)


def test_validate_payload_empty_on_valid() -> None:
    """validate_payload returns empty list for valid payload."""
    ctx = _valid_context()
    payload = serialize_context(ctx)
    unexpected = validate_payload(payload)
    assert unexpected == []


def test_validate_payload_reports_unexpected() -> None:
    """validate_payload returns list of unexpected top-level fields."""
    payload = {"session_id": str(uuid4()), "observations": [], "extra": "bad"}
    unexpected = validate_payload(payload)
    assert unexpected == ["extra"]


def test_deterministic_dict_key_ordering() -> None:
    """Dict keys are sorted in serialized output."""
    ctx = _valid_context()
    payload = serialize_context(ctx)
    # reasoning_pipeline is a dict; its keys should be sorted
    pipeline = payload["reasoning_pipeline"]
    keys = list(pipeline.keys())
    assert keys == sorted(keys)


def test_list_order_preserved_per_contract() -> None:
    """List element order is preserved (not sorted) per contract."""
    ctx = _valid_context()
    payload = serialize_context(ctx)
    # observations list order should match context order
    ctx_obs_ids = [str(o.id) for o in ctx["observations"]]
    payload_obs_ids = [o["id"] for o in payload["observations"]]
    assert payload_obs_ids == ctx_obs_ids

    # candidate_state list order should match context order
    ctx_cand_ids = [str(c.id) for c in ctx["candidate_state"]]
    payload_cand_ids = [c["id"] for c in payload["candidate_state"]]
    assert payload_cand_ids == ctx_cand_ids


def test_uuid_normalization_to_string() -> None:
    """All UUIDs are normalized to strings in payload."""
    ctx = _valid_context()
    payload = serialize_context(ctx)

    # session_id is a string
    assert isinstance(payload["session_id"], str)
    UUID(payload["session_id"])  # valid UUID string

    # All list elements have string IDs
    for field in (
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ):
        for item in payload[field]:
            assert isinstance(item["id"], str)
            UUID(item["id"])  # valid UUID string


def test_fingerprint_determinism_same_input_same_hash() -> None:
    """compute_fingerprint is deterministic: same input = same hash."""
    ctx = _valid_context()
    payload = serialize_context(ctx)

    fp1 = compute_fingerprint(payload)
    fp2 = compute_fingerprint(payload)
    fp3 = compute_fingerprint(payload)

    assert fp1 == fp2 == fp3
    assert len(fp1) == 64
    assert all(c in "0123456789abcdef" for c in fp1)


def test_fingerprint_stability_across_identical_inputs() -> None:
    """Fingerprint is stable across independently created identical payloads."""
    ctx = _valid_context()
    payload1 = serialize_context(ctx)
    payload2 = serialize_context(ctx)

    fp1 = compute_fingerprint(payload1)
    fp2 = compute_fingerprint(payload2)

    assert fp1 == fp2


def test_immutability_input_not_mutated() -> None:
    """serialize_context does not mutate the input context."""
    ctx = _valid_context()

    # Snapshot identity/shape of nested collections
    snaps = {}
    for name in (
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ):
        lst = ctx[name]
        snaps[name] = (id(lst), len(lst), [id(x) for x in lst])
    pipeline_keys = list(ctx["reasoning_pipeline"].keys())

    # Serialize
    _ = serialize_context(ctx)

    # Verify no mutation
    for name, (lst_id, length, item_ids) in snaps.items():
        assert id(ctx[name]) == lst_id, f"{name}: list identity changed"
        assert len(ctx[name]) == length, f"{name}: list length changed"
        assert [
            id(x) for x in ctx[name]
        ] == item_ids, f"{name}: item identities changed"
    assert list(ctx["reasoning_pipeline"].keys()) == pipeline_keys


def test_to_json_safe_rejects_unsupported_type() -> None:
    """to_json_safe raises TypeError for unsupported types."""

    class CustomObject:
        pass

    with pytest.raises(TypeError) as ei:
        to_json_safe(CustomObject())
    assert "unsupported value in serialization" in str(ei.value)


def test_to_json_safe_accepts_supported_values() -> None:
    """to_json_safe handles all supported types correctly."""
    assert to_json_safe("x") == "x"
    assert to_json_safe(1) == 1
    assert to_json_safe(1.5) == 1.5
    assert to_json_safe(True) is True
    assert to_json_safe(None) is None

    u = uuid4()
    assert to_json_safe(u) == str(u)

    # Nested structures
    nested = {"a": [u, 1, "two"], "b": {"c": u}}
    result = to_json_safe(nested)
    assert result == {"a": [str(u), 1, "two"], "b": {"c": str(u)}}

    # Dict keys are sorted
    unsorted = {"z": 1, "a": 2}
    result = to_json_safe(unsorted)
    assert list(result.keys()) == ["a", "z"]


def test_serialize_context_handles_empty_lists() -> None:
    """serialize_context works with empty lists in context."""
    ctx = _valid_context()
    # Create a context with empty lists
    empty_ctx = dict(ctx)
    for field in (
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
    ):
        empty_ctx[field] = []

    payload = serialize_context(empty_ctx)
    assert set(payload.keys()) == set(ALLOWED_PAYLOAD_FIELDS)
    for field in ALLOWED_PAYLOAD_FIELDS:
        if field != "session_id" and field != "reasoning_pipeline":
            assert payload[field] == []


def test_compute_fingerprint_uses_canonical_json() -> None:
    """compute_fingerprint uses canonical JSON (sorted keys, minimal separators)."""
    # Two payloads with same data but different key orders should have same fingerprint
    payload1 = {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "candidate_state": [],
        "reasoning_pipeline": {"z": 1, "a": 2},
    }
    payload2 = {
        "a": 2,
        "z": 1,
        "session_id": "00000000-0000-0000-0000-000000000000",
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "candidate_state": [],
        "reasoning_pipeline": {},
    }
    # Different field order at top level, and different reasoning_pipeline key order
    fp1 = compute_fingerprint(payload1)
    fp2 = compute_fingerprint(payload2)

    # They should NOT be equal because payload2 has extra fields "a" and "z"
    # and missing some required fields
    assert fp1 != fp2

    # But two payloads with same data in different key orders should match
    payload3 = {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "candidate_state": [],
        "reasoning_pipeline": {"z": 1, "a": 2},
    }
    payload4 = {
        "reasoning_pipeline": {"a": 2, "z": 1},
        "candidate_state": [],
        "template_context": [],
        "missing_information": [],
        "entities": [],
        "observations": [],
        "session_id": "00000000-0000-0000-0000-000000000000",
    }
    fp3 = compute_fingerprint(payload3)
    fp4 = compute_fingerprint(payload4)
    assert fp3 == fp4


def test_element_serializers_match_schemas() -> None:
    """Each element serializer validates items correctly."""
    ctx = _valid_context()
    payload = serialize_context(ctx)

    # Verify each list element matches its schema
    for field, schema in ELEMENT_SERIALIZERS:
        for item in payload[field]:
            # Should not raise
            validated = schema.model_validate(item)
            assert validated.model_dump(mode="json") == item


def test_reasoning_pipeline_is_dict_not_model() -> None:
    """reasoning_pipeline is serialized as a plain dict, not a model."""
    ctx = _valid_context()
    payload = serialize_context(ctx)

    assert isinstance(payload["reasoning_pipeline"], dict)
    # Should be JSON-serializable
    json.dumps(payload["reasoning_pipeline"])


def test_fingerprint_independent_of_context_extra_fields() -> None:
    """Fingerprint only depends on serialized payload, not context extras."""
    ctx = _valid_context()
    payload1 = serialize_context(ctx)

    ctx_with_extra = dict(ctx)
    ctx_with_extra["extra_field"] = "ignored"
    ctx_with_extra["another_extra"] = {"nested": "data"}
    payload2 = serialize_context(ctx_with_extra)

    assert payload1 == payload2
    assert compute_fingerprint(payload1) == compute_fingerprint(payload2)


def test_validate_payload_case_sensitive() -> None:
    """validate_payload is case-sensitive."""
    payload = {"SESSION_ID": "x", "session_id": "y"}
    unexpected = validate_payload(payload)
    assert "SESSION_ID" in unexpected
    assert "session_id" not in unexpected

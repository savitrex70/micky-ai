"""Task 104: hardened deterministic LLM request serialization boundary.

Extracted and hardened from Task 057. Pure functions only: no DB,
no HTTP, no provider calls, no mutation, deterministic ordering.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.schemas.candidate_hypothesis import CandidateHypothesisRead
from rop.schemas.entity import EntityRead
from rop.schemas.llm_request_serialization import (
    LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104,
)
from rop.schemas.missing_information import MissingInformationRead
from rop.schemas.observation import ObservationRead
from rop.schemas.template_match import TemplateMatchRead

__all__ = [
    "LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104",
    "ALLOWED_PAYLOAD_FIELDS",
    "ELEMENT_SERIALIZERS",
    "serialize_context",
    "to_json_safe",
    "compute_fingerprint",
    "validate_payload",
]

# Fields the model is allowed to receive. Nothing else is exposed.
# Same seven fields as Task 057.
ALLOWED_PAYLOAD_FIELDS = (
    "session_id",
    "observations",
    "entities",
    "missing_information",
    "template_context",
    "candidate_state",
    "reasoning_pipeline",
)

# Context lists and the Read schemas that serialize each element for
# the model. Reused, not duplicated.
ELEMENT_SERIALIZERS = (
    ("observations", ObservationRead),
    ("entities", EntityRead),
    ("missing_information", MissingInformationRead),
    ("template_context", TemplateMatchRead),
    ("candidate_state", CandidateHypothesisRead),
)


def serialize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Project the context into a JSON-safe, model-safe payload.

    Only the allowed fields are emitted. Each list element is normalized
    through its own Read schema; anything else in the context (ORM
    internals, private attributes, extra Task 055 fields) is never exposed.

    Args:
        context: A Task 055 canonical context mapping.

    Returns:
        A canonical dict containing only ALLOWED_PAYLOAD_FIELDS, with
        all values JSON-safe (UUID -> str, Mapping -> sorted dict).
    """
    payload: dict[str, Any] = {
        "session_id": str(context["session_id"]),
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "candidate_state": [],
        "reasoning_pipeline": dict(context["reasoning_pipeline"]),
    }
    for field, schema in ELEMENT_SERIALIZERS:
        for item in context[field]:
            validated = schema.model_validate(item)
            payload[field].append(validated.model_dump(mode="json"))
    return to_json_safe(payload)


def to_json_safe(value: Any) -> Any:
    """Deterministic JSON-safe conversion.

    - UUID -> str
    - Mapping -> dict with string keys, sorted by key, values recursively converted
    - list -> list with elements recursively converted
    - primitives (str, int, float, bool, None) -> as-is
    - unsupported types -> raises TypeError

    Args:
        value: Any Python value.

    Returns:
        A JSON-serializable value with deterministic ordering.

    Raises:
        TypeError: If value contains an unsupported type.
    """
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(k): to_json_safe(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, list):
        return [to_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported value in serialization: {type(value).__name__}")


def compute_fingerprint(serialized: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 fingerprint via canonical JSON.

    Uses canonical JSON with sorted keys, minimal separators, and
    to_json_safe as the default serializer.

    Args:
        serialized: A JSON-safe mapping (output of serialize_context).

    Returns:
        Hex digest string (64 lowercase hex chars).
    """
    canonical = to_json_safe(serialized)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    """Validate that payload contains only allowed top-level fields.

    Args:
        payload: A mapping to validate.

    Returns:
        List of unexpected field names (empty if valid).
    """
    allowed = set(ALLOWED_PAYLOAD_FIELDS)
    return [key for key in payload.keys() if key not in allowed]

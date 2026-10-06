"""Task 115: canonical context snapshot / TOCTOU protection tests.

The boundary must operate on one deterministic snapshot: Task 056
audits it, Task 104 serializes it, the fingerprint covers it, and the
provider request carries it. A mutable/adversarial caller mapping whose
values shift between reads cannot change what was approved. No real
provider, no network.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping
from typing import Any

from rop.services.llm_request_serialization import (
    PAYLOAD_FIELDS,
    compute_fingerprint,
    serialize_context,
)
from tests.test_llm_live_boundary_enforcement import (
    FakeProvider,
    _service_with,
    _valid_context,
    _valid_model_output,
)


class _ShiftingMapping(Mapping[str, Any]):
    """A hostile mapping: ``candidate_state`` empties after its first read.

    Without a construct-time snapshot, the audit step and the later
    serialization step would observe different contexts (TOCTOU). With
    the Task 115 snapshot, every step observes the first-read values.
    """

    def __init__(self, base: Mapping[str, Any]) -> None:
        self._base = base
        self._reads: dict[str, int] = {}

    def __getitem__(self, key: str) -> Any:
        count = self._reads.get(key, 0)
        self._reads[key] = count + 1
        if key == "candidate_state" and count >= 1:
            return []
        value = self._base[key]
        if count >= 1 and isinstance(value, list):
            return list(value)
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._base)

    def __len__(self) -> int:
        return len(self._base)


def test_shifting_context_still_yields_approved_snapshot() -> None:
    ctx = _valid_context()
    approved_payload = serialize_context(ctx)
    approved_fingerprint = compute_fingerprint(approved_payload)
    expected_text = _valid_model_output(ctx)
    expected_count = len(ctx["candidate_state"])

    seen: dict[str, Any] = {}

    class _RecordingProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            seen["payload"] = copy.deepcopy(request.payload)
            seen["fingerprint"] = request.context_fingerprint
            return super().generate_reasoning(request)

    shifting: Mapping[str, Any] = _ShiftingMapping(ctx)
    result = _service_with(_RecordingProvider(response_text=expected_text)).build(
        context=shifting
    )

    # Every step observed the approved first-read snapshot.
    assert seen["payload"] == approved_payload
    assert seen["fingerprint"] == approved_fingerprint
    assert compute_fingerprint(seen["payload"]) == seen["fingerprint"]
    assert set(seen["payload"].keys()) == set(PAYLOAD_FIELDS)

    assert result["available"] is True
    assert result["proposal_consistent"] is True
    assert result["context_fingerprint"] == approved_fingerprint
    assert len(result["candidate_assessments"]) == expected_count


def test_snapshot_introduces_no_extra_fields() -> None:
    ctx = _valid_context()
    seen: dict[str, Any] = {}

    class _RecordingProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            seen["keys"] = set(request.payload.keys())
            return super().generate_reasoning(request)

    _service_with(_RecordingProvider(response_text=_valid_model_output(ctx))).build(
        context=dict(ctx)
    )

    assert seen["keys"] == set(PAYLOAD_FIELDS)
    assert len(seen["keys"]) == len(PAYLOAD_FIELDS)


def test_post_call_caller_mutation_cannot_rewrite_history() -> None:
    ctx = _valid_context()
    caller = dict(ctx)
    result = _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build(
        context=caller
    )

    fingerprint_before = result["context_fingerprint"]
    caller["candidate_state"] = []
    caller["observations"] = []
    assert compute_fingerprint(serialize_context(caller)) != fingerprint_before
    assert result["proposal_consistent"] is True

"""Task 204: native request/evidence binding contract.

Contract-only layer that associates one validated
``NativeReasoningRequest`` (Task 202) with the exact native evidence
records (Task 203) supplied for it. No reasoning, evaluation,
ranking, diagnosis, inference, training, network, persistence, or
model/provider involvement lives here.

Binding policy (fail-closed, nothing silently repaired or discarded):

- Every supplied record's ``session_id`` must equal the request's
  ``session_id``; every record's ``context_fingerprint`` must equal
  the request's ``context_fingerprint``. Mismatches are rejected,
  never corrected or overwritten.
- The set of supplied ``evidence_id`` values must equal the request's
  ``evidence_ids`` set exactly. A referenced-but-missing record is
  rejected (never invented); a supplied-but-unreferenced record is
  rejected (never silently discarded).
- Duplicate supplied ``evidence_id`` values are rejected.
- Supplied records must arrive sorted by ``str(evidence_id)``,
  consistent with the Task 202 convention of rejecting unsorted
  identifier order rather than silently reordering it.
- An explicitly empty request reference set bound to zero supplied
  records is valid; omission of either collection is rejected.
- Nested request/record validation is fully preserved: malformed
  identifiers, fingerprints, digests, or types fail through the
  approved Task 202/203 contracts.
- The binding makes no authenticity claim. Provenance fields remain
  syntactically validated only (Task 203), and unknown fields --
  including any caller-supplied bypass or trust flag -- are
  rejected.

The model is ``frozen`` with tuple nesting, so validated bindings
are deeply immutable. JSON arrays are accepted on input and still
serialize as arrays under ``mode="json"``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rop.schemas.native_evidence import NativeEvidenceRecord
from rop.schemas.native_reasoning import NativeReasoningRequest

NATIVE_BINDING_SOURCE_TASK_204 = "NATIVE_BINDING_TASK_204"

# Mirrors the Task 202 evidence-reference bound: exact set equality
# with the request's references means the binding can never need
# more records than the request may reference.
MAX_BINDING_RECORDS = 64


class NativeEvidenceBinding(BaseModel):
    """Strict immutable binding of a request to its evidence (Task 204)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: NativeReasoningRequest
    evidence: tuple[NativeEvidenceRecord, ...] = Field(max_length=MAX_BINDING_RECORDS)
    binding_source: Literal["NATIVE_BINDING_TASK_204"]

    @model_validator(mode="after")
    def _strict_binding(self) -> NativeEvidenceBinding:
        request = self.request
        records = self.evidence
        order = [str(record.evidence_id) for record in records]
        if len(set(order)) != len(order):
            raise ValueError("evidence identifiers must not contain duplicates")
        if order != sorted(order):
            raise ValueError("evidence must be unique and sorted")
        for record in records:
            if record.session_id != request.session_id:
                raise ValueError("evidence session binding is invalid")
            if record.context_fingerprint != request.context_fingerprint:
                raise ValueError("evidence context binding is invalid")
        referenced = {str(value) for value in request.evidence_ids}
        supplied = set(order)
        if supplied != referenced:
            if referenced - supplied:
                raise ValueError("referenced evidence is missing")
            raise ValueError("supplied evidence is unreferenced")
        return self


__all__ = [
    "MAX_BINDING_RECORDS",
    "NATIVE_BINDING_SOURCE_TASK_204",
    "NativeEvidenceBinding",
]

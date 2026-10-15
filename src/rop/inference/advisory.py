"""Task 213: strict model-output validation and advisory integration adapter.

Explicitly invoked, isolated boundary. It consumes an untrusted Task 212
``InferenceResult``, the validated deterministic request context, and an
explicitly configured class-label mapping, and either returns an
advisory-only ``AdvisoryAdapterResult`` or fails closed with a sanitized,
typed ``AdvisoryAdapterError``.

The deterministic ROP reasoning and evidence chain remains authoritative.
The model may suggest a candidate label; it cannot establish a fact,
manufacture evidence, settle a contradiction, determine an authoritative
status, supply identity or provenance, or change a deterministic finding.
No torch dependency lives here: the adapter works purely on validated
schema records, so its unit tests need no trained artifact.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from pydantic import ValidationError

from rop.schemas.advisory import (
    ADVISORY_CONTRACT_VERSION,
    MAX_APPROVED_LABELS,
    MAX_LABEL_LENGTH,
    AdvisoryAdapterResult,
    AdvisoryClassLabelMapping,
    AdvisoryErrorCode,
    AdvisoryModelSuggestion,
    AdvisoryRejectionReason,
)
from rop.schemas.inference import InferenceResult
from rop.schemas.native_reasoning import (
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
)

__all__ = [
    "AdvisoryAdapter",
    "AdvisoryAdapterError",
    "stable_softmax",
]

_NON_ADMISSIBLE_BY_STATUS: dict[NativeReasoningStatus, AdvisoryRejectionReason] = {
    "CONTRADICTED": AdvisoryRejectionReason.CONTEXT_CONTRADICTED,
    "INSUFFICIENT": AdvisoryRejectionReason.CONTEXT_INSUFFICIENT,
    "UNAVAILABLE": AdvisoryRejectionReason.CONTEXT_UNAVAILABLE,
    "ABSTAINED": AdvisoryRejectionReason.CONTEXT_ABSTAINED,
}
"""Every non-SUPPORTED deterministic status makes a suggestion non-admissible.

``SUPPORTED`` is the only status absent from this map. Anything the
map does not name fails closed to ``CONTEXT_UNKNOWN`` rather than
being admitted.
"""


class AdvisoryAdapterError(Exception):
    """A typed adapter failure with a static, sanitized message."""

    def __init__(self, code: AdvisoryErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def stable_softmax(logits: Sequence[float]) -> tuple[float, ...]:
    """Numerically stable softmax over one logits row.

    Max-subtraction keeps ``math.exp`` finite for arbitrarily large
    magnitudes. The result is a bounded score derived from raw logits;
    it is not a calibrated probability and must not be labelled as a
    confidence or a correctness likelihood.
    """
    if isinstance(logits, (str, bytes)) or not isinstance(logits, Sequence):
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.INVALID_REQUEST, "advisory logits are invalid"
        )
    if not logits:
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.INVALID_REQUEST, "advisory logits are empty"
        )
    normalized_logits: list[float] = []
    for value in logits:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST, "advisory logits are invalid"
            )
        try:
            numeric_value = float(value)
        except OverflowError:
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST, "advisory logits are invalid"
            ) from None
        if not math.isfinite(numeric_value):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST, "advisory logits are invalid"
            )
        normalized_logits.append(numeric_value)

    peak = max(normalized_logits)
    exps = [math.exp(value - peak) for value in normalized_logits]
    total = math.fsum(exps)
    if total <= 0.0 or not math.isfinite(total):
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.CONTRACT_VIOLATION,
            "advisory score computation failed",
        )
    return tuple(value / total for value in exps)


def _checked_inference_result(value: object) -> InferenceResult:
    if not isinstance(value, InferenceResult):
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.INVALID_INPUT, "advisory inference result is invalid"
        )
    try:
        return InferenceResult.model_validate(value.model_dump())
    except ValidationError:
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.CONTRACT_VIOLATION,
            "advisory inference result is invalid",
        ) from None


def _checked_request(value: object) -> NativeReasoningRequest:
    if not isinstance(value, NativeReasoningRequest):
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.INVALID_INPUT, "advisory request context is invalid"
        )
    try:
        return NativeReasoningRequest.model_validate(value.model_dump())
    except ValidationError:
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.CONTRACT_VIOLATION,
            "advisory request context is invalid",
        ) from None


def _checked_deterministic(value: object) -> NativeReasoningResult:
    if not isinstance(value, NativeReasoningResult):
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.INVALID_INPUT,
            "advisory deterministic context is invalid",
        )
    try:
        return NativeReasoningResult.model_validate(value.model_dump())
    except ValidationError:
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.CONTRACT_VIOLATION,
            "advisory deterministic context is invalid",
        ) from None


class AdvisoryAdapter:
    """Validate untrusted logits and publish advisory-only suggestions.

    Immutable, dependency-free, and explicitly constructed. All accepted
    labels come from the caller-supplied, schema-validated class-label
    mapping; every label must belong to the approved label space given
    at construction. A class index the mapping does not declare never
    produces a label: unmapped output fails closed instead of being
    repaired, clamped, or reinterpreted.

    Configuration immutability is structural, not nominal: the
    index-to-label lookup is an immutable mapping view and instance
    attribute reassignment or deletion is rejected after construction,
    so straightforward post-construction mutation cannot bypass the
    validated mapping. This guards against accidental or casual
    mutation; it is not a claim of protection against hostile
    in-process reflection, which ordinary Python objects cannot
    provide.
    """

    def __init__(
        self,
        *,
        class_label_mapping: AdvisoryClassLabelMapping,
        approved_labels: Sequence[str],
    ) -> None:
        if not isinstance(class_label_mapping, AdvisoryClassLabelMapping):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_INPUT,
                "advisory class-label mapping is invalid",
            )
        try:
            mapping = AdvisoryClassLabelMapping.model_validate(
                class_label_mapping.model_dump()
            )
        except ValidationError:
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.CONTRACT_VIOLATION,
                "advisory class-label mapping is invalid",
            ) from None
        if isinstance(approved_labels, (str, bytes)) or not isinstance(
            approved_labels, Sequence
        ):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "advisory approved label space is invalid",
            )
        labels = tuple(approved_labels)
        if (
            not labels
            or len(labels) > MAX_APPROVED_LABELS
            or any(
                not isinstance(label, str)
                or not label.strip()
                or len(label) > MAX_LABEL_LENGTH
                or label != label.strip()
                or not label.isprintable()
                for label in labels
            )
            or len(set(labels)) != len(labels)
        ):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "advisory approved label space is invalid",
            )
        unapproved = {entry.label for entry in mapping.entries} - set(labels)
        if unapproved:
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "class-label mapping cites labels outside the approved space",
            )
        object.__setattr__(self, "_mapping", mapping)
        object.__setattr__(
            self,
            "_label_by_index",
            MappingProxyType(
                {entry.class_index: entry.label for entry in mapping.entries}
            ),
        )
        object.__setattr__(self, "_num_classes", mapping.num_classes)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "advisory adapter configuration is immutable",
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AdvisoryAdapterError(
            AdvisoryErrorCode.INVALID_REQUEST,
            "advisory adapter configuration is immutable",
        )

    @property
    def mapping(self) -> AdvisoryClassLabelMapping:
        """The validated class-label mapping (read-only)."""
        return self._mapping

    @property
    def label_by_index(self) -> Mapping[int, str]:
        """Immutable index-to-label lookup view (read-only)."""
        return self._label_by_index

    @property
    def num_classes(self) -> int:
        """The configured model class count (read-only)."""
        return self._num_classes

    def propose(
        self,
        *,
        inference_result: InferenceResult,
        request: NativeReasoningRequest,
        deterministic_result: NativeReasoningResult | None = None,
    ) -> AdvisoryAdapterResult:
        """Validate one inference row and return an advisory-only result.

        ``request`` is the validated deterministic context identity; the
        published result binds to it exactly. ``deterministic_result``,
        when supplied, gates admissibility: a contradicted, insufficient,
        unavailable, abstained, or unknown deterministic context makes
        the suggestion non-admissible regardless of model output, and a
        detached deterministic result (different identity, or evidence
        references outside the request's ``evidence_ids`` set) is
        rejected. The adapter never mutates any of its inputs.
        """
        result = _checked_inference_result(inference_result)
        checked_request = _checked_request(request)
        if result.batch_size != 1:
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "the advisory adapter accepts exactly one inference row",
            )
        if result.num_classes != self._num_classes:
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "inference class count does not match the configured mapping",
            )

        rejection: AdvisoryRejectionReason | None = None
        if deterministic_result is None:
            rejection = AdvisoryRejectionReason.CONTEXT_UNAVAILABLE
        else:
            checked_deterministic = _checked_deterministic(deterministic_result)
            self._assert_same_context(checked_request, checked_deterministic)
            if checked_deterministic.status != "SUPPORTED":
                rejection = _NON_ADMISSIBLE_BY_STATUS.get(
                    checked_deterministic.status,
                    AdvisoryRejectionReason.CONTEXT_UNKNOWN,
                )

        row = result.logits[0]
        probabilities = stable_softmax(row)
        winning_index = max(range(len(row)), key=lambda index: (row[index], -index))
        label = self._label_by_index.get(winning_index)
        if label is None and rejection is None:
            rejection = AdvisoryRejectionReason.UNMAPPED_WINNING_CLASS

        if rejection is not None:
            return self._result(
                checked_request,
                artifact_id=result.artifact_id,
                admissible=False,
                suggestion=None,
                rejection_reason=rejection,
            )

        suggestion = AdvisoryModelSuggestion(
            candidate_label=label,
            softmax_score=probabilities[winning_index],
            advisory_only=True,
        )
        return self._result(
            checked_request,
            artifact_id=result.artifact_id,
            admissible=True,
            suggestion=suggestion,
            rejection_reason=None,
        )

    @staticmethod
    def _assert_same_context(
        request: NativeReasoningRequest, deterministic: NativeReasoningResult
    ) -> None:
        if (
            deterministic.request_id != request.request_id
            or deterministic.session_id != request.session_id
            or deterministic.context_fingerprint != request.context_fingerprint
        ):
            raise AdvisoryAdapterError(
                AdvisoryErrorCode.INVALID_REQUEST,
                "deterministic context is detached from the request identity",
            )
        # Evidence binding (Task 202 + Task 204): the request's
        # ``evidence_ids`` is the authoritative allowed reference set for
        # this boundary — Task 204's ``NativeEvidenceBinding`` enforces
        # exact set equality between those references and the supplied
        # Task 203 records, and Task 205's composition builds result
        # evidence references from the bound records. A caller-supplied
        # result object passes Pydantic validation without that pipeline,
        # so the adapter requires every supporting and contradicting
        # evidence ID to be a subset of the trusted request set. Statuses
        # that carry no evidence satisfy this vacuously. The rejected
        # payload is never disclosed.
        allowed = {str(value) for value in request.evidence_ids}
        for evidence_id in (
            *deterministic.supporting_evidence_ids,
            *deterministic.contradicting_evidence_ids,
        ):
            if str(evidence_id) not in allowed:
                raise AdvisoryAdapterError(
                    AdvisoryErrorCode.INVALID_REQUEST,
                    "deterministic evidence is not bound to the request",
                )

    @staticmethod
    def _result(
        request: NativeReasoningRequest,
        *,
        artifact_id: str,
        admissible: bool,
        suggestion: AdvisoryModelSuggestion | None,
        rejection_reason: AdvisoryRejectionReason | None,
    ) -> AdvisoryAdapterResult:
        return AdvisoryAdapterResult(
            contract_version=ADVISORY_CONTRACT_VERSION,
            artifact_id=artifact_id,
            request_id=request.request_id,
            session_id=request.session_id,
            context_fingerprint=request.context_fingerprint,
            admissible=admissible,
            suggestion=suggestion,
            rejection_reason=rejection_reason,
        )

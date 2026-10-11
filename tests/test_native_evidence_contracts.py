"""Task 203 structured evidence/provenance contract tests; no I/O or model runtime."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from rop.schemas.native_evidence import (
    NativeEvidenceAvailability,
    NativeEvidenceBundle,
    NativeEvidenceKind,
    NativeEvidenceProvenance,
    NativeEvidenceRecord,
    NativeEvidenceStance,
    NativeEvidenceUncertainty,
    NativeProvenanceKind,
    validate_native_evidence_binding,
)
from rop.schemas.native_reasoning import NativeReasoningRequest, NativeReasoningTask

FINGERPRINT = "a" * 64


def _provenance(**patch: object) -> dict:
    value = {
        "source_id": UUID(int=900),
        "source_kind": NativeProvenanceKind.DOCUMENT,
        "source_reference": "source:document-900",
        "source_fingerprint": "b" * 64,
        "availability": NativeEvidenceAvailability.AVAILABLE,
    }
    value.update(patch)
    return value


def _record(
    evidence_id: UUID,
    *,
    session_id: UUID | None = None,
    context_fingerprint: str = FINGERPRINT,
    kind: NativeEvidenceKind = NativeEvidenceKind.OBSERVATION,
    derived_from_ids: tuple[UUID, ...] = (),
    provenance: dict | None = None,
    **patch: object,
) -> NativeEvidenceRecord:
    value = {
        "contract_version": "1",
        "evidence_id": evidence_id,
        "session_id": session_id or UUID(int=100),
        "context_fingerprint": context_fingerprint,
        "assertion": "A bounded, source-linked observation.",
        "kind": kind,
        "stance": NativeEvidenceStance.SUPPORTS,
        "provenance": provenance or _provenance(),
        "derived_from_ids": derived_from_ids,
        "uncertainty": NativeEvidenceUncertainty.LOW,
    }
    value.update(patch)
    return NativeEvidenceRecord.model_validate(value)


def _bundle(
    records: tuple[NativeEvidenceRecord, ...], **patch: object
) -> NativeEvidenceBundle:
    value = {
        "contract_version": "1",
        "session_id": UUID(int=100),
        "context_fingerprint": FINGERPRINT,
        "records": records,
    }
    value.update(patch)
    return NativeEvidenceBundle.model_validate(value)


def _request(*evidence_ids: UUID, **patch: object) -> NativeReasoningRequest:
    value = {
        "contract_version": "1",
        "request_id": UUID(int=700),
        "session_id": UUID(int=100),
        "context_fingerprint": FINGERPRINT,
        "task": NativeReasoningTask.EVALUATE_EVIDENCE,
        "evidence_ids": list(evidence_ids),
    }
    value.update(patch)
    return NativeReasoningRequest.model_validate(value)


def test_valid_record_and_bundle_preserve_canonical_identifiers() -> None:
    first = _record(UUID(int=1))
    second = _record(UUID(int=2))
    bundle = _bundle((first, second))
    assert [item.evidence_id for item in bundle.records] == [UUID(int=1), UUID(int=2)]


def test_records_and_provenance_are_immutable() -> None:
    record = _record(UUID(int=1))
    with pytest.raises(ValidationError):
        record.assertion = "changed"
    with pytest.raises(ValidationError):
        record.provenance.source_reference = "changed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context_fingerprint", "A" * 64),
        ("context_fingerprint", "short"),
        ("assertion", "  "),
        ("contract_version", "2"),
    ],
)
def test_record_rejects_invalid_contract_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _record(UUID(int=1), **{field: value})


def test_provenance_requires_nonblank_reference_and_canonical_hash() -> None:
    with pytest.raises(ValidationError):
        NativeEvidenceProvenance.model_validate(_provenance(source_reference=" "))
    with pytest.raises(ValidationError):
        NativeEvidenceProvenance.model_validate(
            _provenance(source_fingerprint="not-a-hash")
        )


@pytest.mark.parametrize(
    "reference",
    [
        r"C:\\Users\\private\\source.json",
        "/home/private/source.json",
        r"\\\\server\\share\\source.json",
        "file:///private/source.json",
        "https://user:password@example.test/source",
        "https://user@example.test/source",
        "source:private\nsource",
        # parent-directory traversal, both separators
        "../private/source.json",
        "../../secrets.txt",
        r"..\private\source.json",
        r"..\..\secrets.txt",
        "source/../../secrets.txt",
        "..",
        # current-directory segments, both separators
        "./private/source.json",
        r".\private\source.json",
        "./source.json",
        # relative directory paths, both separators
        "private/source.json",
        r"private\source.json",
        "private/sub/source.json",
        r"private\sub\source.json",
        # drive-relative and drive-absolute Windows forms
        "C:private",
        "C:/private/source.json",
        r"C:\private\source.json",
        # bare, ambiguous names and other unsupported shapes
        "secrets.txt",
        "document-900",
        "~/private/source.json",
        "ftp://example.test/source",
        "https:/example.test/source",
        "https://",
        r"https://example.test\private",
        "source: document-900",
        "source:.hidden",
        "file:private/source.json",
    ],
)
def test_provenance_rejects_paths_credentials_and_control_characters(
    reference: str,
) -> None:
    with pytest.raises(ValidationError):
        NativeEvidenceProvenance.model_validate(_provenance(source_reference=reference))


def test_bundle_rejects_duplicate_or_noncanonical_evidence_ids() -> None:
    record = _record(UUID(int=1))
    with pytest.raises(ValidationError):
        _bundle((record, record))
    with pytest.raises(ValidationError):
        _bundle((_record(UUID(int=2)), _record(UUID(int=1))))


def test_bundle_rejects_session_or_fingerprint_mismatch() -> None:
    with pytest.raises(ValidationError):
        _bundle((_record(UUID(int=1), session_id=UUID(int=101)),))
    with pytest.raises(ValidationError):
        _bundle((_record(UUID(int=1), context_fingerprint="c" * 64),))


def test_derived_evidence_requires_parent_and_derived_provenance() -> None:
    with pytest.raises(ValidationError):
        _record(UUID(int=2), kind=NativeEvidenceKind.DERIVED_INTERPRETATION)
    with pytest.raises(ValidationError):
        _record(
            UUID(int=2),
            kind=NativeEvidenceKind.DERIVED_INTERPRETATION,
            derived_from_ids=(UUID(int=1),),
        )
    derived = _record(
        UUID(int=2),
        kind=NativeEvidenceKind.DERIVED_INTERPRETATION,
        derived_from_ids=(UUID(int=1),),
        provenance=_provenance(source_kind=NativeProvenanceKind.DERIVED_RECORD),
    )
    assert derived.kind == NativeEvidenceKind.DERIVED_INTERPRETATION


def test_bundle_rejects_missing_self_and_cyclic_parent_references() -> None:
    missing_parent = _record(
        UUID(int=2),
        kind=NativeEvidenceKind.DERIVED_INTERPRETATION,
        derived_from_ids=(UUID(int=1),),
        provenance=_provenance(source_kind=NativeProvenanceKind.DERIVED_RECORD),
    )
    with pytest.raises(ValidationError, match="missing parent"):
        _bundle((missing_parent,))

    with pytest.raises(ValidationError, match="cannot derive from itself"):
        _bundle(
            (
                _record(
                    UUID(int=1),
                    kind=NativeEvidenceKind.DERIVED_INTERPRETATION,
                    derived_from_ids=(UUID(int=1),),
                    provenance=_provenance(
                        source_kind=NativeProvenanceKind.DERIVED_RECORD
                    ),
                ),
            )
        )

    first = _record(
        UUID(int=1),
        kind=NativeEvidenceKind.DERIVED_INTERPRETATION,
        derived_from_ids=(UUID(int=2),),
        provenance=_provenance(source_kind=NativeProvenanceKind.DERIVED_RECORD),
    )
    second = _record(
        UUID(int=2),
        kind=NativeEvidenceKind.DERIVED_INTERPRETATION,
        derived_from_ids=(UUID(int=1),),
        provenance=_provenance(source_kind=NativeProvenanceKind.DERIVED_RECORD),
    )
    with pytest.raises(ValidationError, match="acyclic"):
        _bundle((first, second))


def test_request_binding_rejects_wrong_session_fingerprint_or_missing_ids() -> None:
    bundle = _bundle((_record(UUID(int=1)),))
    validate_native_evidence_binding(_request(UUID(int=1)), bundle)

    with pytest.raises(ValueError, match="session_id"):
        validate_native_evidence_binding(
            _request(UUID(int=1), session_id=UUID(int=101)), bundle
        )
    with pytest.raises(ValueError, match="context_fingerprint"):
        validate_native_evidence_binding(
            _request(UUID(int=1), context_fingerprint="c" * 64), bundle
        )
    with pytest.raises(ValueError, match="absent"):
        validate_native_evidence_binding(_request(UUID(int=2)), bundle)


def test_bundle_rejects_extra_fields_and_oversized_record_lists() -> None:
    record = _record(UUID(int=1))
    with pytest.raises(ValidationError):
        _bundle((record,), provider="external")
    records = tuple(_record(UUID(int=i)) for i in range(1, 258))
    with pytest.raises(ValidationError):
        _bundle(records)


@pytest.mark.parametrize(
    "reference",
    [
        "source:document-900",
        "doc:abc_123.v2",
        "urn:uuid:6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "db:records~42",
        "https://example.test/source",
        "http://example.test/path/to/source?id=1#part",
        "HTTPS://Example.test:8443/source",
        "https://example.test/a/../b",
    ],
)
def test_provenance_accepts_opaque_identifiers_and_safe_urls(reference: str) -> None:
    provenance = NativeEvidenceProvenance.model_validate(
        _provenance(source_reference=reference)
    )
    assert provenance.source_reference == reference

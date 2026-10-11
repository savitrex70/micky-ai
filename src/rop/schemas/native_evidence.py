"""Task 203 structured evidence and provenance contracts; no runtime or I/O."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

from rop.schemas.native_reasoning import NativeReasoningRequest

EVIDENCE_CONTRACT_VERSION = "1"
MAX_STRUCTURED_EVIDENCE_RECORDS = 256
MAX_DERIVATION_PARENTS = 64


# HTTP(S) URL shape: authority without userinfo, backslashes or whitespace, then an
# optional path/query/fragment. The authority is validated separately below.
_HTTP_URL = re.compile(
    r"https?://(?P<authority>[^/?#\\@\s]+)(?:[/?#][^\\\s]*)?", re.IGNORECASE
)
_BRACKETED_HOST = re.compile(r"\[(?P<ip>[0-9A-Fa-f:.]+)\](?::(?P<port>[^:]*))?")
_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_DNS_NAME = re.compile(rf"{_DNS_LABEL}(?:\.{_DNS_LABEL})*")
_MAX_HOST_LENGTH = 253


def _valid_port(port: str) -> bool:
    return port.isascii() and port.isdigit() and 1 <= int(port) <= 65535


def _valid_authority(authority: str) -> bool:
    """Syntactic host[:port] check; bracketed IPv6, IPv4 and DNS names only."""
    bracketed = _BRACKETED_HOST.fullmatch(authority)
    if bracketed:
        try:
            ipaddress.IPv6Address(bracketed["ip"])
        except ValueError:
            return False
        port = bracketed["port"]
        return port is None or _valid_port(port)
    if authority.startswith("[") or "[" in authority or "]" in authority:
        return False
    host, separator, port = authority.partition(":")
    if separator and not _valid_port(port):
        return False
    if len(host) > _MAX_HOST_LENGTH or not _DNS_NAME.fullmatch(host):
        return False
    if re.fullmatch(r"[0-9.]+", host):
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            return False
    return True


def _is_safe_http_url(value: str) -> bool:
    match = _HTTP_URL.fullmatch(value)
    return match is not None and _valid_authority(match["authority"])


# Opaque `scheme:identifier`: scheme of 2+ characters (so `C:` drive prefixes never
# match) and an identifier with no path separators, whitespace or leading dot.
_OPAQUE_IDENTIFIER = re.compile(
    r"(?!(?:https?|file):)[A-Za-z][A-Za-z0-9+.-]+:[A-Za-z0-9][A-Za-z0-9._~:+=%@-]*"
)


class NativeEvidenceKind(StrEnum):
    OBSERVATION = "OBSERVATION"
    SOURCE_RECORD = "SOURCE_RECORD"
    DERIVED_INTERPRETATION = "DERIVED_INTERPRETATION"


class NativeEvidenceStance(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class NativeProvenanceKind(StrEnum):
    USER_PROVIDED = "USER_PROVIDED"
    DOCUMENT = "DOCUMENT"
    DATABASE_RECORD = "DATABASE_RECORD"
    INSTRUMENT = "INSTRUMENT"
    DERIVED_RECORD = "DERIVED_RECORD"


class NativeEvidenceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"


class NativeEvidenceUncertainty(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNASSESSED = "UNASSESSED"


class NativeEvidenceProvenance(BaseModel):
    """Minimal source lineage; references do not imply source authenticity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    source_kind: NativeProvenanceKind
    source_reference: StrictStr = Field(min_length=1, max_length=500)
    source_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    availability: NativeEvidenceAvailability

    @field_validator("source_reference")
    @classmethod
    def _nonblank_source_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_reference must not be blank")
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("source_reference must not contain control characters")
        if (
            value.startswith(("/", "\\\\"))
            or re.match(r"^[A-Za-z]:[\\/]", value)
            or value.lower().startswith("file:")
        ):
            raise ValueError("source_reference must not expose a filesystem path")
        if re.search(r"://[^/@:]+:[^/@]+@", value):
            raise ValueError("source_reference must not contain URL credentials")
        # Policy: a reference is either a safe external HTTP(S) URL or an opaque
        # `scheme:identifier` token. Anything else, including relative paths in
        # POSIX or Windows form, is rejected rather than rewritten. Both slash
        # conventions are inspected explicitly so results do not depend on the
        # host operating system.
        if _is_safe_http_url(value) or _OPAQUE_IDENTIFIER.fullmatch(value):
            return value
        raise ValueError(
            "source_reference must be an opaque identifier or a safe HTTP(S) URL"
        )


class NativeEvidenceRecord(BaseModel):
    """Immutable evidence item bound to one session and context fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    evidence_id: UUID
    session_id: UUID
    context_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    assertion: StrictStr = Field(min_length=1, max_length=2000)
    kind: NativeEvidenceKind
    stance: NativeEvidenceStance
    provenance: NativeEvidenceProvenance
    derived_from_ids: tuple[UUID, ...] = Field(max_length=MAX_DERIVATION_PARENTS)
    uncertainty: NativeEvidenceUncertainty

    @field_validator("assertion")
    @classmethod
    def _nonblank_assertion(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assertion must not be blank")
        return value

    @field_validator("derived_from_ids")
    @classmethod
    def _canonical_parent_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("derived_from_ids must not contain duplicates")
        if value != tuple(sorted(value, key=str)):
            raise ValueError("derived_from_ids must be sorted by canonical UUID")
        return value

    @model_validator(mode="after")
    def _kind_matches_lineage(self) -> NativeEvidenceRecord:
        if self.kind == NativeEvidenceKind.DERIVED_INTERPRETATION:
            if not self.derived_from_ids:
                raise ValueError("derived interpretations require source evidence")
            if self.provenance.source_kind != NativeProvenanceKind.DERIVED_RECORD:
                raise ValueError(
                    "derived interpretations require DERIVED_RECORD provenance"
                )
        elif self.derived_from_ids:
            raise ValueError("only derived interpretations may declare parent evidence")
        elif self.provenance.source_kind == NativeProvenanceKind.DERIVED_RECORD:
            raise ValueError(
                "DERIVED_RECORD provenance requires a derived interpretation"
            )
        return self


class NativeEvidenceBundle(BaseModel):
    """Canonical, internally bound set of evidence records for one context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    session_id: UUID
    context_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    records: tuple[NativeEvidenceRecord, ...] = Field(
        max_length=MAX_STRUCTURED_EVIDENCE_RECORDS
    )

    @field_validator("records")
    @classmethod
    def _canonical_records(
        cls, value: tuple[NativeEvidenceRecord, ...]
    ) -> tuple[NativeEvidenceRecord, ...]:
        ids = [record.evidence_id for record in value]
        if len(set(ids)) != len(ids):
            raise ValueError("evidence record identifiers must be unique")
        if ids != sorted(ids, key=str):
            raise ValueError("evidence records must be sorted by canonical UUID")
        return value

    @model_validator(mode="after")
    def _validate_binding_and_references(self) -> NativeEvidenceBundle:
        records_by_id = {record.evidence_id: record for record in self.records}
        for record in self.records:
            if record.session_id != self.session_id:
                raise ValueError("evidence session_id does not match bundle")
            if record.context_fingerprint != self.context_fingerprint:
                raise ValueError("evidence context_fingerprint does not match bundle")
            if record.evidence_id in record.derived_from_ids:
                raise ValueError("evidence cannot derive from itself")
            for parent_id in record.derived_from_ids:
                parent = records_by_id.get(parent_id)
                if parent is None:
                    raise ValueError("derived evidence references a missing parent")
                if parent.session_id != record.session_id:
                    raise ValueError("derived evidence parent has a different session")
                if parent.context_fingerprint != record.context_fingerprint:
                    raise ValueError("derived evidence parent has a different context")

        self._reject_derivation_cycles(records_by_id)
        return self

    @staticmethod
    def _reject_derivation_cycles(
        records_by_id: dict[UUID, NativeEvidenceRecord],
    ) -> None:
        visited: set[UUID] = set()
        active: set[UUID] = set()

        def visit(evidence_id: UUID) -> None:
            if evidence_id in active:
                raise ValueError("evidence derivation graph must be acyclic")
            if evidence_id in visited:
                return
            active.add(evidence_id)
            for parent_id in records_by_id[evidence_id].derived_from_ids:
                visit(parent_id)
            active.remove(evidence_id)
            visited.add(evidence_id)

        for evidence_id in records_by_id:
            visit(evidence_id)


def validate_native_evidence_binding(
    request: NativeReasoningRequest, bundle: NativeEvidenceBundle
) -> None:
    """Fail closed unless request identity and requested evidence references bind."""

    if request.session_id != bundle.session_id:
        raise ValueError("request session_id does not match evidence bundle")
    if request.context_fingerprint != bundle.context_fingerprint:
        raise ValueError("request context_fingerprint does not match evidence bundle")

    available_ids = {record.evidence_id for record in bundle.records}
    missing_ids = set(request.evidence_ids) - available_ids
    if missing_ids:
        raise ValueError("request references evidence absent from the supplied bundle")

"""Task 207: strict source-authorization contracts for dataset governance.

Data-only contracts describing who authorized a dataset source,
for what purpose and operation, under which constraints, and for
how long. Validation here is structural: field presence, formats,
and internal consistency. Trust is established only by the
pipeline receiving the entry through an explicitly injected
registry -- never by a caller-supplied approval flag, of which
this module defines none.
"""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DATASET_AUTHORIZATION_VERSION = "1.0"

TEST_SOURCE_PREFIX = "synthetic-test-"
"""Source-id namespace reserved for unmistakable synthetic test data."""

_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SAFE_NOTE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,;:_()/-]{0,199}")

AuthorizationStatus = Literal["APPROVED", "SUSPENDED", "REVOKED", "EXPIRED", "PENDING"]
PermittedOperation = Literal["training", "validation", "evaluation"]


class DataSourceAuthorization(BaseModel):
    """One auditable source-authorization record (Task 207).

    ``restrictions`` and ``retention_notes`` are audit metadata
    only: the offline pipeline cannot verify compliance with
    unevaluated conditions, so a non-empty ``restrictions`` entry
    is unusable for automated preparation and fails closed there.
    ``valid_until`` is inclusive: the entry authorizes operations
    on dates up to and including that day, compared against an
    explicitly supplied reference date (the pipeline never reads
    a clock).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=64)
    authorization_version: Literal["1.0"]
    origin_description: str = Field(min_length=1, max_length=500)
    license_basis: str = Field(min_length=1, max_length=120)
    intended_purpose: str = Field(min_length=1, max_length=64)
    permitted_operations: tuple[PermittedOperation, ...] = Field(min_length=1)
    retention_notes: str | None = Field(default=None, max_length=200)
    restrictions: tuple[str, ...] = ()
    status: AuthorizationStatus
    approval_reference: str = Field(min_length=1, max_length=64)
    valid_until: str | None = None

    @model_validator(mode="after")
    def _strict_authorization(self) -> DataSourceAuthorization:
        if not _ID_RE.fullmatch(self.source_id):
            raise ValueError("source_id is invalid")
        if not _ID_RE.fullmatch(self.intended_purpose):
            raise ValueError("intended_purpose is invalid")
        if not _ID_RE.fullmatch(self.approval_reference):
            raise ValueError("approval_reference is invalid")
        for text, name in (
            (self.origin_description, "origin_description"),
            (self.license_basis, "license_basis"),
        ):
            if not _SAFE_NOTE_RE.fullmatch(text):
                raise ValueError(f"{name} is invalid")
        if self.retention_notes is not None and not _SAFE_NOTE_RE.fullmatch(
            self.retention_notes
        ):
            raise ValueError("retention_notes is invalid")
        for restriction in self.restrictions:
            if not _SAFE_NOTE_RE.fullmatch(restriction):
                raise ValueError("restrictions entry is invalid")
        if len(set(self.restrictions)) != len(self.restrictions):
            raise ValueError("restrictions must not contain duplicates")
        operations = list(self.permitted_operations)
        if len(set(operations)) != len(operations):
            raise ValueError("permitted_operations must not contain duplicates")
        if operations != sorted(operations):
            raise ValueError("permitted_operations must be sorted")
        if self.valid_until is not None:
            if not _DATE_RE.fullmatch(self.valid_until):
                raise ValueError("valid_until is invalid")
            try:
                datetime.date.fromisoformat(self.valid_until)
            except ValueError:
                raise ValueError("valid_until is invalid") from None
        return self


__all__ = [
    "DATASET_AUTHORIZATION_VERSION",
    "TEST_SOURCE_PREFIX",
    "AuthorizationStatus",
    "DataSourceAuthorization",
    "PermittedOperation",
]

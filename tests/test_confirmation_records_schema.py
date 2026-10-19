"""Task 227: contract-level tests for the export-completeness documentation.

These tests protect the *semantic* contract exposed by the export schema: an
export represents one consistent database snapshot, so a concurrent write that
commits after the snapshot was established does not make that snapshot
incomplete. They assert against stable contract surfaces (the Pydantic model
description exposed through the OpenAPI schema, and the model's own `notes`
default) rather than against incidental prose punctuation, so wording may be
refined without breaking the guarantee this protects.

They do not need a database: building ``app.openapi()`` introspects route and
model definitions only, and the model itself is imported directly.
"""

from __future__ import annotations

from rop.main import app
from rop.schemas.assistant_confirmation import (
    AssistantConfirmationExportBundle,
)


def _openapi_schema_for_bundle() -> dict:
    spec = app.openapi()
    # The route uses response_model=AssistantConfirmationExportBundle, so the
    # schema name is the class name.
    schemas = spec["components"]["schemas"]
    assert "AssistantConfirmationExportBundle" in schemas, (
        "AssistantConfirmationExportBundle missing from OpenAPI components"
    )
    return schemas["AssistantConfirmationExportBundle"]


def test_bundle_openapi_description_describes_a_snapshot() -> None:
    """The contract must say the export is one consistent snapshot.

    The concrete guarantee being protected: post-snapshot writes are
    invisible to the export and do not make it incomplete. That is the
    semantic point that a caller needs, and it is what makes
    ``is_complete=True`` meaningful on a bundle produced under concurrent
    write activity.
    """
    schema = _openapi_schema_for_bundle()
    description = schema.get("description", "")
    assert description, "bundle schema must have a description"

    lowered = description.lower()
    # The semantic point, worded loosely to survive copy-edits.
    assert "snapshot" in lowered, (
        "description must state the export represents a snapshot; got: "
        + description
    )
    # The old, contradictory claim ("concurrent insert or delete during
    # export makes that equality fail, and the endpoint reports
    # is_complete=False") must be gone.
    assert "concurrent insert or delete" not in lowered, (
        "description still says a concurrent write makes the export "
        "incomplete; that contradicts the REPEATABLE READ implementation"
    )


def test_bundle_openapi_documents_is_complete_as_snapshot_completeness() -> None:
    """The `is_complete` property description must refer to the snapshot."""
    schema = _openapi_schema_for_bundle()
    props = schema.get("properties", {})
    assert "is_complete" in props, "is_complete missing from bundle schema"
    prop = props["is_complete"]
    description = (prop.get("description", "") or "").lower()
    assert description, "is_complete must have a description"
    assert "snapshot" in description or "collected" in description, (
        "is_complete description must speak in terms of the exported "
        "snapshot; got: " + repr(prop.get("description", ""))
    )


def test_bundle_openapi_documents_total_as_snapshot_count() -> None:
    """`total_record_count` refers to the snapshot, not a live counter."""
    schema = _openapi_schema_for_bundle()
    props = schema.get("properties", {})
    assert "total_record_count" in props
    description = (props["total_record_count"].get("description", "") or "").lower()
    # We only require that the description does not claim the live database
    # count "at export start"; the snapshot count is the correct meaning.
    assert "at export start" not in description, (
        "total_record_count must not be documented as the live count at "
        "export start; it is the count in the exported snapshot"
    )


def test_bundle_notes_default_mentions_snapshot_and_invisibility() -> None:
    """The default `notes` field must describe the snapshot semantics.

    `notes` is part of the model's default payload; it is what a bundle
    consumer reads if they only skim the JSON. It must therefore carry the
    same semantic contract as the docstring.
    """
    joined = " ".join(AssistantConfirmationExportBundle.model_fields["notes"].default)
    lowered = joined.lower()
    assert "snapshot" in lowered, (
        "notes must state the export is a snapshot; got: " + joined
    )
    assert "incomplete" in lowered and (
        "invisible" in lowered or "do not" in lowered or "not make" in lowered
    ), (
        "notes must state that post-snapshot writes do not make the export "
        "incomplete; got: " + joined
    )

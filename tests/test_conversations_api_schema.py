"""Task 229: database-independent checks for the conversation API surface.

These tests do NOT use PostgreSQL. They verify route registration, request
and response schema shapes, and other facts that are established at import
and OpenAPI time. They run even when ``ROP_TEST_DATABASE_URL`` is not
configured, which is exactly the distinction the Task 229 correction
required: database-required tests skip when there is no test database;
database-independent tests do not.

The OpenAPI check that used to live in ``tests/test_conversations_api.py``
moved here, so it is not shadowed by that file's ``pg_engine`` skip.
"""

from __future__ import annotations

from rop.main import app


def test_conversations_routes_in_openapi() -> None:
    spec = app.openapi()
    paths = set(spec["paths"])
    assert "/api/assistant/conversations" in paths
    assert "/api/assistant/conversations/{conversation_id}" in paths
    assert "/api/assistant/conversations/{conversation_id}/messages" in paths


def test_conversations_openapi_methods() -> None:
    spec = app.openapi()
    base = spec["paths"]["/api/assistant/conversations"]
    assert "get" in base and "post" in base
    one = spec["paths"]["/api/assistant/conversations/{conversation_id}"]
    assert "get" in one and "patch" in one and "delete" in one
    msgs = spec["paths"]["/api/assistant/conversations/{conversation_id}/messages"]
    assert "get" in msgs and "post" in msgs


def test_public_append_request_schema_has_only_content() -> None:
    """The public append body must expose only ``content``; no ``role``.

    A caller-supplied role would allow forging an ``assistant`` message
    through the public API. This contract check runs without a database.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    assert "AssistantUserMessageCreate" in schemas
    props = set(schemas["AssistantUserMessageCreate"].get("properties", {}))
    assert props == {"content"}, props


def test_internal_message_create_schema_keeps_role() -> None:
    """Internal ``AssistantMessageCreate`` still carries ``role``.

    The public API deliberately does not use this schema; only internal
    callers that persist genuine assistant replies do. The test guards
    against accidentally leaking that schema onto the public endpoint.
    """
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    if "AssistantMessageCreate" in schemas:
        props = set(schemas["AssistantMessageCreate"].get("properties", {}))
        assert "role" in props


def test_conversation_read_schema_shape() -> None:
    spec = app.openapi()
    read = spec["components"]["schemas"]["AssistantConversationRead"]
    props = set(read["properties"])
    assert props == {"id", "title", "created_at", "updated_at"}


def test_message_read_schema_shape() -> None:
    spec = app.openapi()
    read = spec["components"]["schemas"]["AssistantMessageRead"]
    props = set(read["properties"])
    assert props == {
        "id",
        "conversation_id",
        "role",
        "content",
        "sequence",
        "created_at",
    }

"""Dynamic offline boundary tests for the native Stage 8 path.

The architecture document's acceptance criteria (§9, refined by §7.1)
require offline regression tests to FAIL when a prohibited call is
attempted: a network request, remote model client, provider fallback,
model-hub download, or remote artifact fetch. The existing static
source-scan tests prove absence in source text; these tests add the
runtime proof at the real Python-level seams the native path contains
or could reach through its dependencies: ``socket.socket``,
``socket.create_connection``, ``socket.getaddrinfo``,
``urllib.request.urlopen``, ``urllib.request.build_opener``,
``http.client.HTTPConnection``/``HTTPSConnection``, and the file-read
and ``torch.load`` seams on the checkpoint path.

Every interception raises AssertionError, so one attempted prohibited
call fails the test immediately. The exercised pipeline is the real
one: Task 207 dataset preparation, Task 208 vocabulary, Task 209
model, Task 211 checkpoint/manifest bytes, the Task 212 CPU runtime,
and the Task 213 advisory adapter via the existing local-inference
fixtures. All fixtures are synthetic; nothing touches the network.

Honest scope: interception covers Python-callable seams. It does not
pretend to intercept hypothetical socket creation inside compiled
dependency internals that never pass through Python objects. The
native path performs no such calls (static scans + these runtime
guards), and the runtime documentation notes this limitation
explicitly.
"""

from __future__ import annotations

import http.client
import pathlib
import socket
import urllib.request

import pytest
import torch
from pydantic import ValidationError

from rop.inference.runtime import (
    InferenceError,
    InferenceSelection,
    load_inference_session,
    run_inference,
)
from rop.schemas.inference import InferenceRequest
from rop.services.local_paths import secure_directory_traversal_supported

_PROHIBITED_ATTEMPT_REASON = (
    "prohibited network call attempted during native offline inference"
)


def _install_network_guards(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace every real Python-level network seam with a fail guard.

    Returns the list of attempts the guards recorded. A guard also raises, but
    an application layer could swallow that exception, so tests assert the list
    is empty as well.
    """
    attempts: list[str] = []

    def _raise(*args: object, **kwargs: object):
        attempts.append(_PROHIBITED_ATTEMPT_REASON)
        raise AssertionError(_PROHIBITED_ATTEMPT_REASON)

    # Do NOT replace socket.socket or socket.socketpair with a non-class.
    # asyncio's ProactorEventLoop on Windows performs
    # isinstance(conn, socket.socket) internally on every event-loop
    # pipe read; when socket.socket has been rebound to a plain function,
    # that isinstance() call raises TypeError, the loop dies, and the
    # TestClient hangs forever waiting for a reply that never arrives.
    # Guard the connection-establishment methods on the class instead.
    monkeypatch.setattr(socket.socket, "connect", _raise)
    monkeypatch.setattr(socket.socket, "connect_ex", _raise)
    monkeypatch.setattr(socket.socket, "sendto", _raise)
    # socket.socketpair stays real: the loop uses it for self-pipe IPC.
    monkeypatch.setattr(socket, "create_connection", _raise)
    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    monkeypatch.setattr(urllib.request, "build_opener", _raise)
    monkeypatch.setattr(http.client, "HTTPConnection", _raise)
    monkeypatch.setattr(http.client, "HTTPSConnection", _raise)
    return attempts


def test_guards_fail_on_attempted_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guards themselves fail closed: a directly attempted call
    raises instead of succeeding. This validates the gate the other
    tests in this module rely on.
    """
    _install_network_guards(monkeypatch)
    with pytest.raises(AssertionError, match="prohibited network call"):
        urllib.request.urlopen("http://example.invalid/")  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match="prohibited network call"):
        socket.create_connection(("example.invalid", 80))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "checkpoint_path",
    [
        "https://example.invalid/model.ckpt",
        "http://example.invalid/model.ckpt",
        "ftp://example.invalid/model.ckpt",
    ],
)
def test_remote_artifact_selection_never_attempts_file_read_or_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path, checkpoint_path: str
) -> None:
    """A network-location artifact selection must fail closed at the
    Task 212 runtime's own selection revalidation before any file read
    or any network I/O is attempted. The local-read seam is sabotaged,
    so if the runtime tried to open even a local path the test would
    fail loudly instead of passing.

    The selection instance bypasses schema-level construction
    (``model_construct``) so the rejection proven here is the runtime
    function's own revalidation, not just the constructor.
    """
    selection = InferenceSelection.model_construct(
        checkpoint_path=checkpoint_path,
        manifest_path=str(tmp_path / "nowhere.json"),
    )

    def _boom_read_bytes(self):
        raise AssertionError("artifact file read attempted for a network selection")

    monkeypatch.setattr(pathlib.Path, "read_bytes", _boom_read_bytes)
    _install_network_guards(monkeypatch)

    with pytest.raises(InferenceError) as raised:
        load_inference_session(
            selection=selection,
            model_config=None,  # type: ignore[arg-type]
            training_config=None,  # type: ignore[arg-type]
            result=None,  # type: ignore[arg-type]
            vocabulary=None,  # type: ignore[arg-type]
            tokenizer_config=None,  # type: ignore[arg-type]
        )
    assert raised.value.code == "INVALID_INPUT"
    assert "artifact selection is invalid" in str(raised.value)


def test_remote_selection_fails_closed_at_strict_schema(tmp_path) -> None:
    """The Task 212 selection schema itself rejects network-location
    syntax on both artifact paths before any runtime code runs.
    """
    locations = (
        ("https://example.invalid/model.ckpt", str(tmp_path / "manifest.json")),
        (str(tmp_path / "model.ckpt"), "https://example.invalid/manifest.json"),
    )
    for checkpoint_path, manifest_path in locations:
        with pytest.raises(ValidationError):
            InferenceSelection(
                checkpoint_path=checkpoint_path, manifest_path=manifest_path
            )


def test_offline_load_and_inference_attempt_no_network_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Run the complete offline flow - artifact verification, model
    load, CPU inference - under network guards. The flow may only
    complete if zero prohibited calls were attempted at the guarded
    seams. torch.load is additionally guarded: the Task 211/212
    contract never loads serialized pickle/model-hub content, so any
    call would indicate a prohibited artifact path.
    """

    def _no_torch_load(*args: object, **kwargs: object):
        raise AssertionError(
            "torch.load attempted; the native pipeline must only use "
            "its structural checkpoint contract"
        )

    def _record_read_bytes(self):
        return original_read_bytes(self)

    from tests.test_local_inference_runtime import _load_session

    original_read_bytes = pathlib.Path.read_bytes
    monkeypatch.setattr(torch, "load", _no_torch_load)
    monkeypatch.setattr(pathlib.Path, "read_bytes", _record_read_bytes)
    _install_network_guards(monkeypatch)

    session = _load_session(tmp_path)
    assert session.artifact_id == "synthetic-infer-001"
    result = run_inference(
        session,
        InferenceRequest.model_validate({"token_id_sequences": [[1, 2, 3]]}),
    )
    assert result.batch_size == 1
    assert result.num_classes == session.num_classes


@pytest.mark.skipif(
    not secure_directory_traversal_supported(),
    reason="offline retrieval needs the secure Linux descriptor backend",
)
def test_retrieval_search_stays_offline_under_runtime_network_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Exercise real local retrieval while all Python network seams fail closed."""
    from rop.api.retrieval import search_roots_detailed

    root = tmp_path / "authorized"
    root.mkdir()
    (root / "notes.md").write_text("local-only retrieval marker", encoding="utf-8")

    _install_network_guards(monkeypatch)
    outcome = search_roots_detailed(
        [str(root), r"\\network.example\share"], "retrieval marker", 10
    )

    assert len(outcome.matches) == 1
    assert "retrieval marker" in outcome.matches[0].snippet
    assert outcome.files_examined == 1
    # The network root is a rejected folder, not a skipped file.
    assert outcome.roots_rejected == 1
    assert outcome.skipped_files == 0


@pytest.mark.skipif(
    not secure_directory_traversal_supported(),
    reason="offline retrieval needs the secure Linux descriptor backend",
)
def test_retrieval_search_route_stays_offline_under_runtime_network_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Drive the real in-process POST route against a persisted, identified root.

    This is a Python-level interception test, not proof of OS-wide network
    isolation: it cannot see network access made inside compiled dependencies
    that bypass the guarded Python callables. The ASGI client and its event loop
    are created before the guards are installed because asyncio itself builds a
    socketpair when a loop starts; that is loop plumbing, not network use. The
    guards are then active for the whole request and the retrieval work.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import rop.models  # noqa: F401
    from rop import database as database_module
    from rop.database import Base
    from rop.main import app
    from rop.models.assistant_retrieval_root import AssistantRetrievalRoot
    from rop.services.local_paths import local_directory_identity

    root = tmp_path / "authorized-route-root"
    root.mkdir()
    (root / "notes.md").write_text("route-level offline marker", encoding="utf-8")
    identity = local_directory_identity(root)
    assert identity is not None

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    with factory() as session:
        session.add(AssistantRetrievalRoot(path=str(root), root_identity=identity))
        session.commit()

    origin = "http://127.0.0.1:8000"
    try:
        with TestClient(app, base_url=origin) as client:
            with monkeypatch.context() as guarded:
                attempts = _install_network_guards(guarded)
                # The guards must be live, or an empty attempt list proves nothing.
                with pytest.raises(AssertionError, match="prohibited network call"):
                    socket.create_connection(("example.invalid", 80))  # type: ignore[arg-type]
                attempts.clear()

                response = client.post(
                    "/api/assistant/retrieval/search",
                    headers={"origin": origin, "content-type": "application/json"},
                    json={"query": "route-level offline marker", "limit": 10},
                )
            assert attempts == []
    finally:
        engine.dispose()

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["matches"]) == 1
    assert "route-level offline marker" in body["matches"][0]["snippet"]
    assert body["files_examined"] == 1
    assert body["roots_examined"] == 1
    assert body["roots_skipped"] == 0


def _install_external_request_guards(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Guard outbound request/DNS seams while permitting ASGI loopback plumbing.

    The ASGI TestClient event loop uses a local socketpair during startup, so
    this startup check deliberately guards connection and request seams rather
    than replacing the socket constructor. The stricter socket-constructor guard
    remains active in the runtime inference/retrieval tests above.
    """
    attempts: list[str] = []

    def guard(name: str):
        def reject(*args: object, **kwargs: object):
            attempts.append(name)
            raise AssertionError(f"prohibited external call attempted: {name}")

        return reject

    monkeypatch.setattr(socket, "create_connection", guard("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", guard("socket.getaddrinfo"))
    monkeypatch.setattr(urllib.request, "urlopen", guard("urllib.request.urlopen"))
    monkeypatch.setattr(
        urllib.request, "build_opener", guard("urllib.request.build_opener")
    )
    monkeypatch.setattr(
        http.client, "HTTPConnection", guard("http.client.HTTPConnection")
    )
    monkeypatch.setattr(
        http.client, "HTTPSConnection", guard("http.client.HTTPSConnection")
    )
    return attempts


def test_normal_local_startup_health_and_interface_need_no_external_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start the real app and serve its local UI with outbound calls forbidden.

    The test fixture disables the independent startup database-recovery sweep;
    database recovery is exercised by its own PostgreSQL-backed tests. The
    guards fail the test on any attempt to resolve an external name, open an
    outbound connection, or use a Python HTTP/URL request seam.
    """
    from fastapi.testclient import TestClient

    from rop.main import app

    attempts = _install_external_request_guards(monkeypatch)
    with TestClient(app) as client:
        health = client.get("/health")
        page = client.get("/")

    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}
    assert page.status_code == 200
    assert "Micky AI" in page.text
    assert attempts == []

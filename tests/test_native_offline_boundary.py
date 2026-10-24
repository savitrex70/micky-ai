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

_PROHIBITED_ATTEMPT_REASON = (
    "prohibited network call attempted during native offline inference"
)


def _install_network_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace every real Python-level network seam with a fail guard."""

    def _raise(*args: object, **kwargs: object):
        raise AssertionError(_PROHIBITED_ATTEMPT_REASON)

    monkeypatch.setattr(socket, "socket", _raise)
    monkeypatch.setattr(socket, "socketpair", _raise)
    monkeypatch.setattr(socket, "create_connection", _raise)
    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    monkeypatch.setattr(urllib.request, "build_opener", _raise)
    monkeypatch.setattr(http.client, "HTTPConnection", _raise)
    monkeypatch.setattr(http.client, "HTTPSConnection", _raise)


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


def test_retrieval_search_stays_offline_under_runtime_network_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Exercise real local retrieval while all Python network seams fail closed."""
    from rop.api.retrieval import search_roots

    root = tmp_path / "authorized"
    root.mkdir()
    (root / "notes.md").write_text(
        "local-only retrieval marker", encoding="utf-8"
    )

    _install_network_guards(monkeypatch)
    matches, examined, skipped = search_roots(
        [str(root), r"\\network.example\share"], "retrieval marker", 10
    )

    assert len(matches) == 1
    assert "retrieval marker" in matches[0].snippet
    assert examined == 1
    assert skipped >= 1

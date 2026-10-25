"""Regression tests for stored retrieval-root authorization in workspace reads."""

from pathlib import Path
from types import SimpleNamespace

from rop.api import retrieval
from rop.schemas.authorization import ProposedOperation
from rop.services import workspace_read


def test_workspace_search_preserves_persisted_root_identity(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "legacy-root"
    root.mkdir()
    (root / "private.md").write_text("legacy root private marker", encoding="utf-8")

    class FakeSession:
        def close(self) -> None:
            pass

    monkeypatch.setattr(
        workspace_read.database_module, "SessionLocal", lambda: FakeSession()
    )
    monkeypatch.setattr(
        workspace_read._REPOSITORY,
        "list_roots",
        lambda _session, **_kwargs: [
            SimpleNamespace(path=str(root), root_identity=None)
        ],
    )
    monkeypatch.setattr(workspace_read._REPOSITORY, "count_roots", lambda _s: 1)
    received: list[object] = []
    search = retrieval.search_roots_detailed

    def observe_root_identity(root_specs, query, limit, **kwargs):
        received.extend(root_specs)
        return search(root_specs, query, limit, **kwargs)

    monkeypatch.setattr(retrieval, "search_roots_detailed", observe_root_identity)
    result = workspace_read.run_workspace_read(
        ProposedOperation(
            operation_id="workspace_search_files",
            parameters={"query": "legacy root private marker"},
        )
    )

    assert received == [(str(root), None)]
    assert "legacy root private marker" not in result
    assert "found 0 matches" in result

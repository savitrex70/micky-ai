"""Native Windows tests for handle-based, fail-closed local retrieval."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from rop.api import retrieval
from rop.services import local_paths

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="native Windows handle and reparse-point integration",
)


def _require_secure_windows_backend() -> None:
    assert local_paths.secure_directory_traversal_supported(), (
        "the Windows handle-relative retrieval backend must be operational; "
        "it must not silently fall back to pathname-based reads"
    )


def test_windows_handle_backend_searches_only_authorized_files(tmp_path: Path) -> None:
    _require_secure_windows_backend()
    root = tmp_path / "approved"
    root.mkdir()
    (root / "note.md").write_text("authorized needle", encoding="utf-8")
    (root / "unsupported.pdf").write_text(
        "needle must not be indexed", encoding="utf-8"
    )
    nested = root / "nested"
    nested.mkdir()
    (nested / "table.csv").write_text("another local file", encoding="utf-8")

    identity = local_paths.local_directory_identity(root)
    assert identity is not None

    outcome = retrieval.search_roots_detailed([(str(root), identity)], "needle", 10)

    assert outcome.secure_backend_available is True
    assert len(outcome.matches) == 1
    assert outcome.matches[0].path == str(root / "note.md")
    assert outcome.files_examined == 3
    assert outcome.skipped_files == 1
    assert outcome.skipped_entries == 0
    assert outcome.roots_examined == 1
    assert outcome.roots_rejected == 0
    assert outcome.roots_skipped == 0


def test_windows_root_path_replacement_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_secure_windows_backend()
    root = tmp_path / "approved"
    root.mkdir()
    (root / "original.md").write_text("original safe text", encoding="utf-8")
    identity = local_paths.local_directory_identity(root)
    assert identity is not None
    displaced = tmp_path / "displaced-original"

    def replace_after_validation(_root: Path) -> None:
        root.rename(displaced)
        root.mkdir()
        (root / "private.md").write_text("replacement secret marker", encoding="utf-8")

    monkeypatch.setattr(retrieval, "_after_root_validation", replace_after_validation)
    outcome = retrieval.search_roots_detailed(
        [(str(root), identity)], "replacement secret marker", 10
    )

    assert outcome.matches == []
    assert outcome.roots_examined == 1
    assert outcome.roots_rejected == 1
    assert outcome.skipped_files == 0


def test_windows_junction_substitution_before_directory_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_secure_windows_backend()
    root = tmp_path / "approved"
    root.mkdir()
    candidate = root / "subdir"
    candidate.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text(
        "junction replacement secret marker", encoding="utf-8"
    )
    identity = local_paths.local_directory_identity(root)
    assert identity is not None
    substituted = False

    def replace_before_open(path: Path, *, directory: bool) -> None:
        nonlocal substituted
        if not directory or path != candidate or substituted:
            return
        candidate.rmdir()
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(candidate), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(
                f"Windows junction creation unavailable: {result.stderr.strip()}"
            )
        substituted = True

    monkeypatch.setattr(retrieval, "_before_candidate_open", replace_before_open)
    outcome = retrieval.search_roots_detailed(
        [(str(root), identity)], "junction replacement secret marker", 10
    )

    assert substituted
    assert outcome.matches == []
    assert outcome.files_examined == 0
    assert outcome.skipped_entries >= 1
    assert outcome.roots_examined == 1
    assert outcome.roots_rejected == 0


def test_windows_open_directory_blocks_rename_until_handle_is_closed(
    tmp_path: Path,
) -> None:
    _require_secure_windows_backend()
    root = tmp_path / "approved"
    root.mkdir()
    child = root / "nested"
    child.mkdir()
    displaced = root / "moved"

    handle = local_paths.open_directory_descriptor(child)
    try:
        with pytest.raises(OSError):
            child.rename(displaced)
    finally:
        local_paths.close_directory_descriptor(handle)

    child.rename(displaced)
    assert displaced.is_dir()

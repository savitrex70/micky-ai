"""Tests for bounded, explicit, offline retrieval of local text files."""

from pathlib import Path

import pytest

from rop.api.retrieval import search_roots
from rop.schemas.retrieval import RetrievalSearchRequest


def test_retrieval_request_rejects_blank_and_unknown_fields() -> None:
    with pytest.raises(ValueError):
        RetrievalSearchRequest(query="   ")
    with pytest.raises(ValueError):
        RetrievalSearchRequest(query="private", network=True)


def test_search_roots_reads_only_allowlisted_files(tmp_path: Path) -> None:
    allowed = tmp_path / "notes.md"
    allowed.write_text("local private note with needle inside", encoding="utf-8")
    ignored = tmp_path / "notes.py"
    ignored.write_text("needle outside allowlist", encoding="utf-8")
    binaryish = tmp_path / "bad.txt"
    binaryish.write_bytes(b"\xff\xfe\xfa")

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)

    assert examined == 2
    assert skipped >= 1
    assert len(matches) == 1
    assert matches[0].path == str(allowed.resolve())
    assert "needle" in matches[0].snippet


def test_search_roots_does_not_escape_selected_folder(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    private = tmp_path / "outside.md"
    private.write_text("never search this root", encoding="utf-8")
    try:
        (root / "escape.md").symlink_to(private)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available in this environment")

    matches, _, _ = search_roots([str(root)], "never", 10)
    assert matches == []


def test_search_roots_skips_unsupported_formats(tmp_path: Path) -> None:
    (tmp_path / "memo.pdf").write_text("needle", encoding="utf-8")
    (tmp_path / "memo.txt").write_text("different contents", encoding="utf-8")

    matches, examined, _ = search_roots([str(tmp_path)], "needle", 10)

    assert matches == []
    assert examined == 1

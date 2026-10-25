"""Adversarial tests for bounded, explicitly authorized local retrieval."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import rop.api.retrieval as retrieval
import rop.api.workspace as workspace_api
from rop.api.retrieval import search_roots
from rop.schemas.retrieval import RetrievalSearchRequest
from rop.schemas.workspace import WorkspaceChangeRequest
from rop.services import local_paths


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


def test_search_roots_rejects_root_replaced_by_symlink(tmp_path: Path) -> None:
    authorized = tmp_path / "authorized"
    authorized.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret.md").write_text("root substitution secret", encoding="utf-8")

    authorized.rmdir()
    try:
        authorized.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are not available in this environment")

    matches, _, skipped = search_roots([str(authorized)], "secret", 10)
    assert matches == []
    assert skipped >= 1


def test_ancestor_symlink_is_rejected_before_resolving_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_parent = tmp_path / "real-parent"
    target_parent.mkdir()
    target_root = target_parent / "approved"
    target_root.mkdir()
    (target_root / "secret.md").write_text("must not be read", encoding="utf-8")
    alias_parent = tmp_path / "parent-alias"
    try:
        alias_parent.symlink_to(target_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are not available in this environment")

    def prohibited_resolve(self, *args, **kwargs):
        raise AssertionError("a path with a symlink ancestor must be rejected first")

    monkeypatch.setattr(Path, "resolve", prohibited_resolve)

    matches, _, skipped = search_roots(
        [str(alias_parent / "approved")], "must not be read", 10
    )

    assert matches == []
    assert skipped >= 1


def test_search_roots_rejects_ancestor_symlink_substitution(tmp_path: Path) -> None:
    original_parent = tmp_path / "original-parent"
    original_parent.mkdir()
    authorized_root = original_parent / "approved"
    authorized_root.mkdir()
    (authorized_root / "secret.md").write_text(
        "outside data behind parent substitution", encoding="utf-8"
    )
    substitute_parent = tmp_path / "substitute-parent"
    substitute_parent.mkdir()
    (substitute_parent / "approved").mkdir()
    (substitute_parent / "approved" / "secret.md").write_text(
        "substituted root secret", encoding="utf-8"
    )

    original_parent.rename(tmp_path / "moved-parent")
    try:
        original_parent.symlink_to(substitute_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are not available in this environment")

    matches, _, skipped = search_roots([str(authorized_root)], "secret", 10)
    assert matches == []
    assert skipped >= 1


def test_search_roots_does_not_traverse_symlinked_directory(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("do not follow directory link", encoding="utf-8")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are not available in this environment")

    matches, _, _ = search_roots([str(root)], "follow directory link", 10)
    assert matches == []


def test_search_roots_skips_junctions_when_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    junction_like = root / "junction"
    junction_like.mkdir()
    (junction_like / "secret.md").write_text("junction content", encoding="utf-8")

    real_check = retrieval._is_junction
    monkeypatch.setattr(
        retrieval,
        "_is_junction",
        lambda path: path == junction_like or real_check(path),
    )

    matches, _, _ = search_roots([str(root)], "junction content", 10)
    assert matches == []


def test_junction_detection_fails_closed_if_the_check_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_check(_path: Path) -> bool:
        raise OSError("simulated reparse-point inspection failure")

    monkeypatch.setattr(Path, "is_junction", broken_check, raising=False)
    assert local_paths.is_junction(tmp_path) is True


@pytest.mark.skipif(os.name != "nt", reason="real junction creation requires Windows")
def test_search_roots_skips_real_windows_junction(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("windows junction secret", encoding="utf-8")
    junction = root / "redirect"

    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"could not create a Windows junction: {result.stderr.strip()}")

    matches, _, _ = search_roots([str(root)], "windows junction secret", 10)
    assert matches == []


def test_network_path_forms_are_rejected() -> None:
    assert local_paths.is_network_path(Path(r"\\server\share"))
    assert local_paths.is_network_path(Path("//server/share"))
    assert local_paths.is_network_path(Path(r"\\?\UNC\server\share"))


def test_mapped_network_drive_detection_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Kernel:
        def __init__(self, result: int | None) -> None:
            self.result = result

        def GetDriveTypeW(self, drive: str) -> int:
            assert drive == "Z:\\"
            if self.result is None:
                raise OSError("drive type unavailable")
            return self.result

    monkeypatch.setattr(local_paths, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        local_paths.ctypes,
        "windll",
        SimpleNamespace(kernel32=Kernel(4)),
        raising=False,
    )
    assert local_paths.is_network_path(PureWindowsPath(r"Z:\approved"))

    monkeypatch.setattr(
        local_paths.ctypes,
        "windll",
        SimpleNamespace(kernel32=Kernel(None)),
        raising=False,
    )
    assert local_paths.is_network_path(PureWindowsPath(r"Z:\approved"))

    monkeypatch.setattr(
        local_paths.ctypes,
        "windll",
        SimpleNamespace(kernel32=Kernel(3)),
        raising=False,
    )
    assert not local_paths.is_network_path(PureWindowsPath(r"Z:\approved"))


@pytest.mark.skipif(
    os.name != "posix" or not local_paths.sys.platform.startswith("linux"),
    reason="Linux mountinfo behavior requires Linux",
)
def test_search_roots_rejects_mocked_linux_network_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "mounted-share"
    root.mkdir()
    (root / "secret.md").write_text("network-mounted secret", encoding="utf-8")
    mounts = ((Path("/"), "overlay"), (root.resolve(), "cifs"))
    monkeypatch.setattr(local_paths, "_linux_mount_table", lambda: mounts)

    matches, _, skipped = search_roots([str(root)], "secret", 10)
    assert matches == []
    assert skipped >= 1


@pytest.mark.skipif(
    os.name != "posix" or not local_paths.sys.platform.startswith("linux"),
    reason="Linux mountinfo behavior requires Linux",
)
def test_workspace_root_add_rejects_mocked_network_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "mounted-share"
    root.mkdir()
    mounts = ((Path("/"), "overlay"), (root.resolve(), "nfs4"))
    monkeypatch.setattr(local_paths, "_linux_mount_table", lambda: mounts)
    request = WorkspaceChangeRequest.model_validate(
        {
            "kind": "retrieval_root",
            "action": "add",
            "idempotency_key": str(uuid4()),
            "path": str(root),
        }
    )

    with pytest.raises(HTTPException) as raised:
        workspace_api._operation_for(request)

    assert raised.value.status_code == 422
    assert "Network folders" in str(raised.value.detail)


def test_workspace_root_add_rejects_link_ancestor_before_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    (real_parent / "approved").mkdir()
    alias_parent = tmp_path / "parent-alias"
    try:
        alias_parent.symlink_to(real_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are not available in this environment")

    request = WorkspaceChangeRequest.model_validate(
        {
            "kind": "retrieval_root",
            "action": "add",
            "idempotency_key": str(uuid4()),
            "path": str(alias_parent / "approved"),
        }
    )

    def prohibited_resolve(self, *args, **kwargs):
        raise AssertionError("linked roots must be rejected before resolution")

    monkeypatch.setattr(Path, "resolve", prohibited_resolve)

    with pytest.raises(HTTPException) as raised:
        workspace_api._operation_for(request)

    assert raised.value.status_code == 422
    assert "linked paths" in str(raised.value.detail)


def test_workspace_root_add_refreshes_mount_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "local-root"
    root.mkdir()
    refresh_calls: list[bool] = []
    monkeypatch.setattr(
        workspace_api,
        "refresh_mount_table",
        lambda: refresh_calls.append(True),
    )
    request = WorkspaceChangeRequest.model_validate(
        {
            "kind": "retrieval_root",
            "action": "add",
            "idempotency_key": str(uuid4()),
            "path": str(root),
        }
    )

    workspace_api._operation_for(request)

    assert refresh_calls == [True]


def test_linux_network_mount_classification_does_not_resolve_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mounted_root = tmp_path / "mounted-share"
    mounted_root.mkdir()
    mount_table = ((Path("/"), "overlay"), (mounted_root, "nfs4"))
    monkeypatch.setattr(local_paths, "_linux_mount_table", lambda: mount_table)

    def prohibited_resolve(self, *args, **kwargs):
        raise AssertionError("network mount detection must not resolve the path")

    monkeypatch.setattr(Path, "resolve", prohibited_resolve)

    assert local_paths.is_network_path(mounted_root / "not-yet-accessible" / "notes.md")


def test_search_roots_fails_closed_if_linux_mount_metadata_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    (root / "secret.md").write_text("local secret", encoding="utf-8")
    monkeypatch.setattr(local_paths, "_linux_mount_table", lambda: None)

    if os.name == "posix" and local_paths.sys.platform.startswith("linux"):
        matches, _, skipped = search_roots([str(root)], "secret", 10)
        assert matches == []
        assert skipped >= 1
    else:
        pytest.skip("Linux mountinfo boundary applies only on Linux")


def test_search_roots_skips_files_from_another_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "mounted.md"
    candidate.write_text("must not cross a mount boundary", encoding="utf-8")
    resolved_candidate = candidate.resolve()
    original_stat = Path.stat

    def fake_stat(path: Path, *args, **kwargs):
        info = original_stat(path, *args, **kwargs)
        if path == resolved_candidate:
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_dev=info.st_dev + 1,
                st_size=info.st_size,
            )
        return info

    monkeypatch.setattr(Path, "stat", fake_stat)
    matches, examined, skipped = search_roots([str(tmp_path)], "mount boundary", 10)

    assert matches == []
    assert examined == 1
    assert skipped >= 1


def test_search_roots_enforces_per_file_byte_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "large.md").write_text("needle" + ("x" * 40), encoding="utf-8")
    monkeypatch.setattr(retrieval, "_MAX_FILE_BYTES", 16)

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)

    assert matches == []
    assert examined == 1
    assert skipped >= 1


def test_search_roots_enforces_aggregate_byte_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.md").write_text("a" * 12, encoding="utf-8")
    (tmp_path / "b.md").write_text("needle end", encoding="utf-8")
    monkeypatch.setattr(retrieval, "_MAX_BYTES_PER_REQUEST", 16)

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)

    assert matches == []
    assert examined == 2
    assert skipped >= 1


def test_search_roots_enforces_file_count_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(4):
        (tmp_path / f"{index}.md").write_text("no match", encoding="utf-8")
    monkeypatch.setattr(retrieval, "_MAX_FILES_PER_REQUEST", 2)

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)

    assert matches == []
    assert examined == 2
    assert skipped >= 1


def test_search_roots_enforces_total_entry_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(8):
        (tmp_path / f"{index}.md").write_text("needle", encoding="utf-8")
    monkeypatch.setattr(retrieval, "_MAX_ENTRIES_PER_REQUEST", 3)

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)

    assert examined <= 3
    assert skipped >= 1
    assert len(matches) <= 3


def test_search_roots_enforces_directory_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a", "b", "c", "d"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "content.md").write_text("needle", encoding="utf-8")
    monkeypatch.setattr(retrieval, "_MAX_DIRECTORIES_PER_ROOT", 2)

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)

    assert examined <= 1
    assert skipped >= 1
    assert len(matches) <= 1


@pytest.mark.skipif(os.name == "nt", reason="FIFO special files are POSIX-specific")
def test_search_roots_never_opens_fifo_with_allowed_suffix(tmp_path: Path) -> None:
    fifo = tmp_path / "named-pipe.txt"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError, NotImplementedError):
        pytest.skip("FIFO creation is not available in this environment")

    matches, examined, skipped = search_roots([str(tmp_path)], "needle", 10)
    assert matches == []
    assert examined == 0
    assert skipped == 0


def test_search_roots_skips_unsupported_formats(tmp_path: Path) -> None:
    (tmp_path / "memo.pdf").write_text("needle", encoding="utf-8")
    (tmp_path / "memo.txt").write_text("different contents", encoding="utf-8")

    matches, examined, _ = search_roots([str(tmp_path)], "needle", 10)

    assert matches == []
    assert examined == 1


@pytest.mark.skipif(
    not local_paths.secure_directory_traversal_supported(),
    reason="descriptor-relative race checks require Linux no-follow primitives",
)
def test_root_substitution_after_validation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "approved"
    root.mkdir()
    (root / "ordinary.md").write_text("ordinary local content", encoding="utf-8")
    original_identity = local_paths.local_directory_identity(root)
    assert original_identity is not None

    def substitute_root(_root: Path) -> None:
        root.rename(parent / "moved-approved")
        root.mkdir()
        (root / "secret.md").write_text(
            "distinctive substituted root private marker", encoding="utf-8"
        )

    monkeypatch.setattr(retrieval, "_after_root_validation", substitute_root)
    matches, examined, skipped = search_roots(
        [(str(root), original_identity)], "substituted root private marker", 10
    )

    assert matches == []
    assert examined == 0
    assert skipped >= 1


@pytest.mark.skipif(
    not local_paths.secure_directory_traversal_supported(),
    reason="descriptor-relative race checks require Linux no-follow primitives",
)
def test_ancestor_replacement_after_validation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "approved"
    root.mkdir()
    original_identity = local_paths.local_directory_identity(root)
    assert original_identity is not None

    def substitute_ancestor(_root: Path) -> None:
        parent.rename(tmp_path / "moved-parent")
        parent.mkdir()
        substituted_root = parent / "approved"
        substituted_root.mkdir()
        (substituted_root / "secret.md").write_text(
            "ancestor replacement private marker", encoding="utf-8"
        )

    monkeypatch.setattr(retrieval, "_after_root_validation", substitute_ancestor)
    matches, examined, skipped = search_roots(
        [(str(root), original_identity)], "ancestor replacement private marker", 10
    )

    assert matches == []
    assert examined == 0
    assert skipped >= 1


@pytest.mark.skipif(
    not local_paths.secure_directory_traversal_supported(),
    reason="descriptor-relative race checks require Linux no-follow primitives",
)
def test_directory_replaced_between_scan_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    child = root / "child"
    child.mkdir()
    outside_content = "same filesystem replacement directory private marker"
    substituted = tmp_path / "replacement"
    substituted.mkdir()
    (substituted / "secret.md").write_text(outside_content, encoding="utf-8")
    swapped = False

    def replace_directory(path: Path, *, directory: bool) -> None:
        nonlocal swapped
        if not swapped and directory and path == child:
            child.rename(root / "original-child")
            os.replace(substituted, child)
            swapped = True

    monkeypatch.setattr(retrieval, "_before_candidate_open", replace_directory)
    matches, _, skipped = search_roots([str(root)], "replacement directory private marker", 10)

    assert swapped
    assert matches == []
    assert skipped >= 1


@pytest.mark.skipif(
    not local_paths.secure_directory_traversal_supported(),
    reason="descriptor-relative race checks require Linux no-follow primitives",
)
def test_same_filesystem_symlink_substitution_before_file_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    candidate = root / "candidate.md"
    candidate.write_text("ordinary original content", encoding="utf-8")
    private = tmp_path / "private.md"
    private.write_text("same filesystem private redirect marker", encoding="utf-8")
    assert candidate.stat().st_dev == private.stat().st_dev
    swapped = False

    def replace_file(path: Path, *, directory: bool) -> None:
        nonlocal swapped
        if not swapped and not directory and path == candidate:
            candidate.unlink()
            try:
                candidate.symlink_to(private)
            except (OSError, NotImplementedError):
                pytest.skip("symbolic links are unavailable")
            swapped = True

    monkeypatch.setattr(retrieval, "_before_candidate_open", replace_file)
    matches, _, skipped = search_roots([str(root)], "same filesystem private redirect marker", 10)

    assert swapped
    assert matches == []
    assert skipped >= 1


@pytest.mark.skipif(
    not local_paths.secure_directory_traversal_supported(),
    reason="descriptor-relative race checks require Linux no-follow primitives",
)
def test_network_classification_change_before_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    candidate = root / "candidate.md"
    candidate.write_text("ordinary original content", encoding="utf-8")
    original_network_check = retrieval._is_network_path
    network_changed = False

    def change_policy(path: Path) -> bool:
        if network_changed and path == candidate:
            return True
        return original_network_check(path)

    def simulate_mount_change(path: Path, *, directory: bool) -> None:
        nonlocal network_changed
        if not directory and path == candidate:
            network_changed = True

    monkeypatch.setattr(retrieval, "_before_candidate_open", simulate_mount_change)
    monkeypatch.setattr(retrieval, "_is_network_path", change_policy)
    matches, _, skipped = search_roots([str(root)], "ordinary original content", 10)

    assert network_changed
    assert matches == []
    assert skipped >= 1

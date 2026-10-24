"""Shared guards for local-only filesystem paths."""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from functools import lru_cache
from pathlib import Path

_REMOTE_FILESYSTEM_TYPES = frozenset(
    {
        "9p",
        "afpfs",
        "ceph",
        "cifs",
        "davfs",
        "davfs2",
        "fuse.curlftpfs",
        "fuse.davfs",
        "fuse.gcsfuse",
        "fuse.goofys",
        "fuse.rclone",
        "fuse.s3fs",
        "fuse.sshfs",
        "glusterfs",
        "nfs",
        "nfs4",
        "smb3",
        "smbfs",
        "sshfs",
    }
)


def _unescape_mount_field(value: str) -> str:
    """Decode the octal escapes used by Linux mountinfo."""
    return (
        value.replace(r"\040", " ")
        .replace(r"\011", "\t")
        .replace(r"\012", "\n")
        .replace(r"\134", "\\")
    )


@lru_cache(maxsize=1)
def _linux_mount_table() -> tuple[tuple[Path, str], ...] | None:
    """Read mount metadata once per retrieval request; None means unknown."""
    if not sys.platform.startswith("linux"):
        return ()
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    mounts: list[tuple[Path, str]] = []
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        right_fields = right.split()
        if len(fields) < 5 or not right_fields:
            continue
        mountpoint = Path(_unescape_mount_field(fields[4]))
        mounts.append((mountpoint, right_fields[0].casefold()))

    if not any(mountpoint == Path("/") for mountpoint, _ in mounts):
        return None
    return tuple(mounts)


def refresh_mount_table() -> None:
    """Refresh the per-request Linux mount snapshot when the platform supports it."""
    clear_cache = getattr(_linux_mount_table, "cache_clear", None)
    if clear_cache is not None:
        clear_cache()


def is_network_path(path: Path) -> bool:
    """Reject UNC paths, remote Windows drives, and known remote Linux mounts."""
    raw = str(path)
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True

    if os.name == "nt" and getattr(path, "drive", ""):
        try:
            return ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == 4
        except (AttributeError, OSError, TypeError):
            return True

    if os.name == "posix" and sys.platform.startswith("linux"):
        mounts = _linux_mount_table()
        if mounts is None:
            # An unreadable mount table makes the network/local distinction
            # unknowable. Retrieval must fail closed rather than guess.
            return True
        try:
            # Classify by lexical path and mount metadata only: resolving a
            # path inside an unavailable network mount could itself access it.
            target = Path(os.path.abspath(os.fspath(path)))
        except (OSError, RuntimeError, ValueError):
            return True

        best_depth = -1
        best_filesystem = ""
        for mountpoint, filesystem in mounts:
            try:
                if target == mountpoint or target.is_relative_to(mountpoint):
                    depth = len(mountpoint.parts)
                    if depth > best_depth:
                        best_depth = depth
                        best_filesystem = filesystem
            except (OSError, RuntimeError, ValueError):
                return True
        return best_filesystem in _REMOTE_FILESYSTEM_TYPES

    return False


def is_junction(path: Path) -> bool:
    """Detect junctions and fail closed if the platform check errors."""
    method = getattr(path, "is_junction", None)
    if method is not None:
        try:
            return bool(method())
        except (OSError, RuntimeError, ValueError):
            return True
    if os.name == "nt":
        try:
            attributes = path.lstat().st_file_attributes
            reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            return bool(attributes & reparse_point)
        except (AttributeError, OSError, RuntimeError, ValueError):
            return True
    return False


def normalized_path_key(path: Path) -> str:
    """Return a normalized absolute spelling without resolving links."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))

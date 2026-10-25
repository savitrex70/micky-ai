"""Shared guards for local-only filesystem paths."""

from __future__ import annotations

import ctypes
import errno
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
    """Read mount metadata once; None means the local/remote boundary is unknown."""
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
    """Refresh the cached Linux mount snapshot."""
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
            return True
        try:
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


def contains_link_or_junction(path: Path) -> bool:
    """Reject a path if any component is a symlink, junction, or parent traversal.

    Inspect prefixes in order and never resolve a pathname while validating it.
    """
    try:
        supplied = Path(os.fspath(path))
        if ".." in supplied.parts:
            return True
        absolute = Path(os.path.abspath(os.fspath(supplied)))
        current = Path(absolute.anchor)
        for component in absolute.parts[1:]:
            current = current / component
            if is_network_path(current):
                return True
            if current.is_symlink() or is_junction(current):
                return True
        return False
    except (OSError, RuntimeError, TypeError, ValueError):
        return True


def secure_directory_traversal_supported() -> bool:
    """Whether Linux exposes the no-follow descriptors and mount identity we need."""
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    supports_fd = getattr(os, "supports_fd", set())
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    return bool(
        sys.platform.startswith("linux")
        and _linux_mount_table() is not None
        and getattr(os, "open", None) in supports_dir_fd
        and getattr(os, "stat", None) in supports_dir_fd
        and getattr(os, "stat", None) in supports_follow_symlinks
        and getattr(os, "scandir", None) in supports_fd
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
    )


def secure_directory_open_flags() -> int:
    """Flags required to open a directory without following a link."""
    if not secure_directory_traversal_supported():
        raise OSError(errno.ENOTSUP, "secure directory traversal is unavailable")
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )


def open_directory_descriptor(path: Path) -> int:
    """Open an absolute directory by walking every component with no-follow openat.

    The caller owns the returned descriptor. This deliberately refuses platforms
    that do not provide the descriptor-relative primitives required by retrieval.
    """
    supplied = Path(os.fspath(path))
    if not supplied.is_absolute() or ".." in supplied.parts:
        raise OSError(errno.EINVAL, "directory path must be absolute and normalized")
    absolute = Path(os.path.abspath(os.fspath(supplied)))
    flags = secure_directory_open_flags()
    current_path = Path(absolute.anchor)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            next_path = current_path / component
            if is_network_path(next_path):
                raise OSError(errno.EPERM, "remote filesystem paths are not allowed")
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            info = os.fstat(next_descriptor)
            if not stat.S_ISDIR(info.st_mode):
                os.close(next_descriptor)
                raise OSError(errno.ENOTDIR, "path component is not a directory")
            os.close(descriptor)
            descriptor = next_descriptor
            current_path = next_path

        refresh_mount_table()
        if is_network_path(absolute):
            raise OSError(errno.EPERM, "remote filesystem paths are not allowed")
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError(errno.ENOTDIR, "path is not a directory")
        result = descriptor
        descriptor = -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def descriptor_mount_id(descriptor: int) -> int | None:
    """Return Linux's mount ID for an opened object, failing closed if unknown."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        lines = Path(f"/proc/self/fdinfo/{descriptor}").read_text(
            encoding="ascii"
        ).splitlines()
        for line in lines:
            name, separator, value = line.partition(":")
            if separator and name == "mnt_id":
                return int(value.strip())
    except (OSError, UnicodeError, ValueError):
        return None
    return None


def directory_identity_from_descriptor(descriptor: int) -> str | None:
    """Bind an approved directory to device, inode, and mount identity."""
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        return None
    device = getattr(info, "st_dev", None)
    inode = getattr(info, "st_ino", None)
    mount_id = descriptor_mount_id(descriptor)
    if (
        not isinstance(device, int)
        or not isinstance(inode, int)
        or device < 0
        or inode <= 0
        or mount_id is None
        or mount_id <= 0
    ):
        return None
    return f"{device:x}:{inode:x}:{mount_id:x}"


def local_directory_identity(path: Path) -> str | None:
    """Validate a local directory and return identity from its opened descriptor."""
    if not secure_directory_traversal_supported():
        return None
    supplied = Path(os.fspath(path))
    if not supplied.is_absolute() or ".." in supplied.parts:
        return None
    if is_network_path(supplied) or contains_link_or_junction(supplied):
        return None
    try:
        descriptor = open_directory_descriptor(supplied)
        try:
            identity = directory_identity_from_descriptor(descriptor)
        finally:
            os.close(descriptor)
        refresh_mount_table()
        if identity is None or is_network_path(supplied):
            return None
        return identity
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def normalized_path_key(path: Path) -> str:
    """Return a normalized absolute spelling without resolving links."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))

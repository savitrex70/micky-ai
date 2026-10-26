"""Shared guards for local-only filesystem paths."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from dataclasses import dataclass
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_OPENAT2_RESOLVE_NO_XDEV = 0x01
_OPENAT2_RESOLVE_NO_MAGICLINKS = 0x02
_OPENAT2_RESOLVE_NO_SYMLINKS = 0x04
_OPENAT2_RESOLVE_BENEATH = 0x08
_OPENAT2_RESOLVE_SAFE = (
    _OPENAT2_RESOLVE_NO_XDEV
    | _OPENAT2_RESOLVE_NO_MAGICLINKS
    | _OPENAT2_RESOLVE_NO_SYMLINKS
    | _OPENAT2_RESOLVE_BENEATH
)


class _OpenHow(ctypes.Structure):
    """Linux openat2 request layout (three unsigned 64-bit fields)."""

    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


# Windows backend constants. All traversal is handle-relative; pathname checks are
# defense in depth, not the authority used to open entries.
_WIN_FILE_READ_DATA = 0x0001
_WIN_FILE_LIST_DIRECTORY = 0x0001
_WIN_FILE_READ_ATTRIBUTES = 0x0080
_WIN_FILE_TRAVERSE = 0x0020
_WIN_SYNCHRONIZE = 0x00100000
_WIN_FILE_OPEN = 1
_WIN_FILE_DIRECTORY_FILE = 0x00000001
_WIN_FILE_NON_DIRECTORY_FILE = 0x00000040
_WIN_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_WIN_FILE_OPEN_REPARSE_POINT = 0x00200000
_WIN_OBJ_CASE_INSENSITIVE = 0x00000040
_WIN_FILE_SHARE_READ = 0x00000001
_WIN_FILE_SHARE_WRITE = 0x00000002
_WIN_FILE_SHARE_DELETE = 0x00000004
_WIN_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_WIN_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WIN_FILE_ATTRIBUTE_DEVICE = 0x00000040
_WIN_FILE_ATTRIBUTE_TAG_INFO = 9
_WIN_FILE_STANDARD_INFO = 1
_WIN_FILE_ID_INFO = 18
_WIN_FILE_ID_EXTD_DIRECTORY_INFO = 19
_WIN_FILE_ID_EXTD_DIRECTORY_RESTART_INFO = 20
_WIN_ERROR_NO_MORE_FILES = 18
_WIN_ERROR_HANDLE_EOF = 38
_WIN_ERROR_NO_MORE_ITEMS = 259
_WIN_DIRECTORY_RECORD_NAME_OFFSET = 88
_WIN_DIRECTORY_RECORD_HEADER_SIZE = 88
_WIN_DIRECTORY_BUFFER_SIZE = 65536


class _WinFileId128(ctypes.Structure):
    _fields_ = [("Identifier", ctypes.c_ubyte * 16)]


class _WinFileIdInfo(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_uint64),
        ("FileId", _WinFileId128),
    ]


class _WinFileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ("FileAttributes", ctypes.c_uint32),
        ("ReparseTag", ctypes.c_uint32),
    ]


class _WinFileStandardInfo(ctypes.Structure):
    _fields_ = [
        ("AllocationSize", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", ctypes.c_uint32),
        ("DeletePending", ctypes.c_ubyte),
        ("Directory", ctypes.c_ubyte),
    ]


class _WinUnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_wchar_p),
    ]


class _WinObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ulong),
        ("RootDirectory", ctypes.c_void_p),
        ("ObjectName", ctypes.POINTER(_WinUnicodeString)),
        ("Attributes", ctypes.c_ulong),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _WinIoStatusUnion(ctypes.Union):
    _fields_ = [
        ("Status", ctypes.c_long),
        ("Pointer", ctypes.c_void_p),
    ]


class _WinIoStatusBlock(ctypes.Structure):
    _anonymous_ = ("StatusUnion",)
    _fields_ = [
        ("StatusUnion", _WinIoStatusUnion),
        ("Information", ctypes.c_size_t),
    ]


@dataclass(frozen=True)
class SecureHandleInfo:
    """Identity and classification queried from an open Windows file handle."""

    identity: str
    volume_id: int
    file_id: str
    size: int
    is_directory: bool
    is_reparse_point: bool
    is_device: bool
    delete_pending: bool


@dataclass(frozen=True)
class SecureDirectoryEntry:
    """A directory entry returned by a handle-based Windows enumeration."""

    name: str
    identity: str
    volume_id: int
    size: int
    is_directory: bool
    is_reparse_point: bool
    is_device: bool


@lru_cache(maxsize=1)
def _windows_api():
    """Load the Windows handle APIs once, with explicit ctypes signatures."""
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows filesystem APIs are unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    kernel.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel.GetFileInformationByHandleEx.restype = ctypes.c_int
    kernel.ReadFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    kernel.ReadFile.restype = ctypes.c_int
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint32
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_uint32,
        ctypes.POINTER(_WinObjectAttributes),
        ctypes.POINTER(_WinIoStatusBlock),
        ctypes.POINTER(ctypes.c_int64),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    ntdll.NtCreateFile.restype = ctypes.c_long
    ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    ntdll.RtlNtStatusToDosError.restype = ctypes.c_uint32
    return kernel, ntdll


def _windows_os_error(operation: str, code: int | None = None) -> OSError:
    error_code = ctypes.get_last_error() if code is None else code
    if error_code <= 0:
        error_code = errno.EIO
    return OSError(error_code, f"{operation} failed with Windows error {error_code}")


def close_directory_descriptor(descriptor: int) -> None:
    """Close a descriptor or native directory handle using its owning API."""
    if os.name == "nt":
        kernel, _ = _windows_api()
        if descriptor and not kernel.CloseHandle(ctypes.c_void_p(descriptor)):
            raise _windows_os_error("CloseHandle")
    else:
        os.close(descriptor)


def secure_handle_info(handle: int) -> SecureHandleInfo:
    """Return file identity and type from an already opened Windows handle."""
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "native handle metadata is Windows-only")
    kernel, _ = _windows_api()
    handle_value = ctypes.c_void_p(handle)
    tag = _WinFileAttributeTagInfo()
    standard = _WinFileStandardInfo()
    identity = _WinFileIdInfo()
    for info_class, target in (
        (_WIN_FILE_ATTRIBUTE_TAG_INFO, tag),
        (_WIN_FILE_STANDARD_INFO, standard),
        (_WIN_FILE_ID_INFO, identity),
    ):
        if not kernel.GetFileInformationByHandleEx(
            handle_value, info_class, ctypes.byref(target), ctypes.sizeof(target)
        ):
            raise _windows_os_error("GetFileInformationByHandleEx")
    file_id = bytes(identity.FileId.Identifier).hex()
    volume_id = int(identity.VolumeSerialNumber)
    attributes = int(tag.FileAttributes)
    return SecureHandleInfo(
        identity=f"{volume_id:x}:{file_id}:{volume_id:x}",
        volume_id=volume_id,
        file_id=file_id,
        size=int(standard.EndOfFile),
        is_directory=bool(standard.Directory),
        is_reparse_point=bool(
            attributes & _WIN_FILE_ATTRIBUTE_REPARSE_POINT or tag.ReparseTag
        ),
        is_device=bool(attributes & _WIN_FILE_ATTRIBUTE_DEVICE),
        delete_pending=bool(standard.DeletePending),
    )


def _windows_open_drive_root(drive: str) -> int:
    """Open a fixed/removable drive root without following a reparse point."""
    kernel, _ = _windows_api()
    normalized_drive = drive if drive.endswith("\\") else drive + "\\"
    drive_type = int(kernel.GetDriveTypeW(normalized_drive))
    if drive_type not in (2, 3):
        raise OSError(errno.EPERM, "only local fixed/removable drives are permitted")
    flags = (
        0x02000000 | _WIN_FILE_OPEN_REPARSE_POINT
    )  # Backup semantics + open reparse point.
    raw_handle = kernel.CreateFileW(
        normalized_drive,
        _WIN_FILE_LIST_DIRECTORY
        | _WIN_FILE_READ_ATTRIBUTES
        | _WIN_FILE_TRAVERSE,
        _WIN_FILE_SHARE_READ | _WIN_FILE_SHARE_WRITE | _WIN_FILE_SHARE_DELETE,
        None,
        3,  # OPEN_EXISTING
        flags,
        None,
    )
    if raw_handle is None or raw_handle == ctypes.c_void_p(-1).value:
        raise _windows_os_error("open local drive root")
    handle = int(raw_handle)
    try:
        info = secure_handle_info(handle)
        if (
            not info.is_directory
            or info.is_reparse_point
            or info.is_device
            or info.delete_pending
        ):
            raise OSError(errno.EPERM, "drive root is not a permitted directory")
        return handle
    except Exception:
        kernel.CloseHandle(ctypes.c_void_p(handle))
        raise


def _windows_open_relative(
    parent_handle: int, name: str, *, directory: bool
) -> int:
    """Open one child relative to a pinned parent handle; never follow reparses."""
    if (
        not name
        or name in {".", ".."}
        or "\x00" in name
        or "/" in name
        or "\\" in name
        or ":" in name
        or name.endswith((".", " "))
        or len(name.encode("utf-16-le")) > 65532
    ):
        raise OSError(errno.EINVAL, "invalid relative filename")
    kernel, ntdll = _windows_api()
    encoded_length = len(name.encode("utf-16-le"))
    name_buffer = ctypes.create_unicode_buffer(name)
    unicode_name = _WinUnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(name_buffer, ctypes.c_wchar_p),
    )
    attributes = _WinObjectAttributes(
        ctypes.sizeof(_WinObjectAttributes),
        ctypes.c_void_p(parent_handle),
        ctypes.pointer(unicode_name),
        _WIN_OBJ_CASE_INSENSITIVE,
        None,
        None,
    )
    io_status = _WinIoStatusBlock()
    output_handle = ctypes.c_void_p()
    access = _WIN_FILE_READ_ATTRIBUTES | _WIN_SYNCHRONIZE
    options = _WIN_FILE_OPEN_REPARSE_POINT | _WIN_FILE_SYNCHRONOUS_IO_NONALERT
    if directory:
        access |= _WIN_FILE_LIST_DIRECTORY | _WIN_FILE_TRAVERSE
        options |= _WIN_FILE_DIRECTORY_FILE
        share = _WIN_FILE_SHARE_READ | _WIN_FILE_SHARE_WRITE | _WIN_FILE_SHARE_DELETE
    else:
        # Refusing write/delete sharing prevents a new writer or rename/delete
        # from racing the bounded read while this handle is open.
        access |= _WIN_FILE_READ_DATA
        options |= _WIN_FILE_NON_DIRECTORY_FILE
        share = _WIN_FILE_SHARE_READ
    status_code = int(
        ntdll.NtCreateFile(
            ctypes.byref(output_handle),
            access,
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            0,
            share,
            _WIN_FILE_OPEN,
            options,
            None,
            0,
        )
    )
    if status_code < 0:
        error_code = int(ntdll.RtlNtStatusToDosError(status_code))
        raise _windows_os_error("safe handle-relative file open", error_code)
    if not output_handle.value:
        raise OSError(errno.EIO, "safe handle-relative open returned no handle")
    handle = int(output_handle.value)
    try:
        info = secure_handle_info(handle)
        if (
            info.is_reparse_point
            or info.is_device
            or info.delete_pending
            or info.is_directory != directory
        ):
            raise OSError(errno.EPERM, "relative entry type or reparse policy refused")
        return handle
    except Exception:
        kernel.CloseHandle(ctypes.c_void_p(handle))
        raise


def iter_secure_directory_entries(handle: int):
    """Yield entries enumerated by handle, using bounded native API buffers."""
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "native handle enumeration is Windows-only")
    kernel, _ = _windows_api()
    parent_info = secure_handle_info(handle)
    if (
        not parent_info.is_directory
        or parent_info.is_reparse_point
        or parent_info.is_device
        or parent_info.delete_pending
    ):
        raise OSError(errno.EPERM, "directory handle is not permitted")
    volume_id = parent_info.volume_id
    first = True
    while True:
        buffer = ctypes.create_string_buffer(_WIN_DIRECTORY_BUFFER_SIZE)
        info_class = (
            _WIN_FILE_ID_EXTD_DIRECTORY_RESTART_INFO
            if first
            else _WIN_FILE_ID_EXTD_DIRECTORY_INFO
        )
        first = False
        if not kernel.GetFileInformationByHandleEx(
            ctypes.c_void_p(handle),
            info_class,
            ctypes.byref(buffer),
            ctypes.sizeof(buffer),
        ):
            error_code = ctypes.get_last_error()
            if error_code in (
                _WIN_ERROR_NO_MORE_FILES,
                _WIN_ERROR_HANDLE_EOF,
                _WIN_ERROR_NO_MORE_ITEMS,
            ):
                return
            raise _windows_os_error("handle-relative directory enumeration", error_code)

        base = ctypes.addressof(buffer)
        offset = 0
        while True:
            if offset + _WIN_DIRECTORY_RECORD_HEADER_SIZE > _WIN_DIRECTORY_BUFFER_SIZE:
                raise OSError(errno.EIO, "invalid native directory record bounds")
            next_offset = int.from_bytes(
                ctypes.string_at(base + offset, 4), "little", signed=False
            )
            file_size = int.from_bytes(
                ctypes.string_at(base + offset + 40, 8), "little", signed=True
            )
            attributes = int.from_bytes(
                ctypes.string_at(base + offset + 56, 4), "little", signed=False
            )
            name_length = int.from_bytes(
                ctypes.string_at(base + offset + 60, 4), "little", signed=False
            )
            reparse_tag = int.from_bytes(
                ctypes.string_at(base + offset + 68, 4), "little", signed=False
            )
            name_end = offset + _WIN_DIRECTORY_RECORD_NAME_OFFSET + name_length
            if (
                name_length <= 0
                or name_length % 2
                or name_end > _WIN_DIRECTORY_BUFFER_SIZE
                or file_size < 0
            ):
                raise OSError(errno.EIO, "invalid native directory entry")
            name = ctypes.string_at(
                base + offset + _WIN_DIRECTORY_RECORD_NAME_OFFSET, name_length
            ).decode("utf-16-le", errors="strict")
            if (
                name in {".", ".."}
                or "\x00" in name
                or "/" in name
                or "\\" in name
            ):
                raise OSError(errno.EPERM, "unexpected native directory name")
            file_id = ctypes.string_at(base + offset + 72, 16).hex()
            is_directory = bool(attributes & _WIN_FILE_ATTRIBUTE_DIRECTORY)
            is_reparse = bool(
                attributes & _WIN_FILE_ATTRIBUTE_REPARSE_POINT or reparse_tag
            )
            is_device = bool(attributes & _WIN_FILE_ATTRIBUTE_DEVICE)
            yield SecureDirectoryEntry(
                name=name,
                identity=f"{volume_id:x}:{file_id}:{volume_id:x}",
                volume_id=volume_id,
                size=file_size,
                is_directory=is_directory,
                is_reparse_point=is_reparse,
                is_device=is_device,
            )
            if next_offset == 0:
                break
            if (
                next_offset < _WIN_DIRECTORY_RECORD_HEADER_SIZE
                or next_offset % 8
                or offset + next_offset >= _WIN_DIRECTORY_BUFFER_SIZE
            ):
                raise OSError(errno.EIO, "invalid native directory entry offset")
            offset += next_offset


def read_secure_file_handle(
    handle: int, maximum_bytes: int
) -> tuple[bytes, SecureHandleInfo]:
    """Read a pinned Windows file only if identity, type, size and stability hold."""
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "native handle reading is Windows-only")
    kernel, _ = _windows_api()
    before = secure_handle_info(handle)
    if (
        before.is_directory
        or before.is_reparse_point
        or before.is_device
        or before.delete_pending
        or before.size < 0
        or before.size > maximum_bytes
    ):
        raise OSError(errno.EPERM, "file metadata violates retrieval policy")
    chunks: list[bytes] = []
    remaining = before.size
    while remaining:
        amount = min(65536, remaining)
        buffer = ctypes.create_string_buffer(amount)
        read_count = ctypes.c_uint32()
        if not kernel.ReadFile(
            ctypes.c_void_p(handle),
            ctypes.byref(buffer),
            amount,
            ctypes.byref(read_count),
            None,
        ):
            raise _windows_os_error("bounded file read")
        if read_count.value == 0 or read_count.value > amount:
            raise OSError(errno.EIO, "file read ended before the recorded size")
        chunks.append(ctypes.string_at(ctypes.addressof(buffer), read_count.value))
        remaining -= read_count.value
    content = b"".join(chunks)
    after = secure_handle_info(handle)
    if (
        before.identity != after.identity
        or before.volume_id != after.volume_id
        or before.size != after.size
        or after.is_directory
        or after.is_reparse_point
        or after.is_device
        or after.delete_pending
        or len(content) != after.size
    ):
        raise OSError(errno.EPERM, "file identity or size changed during retrieval")
    return content, after


@lru_cache(maxsize=1)
def _windows_secure_backend_supported() -> bool:
    """Probe Windows handle identity, relative-open, and enumeration APIs."""
    if os.name != "nt":
        return False
    handle = -1
    child = -1
    try:
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        drive = windir.drive or os.environ.get("SystemDrive", "C:")
        handle = _windows_open_drive_root(drive)
        root_info = secure_handle_info(handle)
        if not root_info.is_directory or root_info.is_reparse_point:
            return False
        # Probe a real relative directory open under a pinned handle. The
        # Windows directory is expected to exist on the system volume.
        parts = windir.parts[1:]
        if parts:
            child = _windows_open_relative(handle, parts[0], directory=True)
            child_info = secure_handle_info(child)
            if (
                not child_info.is_directory
                or child_info.is_reparse_point
                or child_info.is_device
                or child_info.delete_pending
                or child_info.volume_id != root_info.volume_id
            ):
                return False
            kernel, _ = _windows_api()
            buffer = ctypes.create_string_buffer(_WIN_DIRECTORY_BUFFER_SIZE)
            ok = kernel.GetFileInformationByHandleEx(
                ctypes.c_void_p(child),
                _WIN_FILE_ID_EXTD_DIRECTORY_RESTART_INFO,
                ctypes.byref(buffer),
                ctypes.sizeof(buffer),
            )
            if not ok and ctypes.get_last_error() not in (
                _WIN_ERROR_NO_MORE_FILES,
                _WIN_ERROR_HANDLE_EOF,
                _WIN_ERROR_NO_MORE_ITEMS,
            ):
                return False
        return True
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False
    finally:
        if child >= 0:
            try:
                close_directory_descriptor(child)
            except OSError:
                pass
        if handle >= 0:
            try:
                close_directory_descriptor(handle)
            except OSError:
                pass


def _openat2_syscall_number() -> int | None:
    """Return the openat2 syscall number only for known Linux architectures."""
    if not sys.platform.startswith("linux") or not hasattr(os, "uname"):
        return None
    machine = os.uname().machine.casefold()
    if machine in {
        "x86_64",
        "amd64",
        "i386",
        "i486",
        "i586",
        "i686",
        "aarch64",
        "armv7l",
        "ppc64",
        "ppc64le",
        "s390x",
        "riscv64",
        "loongarch64",
    }:
        return 437
    return None


def _openat2(directory_fd: int, path: str, *, flags: int, resolve: int) -> int:
    """Open a relative path atomically under Linux openat2 resolution rules."""
    syscall_number = _openat2_syscall_number()
    if syscall_number is None:
        raise OSError(errno.ENOTSUP, "openat2 is unavailable on this platform")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        syscall = libc.syscall
        syscall.restype = ctypes.c_long
        request = _OpenHow(flags=flags, mode=0, resolve=resolve)
        ctypes.set_errno(0)
        result = syscall(
            ctypes.c_long(syscall_number),
            ctypes.c_int(directory_fd),
            ctypes.c_char_p(os.fsencode(path)),
            ctypes.byref(request),
            ctypes.c_size_t(ctypes.sizeof(request)),
        )
        if result < 0:
            error_code = ctypes.get_errno()
            raise OSError(error_code, os.strerror(error_code), path)
        return int(result)
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        raise


@lru_cache(maxsize=1)
def _openat2_supported() -> bool:
    """Probe the exact no-link, beneath, no-mount-crossing resolution contract."""
    if _openat2_syscall_number() is None or not hasattr(os, "O_DIRECTORY"):
        return False
    descriptor = -1
    probe = -1
    try:
        descriptor = os.open(
            "/",
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
        )
        probe = _openat2(
            descriptor,
            ".",
            flags=os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
            resolve=_OPENAT2_RESOLVE_SAFE,
        )
        return stat.S_ISDIR(os.fstat(probe).st_mode)
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if probe >= 0:
            os.close(probe)
        if descriptor >= 0:
            os.close(descriptor)


def open_directory_at(directory_fd: int, name: str) -> int:
    """Open one child directory without links, escapes, or mount crossings."""
    if os.name == "nt":
        child = _windows_open_relative(directory_fd, name, directory=True)
        try:
            parent_info = secure_handle_info(directory_fd)
            child_info = secure_handle_info(child)
            if (
                not child_info.is_directory
                or child_info.is_reparse_point
                or child_info.is_device
                or child_info.delete_pending
                or child_info.volume_id != parent_info.volume_id
            ):
                raise OSError(errno.EPERM, "child directory violated the local-handle policy")
            return child
        except Exception:
            close_directory_descriptor(child)
            raise
    if not _openat2_supported():
        raise OSError(errno.ENOTSUP, "safe descriptor-relative open is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    return _openat2(directory_fd, name, flags=flags, resolve=_OPENAT2_RESOLVE_SAFE)


def open_regular_file_at(directory_fd: int, name: str, flags: int) -> int:
    """Open a pinned regular file without invoking special-file open behavior.

    First acquire an O_PATH descriptor using openat2. Only after fstat confirms
    a regular file do we open that pinned object through procfs, not through the
    attacker-mutable directory entry. If procfs or O_PATH is unavailable, fail
    closed instead of falling back to a pathname-based read open.
    """
    if os.name == "nt":
        opened = _windows_open_relative(directory_fd, name, directory=False)
        try:
            info = secure_handle_info(opened)
            if (
                info.is_directory
                or info.is_reparse_point
                or info.is_device
                or info.delete_pending
            ):
                raise OSError(errno.EPERM, "candidate is not a permitted regular file")
            return opened
        except Exception:
            close_directory_descriptor(opened)
            raise
    if not _openat2_supported() or not hasattr(os, "O_PATH"):
        raise OSError(errno.ENOTSUP, "safe descriptor-relative open is unavailable")
    pinned = _openat2(
        directory_fd,
        name,
        flags=os.O_PATH | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        resolve=_OPENAT2_RESOLVE_SAFE,
    )
    try:
        pinned_info = os.fstat(pinned)
        if not stat.S_ISREG(pinned_info.st_mode):
            raise OSError(errno.EPERM, "candidate is not a regular file", name)
        readable_flags = flags & ~getattr(os, "O_NOFOLLOW", 0)
        readable = os.open(f"/proc/self/fd/{pinned}", readable_flags)
        try:
            readable_info = os.fstat(readable)
            if (
                not stat.S_ISREG(readable_info.st_mode)
                or readable_info.st_dev != pinned_info.st_dev
                or readable_info.st_ino != pinned_info.st_ino
                or descriptor_mount_id(readable) != descriptor_mount_id(pinned)
            ):
                raise OSError(errno.EPERM, "pinned file identity changed", name)
            result = readable
            readable = -1
            return result
        finally:
            if readable >= 0:
                os.close(readable)
    finally:
        os.close(pinned)


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
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\")
            return drive_type not in (2, 3)
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
    """Whether the platform exposes the pinned-handle primitives retrieval needs."""
    if os.name == "nt":
        return _windows_secure_backend_supported()
    if not sys.platform.startswith("linux"):
        return False
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    supports_fd = getattr(os, "supports_fd", set())
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    return bool(
        _linux_mount_table() is not None
        and _openat2_supported()
        and getattr(os, "open", None) in supports_dir_fd
        and getattr(os, "stat", None) in supports_dir_fd
        and getattr(os, "stat", None) in supports_follow_symlinks
        and getattr(os, "scandir", None) in supports_fd
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
    )


def secure_directory_open_flags() -> int:
    """POSIX flags required to open a directory without following a link."""
    if not sys.platform.startswith("linux") or not secure_directory_traversal_supported():
        raise OSError(errno.ENOTSUP, "secure directory traversal is unavailable")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def open_directory_descriptor(path: Path) -> int:
    """Open an absolute directory without following links; caller owns the handle."""
    supplied = Path(os.fspath(path))
    if not supplied.is_absolute() or ".." in supplied.parts:
        raise OSError(errno.EINVAL, "directory path must be absolute and normalized")
    absolute = Path(os.path.abspath(os.fspath(supplied)))
    if os.name == "nt":
        return _windows_open_directory_path(absolute)
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
    """Return Linux mount ID or Windows volume identity for an opened object."""
    if os.name == "nt":
        try:
            return secure_handle_info(descriptor).volume_id
        except (OSError, RuntimeError, ValueError):
            return None
    if not sys.platform.startswith("linux"):
        return None
    try:
        lines = (
            Path(f"/proc/self/fdinfo/{descriptor}")
            .read_text(encoding="ascii")
            .splitlines()
        )
        for line in lines:
            name, separator, value = line.partition(":")
            if separator and name == "mnt_id":
                return int(value.strip())
    except (OSError, UnicodeError, ValueError):
        return None
    return None


def directory_identity_from_descriptor(descriptor: int) -> str | None:
    """Bind an approved directory handle to stable filesystem/object identity."""
    if os.name == "nt":
        try:
            info = secure_handle_info(descriptor)
        except (OSError, RuntimeError, ValueError):
            return None
        if (
            not info.is_directory
            or info.is_reparse_point
            or info.is_device
            or info.delete_pending
        ):
            return None
        return info.identity
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
            close_directory_descriptor(descriptor)
        refresh_mount_table()
        if identity is None or is_network_path(supplied):
            return None
        return identity
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _windows_open_directory_path(path: Path) -> int:
    """Open a Windows absolute directory component-by-component from a pinned drive."""
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows directory opens are unavailable")
    supplied = Path(os.fspath(path))
    if (
        not supplied.is_absolute()
        or not supplied.drive
        or ".." in supplied.parts
        or is_network_path(supplied)
    ):
        raise OSError(errno.EPERM, "directory path is not a permitted local absolute path")

    descriptor = _windows_open_drive_root(supplied.drive)
    current_info = secure_handle_info(descriptor)
    try:
        for component in supplied.parts[1:]:
            next_descriptor = _windows_open_relative(
                descriptor, component, directory=True
            )
            next_info = secure_handle_info(next_descriptor)
            if (
                not next_info.is_directory
                or next_info.is_reparse_point
                or next_info.is_device
                or next_info.delete_pending
                or next_info.volume_id != current_info.volume_id
            ):
                close_directory_descriptor(next_descriptor)
                raise OSError(
                    errno.EPERM, "directory component crossed a volume or reparse point"
                )
            close_directory_descriptor(descriptor)
            descriptor = next_descriptor
            current_info = next_info
        return descriptor
    except Exception:
        close_directory_descriptor(descriptor)
        raise


def normalized_path_key(path: Path) -> str:
    """Return a normalized absolute spelling without resolving links."""
    return os.path.normcase(os.path.abspath(os.fspath(path)))

"""Bounded, offline retrieval from explicitly authorized local roots.

Traversal requires descriptor-relative, no-follow filesystem primitives. On
platforms that cannot provide them, retrieval refuses to read files rather than
fall back to pathname-based checks followed by unsafe opens.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from fastapi import APIRouter, Request

from rop import database as database_module
from rop.api.origin import enforce_local_origin
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.retrieval import (
    RetrievalMatch,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from rop.services.local_paths import (
    contains_link_or_junction,
    descriptor_mount_id as _descriptor_mount_id,
    directory_identity_from_descriptor as _identity_from_descriptor,
    is_junction as _is_junction,
    is_network_path as _is_network_path,
    local_directory_identity,
    normalized_path_key as _path_key,
    open_directory_at,
    open_directory_descriptor,
    open_regular_file_at,
    refresh_mount_table,
    secure_directory_traversal_supported,
)

router = APIRouter(prefix="/api/assistant/retrieval", tags=["assistant-retrieval"])
_REPOSITORY = AssistantWorkspaceRepository()
_ALLOWED_SUFFIXES = frozenset({".txt", ".md", ".json", ".csv"})
_MAX_FILE_BYTES = 1_000_000
_MAX_BYTES_PER_REQUEST = 20_000_000
_MAX_FILES_PER_REQUEST = 1_000
_MAX_ENTRIES_PER_REQUEST = 10_000
_MAX_DIRECTORIES_PER_ROOT = 250


def _safe_root(raw_path: str) -> Path | None:
    """Validate a stored, normalized root spelling without resolving it."""
    try:
        supplied = Path(raw_path)
        if (
            not supplied.is_absolute()
            or ".." in supplied.parts
            or str(supplied) != os.path.abspath(raw_path)
            or _is_network_path(supplied)
            or contains_link_or_junction(supplied)
        ):
            return None
        return supplied
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _after_root_validation(root: Path) -> None:
    """Deterministic race-test seam; production intentionally does nothing."""


def _before_candidate_open(path: Path, *, directory: bool) -> None:
    """Deterministic race-test seam just before descriptor-relative open."""


def _same_object(first: os.stat_result, second: os.stat_result) -> bool:
    """Compare an observed directory entry with the object actually opened."""
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _root_spec(
    item: str | tuple[str, str | None],
) -> tuple[str, str | None]:
    """Accept persisted path/identity pairs or capture identity for direct callers."""
    if isinstance(item, tuple):
        path, identity = item
        return path, identity
    path = item
    try:
        identity = local_directory_identity(Path(path))
    except (OSError, RuntimeError, TypeError, ValueError):
        identity = None
    return path, identity


def search_roots(
    root_paths: list[str | tuple[str, str | None]], query: str, limit: int
) -> tuple[list[RetrievalMatch], int, int]:
    """Search bounded local roots through pinned directory descriptors only."""
    if not secure_directory_traversal_supported():
        return [], 0, len(root_paths)

    refresh_mount_table()
    needle = query.casefold()
    matches: list[RetrievalMatch] = []
    files_examined = 0
    skipped_files = 0
    entries_examined = 0
    bytes_read = 0
    root_paths_seen: set[str] = set()
    stop = False
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )

    for root_spec in root_paths:
        if stop:
            break
        raw_root, approved_identity = _root_spec(root_spec)
        root = _safe_root(raw_root)
        if root is None or not approved_identity:
            skipped_files += 1
            continue
        root_key = _path_key(root)
        if root_key in root_paths_seen:
            continue
        root_paths_seen.add(root_key)

        # The hook deliberately sits after lexical policy checks. Opening the
        # path component-by-component below must still catch a race at this seam.
        _after_root_validation(root)
        try:
            root_fd = open_directory_descriptor(root)
            root_info = os.fstat(root_fd)
            opened_identity = _identity_from_descriptor(root_fd)
            root_mount_id = _descriptor_mount_id(root_fd)
            if (
                opened_identity is None
                or opened_identity != approved_identity
                or root_mount_id is None
                or _is_network_path(root)
            ):
                os.close(root_fd)
                skipped_files += 1
                continue
            root_device = root_info.st_dev
        except (OSError, RuntimeError, ValueError):
            skipped_files += 1
            continue

        pending: list[tuple[Path, int]] = [(root, root_fd)]
        directories_seen = 0
        try:
            while pending and not stop:
                current, current_fd = pending.pop()
                try:
                    if directories_seen >= _MAX_DIRECTORIES_PER_ROOT:
                        skipped_files += 1
                        stop = True
                        continue
                    directories_seen += 1

                    refresh_mount_table()
                    if _is_network_path(current):
                        skipped_files += 1
                        continue

                    names: list[str] = []
                    try:
                        with os.scandir(current_fd) as iterator:
                            for entry in iterator:
                                if entries_examined >= _MAX_ENTRIES_PER_REQUEST:
                                    skipped_files += 1
                                    stop = True
                                    break
                                entries_examined += 1
                                names.append(entry.name)
                    except OSError:
                        skipped_files += 1
                        continue

                    child_directories: list[tuple[Path, int]] = []
                    for name in sorted(names):
                        candidate = current / name
                        try:
                            refresh_mount_table()
                            if _is_network_path(candidate):
                                skipped_files += 1
                                continue
                            entry_info = os.stat(
                                name, dir_fd=current_fd, follow_symlinks=False
                            )
                        except (OSError, RuntimeError, ValueError):
                            skipped_files += 1
                            continue

                        if stat.S_ISLNK(entry_info.st_mode) or _is_junction(candidate):
                            skipped_files += 1
                            continue

                        if stat.S_ISDIR(entry_info.st_mode):
                            if entry_info.st_dev != root_device:
                                skipped_files += 1
                                continue
                            queued_directories = (
                                directories_seen + len(pending) + len(child_directories)
                            )
                            if queued_directories >= _MAX_DIRECTORIES_PER_ROOT:
                                skipped_files += 1
                                continue
                            _before_candidate_open(candidate, directory=True)
                            try:
                                refresh_mount_table()
                                if _is_network_path(candidate):
                                    skipped_files += 1
                                    continue
                                child_fd = open_directory_at(current_fd, name)
                                child_info = os.fstat(child_fd)
                                if (
                                    not stat.S_ISDIR(child_info.st_mode)
                                    or not _same_object(entry_info, child_info)
                                    or child_info.st_dev != root_device
                                    or _descriptor_mount_id(child_fd) != root_mount_id
                                    or _is_network_path(candidate)
                                ):
                                    os.close(child_fd)
                                    skipped_files += 1
                                    continue
                            except (OSError, RuntimeError, ValueError):
                                skipped_files += 1
                                continue
                            child_directories.append((candidate, child_fd))
                            continue

                        if not stat.S_ISREG(entry_info.st_mode):
                            continue
                        if candidate.suffix.casefold() not in _ALLOWED_SUFFIXES:
                            continue
                        if files_examined >= _MAX_FILES_PER_REQUEST:
                            skipped_files += 1
                            stop = True
                            break
                        files_examined += 1

                        remaining_bytes = _MAX_BYTES_PER_REQUEST - bytes_read
                        if remaining_bytes <= 0:
                            skipped_files += 1
                            stop = True
                            break
                        read_limit = min(_MAX_FILE_BYTES, remaining_bytes)
                        if (
                            entry_info.st_dev != root_device
                            or entry_info.st_size > read_limit
                        ):
                            skipped_files += 1
                            continue

                        _before_candidate_open(candidate, directory=False)
                        try:
                            refresh_mount_table()
                            if _is_network_path(candidate):
                                skipped_files += 1
                                continue
                            descriptor = open_regular_file_at(
                                current_fd, name, file_flags
                            )
                            with os.fdopen(descriptor, "rb") as stream:
                                opened_info = os.fstat(stream.fileno())
                                if (
                                    not stat.S_ISREG(opened_info.st_mode)
                                    or not _same_object(entry_info, opened_info)
                                    or opened_info.st_dev != root_device
                                    or _descriptor_mount_id(stream.fileno()) != root_mount_id
                                    or opened_info.st_size > read_limit
                                    or opened_info.st_size != entry_info.st_size
                                ):
                                    skipped_files += 1
                                    continue
                                content_bytes = stream.read(read_limit)
                                bytes_read += len(content_bytes)
                                final_info = os.fstat(stream.fileno())
                                if (
                                    not stat.S_ISREG(final_info.st_mode)
                                    or not _same_object(opened_info, final_info)
                                    or final_info.st_dev != root_device
                                    or _descriptor_mount_id(stream.fileno()) != root_mount_id
                                    or final_info.st_size > read_limit
                                    or len(content_bytes) != final_info.st_size
                                ):
                                    skipped_files += 1
                                    continue
                            content = content_bytes.decode("utf-8")
                        except (OSError, UnicodeError, RuntimeError, ValueError):
                            skipped_files += 1
                            continue

                        index = content.casefold().find(needle)
                        if index < 0:
                            continue
                        start = max(0, index - 120)
                        end = min(len(content), index + len(query) + 240)
                        snippet = " ".join(content[start:end].split())[:500]
                        matches.append(
                            RetrievalMatch(path=str(candidate), snippet=snippet)
                        )
                        if len(matches) >= limit:
                            stop = True
                            break

                    # Preserve deterministic depth-first order while retaining
                    # the already-opened descriptors for each approved child.
                    pending.extend(reversed(child_directories))
                    if stop:
                        for _, child_fd in child_directories:
                            if any(fd == child_fd for _, fd in pending):
                                continue
                            try:
                                os.close(child_fd)
                            except OSError:
                                pass
                finally:
                    os.close(current_fd)
        finally:
            for _, descriptor in pending:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    return matches, files_examined, skipped_files


@router.post("/search", response_model=RetrievalSearchResponse)
def search_local_files(
    body: RetrievalSearchRequest, http_request: Request
) -> RetrievalSearchResponse:
    """Search only persistently authorized folders using local bounded reads."""
    enforce_local_origin(http_request)
    session = database_module.SessionLocal()
    try:
        roots = _REPOSITORY.list_roots(session)
        root_specs = [(root.path, root.root_identity) for root in roots]
    finally:
        session.close()

    matches, files_examined, skipped_files = search_roots(
        root_specs, body.query, body.limit
    )
    return RetrievalSearchResponse(
        query=body.query,
        matches=matches,
        files_examined=files_examined,
        skipped_files=skipped_files,
    )


__all__ = ["router", "search_roots"]

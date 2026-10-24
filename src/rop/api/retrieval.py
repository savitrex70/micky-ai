"""Bounded, offline retrieval from explicitly authorized local roots."""

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
from rop.services.local_paths import is_junction as _is_junction
from rop.services.local_paths import is_network_path as _is_network_path
from rop.services.local_paths import normalized_path_key as _path_key
from rop.services.local_paths import refresh_mount_table

router = APIRouter(prefix="/api/assistant/retrieval", tags=["assistant-retrieval"])
_REPOSITORY = AssistantWorkspaceRepository()
_ALLOWED_SUFFIXES = frozenset({".txt", ".md", ".json", ".csv"})
_MAX_FILE_BYTES = 1_000_000
_MAX_BYTES_PER_REQUEST = 20_000_000
_MAX_FILES_PER_REQUEST = 1_000
_MAX_ENTRIES_PER_REQUEST = 10_000
_MAX_DIRECTORIES_PER_ROOT = 250


def _safe_root(raw_path: str) -> Path | None:
    """Reject a substituted path instead of authorizing its newly resolved target."""
    try:
        supplied = Path(raw_path).expanduser()
        if (
            _is_network_path(supplied)
            or supplied.is_symlink()
            or _is_junction(supplied)
        ):
            return None
        root = supplied.resolve(strict=True)
        if _is_network_path(root) or not root.is_dir():
            return None
        # Roots are stored in resolved form at authorization time. If the
        # same spelling now resolves somewhere else, a link/junction or
        # ancestor substitution occurred; do not silently authorize its target.
        if _path_key(supplied) != _path_key(root):
            return None
        return root
    except (OSError, RuntimeError, ValueError):
        return None


def _contained_local_path(
    candidate: Path, root: Path, root_device: int, *, directory: bool
) -> Path | None:
    """Resolve and validate one candidate against the approved local root."""
    try:
        if candidate.is_symlink() or _is_junction(candidate):
            return None
        resolved = candidate.resolve(strict=True)
        if (
            _path_key(candidate) != _path_key(resolved)
            or not resolved.is_relative_to(root)
            or _is_network_path(resolved)
        ):
            return None
        info = resolved.stat()
        if info.st_dev != root_device:
            return None
        if directory:
            return resolved if stat.S_ISDIR(info.st_mode) else None
        return resolved if stat.S_ISREG(info.st_mode) else None
    except (OSError, RuntimeError, ValueError):
        return None


def search_roots(
    root_paths: list[str], query: str, limit: int
) -> tuple[list[RetrievalMatch], int, int]:
    """Search bounded local directories without following links or crossing devices."""
    refresh_mount_table()
    needle = query.casefold()
    matches: list[RetrievalMatch] = []
    files_examined = 0
    skipped_files = 0
    entries_examined = 0
    bytes_read = 0
    root_paths_seen: set[str] = set()
    stop = False

    for raw_root in root_paths:
        if stop:
            break
        root = _safe_root(raw_root)
        if root is None:
            skipped_files += 1
            continue
        root_key = _path_key(root)
        if root_key in root_paths_seen:
            continue
        root_paths_seen.add(root_key)
        try:
            root_info = root.stat()
            if not stat.S_ISDIR(root_info.st_mode) or _is_network_path(root):
                skipped_files += 1
                continue
            root_device = root_info.st_dev
        except OSError:
            skipped_files += 1
            continue

        pending: list[Path] = [root]
        directories_seen = 0
        while pending and not stop:
            if directories_seen >= _MAX_DIRECTORIES_PER_ROOT:
                skipped_files += 1
                break
            current = pending.pop()
            directories_seen += 1
            current = _contained_local_path(current, root, root_device, directory=True)
            if current is None:
                skipped_files += 1
                continue

            entries = []
            try:
                # scandir is consumed only up to the request ceiling; an
                # unbounded os.walk list/sort could exhaust memory before
                # the directory count limit had any effect.
                with os.scandir(current) as iterator:
                    for entry in iterator:
                        if entries_examined >= _MAX_ENTRIES_PER_REQUEST:
                            skipped_files += 1
                            stop = True
                            break
                        entries_examined += 1
                        entries.append(entry)
            except OSError:
                skipped_files += 1
                continue

            child_directories: list[Path] = []
            for entry in sorted(entries, key=lambda item: item.name):
                candidate = Path(entry.path)
                try:
                    if entry.is_symlink() or _is_junction(candidate):
                        continue
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_regular_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    skipped_files += 1
                    continue

                if is_directory:
                    resolved_directory = _contained_local_path(
                        candidate, root, root_device, directory=True
                    )
                    if resolved_directory is None:
                        skipped_files += 1
                        continue
                    queued_directories = (
                        directories_seen + len(pending) + len(child_directories)
                    )
                    if queued_directories >= _MAX_DIRECTORIES_PER_ROOT:
                        skipped_files += 1
                        continue
                    child_directories.append(resolved_directory)
                    continue

                # Do not open FIFOs, sockets, device nodes, or other special
                # files even when their names use an allowed suffix.
                if not is_regular_file:
                    continue
                if candidate.suffix.casefold() not in _ALLOWED_SUFFIXES:
                    continue
                if files_examined >= _MAX_FILES_PER_REQUEST:
                    skipped_files += 1
                    stop = True
                    break
                files_examined += 1

                resolved_file = _contained_local_path(
                    candidate, root, root_device, directory=False
                )
                if resolved_file is None:
                    skipped_files += 1
                    continue

                remaining_bytes = _MAX_BYTES_PER_REQUEST - bytes_read
                if remaining_bytes <= 0:
                    skipped_files += 1
                    stop = True
                    break
                read_limit = min(_MAX_FILE_BYTES, remaining_bytes)

                try:
                    file_info = resolved_file.stat()
                    if (
                        not stat.S_ISREG(file_info.st_mode)
                        or file_info.st_dev != root_device
                        or file_info.st_size > read_limit
                    ):
                        skipped_files += 1
                        continue

                    # O_NOFOLLOW closes the final-component symlink race on
                    # platforms that support it. The descriptor size/type and
                    # post-read size are checked before content is decoded.
                    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(resolved_file, flags)
                    with os.fdopen(descriptor, "rb") as stream:
                        opened_info = os.fstat(stream.fileno())
                        if (
                            not stat.S_ISREG(opened_info.st_mode)
                            or opened_info.st_dev != root_device
                            or opened_info.st_size > read_limit
                        ):
                            skipped_files += 1
                            continue
                        content_bytes = stream.read(read_limit)
                        bytes_read += len(content_bytes)
                        final_info = os.fstat(stream.fileno())
                        if (
                            not stat.S_ISREG(final_info.st_mode)
                            or final_info.st_dev != root_device
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
                matches.append(RetrievalMatch(path=str(resolved_file), snippet=snippet))
                if len(matches) >= limit:
                    stop = True
                    break

            pending.extend(reversed(child_directories))

    return matches, files_examined, skipped_files


@router.post("/search", response_model=RetrievalSearchResponse)
def search_local_files(
    body: RetrievalSearchRequest, http_request: Request
) -> RetrievalSearchResponse:
    """Search only authorized folders using local bounded text reads."""
    enforce_local_origin(http_request)
    session = database_module.SessionLocal()
    try:
        roots = _REPOSITORY.list_roots(session)
        root_paths = [root.path for root in roots]
    finally:
        session.close()

    matches, files_examined, skipped_files = search_roots(
        root_paths, body.query, body.limit
    )
    return RetrievalSearchResponse(
        query=body.query,
        matches=matches,
        files_examined=files_examined,
        skipped_files=skipped_files,
    )


__all__ = ["router", "search_roots"]

"""Bounded, offline retrieval from explicitly authorized local roots."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from rop import database as database_module
from rop.api.origin import enforce_local_origin
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.retrieval import (
    RetrievalMatch,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)

router = APIRouter(prefix="/api/assistant/retrieval", tags=["assistant-retrieval"])
_REPOSITORY = AssistantWorkspaceRepository()
_ALLOWED_SUFFIXES = frozenset({".txt", ".md", ".json", ".csv"})
_MAX_FILE_BYTES = 1_000_000
_MAX_FILES_PER_REQUEST = 1_000
_MAX_DIRECTORIES_PER_ROOT = 250


def _is_network_path(path: Path) -> bool:
    """Reject UNC and mapped network-drive paths."""
    raw = str(path)
    if raw.startswith("\\\\") or raw.startswith("//"):
        return True
    if os.name == "nt" and path.drive:
        try:
            return ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == 4
        except (AttributeError, OSError, TypeError):
            return True
    return False


def _is_junction(path: Path) -> bool:
    method = getattr(path, "is_junction", None)
    return bool(method and method())


def _safe_root(raw_path: str) -> Path | None:
    try:
        supplied = Path(raw_path).expanduser()
        if _is_network_path(supplied):
            return None
        root = supplied.resolve(strict=True)
        if _is_network_path(root) or not root.is_dir():
            return None
        return root
    except (OSError, RuntimeError, ValueError):
        return None


def search_roots(
    root_paths: list[str], query: str, limit: int
) -> tuple[list[RetrievalMatch], int, int]:
    """Search bounded local directories without following links or crossing devices."""
    needle = query.casefold()
    matches: list[RetrievalMatch] = []
    files_examined = 0
    skipped_files = 0
    root_paths_seen: set[str] = set()

    for raw_root in root_paths:
        root = _safe_root(raw_root)
        if root is None:
            skipped_files += 1
            continue
        root_key = str(root)
        if root_key in root_paths_seen:
            continue
        root_paths_seen.add(root_key)
        try:
            root_device = root.stat().st_dev
        except OSError:
            skipped_files += 1
            continue

        directories_seen = 0
        stop = False
        for directory, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            directories_seen += 1
            if directories_seen > _MAX_DIRECTORIES_PER_ROOT:
                skipped_files += 1
                break

            base = Path(directory)
            safe_dirs: list[str] = []
            for name in sorted(dirnames):
                candidate = base / name
                if candidate.is_symlink() or _is_junction(candidate):
                    continue
                try:
                    resolved = candidate.resolve(strict=True)
                    info = resolved.stat()
                except (OSError, RuntimeError, ValueError):
                    continue
                if (
                    not resolved.is_relative_to(root)
                    or not resolved.is_dir()
                    or _is_network_path(resolved)
                    or info.st_dev != root_device
                ):
                    continue
                safe_dirs.append(name)
            dirnames[:] = safe_dirs

            for name in sorted(filenames):
                candidate = base / name
                if candidate.is_symlink() or _is_junction(candidate):
                    continue
                if candidate.suffix.casefold() not in _ALLOWED_SUFFIXES:
                    continue
                files_examined += 1
                if files_examined > _MAX_FILES_PER_REQUEST:
                    files_examined = _MAX_FILES_PER_REQUEST
                    skipped_files += 1
                    stop = True
                    break
                try:
                    resolved = candidate.resolve(strict=True)
                    info = resolved.stat()
                    if (
                        not resolved.is_relative_to(root)
                        or not resolved.is_file()
                        or _is_network_path(resolved)
                        or info.st_dev != root_device
                        or info.st_size > _MAX_FILE_BYTES
                    ):
                        skipped_files += 1
                        continue
                    content = resolved.read_text(encoding="utf-8")
                except (OSError, UnicodeError, RuntimeError, ValueError):
                    skipped_files += 1
                    continue

                index = content.casefold().find(needle)
                if index < 0:
                    continue
                start = max(0, index - 120)
                end = min(len(content), index + len(query) + 240)
                snippet = " ".join(content[start:end].split())[:500]
                matches.append(RetrievalMatch(path=str(resolved), snippet=snippet))
                if len(matches) >= limit:
                    stop = True
                    break
            if stop:
                break
        if stop:
            break
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

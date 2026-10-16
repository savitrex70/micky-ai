"""Serve the local Micky AI web interface.

The static assets live beside this module under ``static/`` so they ship
with the package. ``STATIC_DIR`` is resolved relative to this file, which
works for both an editable install (points at the source tree) and a
wheel/Docker install (needs the ``package-data`` entry in ``pyproject.toml``).
"""

from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

router = APIRouter(tags=["web"])


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the Micky AI browser interface."""
    return FileResponse(INDEX_FILE)


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """Return 204 for the browser's implicit favicon request.

    The interface has no favicon; a 204 keeps the log clean without
    shipping an unrelated binary asset.
    """
    return Response(status_code=204)


def mount_static(app) -> None:
    """Mount the static asset directory on the given FastAPI app."""
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

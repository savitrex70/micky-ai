"""Database-aware readiness endpoint alongside the existing liveness endpoint.

The liveness endpoint (``GET /health``) is defined in :mod:`rop.main` and
remains unchanged; it reports only that the process can answer requests. This
module adds ``GET /health/ready``, which additionally verifies that the
configured PostgreSQL database can execute a trivial read-only statement.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from rop.database import engine as database_engine

router = APIRouter(tags=["system"])


def check_database(engine: Engine) -> None:
    """Execute a trivial read-only statement against ``engine``.

    The connection is always released. Any SQLAlchemy error propagates so the
    caller can map it to a readiness response; the raised error text is never
    echoed to HTTP clients.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_database_check() -> Callable[[], None]:
    """FastAPI dependency returning a callable that probes the database."""

    def _check() -> None:
        check_database(database_engine)

    return _check


@router.get("/health/ready")
def health_ready(
    check: Callable[[], None] = Depends(get_database_check),
) -> JSONResponse:
    """Report database readiness without exposing connection details."""
    try:
        check()
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "database": "ok"},
    )

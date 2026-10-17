"""Loopback same-origin enforcement for state-changing confirmation requests.

The application is documented and started on loopback for a single local
user, so a state-changing confirmation request must come from the
configured local origin: the ``Origin`` header must match it, the ``Host``
header must name that origin, and the body must be JSON. A missing or
mismatched header is refused with a static, value-free body.

This is not a security boundary against code running as the same local
user, and it is not authentication. It defends the documented loopback
application against a cross-site page silently submitting a confirmation
request. The trusted origin is read from configuration, never derived from
an incoming request header, and no permissive CORS behaviour is added.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

from rop.config import get_settings

REFUSED_DETAIL = "This request was refused."
"""Value-free body for every origin, host, or content-type refusal."""


def _trusted_origin() -> str:
    return get_settings().assistant_local_origin.rstrip("/")


def enforce_local_origin(request: Request) -> None:
    """Refuse a state-changing request that is not from the local origin.

    Raises:
        HTTPException: 403 when the request lacks a JSON content type or an
            ``Origin``/``Host`` that matches the configured loopback origin.
    """
    expected = _trusted_origin()
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=REFUSED_DETAIL
        )

    expected_host = urlparse(expected).netloc
    host = request.headers.get("host")
    if host is None or host != expected_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=REFUSED_DETAIL
        )

    content_type = request.headers.get("content-type")
    if (
        content_type is None
        or content_type.split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=REFUSED_DETAIL
        )


async def require_local_origin(request: Request) -> None:
    """FastAPI dependency form of :func:`enforce_local_origin`."""
    enforce_local_origin(request)


__all__ = ["REFUSED_DETAIL", "enforce_local_origin", "require_local_origin"]

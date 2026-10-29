"""Loopback host/origin enforcement for the local assistant.

The ASGI middleware rejects every HTTP request whose Host authority does not
match the configured loopback origin. This includes private read APIs, static
assets, and the root page, so a DNS-rebinding hostname cannot use a sensitive
GET route as an alternate path around the write-side origin checks.

State-changing JSON requests additionally use enforce_local_origin, which
validates Origin, Host, and content type. These controls are not
authentication and do not protect against malicious code running as the same
local user. The configured trusted origin is never derived from an incoming
request header, and no permissive CORS behaviour is added.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse

from rop.config import get_settings

REFUSED_DETAIL = "This request was refused."
"""Value-free body for every origin, host, or content-type refusal."""


class TrustedLocalHostMiddleware:
    """Reject every HTTP request not addressed to the configured local origin.

    The comparison uses the configured authority (host plus port), not a value
    copied from request headers. TestClient's synthetic authority is accepted
    only when the application itself is configured for the testing environment.
    """

    def __init__(
        self,
        app,
        *,
        trusted_origin: str,
        allow_testserver: bool = False,
    ) -> None:
        self.app = app
        authority = urlparse(trusted_origin).netloc.casefold()
        if not authority:
            raise ValueError("trusted local origin has no authority")
        self.allowed_authorities = {authority}
        if allow_testserver:
            self.allowed_authorities.add("testserver")

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        host_values = [
            value.decode("latin-1").casefold()
            for name, value in scope.get("headers", ())
            if name.lower() == b"host"
        ]
        if len(host_values) != 1 or host_values[0] not in self.allowed_authorities:
            response = JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": REFUSED_DETAIL},
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


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


__all__ = [
    "REFUSED_DETAIL",
    "TrustedLocalHostMiddleware",
    "enforce_local_origin",
    "require_local_origin",
]

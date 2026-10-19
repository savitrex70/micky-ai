import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from rop.api.assistant import router as assistant_router
from rop.api.confirmation_records import router as confirmation_records_router
from rop.api.confirmations import router as confirmations_router
from rop.api.conversations import router as conversations_router
from rop.api.health import router as health_router
from rop.api.sessions import router as sessions_router
from rop.config import get_settings
from rop.logging_config import configure_logging
from rop.services.confirmation_recovery import recover_confirmation_state
from rop.web.routes import mount_static
from rop.web.routes import router as web_router

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    # Bounded, fail-closed crash recovery. Gated so test environments that
    # drive the confirmation clock with a fixed instant are not swept
    # against the real wall clock. Production leaves the setting enabled.
    if settings.startup_recovery_enabled:
        if not recover_confirmation_state():
            logger.warning(
                "Assistant confirmation startup recovery did not complete; "
                "it will be retried on the next startup."
            )
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(assistant_router)
app.include_router(confirmations_router)
app.include_router(confirmation_records_router)
app.include_router(conversations_router)
app.include_router(sessions_router)
app.include_router(web_router)
mount_static(app)


@app.exception_handler(RequestValidationError)
async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Strip user input from 422 bodies on the assistant endpoint.

    FastAPI's default 422 body includes the offending ``input`` value. For
    the assistant endpoint we never want to echo the user's message, so we
    return a value-free error body scoped strictly to ``/api/assistant/``.
    Every other path keeps FastAPI's default response.
    """
    if request.url.path.startswith("/api/assistant/"):
        safe_errors: list[dict[str, Any]] = []
        for err in exc.errors():
            safe_errors.append(
                {
                    "loc": list(err.get("loc", [])),
                    "msg": err.get("msg", "invalid"),
                    "type": err.get("type", "value_error"),
                }
            )
        return JSONResponse(status_code=422, content={"detail": safe_errors})
    return await request_validation_exception_handler(request, exc)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "healthy"}

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rop.api.sessions import router as sessions_router
from rop.config import get_settings
from rop.logging_config import configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(sessions_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "healthy"}

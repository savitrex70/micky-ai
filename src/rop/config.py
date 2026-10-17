from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "testing", "production"]
LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class SettingsError(RuntimeError):
    """Raised when required application configuration is missing or invalid.

    The message names the failing fields and never includes their values, so
    secrets from the environment or the ``.env`` file cannot leak through
    startup errors or logs.
    """


class Settings(BaseSettings):
    app_name: str = Field(min_length=1)
    environment: Environment
    log_level: LogLevel
    database_url: str = Field(min_length=1)
    assistant_local_origin: str = "http://127.0.0.1:8000"
    startup_recovery_enabled: bool = True
    """Run the bounded startup recovery sweep during application startup.

    Disabled in test environments so challenge expiry, which tests drive
    with a fixed clock, is not disturbed by a sweep that sees the real
    wall clock. Production deployments leave this enabled.
    """
    """The trusted loopback origin for state-changing confirmation requests.

    Read from configuration and validated as a loopback ``http`` origin, so
    it can never be pointed at a remote host through the environment or an
    incoming request. It is the origin the browser uses to load the local
    application.
    """

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use the postgresql+psycopg scheme")
        return value

    @field_validator("assistant_local_origin")
    @classmethod
    def validate_assistant_local_origin(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http":
            raise ValueError("assistant_local_origin must use the http scheme")
        if parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("assistant_local_origin must be a loopback origin")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("assistant_local_origin must be a bare origin")
        if parsed.username or parsed.password:
            raise ValueError("assistant_local_origin must not carry credentials")
        return value

    model_config = SettingsConfigDict(
        env_prefix="ROP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def _format_settings_error(error: ValidationError) -> SettingsError:
    """Translate a raw ``ValidationError`` into a value-free ``SettingsError``."""
    fields: list[str] = []
    for issue in error.errors():
        location = issue.get("loc") or ()
        name = ".".join(str(part) for part in location) if location else "unknown"
        if name not in fields:
            fields.append(name)
    if not fields:
        return SettingsError(
            "Invalid application configuration. "
            "Check the ROP_* environment variables or the .env file."
        )
    joined = ", ".join(fields)
    return SettingsError(
        f"Invalid application configuration for: {joined}. "
        "Check the corresponding ROP_* environment variables or the .env file."
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings.

    Raises:
        SettingsError: If required configuration is missing or invalid. The
            raised error names the failing fields but never includes values.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise _format_settings_error(exc) from None

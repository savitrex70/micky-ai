from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "testing", "production"]
LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    app_name: str = Field(min_length=1)
    environment: Environment
    log_level: LogLevel
    database_url: str = Field(min_length=1)

    # Task 057 LLM reasoning boundary. Both are optional at the
    # settings layer so existing environments need no change; the
    # Ollama provider raises MODEL_UNAVAILABLE cleanly if either is
    # absent when it is actually invoked. Env vars are
    # ROP_OLLAMA_BASE_URL and ROP_OLLAMA_REASONING_MODEL.
    ollama_base_url: str = Field(
        default="http://localhost:11434", min_length=1
    )
    ollama_reasoning_model: str | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use the postgresql+psycopg scheme")
        return value

    model_config = SettingsConfigDict(
        env_prefix="ROP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

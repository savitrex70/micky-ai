import pytest
from pydantic import ValidationError

from rop.config import Settings

VALID_SETTINGS = {
    "app_name": "Reasoning Operating Platform",
    "environment": "testing",
    "log_level": "INFO",
    "database_url": "postgresql+psycopg://rop:rop@localhost:5432/rop",
}


def test_settings_load_required_values(monkeypatch) -> None:
    monkeypatch.setenv("ROP_APP_NAME", "Test ROP")
    monkeypatch.setenv("ROP_ENVIRONMENT", "testing")
    monkeypatch.setenv("ROP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "ROP_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test"
    )

    settings = Settings()

    assert settings.app_name == "Test ROP"
    assert settings.environment == "testing"
    assert settings.log_level == "DEBUG"
    assert settings.database_url.endswith("/test")


def test_settings_load_dotenv_file(tmp_path, monkeypatch) -> None:
    for variable in (
        "ROP_APP_NAME",
        "ROP_ENVIRONMENT",
        "ROP_LOG_LEVEL",
        "ROP_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ROP_APP_NAME=Dotenv ROP",
                "ROP_ENVIRONMENT=development",
                "ROP_LOG_LEVEL=WARNING",
                "ROP_DATABASE_URL=postgresql+psycopg://rop:rop@localhost:5432/rop",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_name == "Dotenv ROP"
    assert settings.environment == "development"
    assert settings.log_level == "WARNING"


def test_settings_reject_missing_required_values(monkeypatch) -> None:
    for variable in (
        "ROP_APP_NAME",
        "ROP_ENVIRONMENT",
        "ROP_LOG_LEVEL",
        "ROP_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_invalid_environment() -> None:
    values = {**VALID_SETTINGS, "environment": "staging"}

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_settings_reject_non_postgresql_database_url() -> None:
    values = {**VALID_SETTINGS, "database_url": "sqlite:///rop.db"}

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)

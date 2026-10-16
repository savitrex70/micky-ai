import pytest
from pydantic import ValidationError

from rop.config import Settings, SettingsError, get_settings

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


def test_get_settings_raises_settings_error_for_invalid_config(monkeypatch) -> None:
    for variable in (
        "ROP_APP_NAME",
        "ROP_ENVIRONMENT",
        "ROP_LOG_LEVEL",
        "ROP_DATABASE_URL",
    ):
        monkeypatch.delenv(variable, raising=False)

    get_settings.cache_clear()
    try:
        with pytest.raises(SettingsError):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_get_settings_error_does_not_leak_secret_sentinel(monkeypatch) -> None:
    sentinel = "SENTINEL_PASSWORD_VALUE_4A7B"
    monkeypatch.setenv("ROP_APP_NAME", "Test")
    monkeypatch.setenv("ROP_ENVIRONMENT", "testing")
    monkeypatch.setenv("ROP_LOG_LEVEL", "INFO")
    monkeypatch.setenv(
        "ROP_DATABASE_URL",
        f"mysql+pymysql://user:{sentinel}@localhost:3306/rop",
    )

    get_settings.cache_clear()
    try:
        with pytest.raises(SettingsError) as excinfo:
            get_settings()
    finally:
        get_settings.cache_clear()

    message = str(excinfo.value)
    assert sentinel not in message
    assert "database_url" in message
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


def test_get_settings_error_names_only_invalid_fields(monkeypatch) -> None:
    sentinel = "ANOTHER_SENTINEL_5C2D"
    monkeypatch.setenv("ROP_APP_NAME", "Test")
    monkeypatch.setenv("ROP_ENVIRONMENT", "not-a-real-environment")
    monkeypatch.setenv("ROP_LOG_LEVEL", "INFO")
    monkeypatch.setenv(
        "ROP_DATABASE_URL",
        f"postgresql+psycopg://user:{sentinel}@localhost:5432/rop",
    )

    get_settings.cache_clear()
    try:
        with pytest.raises(SettingsError) as excinfo:
            get_settings()
    finally:
        get_settings.cache_clear()

    message = str(excinfo.value)
    assert sentinel not in message
    assert "environment" in message

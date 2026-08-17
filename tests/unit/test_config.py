import pytest


def test_load_settings_returns_typed_secret_configuration() -> None:
    from packages.common.config import load_settings

    settings = load_settings(
        {"DATABASE_URL": "postgresql+psycopg://user:private@db/app"}
    )

    assert settings.database_url.get_secret_value().endswith("@db/app")
    assert settings.log_level == "INFO"
    assert "private" not in repr(settings)


def test_missing_database_url_raises_readable_configuration_error() -> None:
    from packages.common.config import ConfigurationError, load_settings

    with pytest.raises(ConfigurationError, match="DATABASE_URL") as captured:
        load_settings({})

    assert "input_value" not in str(captured.value)


def test_invalid_log_level_error_does_not_expose_environment_values() -> None:
    from packages.common.config import ConfigurationError, load_settings

    database_secret = "postgresql+psycopg://user:do-not-print@db/app"
    rejected_level = "secret-debug-mode"
    with pytest.raises(ConfigurationError, match="LOG_LEVEL") as captured:
        load_settings({"DATABASE_URL": database_secret, "LOG_LEVEL": rejected_level})

    message = str(captured.value)
    assert database_secret not in message
    assert rejected_level not in message

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError


class ConfigurationError(RuntimeError):
    """Raised when environment configuration cannot be loaded safely."""


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    database_url: SecretStr
    log_level: LogLevel = "INFO"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if environ is None else environ
    values: dict[str, str] = {}
    if "DATABASE_URL" in source:
        values["database_url"] = source["DATABASE_URL"]
    if "LOG_LEVEL" in source:
        values["log_level"] = source["LOG_LEVEL"].upper()
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        messages = [
            f"{_environment_name(error['loc'])}: {error['msg']}" for error in errors
        ]
        message = "Invalid configuration: " + "; ".join(messages)
        raise ConfigurationError(message) from None


def _environment_name(location: tuple[str | int, ...]) -> str:
    names = {"database_url": "DATABASE_URL", "log_level": "LOG_LEVEL"}
    return names.get(str(location[0]), str(location[0]))

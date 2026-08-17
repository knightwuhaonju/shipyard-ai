"""Secret-safe structured logging utilities."""

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_SUFFIXES = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "database_url",
)

_OMITTED_FIELD_NAMES = frozenset(
    {
        "args",
        "body",
        "bodies",
        "exc_info",
        "exc_text",
        "header",
        "headers",
        "query",
        "queries",
        "stack_info",
    }
)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | (
    _OMITTED_FIELD_NAMES
)


def redact(value: object) -> object:
    """Recursively remove values associated with sensitive mapping keys."""
    if isinstance(value, BaseException):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "_")
    return any(normalized.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


class JsonFormatter(logging.Formatter):
    """Formats records as JSON without serializing exception details."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _safe_message(record),
        }
        payload.update(
            {
                key: redact(value)
                for key, value in record.__dict__.items()
                if key not in _STANDARD_RECORD_FIELDS and not _is_omitted_field(key)
            }
        )
        return json.dumps(payload, default=str)


def _is_omitted_field(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "_")
    return normalized in _OMITTED_FIELD_NAMES or normalized.startswith("customer")


def _safe_message(record: logging.LogRecord) -> str:
    if _contains_exception(record.msg) or _contains_exception(record.args):
        return record.msg if isinstance(record.msg, str) else REDACTED
    return record.getMessage()


def _contains_exception(value: object) -> bool:
    if isinstance(value, BaseException):
        return True
    if isinstance(value, Mapping):
        return any(_contains_exception(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_exception(item) for item in value)
    return False


def configure_logging(level: str) -> logging.Logger:
    """Configure the application logger with one secret-safe JSON handler."""
    logger = logging.getLogger("shipyard_ai")
    logger.setLevel(level.upper())
    logger.propagate = False
    has_json_handler = any(
        isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers
    )
    if not has_json_handler:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger

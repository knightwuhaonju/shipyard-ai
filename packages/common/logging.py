"""Secret-safe structured logging utilities."""

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

REDACTED = "[REDACTED]"
_UNSERIALIZABLE = "[UNSERIALIZABLE]"

_SENSITIVE_KEY_SUFFIXES = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "database_url",
    "credential",
    "credentials",
)

_CANONICAL_FIELDS = frozenset({"timestamp", "level", "logger", "message"})

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
_PROHIBITED_FIELD_TOKENS = frozenset(
    {"body", "bodies", "header", "headers", "query", "queries", "customer"}
)
_STANDARD_RECORD_FIELDS = (
    frozenset(logging.makeLogRecord({}).__dict__)
    | _OMITTED_FIELD_NAMES
    | _CANONICAL_FIELDS
)


def redact(value: object) -> object:
    """Recursively remove values associated with sensitive mapping keys."""
    if isinstance(value, BaseException):
        return REDACTED
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value


def _redact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: REDACTED if _is_sensitive_key(key) else redact(item)
        for key, item in value.items()
        if not _is_prohibited_field_name(key)
    }


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
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS
        }
        payload.update(_redact_mapping(extras))
        return json.dumps(payload, default=_safe_json_fallback)


def _safe_json_fallback(_value: object) -> str:
    return _UNSERIALIZABLE


def _is_prohibited_field_name(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "_")
    return (
        normalized in _OMITTED_FIELD_NAMES
        or normalized.startswith("customer")
        or bool(set(normalized.split("_")) & _PROHIBITED_FIELD_TOKENS)
    )


def _safe_message(record: logging.LogRecord) -> str:
    if record.args or _contains_exception(record.msg):
        return record.msg if isinstance(record.msg, str) else REDACTED
    return record.getMessage()


def _contains_exception(value: object) -> bool:
    if isinstance(value, BaseException):
        return True
    if isinstance(value, Mapping):
        return any(_contains_exception(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_exception(item) for item in value)
    return False


def configure_logging(level: str) -> logging.Logger:
    """Configure the application logger with one secret-safe JSON handler."""
    logger = logging.getLogger("shipyard_ai")
    logger.setLevel(level.upper())
    logger.propagate = False
    logging.getLogger("shipyard_ai.request").setLevel(logging.INFO)
    has_json_handler = any(
        isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers
    )
    if not has_json_handler:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger

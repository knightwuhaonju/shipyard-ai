import json
import logging
from collections import UserList
from collections.abc import Generator
from datetime import datetime

import pytest


@pytest.fixture
def restore_shipyard_logger() -> Generator[None]:
    logger = logging.getLogger("shipyard_ai")
    request_logger = logging.getLogger("shipyard_ai.request")
    handlers = list(logger.handlers)
    level = logger.level
    propagate = logger.propagate
    request_level = request_logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate
    request_logger.setLevel(request_level)


def test_redact_removes_nested_sensitive_values() -> None:
    from packages.common.logging import REDACTED, redact

    assert redact(
        {
            "DATABASE_URL": "db-secret",
            "nested": [
                {"api-key": "api-secret"},
                {"Authorization": "Bearer token", "safe": "kept"},
            ],
        }
    ) == {
        "DATABASE_URL": REDACTED,
        "nested": [
            {"api-key": REDACTED},
            {"Authorization": REDACTED, "safe": "kept"},
        ],
    }


def test_redact_removes_direct_credential_key_variants() -> None:
    from packages.common.logging import REDACTED, redact

    assert redact(
        {
            "credential": "direct-secret",
            "credentials": "plural-secret",
        }
    ) == {
        "credential": REDACTED,
        "credentials": REDACTED,
    }


def test_redact_removes_nested_normalized_credential_key_variants() -> None:
    from packages.common.logging import REDACTED, redact

    assert redact(
        {
            "context": {
                "service-credential": "nested-secret",
                "backup_credentials": "nested-plural-secret",
            }
        }
    ) == {
        "context": {
            "service-credential": REDACTED,
            "backup_credentials": REDACTED,
        }
    }


def test_redact_sanitizes_general_non_string_sequences() -> None:
    from packages.common.logging import REDACTED, redact

    assert redact(UserList([{"password": "sequence-secret"}])) == [
        {"password": REDACTED}
    ]


def test_json_formatter_redacts_structured_fields() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1, "request_completed", (), None
    )
    record.request_id = "request-123"
    record.context = {"password": "never-print", "ship_id": "ship-1"}
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "request_completed"
    assert payload["request_id"] == "request-123"
    assert payload["context"] == {
        "password": "[REDACTED]",
        "ship_id": "ship-1",
    }
    assert "never-print" not in json.dumps(payload)


def test_json_formatter_does_not_stringify_unknown_object_contents() -> None:
    from packages.common.logging import JsonFormatter

    class SecretBearingObject:
        def __str__(self) -> str:
            return "object-secret"

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1, "request_completed", (), None
    )
    record.context = SecretBearingObject()

    payload = json.loads(JsonFormatter().format(record))

    assert payload["context"] == "[UNSERIALIZABLE]"
    assert "object-secret" not in json.dumps(payload)


def test_json_formatter_preserves_canonical_envelope_on_extra_collisions() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1, "request_completed", (), None
    )
    record.timestamp = "attacker-timestamp"
    record.level = "attacker-level"
    record.logger = "attacker-logger"
    record.message = "attacker-message"

    payload = json.loads(JsonFormatter().format(record))

    assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None
    assert payload["level"] == "INFO"
    assert payload["logger"] == "shipyard_ai.request"
    assert payload["message"] == "request_completed"


def test_configure_logging_adds_only_one_json_handler(
    restore_shipyard_logger: None,
) -> None:
    from packages.common.logging import JsonFormatter, configure_logging

    logger = configure_logging("INFO")
    configure_logging("DEBUG")
    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler.formatter, JsonFormatter)
    ]
    assert len(handlers) == 1
    assert logger.level == logging.DEBUG


def test_json_formatter_omits_unsafe_fields_and_exception_messages() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1, "request_completed", (), None
    )
    record.headers = {"Authorization": "Bearer never-print"}
    record.query = "ship_name=never-print"
    record.body = {"ship_id": "never-print"}
    record.customer_record = {"name": "never-print"}
    record.failure = RuntimeError("never-print")

    rendered = JsonFormatter().format(record)

    assert "never-print" not in rendered
    assert "headers" not in rendered
    assert "query" not in rendered
    assert "body" not in rendered
    assert "customer_record" not in rendered


def test_json_formatter_does_not_interpolate_exception_arguments() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request",
        logging.ERROR,
        __file__,
        1,
        "request_failed: %s",
        (RuntimeError("never-print"),),
        None,
    )

    rendered = JsonFormatter().format(record)

    assert "never-print" not in rendered


def test_json_formatter_redacts_sensitive_direct_extra_fields() -> None:
    from packages.common.logging import REDACTED, JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1, "request_completed", (), None
    )
    record.authorization = "Bearer never-print"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["authorization"] == REDACTED
    assert "never-print" not in json.dumps(payload)


def test_json_formatter_omits_reserved_field_name_variants_recursively() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1, "request_completed", (), None
    )
    record.request_body = {"ship_id": "never-print"}
    record.query_params = "ship_id=never-print"
    record.context = {
        "body": {"ship_id": "never-print"},
        "request-headers": {"Authorization": "Bearer never-print"},
        "customer_data": {"name": "never-print"},
        "safe": "kept",
    }

    payload = json.loads(JsonFormatter().format(record))

    assert "request_body" not in payload
    assert "query_params" not in payload
    assert payload["context"] == {"safe": "kept"}
    assert "never-print" not in json.dumps(payload)


def test_json_formatter_does_not_interpolate_sensitive_message_arguments() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request",
        logging.INFO,
        __file__,
        1,
        "request_completed: %s",
        ({"authorization": "Bearer never-print"},),
        None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "request_completed: %s"
    assert "never-print" not in json.dumps(payload)

import logging
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.responses import StreamingResponse

from apps.api.main import create_app
from packages.common.config import LogLevel, Settings

TEST_SETTINGS = Settings(
    database_url=SecretStr("postgresql://test:test@localhost/test")
)


class CollectingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_application_startup_fails_when_required_config_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.main import create_app
    from packages.common.config import ConfigurationError

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        with TestClient(create_app()):
            pass


def test_health_returns_service_status() -> None:
    with TestClient(create_app(TEST_SETTINGS)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "shipyard-ai-api",
        "status": "ok",
    }


def test_health_emits_generated_request_id() -> None:
    with TestClient(create_app(TEST_SETTINGS)) as client:
        response = client.get("/health")

    assert UUID(response.headers["X-Request-ID"]).version == 4


def test_health_preserves_safe_inbound_request_id() -> None:
    with TestClient(create_app(TEST_SETTINGS)) as client:
        response = client.get("/health", headers={"X-Request-ID": "edge-123"})

    assert response.headers["X-Request-ID"] == "edge-123"


def test_health_replaces_unsafe_inbound_request_id() -> None:
    unsafe_id = "unsafe value with spaces"
    with TestClient(create_app(TEST_SETTINGS)) as client:
        response = client.get("/health", headers={"X-Request-ID": unsafe_id})

    emitted = response.headers["X-Request-ID"]
    assert emitted != unsafe_id
    assert UUID(emitted).version == 4


def test_health_logs_safe_request_completion() -> None:
    logger = logging.getLogger("shipyard_ai.request")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(create_app(TEST_SETTINGS)) as client:
            response = client.get(
                "/health?token=never-print",
                headers={"Authorization": "Bearer never-print"},
            )
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.getMessage() == "request_completed"
    assert getattr(record, "request_id") == response.headers["X-Request-ID"]
    assert getattr(record, "method") == "GET"
    assert getattr(record, "path") == "/health"
    assert getattr(record, "status_code") == 200
    assert getattr(record, "duration_ms") >= 0
    assert "never-print" not in repr(record.__dict__)
    assert "Authorization" not in record.__dict__


def test_failure_logs_safe_request_failure() -> None:
    application = create_app(TEST_SETTINGS)

    @application.get("/boom")
    def boom() -> None:
        raise RuntimeError("do-not-print")

    logger = logging.getLogger("shipyard_ai.request")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(application) as client:
            response = client.get("/boom")
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "do-not-print" not in response.text
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.getMessage() == "request_failed"
    assert getattr(record, "request_id") == response.headers["X-Request-ID"]
    assert getattr(record, "status_code") == 500
    assert getattr(record, "error_class") == "RuntimeError"
    assert "do-not-print" not in repr(record.__dict__)


@pytest.mark.parametrize(
    "log_level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
)
def test_request_audit_records_are_emitted_at_every_supported_log_level(
    log_level: LogLevel,
) -> None:
    settings = Settings(
        database_url=SecretStr("postgresql://test:test@localhost/test"),
        log_level=log_level,
    )
    application = create_app(settings)

    @application.get("/boom")
    def boom() -> None:
        raise RuntimeError("do-not-print")

    logger = logging.getLogger("shipyard_ai.request")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(application) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/boom").status_code == 500
    finally:
        logger.removeHandler(handler)

    assert [record.getMessage() for record in handler.records] == [
        "request_completed",
        "request_failed",
    ]


def test_streaming_failure_returns_sanitized_500_without_false_completion() -> None:
    application = create_app(TEST_SETTINGS)

    async def broken_stream() -> AsyncIterator[bytes]:
        if False:
            yield b"never-sent"
        raise RuntimeError("stream-do-not-print")

    @application.get("/stream/{ship_id}")
    def stream(ship_id: str) -> StreamingResponse:
        return StreamingResponse(broken_stream())

    logger = logging.getLogger("shipyard_ai.request")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(application) as client:
            response = client.get("/stream/customer-secret-123")
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert UUID(response.headers["X-Request-ID"]).version == 4
    assert [record.getMessage() for record in handler.records] == ["request_failed"]
    record = handler.records[0]
    assert getattr(record, "path") == "/stream/{ship_id}"
    assert getattr(record, "error_class") == "RuntimeError"
    assert "customer-secret-123" not in repr(record.__dict__)
    assert "stream-do-not-print" not in repr(record.__dict__)
    assert "stream-do-not-print" not in response.text


def test_request_log_uses_route_template_without_dynamic_path_value() -> None:
    application = create_app(TEST_SETTINGS)

    @application.get("/ships/{ship_id}")
    def ship_status(ship_id: str) -> dict[str, str]:
        return {"status": "ok"}

    secret_ship_id = "customer-secret-123"
    logger = logging.getLogger("shipyard_ai.request")
    handler = CollectingHandler()
    logger.addHandler(handler)
    try:
        with TestClient(application) as client:
            response = client.get(f"/ships/{secret_ship_id}")
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 200
    assert len(handler.records) == 1
    record = handler.records[0]
    assert getattr(record, "path") == "/ships/{ship_id}"
    assert secret_ship_id not in repr(record.__dict__)


def test_health_exposes_typed_response_contract() -> None:
    with TestClient(create_app(TEST_SETTINGS)) as client:
        openapi = client.get("/openapi.json").json()

    response_schema = openapi["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/HealthResponse"}
    assert openapi["paths"]["/health"]["get"]["responses"]["200"]["headers"] == {
        "X-Request-ID": {
            "description": "Request correlation identifier.",
            "schema": {"type": "string"},
        }
    }
    assert openapi["components"]["schemas"]["HealthResponse"] == {
        "properties": {
            "service": {
                "const": "shipyard-ai-api",
                "title": "Service",
                "type": "string",
            },
            "status": {"const": "ok", "title": "Status", "type": "string"},
        },
        "required": ["service", "status"],
        "title": "HealthResponse",
        "type": "object",
    }

import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from packages.common.config import Settings, load_settings
from packages.common.logging import configure_logging

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}", re.ASCII)
REQUEST_LOGGER = logging.getLogger("shipyard_ai.request")
UNMATCHED_ROUTE_TEMPLATE = "<unmatched>"


class HealthResponse(BaseModel):
    service: Literal["shipyard-ai-api"]
    status: Literal["ok"]


def _route_template(scope: Scope) -> str:
    route_path = getattr(scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) else UNMATCHED_ROUTE_TEMPLATE


class RequestLoggingMiddleware:
    """Correlate and safely log the complete lifecycle of each HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        inbound_request_id = Headers(scope=scope).get("X-Request-ID")
        request_id = (
            inbound_request_id
            if inbound_request_id is not None
            and REQUEST_ID_PATTERN.fullmatch(inbound_request_id)
            else str(uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id
        pending_start: Message | None = None
        response_started = False
        response_finished = False
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal pending_start, response_started, response_finished, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(raw=message["headers"])
                headers["X-Request-ID"] = request_id
                message["headers"] = headers.raw
                pending_start = message
                return
            if message["type"] == "http.response.body":
                if pending_start is not None:
                    await send(pending_start)
                    pending_start = None
                    response_started = True
                await send(message)
                if not message.get("more_body", False):
                    response_finished = True
                return
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            _log_request_failure(scope, request_id, started_at, exc)
            if not response_started:
                response = PlainTextResponse(
                    "Internal Server Error",
                    status_code=500,
                    headers={"X-Request-ID": request_id},
                )
                try:
                    await response(scope, receive, send)
                except Exception:
                    pass
            elif not response_finished:
                try:
                    await send(
                        {"type": "http.response.body", "body": b"", "more_body": False}
                    )
                except Exception:
                    pass
            return

        if pending_start is not None:
            await send(pending_start)
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            response_finished = True
        if response_finished:
            REQUEST_LOGGER.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": scope["method"],
                    "path": _route_template(scope),
                    "status_code": status_code,
                    "duration_ms": _duration_ms(started_at),
                },
            )


def _log_request_failure(
    scope: Scope,
    request_id: str,
    started_at: float,
    exc: Exception,
) -> None:
    REQUEST_LOGGER.warning(
        "request_failed",
        extra={
            "request_id": request_id,
            "method": scope["method"],
            "path": _route_template(scope),
            "status_code": 500,
            "duration_ms": _duration_ms(started_at),
            "error_class": type(exc).__name__,
        },
    )


def _duration_ms(started_at: float) -> int:
    return round(max(0, (time.perf_counter() - started_at) * 1000))


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings if settings is not None else load_settings()
        application.state.settings = resolved_settings
        configure_logging(resolved_settings.log_level)
        yield

    application = FastAPI(title="Shipyard AI API", lifespan=lifespan)
    application.add_middleware(RequestLoggingMiddleware)

    @application.get(
        "/health",
        responses={
            200: {
                "headers": {
                    "X-Request-ID": {
                        "description": "Request correlation identifier.",
                        "schema": {"type": "string"},
                    }
                }
            }
        },
    )
    def health() -> HealthResponse:
        return HealthResponse(service="shipyard-ai-api", status="ok")

    return application


app = create_app()

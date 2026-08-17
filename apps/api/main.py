import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

from packages.common.config import Settings, load_settings
from packages.common.logging import configure_logging

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}", re.ASCII)
REQUEST_LOGGER = logging.getLogger("shipyard_ai.request")


class HealthResponse(BaseModel):
    service: Literal["shipyard-ai-api"]
    status: Literal["ok"]

def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings if settings is not None else load_settings()
        application.state.settings = resolved_settings
        configure_logging(resolved_settings.log_level)
        yield

    application = FastAPI(title="Shipyard AI API", lifespan=lifespan)

    @application.exception_handler(Exception)
    async def internal_server_error(request: Request, _: Exception) -> Response:
        return PlainTextResponse(
            "Internal Server Error",
            status_code=500,
            headers={"X-Request-ID": request.state.request_id},
        )

    @application.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = time.perf_counter()
        inbound_request_id = request.headers.get("X-Request-ID")
        request_id = (
            inbound_request_id
            if inbound_request_id is not None
            and REQUEST_ID_PATTERN.fullmatch(inbound_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception as exc:
            REQUEST_LOGGER.warning(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(
                        max(0, (time.perf_counter() - started_at) * 1000)
                    ),
                    "error_class": type(exc).__name__,
                },
            )
            raise
        response.headers["X-Request-ID"] = request_id
        REQUEST_LOGGER.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(max(0, (time.perf_counter() - started_at) * 1000)),
            },
        )
        return response

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

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: Literal["shipyard-ai-api"]
    status: Literal["ok"]

app = FastAPI(title="Shipyard AI API")


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse(service="shipyard-ai-api", status="ok")

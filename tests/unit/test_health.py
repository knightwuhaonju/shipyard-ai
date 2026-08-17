from fastapi.testclient import TestClient

from apps.api.main import app


def test_health_returns_service_status() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "shipyard-ai-api",
        "status": "ok",
    }


def test_health_exposes_typed_response_contract() -> None:
    openapi = TestClient(app).get("/openapi.json").json()

    response_schema = openapi["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/HealthResponse"}
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

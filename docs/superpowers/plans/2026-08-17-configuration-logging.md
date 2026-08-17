# Task 003 Configuration and Structured Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add typed environment configuration and secret-safe structured request logging to the FastAPI service.

**Architecture:** Pydantic configuration and standard-library JSON logging live in framework-independent `packages/common`. FastAPI startup and request middleware stay in `apps/api`; startup validates configuration and middleware correlates requests without logging headers, queries, bodies, raw URL paths, or secret values.

**Tech Stack:** Python 3.12, FastAPI 0.115.x, Pydantic 2.x, pytest 8.x, Ruff 0.9.x, mypy 1.14.x.

## Global Constraints

- Implement only `tasks/003-configuration-logging.md`; do not begin Task 004.
- Preserve `apps -> packages/common`; common code must not import FastAPI, PostgreSQL, or an LLM SDK.
- Read secrets only from environment or an injected environment mapping.
- Never log credentials, request bodies, query strings, authentication headers, or customer data.
- Unit tests use no network, database, or external model calls.
- Every behavior follows RED, confirmed failure, minimal GREEN, focused verification, and relevant-suite verification.
- Keep the `/health` JSON body unchanged.

---

### Task 1: Typed and Secret-Safe Configuration

**Files:**
- Create: `packages/__init__.py`
- Create: `packages/common/__init__.py`
- Create: `packages/common/config.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `os.environ` or `Mapping[str, str]` with `DATABASE_URL` and optional `LOG_LEVEL`.
- Produces: `ConfigurationError`, `LogLevel`, `Settings`, and `load_settings(environ: Mapping[str, str] | None = None) -> Settings`.

- [ ] **Step 1: Write the first failing typed-loading test**

```python
def test_load_settings_returns_typed_secret_configuration() -> None:
    from packages.common.config import load_settings

    settings = load_settings(
        {"DATABASE_URL": "postgresql+psycopg://user:private@db/app"}
    )

    assert settings.database_url.get_secret_value().endswith("@db/app")
    assert settings.log_level == "INFO"
    assert "private" not in repr(settings)
```

- [ ] **Step 2: Run it and confirm RED**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_config.py::test_load_settings_returns_typed_secret_configuration -v
```

Expected: FAIL inside the test with `ModuleNotFoundError` because `packages` does not exist.

- [ ] **Step 3: Implement the minimum typed loader**

Create both package markers, include `packages*` in setuptools discovery, and add:

```python
import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, SecretStr


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    database_url: SecretStr
    log_level: str = "INFO"


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if environ is None else environ
    values: dict[str, str] = {}
    if "DATABASE_URL" in source:
        values["database_url"] = source["DATABASE_URL"]
    if "LOG_LEVEL" in source:
        values["log_level"] = source["LOG_LEVEL"].upper()
    return Settings.model_validate(values)
```

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run Step 2 again. Expected: `1 passed`.

- [ ] **Step 5: Write the failing missing-config test**

```python
def test_missing_database_url_raises_readable_configuration_error() -> None:
    from packages.common.config import ConfigurationError, load_settings

    with pytest.raises(ConfigurationError, match="DATABASE_URL") as captured:
        load_settings({})

    assert "input_value" not in str(captured.value)
```

- [ ] **Step 6: Confirm RED, then translate validation failures safely**

Run that test alone. Expected: FAIL because `ConfigurationError` does not exist. Add `ConfigurationError(RuntimeError)`, catch `ValidationError`, and format only field names and messages from `exc.errors(include_input=False, include_url=False)`. Map `database_url` to `DATABASE_URL` and raise from `None`. Rerun and expect `1 passed`.

- [ ] **Step 7: Write the failing log-level security test**

```python
def test_invalid_log_level_error_does_not_expose_environment_values() -> None:
    from packages.common.config import ConfigurationError, load_settings

    database_secret = "postgresql+psycopg://user:do-not-print@db/app"
    rejected_level = "secret-debug-mode"
    with pytest.raises(ConfigurationError, match="LOG_LEVEL") as captured:
        load_settings({"DATABASE_URL": database_secret, "LOG_LEVEL": rejected_level})

    message = str(captured.value)
    assert database_secret not in message
    assert rejected_level not in message
```

- [ ] **Step 8: Confirm RED, restrict the type, and confirm GREEN**

Run the test alone. Expected: FAIL because arbitrary strings are accepted. Define `LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]`, use it on `Settings.log_level`, map the field to `LOG_LEVEL`, and rerun all of `tests/unit/test_config.py -v`.

- [ ] **Step 9: Commit the configuration unit**

```bash
git add packages/__init__.py packages/common/__init__.py packages/common/config.py pyproject.toml tests/unit/test_config.py
git commit -m "feat: add typed environment configuration"
```

---

### Task 2: Recursive Redaction and JSON Logging

**Files:**
- Create: `packages/common/logging.py`
- Test: `tests/unit/test_logging.py`

**Interfaces:**
- Consumes: structured Python values and standard `logging.LogRecord` instances.
- Produces: `REDACTED`, `redact(value: object) -> object`, `JsonFormatter`, and `configure_logging(level: str) -> logging.Logger`.

- [ ] **Step 1: Write the failing recursive-redaction test**

```python
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
```

- [ ] **Step 2: Confirm RED, implement recursive redaction, and confirm GREEN**

Run the test alone. Expected: FAIL because `packages.common.logging` does not exist. Implement key normalization with lowercase plus `-` to `_`; redact keys equal to or ending in `password`, `secret`, `token`, `authorization`, `cookie`, `api_key`, or `database_url`. Recurse through mappings, lists, and tuples. Rerun and expect `1 passed`.

- [ ] **Step 3: Write the failing JSON formatter test**

```python
def test_json_formatter_redacts_structured_fields() -> None:
    from packages.common.logging import JsonFormatter

    record = logging.LogRecord(
        "shipyard_ai.request", logging.INFO, __file__, 1,
        "request_completed", (), None
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
```

- [ ] **Step 4: Confirm RED, implement formatting, and confirm GREEN**

Run the formatter test alone. Expected: FAIL because `JsonFormatter` does not exist. Emit UTC `timestamp`, `level`, `logger`, `message`, and redacted non-standard record fields with `json.dumps(..., default=str)`. Never serialize exception text or exception messages. Rerun and expect `1 passed`.

- [ ] **Step 5: Add the failing idempotent-configuration test**

```python
def test_configure_logging_adds_only_one_json_handler() -> None:
    from packages.common.logging import JsonFormatter, configure_logging

    logger = configure_logging("INFO")
    configure_logging("DEBUG")
    handlers = [
        handler for handler in logger.handlers
        if isinstance(handler.formatter, JsonFormatter)
    ]
    assert len(handlers) == 1
    assert logger.level == logging.DEBUG
```

- [ ] **Step 6: Confirm RED, implement configuration, and confirm GREEN**

Run the test alone. Expected: FAIL because `configure_logging` does not exist. Configure only the `shipyard_ai` logger, set `propagate = False`, preserve unrelated handlers, and add at most one handler with `JsonFormatter`. Restore prior logger state in a pytest fixture and run all of `tests/unit/test_logging.py -v`.

- [ ] **Step 7: Commit the logging unit**

```bash
git add packages/common/logging.py tests/unit/test_logging.py
git commit -m "feat: add secret-safe JSON logging"
```

---

### Task 3: FastAPI Startup and Request Correlation

**Files:**
- Modify: `apps/api/main.py`
- Modify: `tests/unit/test_health.py`

**Interfaces:**
- Consumes: `Settings`, `load_settings()`, and `configure_logging()`.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`, module-level `app`, and documented `X-Request-ID` response headers.

- [ ] **Step 1: Write the failing startup validation test**

```python
def test_application_startup_fails_when_required_config_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.main import create_app
    from packages.common.config import ConfigurationError

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        with TestClient(create_app()):
            pass
```

- [ ] **Step 2: Confirm RED, add the app factory/lifespan, and confirm GREEN**

Run the test alone. Expected: FAIL because `create_app` does not exist. Add an `asynccontextmanager` lifespan that resolves injected settings or calls `load_settings()`, stores settings on `application.state`, calls `configure_logging`, and yields. Define `app = create_app()` without reading environment at import. Update existing health tests to use injected synthetic `Settings`, then run `tests/unit/test_health.py -v`.

- [ ] **Step 3: Add request-ID behavior one RED/GREEN cycle at a time**

Write and run these tests separately in this order:

```python
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
```

Expected failures and minimal implementations:

1. Missing header -> generate UUID and attach the response header.
2. Safe inbound value not preserved -> reuse non-empty input.
3. Unsafe value preserved -> accept only full ASCII match `[A-Za-z0-9._-]{1,128}`.

Rerun each focused test after its minimal change, then all three together.

- [ ] **Step 4: Write the failing structured completion-log test**

Attach a test-only collecting handler directly to `shipyard_ai.request`. Send `/health?token=never-print` with an `Authorization` header and assert one `request_completed` record:

```python
assert record.request_id == response.headers["X-Request-ID"]
assert record.method == "GET"
assert record.path == "/health"
assert record.status_code == 200
assert record.duration_ms >= 0
assert "never-print" not in repr(record.__dict__)
assert "Authorization" not in record.__dict__
```

- [ ] **Step 5: Confirm RED, log completion, and confirm GREEN**

Expected RED: no record exists. Measure with `time.perf_counter()`, then log request ID, method, matched route template only, status code, and rounded non-negative milliseconds. Use a fixed placeholder for unmatched routes. Do not add headers, query, body, raw URL paths, or client identity. Rerun the focused test.

- [ ] **Step 6: Cover the sanitized failure path with RED/GREEN**

Register a test-only `/boom` endpoint that raises `RuntimeError("do-not-print")`. Use the default `TestClient` exception behavior and assert a generic 500 response with `X-Request-ID`; assert `request_failed` contains `status_code == 500` and `error_class == "RuntimeError"`, but not the exception message. Confirm RED, implement the error log and sanitized response without re-raising, and confirm GREEN.

- [ ] **Step 7: Document the header in OpenAPI and test it**

Add this route metadata and assert its literal presence in the existing OpenAPI test:

```python
responses={
    200: {
        "headers": {
            "X-Request-ID": {
                "description": "Request correlation identifier.",
                "schema": {"type": "string"},
            }
        }
    }
}
```

Run `tests/unit/test_health.py -v`; all health, startup, correlation, and logging tests must pass.

- [ ] **Step 8: Commit the API integration unit**

```bash
git add apps/api/main.py tests/unit/test_health.py
git commit -m "feat: add request correlation logging"
```

---

### Task 4: Public Contract, Verification, and Review

**Files:**
- Create: `.env.example`
- Modify: `README.md`
- Review: every file in `origin/main...HEAD`

**Interfaces:**
- Consumes: implemented `DATABASE_URL`, `LOG_LEVEL`, and `X-Request-ID` behavior.
- Produces: credential-free public documentation and verified acceptance evidence.

- [ ] **Step 1: Create and document the public contract**

Create:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
LOG_LEVEL=INFO
```

Document in README: required `DATABASE_URL`; allowed `LOG_LEVEL` values and `INFO` default; startup failure on invalid config; the `/health` response's `X-Request-ID`; accepted inbound ID pattern and length; and exclusion of headers, queries, bodies, and raw URL paths from request logs.

- [ ] **Step 2: Verify documentation and commit it**

```bash
git diff --check
git diff -- .env.example README.md
git add .env.example README.md
git commit -m "docs: document runtime configuration"
```

Expected: no whitespace errors and no usable credential or customer value.

- [ ] **Step 3: Run focused tests**

```bash
/Users/wuhao/Documents/shipyard-ai/.venv/bin/python -m pytest tests/unit/test_config.py tests/unit/test_logging.py tests/unit/test_health.py -v
```

Expected: every Task 003 unit test passes.

- [ ] **Step 4: Run the full quality gate**

```bash
make check PYTHON=/Users/wuhao/Documents/shipyard-ai/.venv/bin/python
```

Expected: dependency closure, all tests, Ruff, and mypy pass.

- [ ] **Step 5: Run repository hygiene checks**

```bash
git diff --check origin/main...HEAD
git status --short
```

Expected: no whitespace errors or unintended files.

- [ ] **Step 6: Request independent principal-engineer review**

Dispatch a separate read-only reviewer to read `AGENTS.md`, Task 003, the approved design, and `origin/main...HEAD`. Require P0-P3 findings with file, line, failure scenario, violated rule, and smallest safe fix.

- [ ] **Step 7: Resolve P0-P2 findings through TDD**

For each P0-P2 finding, add a focused failing regression test, confirm its expected failure, implement the smallest safe fix, rerun the focused test, rerun the full quality gate, and re-review until no P0-P2 findings remain.

- [ ] **Step 8: Evaluate and report acceptance**

Record evidence that missing config fails fast with a readable secret-free error; `/health` emits and documents a safe request ID; application configuration errors, representations, and structured logs omit sensitive environment values; and unit tests cover nested redaction. Report changed files, exact commands/results, Ruff, mypy, architecture decisions, reviewer result, known limitations, and that Task 004 was not started.

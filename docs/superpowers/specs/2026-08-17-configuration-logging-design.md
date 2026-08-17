# Task 003: Configuration and Structured Logging Design

## Scope

Task 003 adds typed environment configuration and structured HTTP request
logging to the existing FastAPI service. It does not connect to PostgreSQL,
introduce authentication, or begin any later task.

## Architecture

Framework-independent configuration and logging utilities live in
`packages/common`. FastAPI lifecycle and middleware integration remain in
`apps/api`, preserving the dependency direction from applications to common
packages. No domain, service, database, or model layer is introduced.

The implementation uses Pydantic and Python's standard logging library, both
already available in the project. It does not add `pydantic-settings`,
`structlog`, or another runtime dependency.

## Configuration Contract

`packages.common.config.Settings` contains:

- `database_url: SecretStr`, populated from required `DATABASE_URL`.
- `log_level`, populated from optional `LOG_LEVEL` and defaulting to `INFO`.

`load_settings()` accepts an optional environment mapping for deterministic
unit tests and otherwise reads `os.environ`. Invalid or missing values raise a
configuration-specific exception whose message identifies the affected field
without reproducing its input value. `SecretStr` prevents the database URL
from appearing in object representations.

The FastAPI application loads settings in its lifespan startup path. This
makes a missing required value fail before the service accepts traffic while
keeping module import and application construction testable. Tests use an app
factory to inject valid settings where startup behavior is not under test.

## Logging and Redaction

`packages.common.logging` provides three framework-independent capabilities:

1. Recursive redaction of mappings and sequences. Keys are compared
   case-insensitively after normalizing hyphens and underscores. Credential,
   password, token, authorization, cookie, API-key, and database-URL fields are
   replaced by the literal `[REDACTED]`.
2. A JSON formatter that emits UTC timestamp, severity, logger name, message,
   and sanitized structured fields. Canonical envelope names cannot be replaced
   by extras, and unsupported objects use a fixed non-content fallback.
3. Idempotent general logging configuration at the requested level. The
   request-audit logger remains at `INFO` so every supported `LOG_LEVEL` emits
   one completion or failure record through the same sanitized handler.

Redaction operates on structured fields. The application never places raw
environment values, headers, query strings, request bodies, or customer data
in a log message.

## Request Flow

For every HTTP request, pure ASGI middleware:

1. Reads `X-Request-ID`.
2. Reuses it only when it contains 1-128 ASCII letters, digits, dots,
   underscores, or hyphens.
3. Generates a UUID when the header is absent or invalid.
4. Measures elapsed time with a monotonic clock.
5. Owns response-start and body delivery through the complete ASGI lifecycle,
   then emits one structured completion log containing request ID, method,
   matched route template, status code, and duration in milliseconds. Unmatched
   routes use a fixed placeholder; raw URL paths are never logged.
6. Adds `X-Request-ID` to the response.

If request processing raises an unhandled exception, the middleware logs the
exception class and a status code of 500, then returns a sanitized generic 500
response with `X-Request-ID`. It does not log or re-raise the exception because
exception text could contain sensitive data.

The deployment disables Uvicorn's raw access logger; sanitized application
request records are the only HTTP access records emitted by the default image.

The `/health` response body remains unchanged. Its `X-Request-ID` response
header is documented in the generated OpenAPI contract and in the README.

## Error Handling

- Missing `DATABASE_URL`: startup raises a readable configuration error.
- Invalid `LOG_LEVEL`: startup raises a readable configuration error without
  including the rejected value.
- Invalid inbound request ID: the value is ignored and replaced; it is never
  logged.
- Request failure: a sanitized failure record is emitted and a generic 500
  response with `X-Request-ID` is returned.

## Testing

Tests exercise real behavior without network or external services:

- Configuration tests cover valid typed loading, missing required values,
  invalid optional values, and secret-free representations/errors.
- Logging tests cover nested mappings and sequences, case and separator
  variants of sensitive keys, and JSON output that contains no secret value.
- API tests cover generated request IDs, preservation of valid inbound IDs,
  replacement of invalid IDs, the response header contract, sanitized 500
  responses, and structured logging that uses route templates without request
  secrets.
- Existing unit and integration tests remain green.
- Final verification runs dependency closure, pytest, Ruff, and mypy.

## Files

- Create `packages/__init__.py`.
- Create `packages/common/__init__.py`.
- Create `packages/common/config.py`.
- Create `packages/common/logging.py`.
- Modify `apps/api/main.py`.
- Modify `pyproject.toml` so builds include `packages*`.
- Create `tests/unit/test_config.py`.
- Create `tests/unit/test_logging.py`.
- Modify `tests/unit/test_health.py`.
- Create `.env.example` with synthetic local placeholders.
- Modify `README.md` to document configuration and the response header.

## Known Boundary

Key-based redaction cannot identify an arbitrary secret embedded in free-form
message text. Task 003 prevents that exposure by keeping sensitive values out
of log messages and routing structured values through the redactor. A secure
trace store and content-classification system are outside this task.

# Task 001: Repository bootstrap

**Dependencies:** None

## Objective

Create the minimal Python monorepo, API health endpoint, PostgreSQL/pgvector Docker service, migration plumbing, and quality commands. No domain or AI features.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `pyproject.toml`
- `docker-compose.yml`
- `apps/api/main.py`
- `tests/unit/test_health.py`
- `infra/postgres/README.md`

Codex may adjust exact paths to match the repository state, but must preserve subsystem boundaries and explain any path change.

## Implementation protocol

- [ ] Read existing code before editing.
- [ ] State the files expected to change.
- [ ] Write the first failing test for the primary behavior.
- [ ] Run the focused test and confirm failure.
- [ ] Implement the minimum code needed.
- [ ] Run the focused test and confirm pass.
- [ ] Add failure/edge/security tests required by this Task.
- [ ] Run the relevant integration suite.
- [ ] Run `ruff check .`.
- [ ] Run `mypy .`.
- [ ] Update public contract/docs only if the Task changes them.
- [ ] Report exact commands and results.

## Acceptance criteria

- [ ] `docker compose up -d` starts PostgreSQL and API.
- [ ] `GET /health` returns 200 with a typed payload.
- [ ] pytest, Ruff, and mypy commands exist and pass.
- [ ] No LLM/RAG dependencies are introduced.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/001-repository-bootstrap.md` in full. Implement Task 001 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 002.

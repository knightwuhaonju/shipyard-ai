# Task 024: ERP/MES/PLM adapter ports and MCP adapter

**Dependencies:** 021,023

## Objective

Define read-only source ports, provide fixture-backed adapters, and add an MCP transport adapter that exposes only the approved tool registry.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `packages/contracts/source_ports.py`
- `adapters/erp/fixture.py`
- `adapters/mes/fixture.py`
- `adapters/plm/fixture.py`
- `adapters/mcp/server.py`
- `tests/integration/test_mcp_exposure.py`

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

- [ ] Business services depend on ports, not vendor schemas.
- [ ] No write method exists in V1 ports.
- [ ] MCP layer only translates transport to typed ToolCall.
- [ ] Tests prove hidden/unregistered tools are not exposed.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/024-source-adapter-ports-mcp.md` in full. Implement Task 024 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 025.

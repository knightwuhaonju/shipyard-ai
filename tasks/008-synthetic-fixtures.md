# Task 008: Synthetic shipyard fixture dataset

**Dependencies:** 006,007

## Objective

Create deterministic synthetic fixtures for at least two ships, drawings, equipment, BOM, POs, suppliers, and project tasks.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `tests/fixtures/shipyard/*.json`
- `tests/fixtures/loader.py`
- `tests/integration/test_fixture_loader.py`

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

- [ ] No real company/customer data appears.
- [ ] Fixtures include overdue and non-overdue procurement cases.
- [ ] Fixtures include alias cases and two security scopes.
- [ ] Reusable fixture loader exists for integration/eval tests.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/008-synthetic-fixtures.md` in full. Implement Task 008 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 009.

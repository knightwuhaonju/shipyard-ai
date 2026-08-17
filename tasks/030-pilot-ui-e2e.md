# Task 030: Pilot UI and end-to-end demo

**Dependencies:** 016,27,29

## Objective

Build minimal authenticated Next.js chat/search UI with answer, evidence drawer, tool/freshness indicators, and synthetic end-to-end demo.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `apps/web/*`
- `tests/e2e/*`
- `README.md`

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

- [ ] One UI entry point supports knowledge and Agent questions.
- [ ] Evidence can be inspected without exposing hidden chain-of-thought.
- [ ] Synthetic 1038-like project demo works end-to-end.
- [ ] E2E test covers knowledge query and procurement-risk query.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/030-pilot-ui-e2e.md` in full. Implement Task 030 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 031.

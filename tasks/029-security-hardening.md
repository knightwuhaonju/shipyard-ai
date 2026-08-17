# Task 029: Security adversarial suite

**Dependencies:** 016,20,23,27,28

## Objective

Add targeted tests for authorization leakage, prompt injection, malformed tools, SQL-like input, stale data, and Wiki source-of-truth violations.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `tests/security/test_retrieval_leakage.py`
- `tests/security/test_prompt_injection.py`
- `tests/security/test_tool_abuse.py`
- `tests/security/test_stale_data.py`

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

- [ ] Cross-scope retrieval/tool access is denied.
- [ ] Retrieved prompt injection cannot create tool instructions.
- [ ] Stale business data is labeled.
- [ ] Suite contains at least 20 adversarial cases and passes.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/029-security-hardening.md` in full. Implement Task 029 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 030.

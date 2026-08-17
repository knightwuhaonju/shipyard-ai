# Task 027: Grounded answer synthesis and response envelope

**Dependencies:** 026,022,023

## Objective

Aggregate document/Wiki/business evidence and synthesize a structured AgentResponse using a model adapter; tests use fake synthesizer.

## Required reading

- `AGENTS.md`
- `docs/00-product-scope.md`
- relevant architecture document(s)
- this Task file

## Expected files

- `packages/contracts/agent.py`
- `services/agent/synthesis.py`
- `adapters/llm/fake_synthesizer.py`
- `tests/unit/agent/test_synthesis.py`

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

- [ ] Factual answer sections reference evidence IDs.
- [ ] Business freshness surfaced.
- [ ] Inference is labeled.
- [ ] Empty evidence produces an explicit 'not enough evidence' response.

## Forbidden shortcuts

- Do not start a later Task.
- Do not add unrelated framework abstractions.
- Do not bypass authorization for convenience.
- Do not use real shipyard/customer data.
- Do not add external model dependencies to unit tests.
- Do not weaken `AGENTS.md`.

## Codex prompt

Read `AGENTS.md` and `tasks/027-answer-synthesis.md` in full. Implement Task 027 only.

Before editing, summarize the architecture constraints that apply and list the files you expect to change.

Use TDD and satisfy every acceptance criterion. At the end, report files changed, exact test/lint/type-check commands and results, architecture decisions, and known limitations. Do not begin Task 028.
